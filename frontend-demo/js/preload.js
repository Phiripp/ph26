// Caudal · precarga en segundo plano: deja listo todo lo que la demo puede tocar mientras la portada
// está en pantalla, para que entrar a una zona o a un caso no espere red, decodificación ni GPU.
//
// Dos fases:
//   1. bytes (parte apenas existe el mapa, con prioridad baja): imágenes de las escenas 3D y tiles
//      satelitales de los vuelos. Solo llena la caché del navegador (y la del service worker): no se
//      analiza ni decodifica nada en el hilo principal, así que puede correr durante la intro.
//   2. datos y escenas (parten cuando termina la intro): código de las vistas, datos y series de cada
//      zona, imágenes de los casos; y se construye la escena 3D de cada zona, de a una y
//      solo mientras la portada está quieta (nunca durante un vuelo).
//
// Estado en <html data-warm="loading | done" data-warm-failures="n">, y un evento `caudal:warm` en
// window al terminar (detail.failures = pasos que no se pudieron completar).
// Nada de esto es necesario para que la página funcione: cualquier fallo se registra y se sigue.

const NET_CONCURRENCY = 6;
const TILE_ZOOMS = [10, 11, 12];        // sobre el encuadre con margen (lo que se ve durante el vuelo)
const TILE_ZOOM_DETAIL = 13;            // solo sobre el encuadre final
const TILE_PAD = { lon: 0.15, lat: 0.12 };
const TILE_PAD_DETAIL = { lon: 0.04, lat: 0.03 };
const MAX_TILES_PER_VIEW = 400;
const MAX_SERIES_BLOCKS = 12;           // zonas con más bloques: solo los de casos y predios de banda alta
const MAX_SERIES_IDS = 150;
const BUSY_POLL_MS = 250;
const IDLE_TIMEOUT_MS = 1500;
const SCENE_GAP_MS = 300;                // breathing room between two scene builds

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const warn = (what, err) => console.warn(`[Caudal] precarga · ${what}:`, (err && err.message) || err);

const lon2tx = (lon, z) => Math.floor(((lon + 180) / 360) * 2 ** z);
const lat2ty = (lat, z) => {
  const r = (lat * Math.PI) / 180;
  return Math.floor(((1 - Math.log(Math.tan(r) + 1 / Math.cos(r)) / Math.PI) / 2) * 2 ** z);
};

/** Tiles [z, x, y] that cover bbox [w, s, e, n] grown by `pad` degrees, at zoom z. */
export function tilesForBbox(bbox, z, pad = { lon: 0, lat: 0 }) {
  if (!Array.isArray(bbox) || bbox.length !== 4 || !bbox.every(Number.isFinite)) return [];
  const [w, s, e, n] = bbox;
  const x0 = lon2tx(w - pad.lon, z), x1 = lon2tx(e + pad.lon, z);
  const y0 = lat2ty(n + pad.lat, z), y1 = lat2ty(s - pad.lat, z);
  const out = [];
  for (let x = x0; x <= x1; x++) for (let y = y0; y <= y1; y++) out.push([z, x, y]);
  return out;
}

/** Every satellite tile worth having for a view framed on bbox (closest zooms last). */
export function tilesForView(bbox) {
  const tiles = [
    ...TILE_ZOOMS.flatMap((z) => tilesForBbox(bbox, z, TILE_PAD)),
    ...tilesForBbox(bbox, TILE_ZOOM_DETAIL, TILE_PAD_DETAIL),
  ];
  return tiles.slice(0, MAX_TILES_PER_VIEW);
}


/** Download a URL into the browser cache; resolves false (never rejects) when it cannot. */
async function pull(url) {
  try {
    const r = await fetch(url, { priority: 'low' });
    if (!r.ok) return false;
    await r.arrayBuffer();
    return true;
  } catch (_) {
    return false;
  }
}

/** Run pull() over urls with a small fixed concurrency, pausing while `paused()`. Returns how many arrived. */
async function pullAll(urls, paused = () => false) {
  const list = [...new Set(urls.filter(Boolean))];
  let next = 0, ok = 0;
  const worker = async () => {
    while (next < list.length) {
      while (paused()) await sleep(BUSY_POLL_MS);   // a flight is on: leave the network to it
      const url = list[next++];
      if (await pull(url)) ok++;
    }
  };
  await Promise.all(Array.from({ length: Math.min(NET_CONCURRENCY, list.length) }, worker));
  return { ok, total: list.length };
}

async function getJSON(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`HTTP ${r.status} en ${url}`);
  return r.json();
}

/** Files a 3D scene downloads: its manifest, DEM and the latest year's imagery. */
async function sceneAssetUrls(base, { allYears }) {
  const dir = base.endsWith('/') ? base : base + '/';
  const man = await getJSON(dir + 'manifest.json');
  const years = [...(man.years || [])].sort((a, b) => a - b);
  const wanted = allYears ? years : years.slice(-1);
  return [
    man.dem ? dir + (man.dem.file || 'dem.png') : null,
    ...wanted.map((y) => `${dir}sat-${y}.jpg`),
    ...(allYears ? years.map((y) => dir + ((man.waterSdf && man.waterSdf[y]) || `water-${y}.png`)) : []),
  ];
}

/** Ids whose series are worth having in memory before anyone opens a ficha. */
function seriesIds(data) {
  const all = (data.predios || []).map((f) => String((f.properties || f).id));
  const blocks = data.series && data.series.lazy ? data.series.lazy.bloques : 0;
  if (blocks <= MAX_SERIES_BLOCKS) return all;
  const ofCases = (data.casos || []).map((c) => c.predio_id).filter((id) => id != null).map(String);
  const alta = (data.predios || []).filter((f) => (f.properties || f).banda === 'alta').map((f) => String((f.properties || f).id));
  return [...new Set([...ofCases, ...alta])].slice(0, MAX_SERIES_IDS);
}

const caseImageUrls = (data) => (data.casos || []).flatMap((c) => (c.imagenes || []).slice(0, 3).flatMap((i) => [i.rgb, i.ndvi]));

/**
 * @param {object} o
 * @param {{id: string, bbox: number[]|null, base: string}[]} o.zonas      zones, in the order they should get ready
 * @param {(id: string) => Promise<object>} o.loadZona                    zone data (shared with the page)
 * @param {(data: object, ids: string[]) => Promise<unknown>} o.ensureSeries
 * @param {(id: string) => Promise<unknown>} o.warmZona                   builds the zone's 3D scene
 * @param {() => boolean} o.isBusy                                        true while the stage is mid-transition
 * @param {((z: number, x: number, y: number) => string|null)|null} o.tileUrl
 * @param {Promise<unknown>} o.scenesAfter                                the scene phase waits for this (the intro)
 * @returns {Promise<{ok: boolean, failures: number}>}
 */
export function startPreload({ zonas, loadZona, ensureSeries, warmZona, isBusy, tileUrl, scenesAfter }) {
  const root = document.documentElement;
  root.dataset.warm = 'loading';

  const tileUrls = (bbox) => (tileUrl && bbox ? tilesForView(bbox).map(([z, x, y]) => tileUrl(z, x, y)) : []);
  let failures = 0;
  const step = (what, fn) => Promise.resolve().then(fn).catch((err) => { failures++; warn(what, err); });
  const pulls = (urls) => pullAll(urls, isBusy);

  /** Wait until the stage is still and the main thread has a free moment. */
  async function calm() {
    while (isBusy()) await sleep(BUSY_POLL_MS);
    await new Promise((r) => (window.requestIdleCallback ? requestIdleCallback(() => r(), { timeout: IDLE_TIMEOUT_MS }) : setTimeout(r, 50)));
    if (isBusy()) return calm();
    return undefined;
  }

  // Bytes only (nothing is parsed or decoded on the main thread): safe to run during the intro flight.
  async function bytes() {
    for (const z of zonas) {
      await step(`escena ${z.id}`, async () => pulls(await sceneAssetUrls(z.base, { allYears: false })));
      await step(`tiles ${z.id}`, () => pulls(tileUrls(z.bbox)));
    }
  }

  // Code and data: parsing them costs main-thread time, so they wait for the intro to finish.
  async function data() {
    await Promise.resolve(scenesAfter).catch(() => {});
    await step('módulos', () => Promise.all([
      import('./valle.js'), import('./ficha.js'), import('./caso.js'),
      import('./expediente.js'), import('./ruta-panel.js'),
    ]));
    for (const z of zonas) {
      const zona = await step(`datos ${z.id}`, () => loadZona(z.id));
      if (!zona) continue;
      await step(`series ${z.id}`, () => ensureSeries(zona, seriesIds(zona)));
      await step(`imágenes de casos ${z.id}`, () => pulls(caseImageUrls(zona)));
    }
  }

  async function scenes() {
    await Promise.resolve(scenesAfter).catch(() => {});
    for (const z of zonas) {
      await calm();
      await sleep(SCENE_GAP_MS);
      await step(`construir ${z.id}`, async () => { if (!(await warmZona(z.id))) throw new Error('escena no disponible'); });
    }
  }

  return Promise.all([bytes(), data(), scenes()]).then(() => {
    root.dataset.warm = 'done';
    root.dataset.warmFailures = String(failures);
    window.dispatchEvent(new CustomEvent('caudal:warm', { detail: { failures } }));
    return { ok: failures === 0, failures };
  });
}
