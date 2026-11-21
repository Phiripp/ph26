// Caudal — mapa nacional (MapLibre GL JS 5.x, global UMD; version in ../.maplibre-version)
// export async function initMap({ container, sites, casos?, onSelect })
//   -> { map, select(id), flyToSite(id, opts) -> Promise, flyHome(opts) -> Promise,
//        flyToBounds([w,s,e,n], opts) -> Promise, setLagoon(on), setValley(on),
//        getHomeCamera() -> {center, zoom, pitch, bearing},
//        introStartCamera() -> {center, zoom, pitch, bearing}  (far-out globe; lifts the zoom/pan
//          limits until the camera is back at the home zoom, flyHome() or setMarkersVisible(true)),
//        setMarkersVisible(bool)  (false: markers, clusters, site glow and fiscalization hidden),
//        zonas: [{id, codigo, name, casos, lon, lat}], casos: [...] }
// select(id) only highlights (no camera move); main.js decides the flights.
//
// Projection: globe ("vertical-perspective") when zoomed far out, blending into flat Mercator
// before the zoom-out floor, so the intro starts on a planet and every interactive view (home
// included) looks exactly like the flat map.
//
// Markers (landing):
//   · zones (sites with kind:"zona", or `valle` for back-compat): cyan ring + "ZONA" badge, label
//     "Z1 · Petorca · 7 casos" always on. Never clustered; when two zones overlap on screen they
//     are pushed apart (Z1/Z2 are ~40 km apart, a dozen px at the national zoom).
//   · Aculeo ("3D" hook): red dot, never clustered.
//   · the 10 validation cases (data/zonas/casos.json, fallback data/sites.json `casos`): hidden
//     below CASES_MIN_ZOOM (at the national view they are reached through the zone markers, the
//     panel and deep links), then small white/red dots, label "FD-0501-181 · Cabildo" on hover/focus/selection (always from zoom
//     CASE_LABEL_ZOOM). Overlapping cases collapse into a count bubble that zooms in on them;
//     from SPREAD_ZOOM on they never cluster: coincident ones fan out around their mean point.
//   · DGA fiscalization points (data/zonas/fiscalizaciones.geojson) as a MapLibre circle layer
//     from zoom FISC_MIN_ZOOM (positivo red, negativo grey, en trámite amber), hidden in 3D modes.
// onSelect(site): zone -> {kind:"zona", zona:"z1", id:"z1", ...}; case -> {kind:"caso",
//   expediente, zona, id:"caso-<expediente>", ...}; Aculeo -> the sites.json entry {id:"aculeo"}.
// Marker ids accepted by select/flyToSite: "z1", "z2", "aculeo", "caso-<expediente>" or the bare
// expediente; "petorca" is an alias of "z1".
//
// Base: Chile in Sentinel-2 cloudless imagery with relief; neighbouring countries as dark
// landmasses, the ocean in the page background colour. Imagery comes from the local tile cache
// (tiles/s2, tiles/dem, described by tiles/index.json) up to its max zoom and from EOX / AWS above
// that; without the cache everything is remote. A world polygon with Chile cut out as holes,
// drawn above the imagery, hides the satellite outside Chile.
// Sites are HTML markers (glowing dot + pulse ring + label pill on hover/focus/selection), which
// follow the terrain and never stack like the old extruded columns.

import { ringsOfChile, clipSatTile, clipDemTile } from './tile-clip.js';

const URL_OF = (p) => new URL(p, import.meta.url).href;
const CHILE_URL = URL_OF('../data/chile.geojson');
const WORLD_URL = URL_OF('../data/world.geojson');
const TILES_INDEX_URL = URL_OF('../tiles/index.json');
const CASOS_URL = URL_OF('../data/zonas/casos.json');
const FISC_URL = URL_OF('../data/zonas/fiscalizaciones.geojson');
const ZONAS_INDEX_URL = URL_OF('../data/zonas/index.json');
const ZONAS_BBOX_URL = URL_OF('../data/zonas/bbox.json');
const SITES_URL = URL_OF('../data/sites.json');
// Local tiles go through the caudal-tile:// protocol (see registerLocalProtocol): tiles listed in
// tiles/index.json come from disk, anything else gets a blank tile without touching the network.
const LOCAL_S2 = 'caudal-tile://s2/{z}/{x}/{y}';
const LOCAL_DEM = 'caudal-tile://dem/{z}/{x}/{y}';
const LOCAL_FILE = { s2: (k) => URL_OF('../tiles/s2/' + k + '.jpg'), dem: (k) => URL_OF('../tiles/dem/' + k + '.png') };

const EOX_TILES = ['https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-2023_3857/default/g/{z}/{y}/{x}.jpg'];
const EOX_ATTR = '<a href="https://s2maps.eu" target="_blank" rel="noopener">Sentinel-2 cloudless 2023 by EOX IT Services GmbH</a> (Contains modified Copernicus Sentinel data)';
const ESRI_TILES = ['https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'];
const ESRI_ATTR = 'Imagery © Esri, Maxar, Earthstar Geographics';
const DEM_TILES = ['https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png'];
const DEM_ATTR = 'Relieve: <a href="https://registry.opendata.aws/terrain-tiles/" target="_blank" rel="noopener">AWS Terrain Tiles</a>';
const BORDERS_ATTR = 'Límites: Natural Earth';

// Relief: stronger at national zoom so the Andes read at a glance, easing off close up.
const TERRAIN_EXAG_LOW = 1.8;       // at zoom <= TERRAIN_Z0
const TERRAIN_EXAG_HIGH = 1.4;      // at zoom >= TERRAIN_Z1
const TERRAIN_Z0 = 5, TERRAIN_Z1 = 9;
const terrainExag = (z) => {
  const t = Math.min(1, Math.max(0, (z - TERRAIN_Z0) / (TERRAIN_Z1 - TERRAIN_Z0)));
  return TERRAIN_EXAG_LOW + (TERRAIN_EXAG_HIGH - TERRAIN_EXAG_LOW) * t;
};
const HILLSHADE_EXAG = ['interpolate', ['linear'], ['zoom'], 4, 0.6, 8, 0.45, 11, 0.35];
const BG = '#05080b';
const OCEAN_GLOBE = '#0b1820';      // ocean on the far-out globe, a step above the space colour
const LAND = '#0d1216';
const LAND_LINE = '#24303a';
const CYAN = '#45d6ee';
const AMBER = '#ffa940';
const RED = '#ff5b3d';

// National "home" view: upright Chile, gently pitched (40°, so markers never stack), zoomed so
// mainland Chile from Arica to Chiloé fills the viewport height. Chile's axis runs ~7° west of
// south; a small POSITIVE bearing rotates the content counter-clockwise and stands it upright
// (a negative one leans it further).
const HOME_CENTER = [-70.5, -30.5];
const HOME_PITCH = 40;
const HOME_BEARING = 7;
const FIT_NORTH = [-70.3, -17.6];   // Arica / límite norte
const FIT_SOUTH = [-73.6, -43.4];   // Chiloé
const MIN_ZOOM_FLOOR = 3.2;
const MAX_ZOOM = 12;
const ZOOM_OUT_ROOM = 0.7;          // how far below the home zoom the user may zoom out
const PAN_LAT = [-60, -8];          // pan limits (lat); lon limits are derived from the viewport
const AUTO_LABEL_ZOOM = 6.3;        // from here on labels show by themselves (collision-filtered)
const LABEL_GAP_PX = 40;            // two labels closer than this on screen: keep the higher loss
const CLUSTER_PX = 26;              // two (non-anchor) dots closer than this on screen cluster
const ANCHOR_CLEAR_PX = 30;         // cluster bubbles are pushed this far from Aculeo / zone markers
const ANCHOR_SEP_PX = 38;           // two zone/anchor markers closer than this are pushed apart
const CASE_LABEL_ZOOM = 10;         // case labels show by themselves from here on
const SPREAD_ZOOM = 10.5;           // from here on cases never cluster; coincident ones fan out
const SPREAD_R = 13;                // fan-out radius (px)
const FISC_MIN_ZOOM = 8;            // DGA fiscalization points show from here on
const CASES_MIN_ZOOM = 7;           // validation-case markers (and their clusters) show from here on
const GLOBE_SPAN = 1.2;             // min zoom levels over which the globe flattens into Mercator
const INTRO_CENTER = [-63, -10];    // intro camera: South America with Chile below centre (the
                                    // unrendered south-pole cap stays hidden on the limb)
const GREY = '#8a979e';
const ZONE_SIZE = 16, ACULEO_SIZE = 14, CASE_SIZE = 9;

const sevColor = (loss) => (loss >= 85 ? RED : AMBER);
const EMPTY_FC = { type: 'FeatureCollection', features: [] };
const titleCase = (s) => String(s || '').toLowerCase().replace(/(^|[\s-])(\p{L})/gu, (_, a, b) => a + b.toUpperCase());
const fmtUTM = (v) => (Number.isFinite(+v) ? (+v).toLocaleString('es-CL', { maximumFractionDigits: 1 }) + ' UTM' : '');
const fmtDate = (iso) => {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso || ''));
  return m ? `${m[3]}-${m[2]}-${m[1]}` : '';
};
/** "FD-0501-181" -> "FD-181" */
const shortExp = (e) => { const p = String(e || '').split('-'); return p.length >= 3 ? `${p[0]}-${p[p.length - 1]}` : String(e || ''); };
const caseId = (exp) => 'caso-' + exp;
const zoneKey = (z) => String(z || '').toLowerCase();

function fetchTimeout(url, ms, init = {}) {
  const ctl = 'AbortController' in window ? new AbortController() : null;
  const t = setTimeout(() => ctl && ctl.abort(), ms);
  return fetch(url, { ...init, signal: ctl ? ctl.signal : undefined }).finally(() => clearTimeout(t));
}

async function fetchJSON(url, ms) {
  try {
    const r = await fetchTimeout(url, ms);
    if (!r.ok) throw new Error(String(r.status));
    return await r.json();
  } catch (_) {
    return null;
  }
}

const polysOf = (fc) => {
  const out = [];
  for (const f of (fc && fc.features) || []) {
    const g = f && f.geometry;
    if (!g) continue;
    if (g.type === 'Polygon') out.push(g.coordinates);
    else if (g.type === 'MultiPolygon') out.push(...g.coordinates);
  }
  return out;
};

/** World polygon with every Chilean outer ring cut out as a hole. */
function worldMinus(chile) {
  const holes = polysOf(chile).map((p) => p[0]);
  return {
    type: 'Feature',
    properties: {},
    geometry: { type: 'Polygon', coordinates: [[[-180, -85], [180, -85], [180, 85], [-180, 85], [-180, -85]], ...holes] }
  };
}

/** Validates tiles/index.json; returns { s2: {minzoom,maxzoom}, dem: {...} } or null per layer. */
function readIndex(idx) {
  const ok = (o) => o && Number.isFinite(o.maxzoom) && (o.count === undefined || o.count > 0);
  if (!idx) return { s2: null, dem: null };
  const pick = (o) => (ok(o) ? {
    minzoom: Number.isFinite(o.minzoom) ? o.minzoom : 0,
    maxzoom: o.maxzoom,
    keys: Array.isArray(o.tiles) ? new Set(o.tiles) : null
  } : null);
  return { s2: pick(idx.s2), dem: pick(idx.dem) };
}

/**
 * caudal-tile://{kind}/{z}/{x}/{y}: listed tiles are fetched from tiles/{kind}/, the rest resolve
 * to a blank tile (black for imagery, sea level for Terrarium DEM) with no request. Answering 404s
 * instead would make MapLibre's terrain fall back to a blurry parent tile for every terrain tile
 * that has even one missing child, which blurred all of Chile.
 */
const blankCache = {};
function blankTile(kind) {
  if (!blankCache[kind]) {
    blankCache[kind] = new Promise((resolve, reject) => {
      const c = document.createElement('canvas');
      c.width = c.height = 256;
      const g = c.getContext('2d');
      g.fillStyle = kind === 'dem' ? 'rgb(128,0,0)' : BG; // Terrarium: R*256+G+B/256-32768 = 0 m
      g.fillRect(0, 0, 256, 256);
      c.toBlob((b) => (b ? b.arrayBuffer().then(resolve, reject) : reject(new Error('blank tile'))), 'image/png');
    });
  }
  return blankCache[kind].then((buf) => buf.slice(0));
}
/**
 * caudal-sat://{z}/{x}/{y}: Chile-only satellite imagery. Nothing outside Chile is ever loaded or
 * drawn — there is no mask "covering" other countries, the background is simply all there is.
 *  - z <= local maxzoom: tile from the local cache if listed, otherwise transparent (no request).
 *  - z  > local maxzoom: remote EOX (or Esri after repeated failures) only when the tile's ancestor
 *    at the local max zoom is in the cached Chile tile set; otherwise transparent (no request).
 *  - Every loaded tile is clipped per pixel to the Chile polygon, so border tiles show no Argentina.
 */
const SAT = { rings: null, remote: 'eox' };
const EOX_URL = (z, x, y) => `https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-2023_3857/default/g/${z}/${y}/${x}.jpg`;
const ESRI_URL = (z, x, y) => `https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/${z}/${y}/${x}`;
function prepareChileRings(chile) {
  SAT.rings = ringsOfChile(chile);
  startClipWorker(SAT.rings);
}
/**
 * Every Chile tile is decoded, clipped to the border on a canvas and re-encoded as PNG. That ran on
 * the main thread, in the middle of the intro flight; a worker does it now (js/tile-clip-worker.js).
 * Without module workers / OffscreenCanvas, or if the worker fails, the same code runs here.
 */
const CLIP = { worker: null, failed: false, seq: 0, pending: new Map() };
function startClipWorker(rings) {
  if (CLIP.worker || CLIP.failed || typeof Worker !== 'function' || typeof OffscreenCanvas !== 'function') return;
  const fail = () => {
    CLIP.failed = true;
    if (CLIP.worker) { try { CLIP.worker.terminate(); } catch (_) { /* already gone */ } }
    CLIP.worker = null;
    for (const p of CLIP.pending.values()) p.reject(new Error('clip worker no disponible'));
    CLIP.pending.clear();
  };
  try {
    const w = new Worker(new URL('./tile-clip-worker.js', import.meta.url), { type: 'module' });
    w.onmessage = (ev) => {
      const { id, buf, error } = ev.data || {};
      const p = CLIP.pending.get(id);
      if (!p) return;
      CLIP.pending.delete(id);
      if (error) p.reject(new Error(error)); else p.resolve(buf);
    };
    w.onerror = () => { console.warn('[map] recorte de tiles: worker no disponible, sigo en el hilo principal'); fail(); };
    w.postMessage({ type: 'init', rings });
    CLIP.worker = w;
  } catch (_) { fail(); }
}
/** Clip through the worker when it is up; on any failure, clip here with the same function. */
async function clipTile(kind, buf, z, x, y) {
  if (!SAT.rings) return buf;
  const local = kind === 'dem' ? clipDemTile : clipSatTile;
  if (!CLIP.worker) return local(buf, z, x, y, SAT.rings);
  try {
    return await new Promise((resolve, reject) => {
      const id = ++CLIP.seq;
      CLIP.pending.set(id, { resolve, reject });
      CLIP.worker.postMessage({ id, kind, buf, z, x, y }); // copied, not transferred: kept for the fallback
    });
  } catch (_) {
    return local(buf, z, x, y, SAT.rings);
  }
}
let transparentTile = null;
function blankTransparent() {
  if (!transparentTile) {
    transparentTile = new Promise((resolve, reject) => {
      const c = document.createElement('canvas');
      c.width = c.height = 1;
      c.toBlob((b) => (b ? b.arrayBuffer().then(resolve, reject) : reject(new Error('blank'))), 'image/png');
    });
  }
  return transparentTile.then((buf) => buf.slice(0));
}
/** Where the satellite tile z/x/y comes from: a local file, a remote URL, or null (outside Chile). */
function satUrlFor(local, z, x, y) {
  const s2 = local && local.s2;
  const remote = () => (SAT.remote === 'esri' ? ESRI_URL : EOX_URL)(z, x, y);
  if (!s2 || !s2.keys) return remote();
  if (z <= s2.maxzoom) return s2.keys.has(`${z}/${x}/${y}`) ? LOCAL_FILE.s2(`${z}/${x}/${y}`) : null;
  const d = z - s2.maxzoom;
  return s2.keys.has(`${s2.maxzoom}/${x >> d}/${y >> d}`) ? remote() : null;
}
function registerSatProtocol(maplibregl, local) {
  SAT.local = local;
  if (registerSatProtocol.done || typeof maplibregl.addProtocol !== 'function') return;
  registerSatProtocol.done = true;
  maplibregl.addProtocol('caudal-sat', async (params, abortController) => {
    const m = /^caudal-sat:\/\/(\d+)\/(\d+)\/(\d+)/.exec(params.url);
    if (!m) throw new Error('bad tile url ' + params.url);
    const z = +m[1], x = +m[2], y = +m[3];
    const s2 = local && local.s2;
    const url = satUrlFor(local, z, x, y);
    if (!url) return { data: await blankTransparent() };
    const r = await fetch(url, { signal: abortController && abortController.signal });
    if (!r.ok) {
      if (z > ((s2 && s2.maxzoom) || 0)) throw new Error('remote tile ' + r.status); // lets the Esri fallback count errors
      return { data: await blankTransparent() };
    }
    const clipped = await clipTile('sat', await r.arrayBuffer(), z, x, y);
    return { data: clipped || (await blankTransparent()) };
  });
}

/**
 * Terrain ('dem') and hillshade ('dem-hs') ask for the same DEM file through two protocols: share
 * the download (small bounded cache; each caller gets its own copy of the bytes). Not abortable on
 * purpose: one consumer giving up must not cancel the other's tile.
 */
const DEM_SHARE_MAX = 96;
const demShare = new Map();
function fetchDemShared(url) {
  let p = demShare.get(url);
  if (!p) {
    p = fetch(url).then((r) => (r.ok ? r.arrayBuffer() : null)).catch(() => null);
    demShare.set(url, p);
    // a failed download must not stick as "flat terrain": forget it so the tile can be asked again
    p.then((buf) => { if (!buf && demShare.get(url) === p) demShare.delete(url); });
    if (demShare.size > DEM_SHARE_MAX) demShare.delete(demShare.keys().next().value);
  }
  return p.then((buf) => (buf ? buf.slice(0) : null));
}

function registerHillshadeProtocol(maplibregl, local) {
  if (registerHillshadeProtocol.done || typeof maplibregl.addProtocol !== 'function') return;
  registerHillshadeProtocol.done = true;
  maplibregl.addProtocol('caudal-hs', async (params, abortController) => {
    const m = /^caudal-hs:\/\/(\d+)\/(\d+)\/(\d+)/.exec(params.url);
    if (!m) throw new Error('bad tile url ' + params.url);
    const z = +m[1], x = +m[2], y = +m[3], key = `${z}/${x}/${y}`;
    const keys = local.dem && local.dem.keys;
    if (keys && !keys.has(key)) return { data: await blankTile('dem') };
    const url = local.dem ? LOCAL_FILE.dem(key) : `https://s3.amazonaws.com/elevation-tiles-prod/terrarium/${key}.png`;
    const buf = await fetchDemShared(url);
    if (!buf) return { data: await blankTile('dem') };
    return { data: await clipTile('dem', buf, z, x, y) };
  });
}

function registerLocalProtocol(maplibregl, local) {
  if (registerLocalProtocol.done || typeof maplibregl.addProtocol !== 'function') return;
  registerLocalProtocol.done = true;
  maplibregl.addProtocol('caudal-tile', async (params, abortController) => {
    const m = /^caudal-tile:\/\/(s2|dem)\/(\d+\/\d+\/\d+)/.exec(params.url);
    if (!m) throw new Error('bad tile url ' + params.url);
    const [, kind, key] = m;
    const keys = local[kind] && local[kind].keys;
    if (keys && !keys.has(key)) return { data: await blankTile(kind) };
    if (kind === 'dem') {
      const buf = await fetchDemShared(LOCAL_FILE.dem(key));
      return { data: buf || (await blankTile('dem')) };
    }
    const r = await fetch(LOCAL_FILE[kind](key), { signal: abortController && abortController.signal });
    if (!r.ok) return { data: await blankTile(kind) };
    return { data: await r.arrayBuffer() };
  });
}

/** Globe far out, flat Mercator from just below the zoom-out floor (homeZoom - ZOOM_OUT_ROOM). */
function globeStops(homeZoom, introZoom) {
  const flat = Math.max(1.5, homeZoom - ZOOM_OUT_ROOM - 0.05);
  const globe = Math.max(0, Math.min(introZoom + 0.05, flat - GLOBE_SPAN));
  return { globe, flat };
}
function projectionFor(homeZoom, introZoom) {
  const { globe, flat } = globeStops(homeZoom, introZoom);
  return { type: ['interpolate', ['linear'], ['zoom'], globe, 'vertical-perspective', flat, 'mercator'] };
}
/** Ocean colour: lifted on the globe so the planet reads against space, BG once flat. */
function oceanFor(homeZoom, introZoom) {
  const { globe, flat } = globeStops(homeZoom, introZoom);
  return ['interpolate', ['linear'], ['zoom'], globe, OCEAN_GLOBE, flat, BG];
}

function buildStyle({ chile, world, local, sitesFC }) {
  const sources = {};
  const layers = [{ id: 'bg', type: 'background', paint: { 'background-color': oceanFor(4.6, 1.8) } }];
  const satPaint = {
    'raster-brightness-max': 0.84,  // a touch darker so amber/red markers pop
    'raster-saturation': -0.12,
    'raster-contrast': 0.06,
    'raster-fade-duration': 0
  };

  // ---- relief (terrain + hillshade) ----
  if (local.dem) {
    sources.dem = { type: 'raster-dem', tiles: [LOCAL_DEM], encoding: 'terrarium', tileSize: 256, minzoom: local.dem.minzoom, maxzoom: local.dem.maxzoom, attribution: DEM_ATTR };
    sources['dem-hs'] = { type: 'raster-dem', tiles: [chile ? 'caudal-hs://{z}/{x}/{y}' : LOCAL_DEM], encoding: 'terrarium', tileSize: 256, minzoom: local.dem.minzoom, maxzoom: local.dem.maxzoom };
  } else {
    sources.dem = { type: 'raster-dem', tiles: DEM_TILES, encoding: 'terrarium', tileSize: 256, maxzoom: 12, attribution: DEM_ATTR };
    sources['dem-hs'] = { type: 'raster-dem', tiles: chile ? ['caudal-hs://{z}/{x}/{y}'] : DEM_TILES, encoding: 'terrarium', tileSize: 256, maxzoom: 12 };
  }

  if (chile) {
    // ---- Chile satellite: local cache (overzoomed past its max) + remote EOX above it ----
    // Both sources go through caudal-sat:// (registerSatProtocol): Chile-only, clipped per pixel.
    if (local.s2) {
      sources['s2-local'] = { type: 'raster', tiles: ['caudal-sat://{z}/{x}/{y}'], tileSize: 256, minzoom: local.s2.minzoom, maxzoom: local.s2.maxzoom, attribution: EOX_ATTR };
      sources['s2-remote'] = { type: 'raster', tiles: ['caudal-sat://{z}/{x}/{y}'], tileSize: 256, minzoom: local.s2.maxzoom, maxzoom: 15 };
      layers.push(
        { id: 's2-local', type: 'raster', source: 's2-local', paint: satPaint },
        { id: 's2-remote', type: 'raster', source: 's2-remote', minzoom: local.s2.maxzoom + 0.5, paint: satPaint }
      );
    } else {
      sources['s2-remote'] = { type: 'raster', tiles: ['caudal-sat://{z}/{x}/{y}'], tileSize: 256, maxzoom: 15, attribution: EOX_ATTR };
      layers.push({ id: 's2-remote', type: 'raster', source: 's2-remote', paint: satPaint });
    }
    layers.push({
      id: 'hillshade', type: 'hillshade', source: 'dem-hs',
      paint: {
        'hillshade-exaggeration': HILLSHADE_EXAG,
        'hillshade-shadow-color': '#000000',
        'hillshade-highlight-color': 'rgba(255,255,255,0.14)',
        'hillshade-accent-color': BG,
        'hillshade-illumination-direction': 315
      }
    });
    // No mask layer: outside Chile no imagery is ever loaded (caudal-sat clips it at the source).
  }

  // ---- neighbouring countries as dark landmasses ----
  if (world) {
    sources.world = { type: 'geojson', data: world, attribution: BORDERS_ATTR };
    layers.push(
      { id: 'countries', type: 'fill', source: 'world', paint: { 'fill-color': LAND, 'fill-opacity': 1 } },
      { id: 'country-lines', type: 'line', source: 'world', paint: { 'line-color': LAND_LINE, 'line-width': 1 } }
    );
  }
  if (!chile) {
    // no Chile boundary: never show imagery world-wide; keep a faint relief instead
    layers.push({
      id: 'hillshade', type: 'hillshade', source: 'dem-hs',
      paint: { 'hillshade-exaggeration': HILLSHADE_EXAG, 'hillshade-shadow-color': '#000000', 'hillshade-highlight-color': 'rgba(69,214,238,0.12)', 'hillshade-accent-color': BG }
    });
  } else {
    sources.chile = { type: 'geojson', data: chile };
    layers.push(
      {
        id: 'chile-glow', type: 'line', source: 'chile',
        paint: { 'line-color': CYAN, 'line-opacity': 0.12, 'line-width': ['interpolate', ['linear'], ['zoom'], 3, 3, 8, 6], 'line-blur': 3 }
      },
      {
        id: 'chile-border', type: 'line', source: 'chile',
        paint: { 'line-color': CYAN, 'line-opacity': 0.55, 'line-width': ['interpolate', ['linear'], ['zoom'], 3, 0.7, 8, 1.3] }
      }
    );
  }

  // ---- DGA fiscalization points (filled in once data/zonas/fiscalizaciones.geojson loads) ----
  sources.fisc = { type: 'geojson', data: EMPTY_FC, attribution: 'Fiscalizaciones: DGA' };
  const fiscColor = ['match', ['get', 'etiqueta'], 'positivo', RED, 'en_tramite', AMBER, GREY];
  layers.push({
    id: 'fisc', type: 'circle', source: 'fisc', minzoom: FISC_MIN_ZOOM,
    paint: {
      'circle-color': fiscColor,
      'circle-radius': ['interpolate', ['linear'], ['zoom'], FISC_MIN_ZOOM, 2, 10, 3, 12, 4.2],
      'circle-opacity': ['interpolate', ['linear'], ['zoom'], FISC_MIN_ZOOM, 0, FISC_MIN_ZOOM + 0.4,
        ['match', ['get', 'etiqueta'], 'positivo', 0.9, 'en_tramite', 0.8, 0.55]],
      'circle-stroke-color': 'rgba(5,8,11,.85)',
      'circle-stroke-width': 0.8,
      'circle-stroke-opacity': ['interpolate', ['linear'], ['zoom'], FISC_MIN_ZOOM, 0, FISC_MIN_ZOOM + 0.4, 1],
      'circle-pitch-alignment': 'map'
    }
  });

  // ---- soft glow under each anchor site (draped on the terrain) ----
  sources.sites = { type: 'geojson', data: sitesFC };
  layers.push({
    id: 'site-glow', type: 'circle', source: 'sites',
    paint: {
      'circle-color': ['get', 'c'],
      'circle-radius': ['interpolate', ['exponential', 1.6], ['zoom'],
        3, ['*', 6, ['get', 'k']], 6, ['*', 16, ['get', 'k']], 9, ['*', 46, ['get', 'k']], 12, ['*', 90, ['get', 'k']]],
      'circle-blur': 1,
      'circle-opacity': 0.32,
      'circle-pitch-alignment': 'map',
      'circle-opacity-transition': { duration: 600 }
    }
  });

  return {
    version: 8,
    sources,
    layers,
    terrain: { source: 'dem', exaggeration: terrainExag(4.6) },
    projection: projectionFor(4.6, 1.8),
    // sun behind the globe, up-left: a thin cyan-white atmosphere rim on the upper-left limb and a
    // dark disc (only used by the globe atmosphere; no fill-extrusions here)
    light: { anchor: 'viewport', position: [1.5, 225, 24] },
    sky: {
      'sky-color': BG,
      'horizon-color': '#0b1a20',
      'fog-color': BG,
      'sky-horizon-blend': 0.6,
      'horizon-fog-blend': 0.4,
      'fog-ground-blend': 0.85,
      // globe atmosphere rim (scaled by MapLibre with the globe->mercator transition, so 0 when flat)
      'atmosphere-blend': ['interpolate', ['linear'], ['zoom'], 0, 1, 3, 0.8, 4, 0.5]
    }
  };
}

/** If the remote EOX tiles keep failing, swap that source to Esri World Imagery in place. */
function watchRemoteSatellite(map) {
  let errors = 0, swapped = false;
  map.on('error', (e) => {
    if (swapped || !e || e.sourceId !== 's2-remote') return;
    if (++errors < 4) return;
    swapped = true;
    try {
      // keep the Chile-only clipping: just switch the remote provider behind caudal-sat://
      SAT.remote = 'esri';
      const src = map.getSource('s2-remote');
      if (src) {
        src.attribution = ESRI_ATTR;
        if (typeof src.setTiles === 'function') src.setTiles(['caudal-sat://{z}/{x}/{y}?esri']);
      }
      console.warn('[map] EOX no responde; usando Esri World Imagery');
    } catch (err) { console.warn('[map] fallback satelital falló:', err); }
  });
}

const CSS = `
.cm{position:absolute;top:0;left:0;width:30px;height:30px;padding:0;margin:0;border:0;background:none;cursor:pointer;
  -webkit-tap-highlight-color:transparent;color:var(--c);font:inherit;outline:none}
.cm-in{position:absolute;inset:0;transition:opacity .45s ease}
.cm.off .cm-in{opacity:0}
.cm.off,.cm.zh{pointer-events:none}
.cm.zh .cm-in{opacity:0}
/* hidden (intro / 3D modes): hold the entrance animation so it plays when the markers come back */
.cm.off.cm-enter .cm-in,.cm.zh.cm-enter .cm-in{animation:none}
.cm-dot{position:absolute;left:50%;top:50%;width:var(--s);height:var(--s);margin:calc(var(--s) / -2) 0 0 calc(var(--s) / -2);border-radius:50%;
  background:radial-gradient(circle at 50% 50%,#fff 0 16%,var(--c) 44%,var(--c) 100%);
  box-shadow:0 0 0 1.5px rgba(5,8,11,.75),0 0 10px 1px var(--c),0 0 26px 4px color-mix(in srgb,var(--c) 38%,transparent);
  transition:transform .25s cubic-bezier(.2,.8,.2,1),box-shadow .25s}
.cm-ring{position:absolute;left:50%;top:50%;width:var(--s);height:var(--s);margin:calc(var(--s) / -2) 0 0 calc(var(--s) / -2);border-radius:50%;
  border:1.5px solid var(--c);opacity:.45;transform:scale(1.7)}
/* static ring: nothing on the page animates by itself once the intro is over */
.cm-enter .cm-in{animation:cm-in .7s cubic-bezier(.2,.8,.2,1) both;animation-delay:var(--e,0s)}
@keyframes cm-in{from{opacity:0;transform:scale(.4)}to{opacity:1;transform:none}}
.cm:hover .cm-dot,.cm:focus-visible .cm-dot{transform:scale(1.18)}
.cm:focus-visible .cm-dot{box-shadow:0 0 0 2px #05080b,0 0 0 3.5px #fff,0 0 14px 2px var(--c)}
.cm.sel .cm-dot{transform:scale(1.3);box-shadow:0 0 0 2px #05080b,0 0 0 3.5px #fff,0 0 16px 3px var(--c),0 0 34px 8px color-mix(in srgb,var(--c) 45%,transparent)}
.cm-badge{position:absolute;left:calc(50% + var(--s) / 2 - 3px);top:calc(50% - var(--s) / 2 - 9px);
  font:600 8.5px/1 'IBM Plex Mono',ui-monospace,monospace;letter-spacing:.04em;padding:2px 3px 1.5px;background:${CYAN};color:#05080b;
  box-shadow:0 0 10px rgba(69,214,238,.55);pointer-events:none}
.cm.lbl .cm-badge{opacity:0}
.cm-badge{transition:opacity .15s}
.cm-tag{position:absolute;left:calc(50% + var(--s) * .3);bottom:50%;display:flex;align-items:flex-start;pointer-events:none;
  opacity:0;transform:translate(-4px,4px);transition:opacity .18s ease,transform .18s ease;visibility:hidden}
.cm.lbl .cm-tag{opacity:1;transform:none;visibility:visible}
.cm-lead{flex:none;width:22px;height:18px;margin-top:11px;
  background:linear-gradient(to top right,transparent calc(50% - .7px),var(--c) 50%,transparent calc(50% + .7px));opacity:.9}
.cm-pill{display:flex;align-items:baseline;gap:7px;white-space:nowrap;height:22px;box-sizing:border-box;padding:4px 8px 0;
  background:rgba(5,8,11,.88);border:1px solid color-mix(in srgb,var(--c) 60%,transparent);
  box-shadow:0 4px 18px rgba(0,0,0,.45);backdrop-filter:blur(3px);-webkit-backdrop-filter:blur(3px)}
.cm-pill b{font:600 12px/1.1 Archivo,'Arial Narrow',sans-serif;letter-spacing:.02em;color:#e4ebee}
.cm-pill em{font:500 12px/1.1 'IBM Plex Mono',ui-monospace,monospace;font-style:normal;color:var(--c)}
.cm-pill i{font:500 9px/1.1 'IBM Plex Mono',ui-monospace,monospace;font-style:normal;color:#05080b;background:${CYAN};padding:2px 3px 1px;align-self:center;margin-top:-3px}
.cm.flip .cm-tag{left:auto;right:calc(50% + var(--s) * .3);flex-direction:row-reverse}
.cm.flip .cm-lead{background:linear-gradient(to top left,transparent calc(50% - .7px),var(--c) 50%,transparent calc(50% + .7px))}
.cm.sel .cm-pill{border-color:var(--c);background:rgba(5,8,11,.94)}
.cm.clu{pointer-events:none}
.cm.clu .cm-in{opacity:0}
/* valley entry: cyan dot inside a static cyan ring, "VALLE" badge */
.cm-halo{position:absolute;left:50%;top:50%;width:calc(var(--s) + 14px);height:calc(var(--s) + 14px);
  margin:calc((var(--s) + 14px) / -2) 0 0 calc((var(--s) + 14px) / -2);border-radius:50%;
  border:1.5px solid ${CYAN};box-shadow:0 0 12px rgba(69,214,238,.45),inset 0 0 8px rgba(69,214,238,.25);
  background:rgba(69,214,238,.08);transition:transform .25s cubic-bezier(.2,.8,.2,1)}
.cm-valle:hover .cm-halo,.cm-valle:focus-visible .cm-halo,.cm-valle.sel .cm-halo{transform:scale(1.15)}
.cm-valle .cm-badge{left:calc(50% + var(--s) / 2 + 4px);top:calc(50% - var(--s) / 2 - 14px)}
/* cluster bubble */
.cc{position:absolute;top:0;left:0;width:var(--z);height:var(--z);padding:0;margin:0;border:0;background:none;cursor:pointer;
  -webkit-tap-highlight-color:transparent;color:var(--c);outline:none;transition:opacity .35s ease}
.cc.off{opacity:0;pointer-events:none}
.cc-b{position:absolute;inset:0;display:grid;place-items:center;border-radius:50%;
  background:radial-gradient(circle,rgba(5,8,11,.72) 55%,color-mix(in srgb,var(--c) 22%,rgba(5,8,11,.8)) 100%);
  border:1.5px solid var(--c);box-shadow:0 0 0 1.5px rgba(5,8,11,.7),0 0 14px 1px color-mix(in srgb,var(--c) 55%,transparent);
  font:600 12px/1 'IBM Plex Mono',ui-monospace,monospace;color:#e4ebee;letter-spacing:.02em;
  transition:transform .2s cubic-bezier(.2,.8,.2,1),box-shadow .2s}
.cc-b::after{content:'';position:absolute;inset:-5px;border-radius:50%;border:1px dashed color-mix(in srgb,var(--c) 55%,transparent)}
.cc:hover .cc-b,.cc:focus-visible .cc-b{transform:scale(1.12)}
.cc:focus-visible .cc-b{box-shadow:0 0 0 2px #05080b,0 0 0 3.5px #fff,0 0 14px 2px var(--c)}
.cc-tip{position:absolute;left:calc(100% + 8px);top:50%;transform:translate(-4px,-50%);white-space:nowrap;pointer-events:none;
  font:500 10.5px/1.2 'IBM Plex Mono',ui-monospace,monospace;color:#cfd8dc;background:rgba(5,8,11,.9);
  border:1px solid color-mix(in srgb,var(--c) 55%,transparent);padding:4px 7px 3px;opacity:0;transition:opacity .15s,transform .15s}
.cc:hover .cc-tip,.cc:focus-visible .cc-tip{opacity:1;transform:translate(0,-50%)}
@media (prefers-reduced-motion: reduce){
  .cc,.cc-b,.cc-tip,.cm-halo{transition:none}
}
/* validation case: small white dot with a red rim, no pulse */
.cm-caso{width:22px;height:22px}
.cm-caso .cm-ring{display:none}
.cm-caso .cm-dot{background:#f4f7f8;box-shadow:0 0 0 2px var(--c),0 0 0 3.5px rgba(5,8,11,.8),0 0 10px 2px color-mix(in srgb,var(--c) 70%,transparent)}
.cm-caso.sel .cm-dot{transform:scale(1.35);box-shadow:0 0 0 2px var(--c),0 0 0 3.5px #05080b,0 0 0 5px #fff,0 0 14px 3px var(--c)}
.cm-caso:focus-visible .cm-dot{box-shadow:0 0 0 2px var(--c),0 0 0 3.5px #05080b,0 0 0 5px #fff}
.cm-caso .cm-pill b{font:600 11.5px/1.1 'IBM Plex Mono',ui-monospace,monospace;letter-spacing:.01em}
.cm-caso .cm-pill em{color:#cfd8dc;font-size:11px}
.cm-zona .cm-pill em{color:#cfd8dc}
/* fiscalization hover tip */
.maplibregl-popup.cf-pop .maplibregl-popup-content{background:rgba(5,8,11,.92);color:#cfd8dc;padding:5px 8px 4px;border-radius:0;
  border:1px solid rgba(138,151,158,.5);box-shadow:0 4px 14px rgba(0,0,0,.45);font:500 10.5px/1.35 'IBM Plex Mono',ui-monospace,monospace;white-space:nowrap}
.maplibregl-popup.cf-pop .maplibregl-popup-tip{display:none}
.cf-pop b{color:#e4ebee;font-weight:600}
.cf-pop i{font-style:normal;color:var(--c,#8a979e)}
@media (prefers-reduced-motion: reduce){
  .cm-enter .cm-in{animation:none}
  .cm-dot,.cm-tag,.cm-in{transition:none}
}
`;

function injectCSS() {
  if (document.getElementById('caudal-map-css')) return;
  const st = document.createElement('style');
  st.id = 'caudal-map-css';
  st.textContent = CSS;
  document.head.appendChild(st);
}

/** Case record from data/zonas/casos.json (or the sites.json fallback) -> normalized, or null. */
function normCaso(c) {
  if (!c || !c.expediente) return null;
  const lon = +c.lon, lat = +c.lat;
  if (!Number.isFinite(lon) || !Number.isFinite(lat)) return null;
  return { ...c, expediente: String(c.expediente), zona: zoneKey(c.zona), lon, lat };
}

/**
 * Two calls inside MapLibre's render make the main thread wait for the GPU process, and during a flight
 * (new tiles every frame) those waits were ~450 ms of dropped frames per flight:
 *  - the globe's precision self-measurement (a pixel readback every few frames). It only corrects the
 *    globe: skipped while the map is fully in mercator (zoom above the globe -> mercator transition).
 *  - gl.checkFramebufferStatus after creating every hillshade / terrain framebuffer: a pure validation
 *    round trip. The formats used (RGBA8 + depth) are always complete in WebGL2, so it answers
 *    "complete" without asking. `?gpucheck=1` restores the real call.
 * Private API on both counts: anything missing leaves the stock behaviour.
 */
function skipGpuWaits(map) {
  try {
    const proj = map.style && map.style.projection;
    const globe = proj && proj._verticalPerspectiveProjection;
    if (globe && typeof globe.updateGPUdependent === 'function' && !globe._caudalPatched) {
      const measure = globe.updateGPUdependent.bind(globe);
      globe.updateGPUdependent = (ctx) => { if (proj.transitionState > 0) measure(ctx); };
      globe._caudalPatched = true;
    }
    const gl = map.painter && map.painter.context && map.painter.context.gl;
    const keepCheck = new URLSearchParams(location.search).get('gpucheck') === '1';
    if (gl && !keepCheck && typeof gl.checkFramebufferStatus === 'function') {
      gl.checkFramebufferStatus = () => gl.FRAMEBUFFER_COMPLETE;
    }
  } catch (err) {
    console.warn('[map] skipGpuWaits:', err && err.message);
  }
}

/**
 * MapLibre dims a marker hidden behind a mountain by reading the terrain depth buffer: a synchronous
 * gl.readPixels per marker, every 100 ms while the map renders (Marker._updateOpacity). With the ~13
 * markers here that was 2.6 s of main thread in the first 22 s of the page, and it grows with every
 * case added to the map. Keep only the cheap globe check (marker on the far side of the planet).
 * Private API: if the method is not there the marker keeps the stock behaviour.
 */
function skipTerrainOcclusion(marker) {
  if (typeof marker._updateOpacity !== 'function') return marker;
  marker._updateOpacity = function updateOpacityNoReadback() {
    const map = this._map;
    if (!map) return;
    let occluded = false;
    try { occluded = !!map.transform.isLocationOccluded(this._lngLat); } catch (_) { /* private API changed */ }
    const target = occluded ? this._opacityWhenCovered : this._opacity;
    if (this._element.style.opacity !== target) {
      this._element.style.opacity = target;
      this._element.classList.toggle('maplibregl-marker-covered', occluded);
    }
  };
  return marker;
}

const FISC_LABEL = { positivo: 'infracción constatada', negativo: 'sin infracción en la visita', en_tramite: 'en trámite', otro: 'otro trámite' };
const FISC_COLOR = { positivo: RED, en_tramite: AMBER };

export async function initMap({ container, sites, casos: casosIn, onSelect } = {}) {
  const maplibregl = globalThis.maplibregl;
  if (typeof maplibregl === 'undefined' || !maplibregl) {
    throw new Error('[map] maplibregl no está cargado: incluye maplibre-gl 5.x (UMD) antes de main.js');
  }
  if (!container) throw new Error('[map] falta el contenedor');
  injectCSS();

  const list = Array.isArray(sites) ? sites : (sites && Array.isArray(sites.sites) ? sites.sites : []);
  const reduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const coarse = window.matchMedia && window.matchMedia('(pointer: coarse)').matches;

  // Boundary files, tile-cache index, cases and zone index in parallel (all small, all local).
  const [chileFC, world, idx, casosJ, zIndex, zBbox] = await Promise.all([
    fetchJSON(CHILE_URL, 8000),
    fetchJSON(WORLD_URL, 8000),
    fetchJSON(TILES_INDEX_URL, 2500),
    Array.isArray(casosIn) ? Promise.resolve(null) : fetchJSON(CASOS_URL, 4000),
    fetchJSON(ZONAS_INDEX_URL, 3000),
    fetchJSON(ZONAS_BBOX_URL, 3000)
  ]);
  const chile = polysOf(chileFC).length ? chileFC : null;
  if (!chile) console.warn('[map] chile.geojson no disponible: mapa oscuro sin satélite');
  const local = readIndex(idx);
  if (local.s2 || local.dem) registerLocalProtocol(maplibregl, local);
  if (chile) { prepareChileRings(chile); registerSatProtocol(maplibregl, local); registerHillshadeProtocol(maplibregl, local); }

  // ---- cases: explicit arg > data/zonas/casos.json > sites.json `casos` ----
  let casosRaw = Array.isArray(casosIn) ? casosIn
    : Array.isArray(casosJ) ? casosJ
    : (casosJ && Array.isArray(casosJ.casos) ? casosJ.casos : null);
  if (!casosRaw && sites && !Array.isArray(sites) && Array.isArray(sites.casos)) casosRaw = sites.casos;
  if (!casosRaw) {
    const sj = await fetchJSON(SITES_URL, 3000);
    casosRaw = (sj && Array.isArray(sj.casos)) ? sj.casos : [];
    if (casosRaw.length) console.info('[map] data/zonas/casos.json no disponible: casos desde data/sites.json');
  }
  const casos = casosRaw.map(normCaso).filter(Boolean);

  // ---- zones: sites.json entries, positioned/named from data/zonas/index.json when present ----
  const zIdx = new Map(((zIndex && zIndex.zonas) || []).map((z) => [zoneKey(z.id || z.codigo), z]));
  const bboxOf = (k) => {
    const e = zIdx.get(k);
    const b = (e && e.bbox_escena) || (zBbox && zBbox[k]);
    return Array.isArray(b) && b.length === 4 && b.every(Number.isFinite) ? b : null;
  };
  const isZone = (s) => s && (s.kind === 'zona' || !!s.valle);
  const items = [];
  for (const s of list) {
    if (!s) continue;
    if (isZone(s)) {
      const k = zoneKey(s.zona || (typeof s.valle === 'string' && /^z\d/i.test(s.valle) ? s.valle : '') || s.id);
      const e = zIdx.get(k) || {};
      const b = bboxOf(k);
      let lon = +s.lon, lat = +s.lat;
      if (Array.isArray(e.centro) && e.centro.every(Number.isFinite)) [lon, lat] = e.centro;
      else if (b) { lon = (b[0] + b[2]) / 2; lat = (b[1] + b[3]) / 2; }
      if (!Number.isFinite(lon) || !Number.isFinite(lat)) continue;
      const nCasos = casos.filter((c) => c.zona === k).length || (Number.isFinite(+s.casos) ? +s.casos : 0);
      const codigo = e.codigo || s.codigo || k.toUpperCase();
      const name = e.nombre || s.name || codigo;
      const orig = { ...s, kind: 'zona', zona: k, id: k, codigo, name, casos: nCasos, lon, lat, bbox: b };
      items.push({ id: k, kind: 'zona', lon, lat, size: ZONE_SIZE, color: CYAN, anchor: true, orig, pri: 500 });
    } else {
      const lon = +s.lon, lat = +s.lat;
      if (!Number.isFinite(lon) || !Number.isFinite(lat)) continue;
      const is3d = s.id === 'aculeo';
      items.push({
        id: s.id, kind: 'site', lon, lat, size: is3d ? ACULEO_SIZE : 11, color: sevColor(s.loss),
        anchor: is3d, is3d, orig: s, pri: 200 + (Number.isFinite(+s.loss) ? +s.loss : 0)
      });
    }
  }
  for (const c of casos) {
    const id = caseId(c.expediente);
    items.push({ id, kind: 'caso', lon: c.lon, lat: c.lat, size: CASE_SIZE, color: RED, anchor: false, orig: { ...c, kind: 'caso', id }, pri: 100 });
  }
  // north -> south order for the entrance stagger
  const data = items.sort((a, b) => b.lat - a.lat).map((d, i) => ({ ...d, _rank: i }));

  const sitesFC = {
    type: 'FeatureCollection',
    features: data.filter((d) => d.anchor).map((d) => ({
      type: 'Feature',
      properties: { id: d.id, c: d.color, k: d.kind === 'zona' ? 0.85 : 1 },
      geometry: { type: 'Point', coordinates: [d.lon, d.lat] }
    }))
  };

  const map = new maplibregl.Map({
    container,
    style: buildStyle({ chile, world, local, sitesFC }),
    center: HOME_CENTER,
    zoom: 4.6,
    pitch: HOME_PITCH,
    bearing: HOME_BEARING,
    minZoom: MIN_ZOOM_FLOOR,
    maxZoom: MAX_ZOOM,
    maxPitch: 60,
    scrollZoom: true,
    doubleClickZoom: true,
    touchZoomRotate: true,
    dragRotate: false,
    pitchWithRotate: false,
    keyboard: true,
    fadeDuration: 0,
    maxTileCacheSize: 1500,
    refreshExpiredTiles: false,
    attributionControl: { compact: true },
    // On touch screens one finger scrolls the page, two fingers move/zoom the map.
    cooperativeGestures: !!coarse,
    locale: {
      'CooperativeGesturesHandler.WindowsHelpText': 'Usa Ctrl + rueda para hacer zoom en el mapa',
      'CooperativeGesturesHandler.MacHelpText': 'Usa ⌘ + rueda para hacer zoom en el mapa',
      'CooperativeGesturesHandler.MobileHelpText': 'Usa dos dedos para mover el mapa',
      'NavigationControl.ZoomIn': 'Acercar',
      'NavigationControl.ZoomOut': 'Alejar'
    }
  });
  map.touchZoomRotate.disableRotation();
  map.keyboard.disableRotation();
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right');
  watchRemoteSatellite(map);
  // Missing cache tiles (outside Chile, or the cache is still being filled) are expected: keep
  // them out of the console; report anything else once as a warning.
  map.on('error', (e) => {
    const id = e && e.sourceId;
    if (id === 's2-local' || id === 'dem' || id === 'dem-hs' || id === 's2-remote') return;
    console.warn('[map]', (e && e.error && e.error.message) || e);
  });

  /**
   * Home camera: fixed center/pitch/bearing, zoom searched so Arica and Chiloé both land inside
   * the padded viewport (landscape and portrait). Uses a cloned transform so the live map does
   * not move while searching.
   */
  function homeCamera() {
    const c = map.getContainer();
    const w = c.clientWidth || innerWidth, h = c.clientHeight || innerHeight;
    const padTop = Math.round(h * 0.13), padBottom = Math.round(h * 0.1), padX = 16;
    let zoom = 4.6;
    let center = maplibregl.LngLat.convert(HOME_CENTER);
    try {
      // MapLibre 5 transforms use setters (setZoom...) and locationToScreenPoint; 4.x used plain
      // properties and locationPoint. The clone is forced to flat Mercator (globeness 0) so the
      // result does not depend on where the live camera is (e.g. the far-out intro globe).
      const tr = map.transform.clone();
      if (typeof tr.setTransitionState === 'function') tr.setTransitionState(0, 0);
      const set = (k, v) => { const f = 'set' + k[0].toUpperCase() + k.slice(1); if (typeof tr[f] === 'function') tr[f](v); else tr[k] = v; };
      if (typeof tr.setMaxBounds === 'function') tr.setMaxBounds(null);
      set('minZoom', 0);
      set('maxZoom', 22);
      tr.resize(w, h, false);
      set('pitch', HOME_PITCH);
      set('bearing', HOME_BEARING);
      const toScreen = (ll) => (typeof tr.locationToScreenPoint === 'function' ? tr.locationToScreenPoint(ll) : tr.locationPoint(ll));
      const toLngLat = (p) => (typeof tr.screenPointToLocation === 'function' ? tr.screenPointToLocation(p) : tr.pointLocation(p));
      const ends = () => [FIT_NORTH, FIT_SOUTH].map((ll) => toScreen(maplibregl.LngLat.convert(ll)));
      const fits = (z) => {
        set('zoom', z);
        const [n, s] = ends();
        if (![n.x, n.y, s.x, s.y].every(Number.isFinite)) return false;
        return Math.abs(s.y - n.y) <= h - padTop - padBottom && Math.abs(s.x - n.x) <= w - 2 * padX && n.y < s.y;
      };
      for (let round = 0; round < 4; round++) {
        set('center', center);
        let lo = 2.5, hi = 7.5;
        if (!fits(lo)) break;
        for (let i = 0; i < 22; i++) {
          const mid = (lo + hi) / 2;
          if (fits(mid)) lo = mid; else hi = mid;
        }
        zoom = lo;
        set('zoom', zoom);
        const [n, s] = ends();
        const wantY = (padTop + h - padBottom) / 2, wantX = w / 2;
        const dy = (n.y + s.y) / 2 - wantY, dx = (n.x + s.x) / 2 - wantX;
        if (Math.abs(dy) < 2 && Math.abs(dx) < 2) break;
        center = toLngLat(new maplibregl.Point(w / 2 + dx, h / 2 + dy));
      }
    } catch (_) { /* private transform API changed: keep the default camera */ }
    return { center: [center.lng, center.lat], zoom, bearing: HOME_BEARING, pitch: HOME_PITCH };
  }

  /**
   * Zoom-out floor and pan limits follow the home view: the user can zoom out a little past it
   * and pan only a bit east/west (the rest of the continent is just dark land).
   */
  let home = null;
  let freeCam = false; // intro: zoom/pan limits lifted (see introStartCamera)
  /** Intro camera zoom: the whole globe at ~62% of the shorter viewport side. */
  function introZoom() {
    const c = map.getContainer();
    const s = Math.min(c.clientWidth || innerWidth, c.clientHeight || innerHeight);
    // never below the zoom where the world is as tall as the viewport: the Mercator constraint
    // applied while jumping from the flat home view would clamp it there anyway
    const hMin = Math.log2((c.clientHeight || innerHeight) / 512) + 0.02;
    return Math.min(3, Math.max(0.4, hMin, Math.log2((0.62 * s * Math.PI) / 512)));
  }
  /**
   * map.setMaxBounds() only updates the live transform; with terrain on, MapLibre 5 keeps a
   * pending camera clone (_requestedCameraState) that jumpTo/flyTo/setMinZoom start from, and
   * its stale bounds would be copied back (clamping the intro zoom, or dropping the pan limits).
   */
  function setBounds(b) {
    map.setMaxBounds(b);
    const rq = map._requestedCameraState;
    if (rq && typeof rq.setMaxBounds === 'function') {
      try { rq.setMaxBounds(b ? maplibregl.LngLatBounds.convert(b) : null); } catch (_) { /* private API changed */ }
    }
  }
  let projKey = '';
  function applyProjection() {
    const p = projectionFor(home.zoom, introZoom());
    const key = JSON.stringify(p);
    if (key === projKey || typeof map.setProjection !== 'function') return;
    try {
      map.setProjection(p);
      const ocean = oceanFor(home.zoom, introZoom());
      map.setPaintProperty('bg', 'background-color', ocean);
      if (map.getLayer('world-mask')) map.setPaintProperty('world-mask', 'fill-color', ocean);
      projKey = key;
    } catch (_) { /* style not ready: retried on style.load */ }
  }
  function applyLimits() {
    home = homeCamera();
    applyProjection();
    if (freeCam) return;
    const minZ = Math.max(MIN_ZOOM_FLOOR, home.zoom - ZOOM_OUT_ROOM);
    const c = map.getContainer();
    const w = c.clientWidth || innerWidth;
    // degrees of longitude the (unpitched) viewport spans at the zoom-out floor, plus some slack
    const spanAtMin = (w / (512 * Math.pow(2, minZ))) * 360;
    const half = Math.max(22, spanAtMin * 0.5 + 8);
    setBounds(null);
    map.setMinZoom(minZ);
    setBounds([[home.center[0] - half, PAN_LAT[0]], [home.center[0] + half, PAN_LAT[1]]]);
  }
  function liftLimits() {
    freeCam = true;
    setBounds(null);
    map.setMinZoom(0);
    // MapLibre 5's GlobeTransform constrains zoom through its inner Mercator / perspective
    // transforms, which only pick up a new minZoom on the next matrix update: force it now so
    // the very next jumpTo can go below the old floor.
    for (const t of [map.transform, map._requestedCameraState]) {
      if (t && typeof t._calcMatrices === 'function') { try { t._calcMatrices(); } catch (_) { /* private API changed */ } }
    }
  }
  function restoreLimits() {
    if (!freeCam) return;
    freeCam = false;
    applyLimits();
  }
  applyLimits();
  map.jumpTo(home);
  globalThis.__caudalMap = map; // debug handle (devtools / headless checks)
  // The style (inline GeoJSON + local index) parses quickly; wait for it so the globe transform
  // and projection are in place before the caller (intro) moves the camera.
  await new Promise((resolve) => {
    if (map.isStyleLoaded && map.isStyleLoaded()) return resolve();
    const t = setTimeout(resolve, 5000);
    map.once('style.load', () => { clearTimeout(t); resolve(); });
  });
  projKey = '';
  applyLimits();
  if (!freeCam) map.jumpTo(home);
  // back at (or past) the zoom-out floor after the intro flight: re-apply the limits
  map.on('moveend', () => {
    if (freeCam && home && map.getZoom() >= home.zoom - ZOOM_OUT_ROOM - 0.02) restoreLimits();
  });

  // Wheel at the zoom-out floor scrolls the page instead of being swallowed by the map, so the
  // full-screen hero never traps the scroll.
  container.addEventListener('wheel', (e) => {
    if (e.ctrlKey || e.metaKey) return;
    if (e.deltaY > 0 && map.getZoom() <= map.getMinZoom() + 0.02) e.stopPropagation();
  }, { capture: true, passive: true });

  // ---------- markers ----------
  let selectedId = null;
  let lagoon = false, valley = false, intro = false;
  const isHidden = () => lagoon || valley || intro;
  let hoverId = null, focusId = null;
  const markers = new Map(); // id -> { d, el, marker, size, anchor, kind, off, p, po }
  const clusters = new Map(); // key (sorted member ids) -> { el, marker, ids }

  for (const d of data) {
    const el = document.createElement('button');
    el.type = 'button';
    el.className = 'cm' + (reduced || d.kind === 'caso' ? '' : ' cm-enter');
    el.dataset.id = d.id;
    el.dataset.kind = d.kind;
    el.style.setProperty('--s', d.size + 'px');
    el.style.setProperty('--c', d.color);
    el.style.setProperty('--d', ((d._rank * 0.37) % 2.8).toFixed(2) + 's');
    el.style.setProperty('--e', (0.25 + d._rank * 0.06).toFixed(2) + 's');
    const o = d.orig;
    let label, badge = '', title, sub, tag = '';
    if (d.kind === 'zona') {
      el.classList.add('cm-valle', 'cm-zona');
      badge = 'ZONA'; tag = 'ZONA';
      title = `${o.codigo} · ${o.name}`;
      sub = o.casos ? `${o.casos} caso${o.casos === 1 ? '' : 's'}` : 'priorización';
      label = `Zona ${o.codigo}, ${o.name}` + (o.casos ? `: ${o.casos} casos sancionados por la DGA` : '') + '. Abrir la priorización de la zona';
    } else if (d.kind === 'caso') {
      el.classList.add('cm-caso');
      title = o.expediente;
      sub = titleCase(o.comuna);
      label = `Caso ${o.expediente}, ${titleCase(o.comuna)}: caso sancionado por la DGA` +
        (o.fecha_inspeccion ? `, inspección ${fmtDate(o.fecha_inspeccion)}` : '') +
        (o.decision ? `, ${o.decision}` : '') + (o.multa_utm != null ? `, multa ${fmtUTM(o.multa_utm)}` : '') + '. Abrir el caso';
    } else {
      if (d.is3d) { badge = '3D'; tag = '3D'; }
      title = o.name;
      sub = Number.isFinite(+o.loss) ? `−${o.loss}%` : '';
      label = `${o.name}, ${o.type || ''} en ${o.region || 'Chile'}` + (Number.isFinite(+o.loss) ? `: pérdida de ${o.loss}%` : '') + (d.is3d ? '. Abrir vista satelital 3D' : '');
    }
    el.innerHTML =
      '<span class="cm-in" aria-hidden="true">' +
        (d.kind === 'zona' ? '<span class="cm-halo"></span>' : '') +
        '<span class="cm-ring"></span><span class="cm-dot"></span>' +
        (badge ? `<span class="cm-badge">${badge}</span>` : '') +
        '<span class="cm-tag"><i class="cm-lead"></i><span class="cm-pill"></span></span>' +
      '</span>';
    const pill = el.querySelector('.cm-pill');
    const b = document.createElement('b'); b.textContent = title;
    pill.append(b);
    if (sub) { const em = document.createElement('em'); em.textContent = sub; pill.append(em); }
    if (tag) { const i = document.createElement('i'); i.textContent = tag; pill.append(i); }

    el.addEventListener('click', (ev) => {
      ev.stopPropagation();
      if (isHidden() || typeof onSelect !== 'function') return;
      try { onSelect(d.orig); } catch (err) { console.error(err); }
    });
    el.addEventListener('pointerenter', () => { hoverId = d.id; layoutLabels(); });
    el.addEventListener('pointerleave', () => { if (hoverId === d.id) { hoverId = null; layoutLabels(); } });
    el.addEventListener('focus', () => { focusId = d.id; layoutLabels(); });
    el.addEventListener('blur', () => { if (focusId === d.id) { focusId = null; layoutLabels(); } });
    // drop the one-off entrance animation class once it has played
    el.addEventListener('animationend', (ev) => { if (ev.animationName === 'cm-in') el.classList.remove('cm-enter'); });

    const marker = skipTerrainOcclusion(new maplibregl.Marker({ element: el, anchor: 'center', opacityWhenCovered: '0.3' }))
      .setLngLat([d.lon, d.lat])
      .addTo(map);
    el.setAttribute('aria-label', label); // Marker.addTo() overwrites it with 'Map marker'
    markers.set(d.id, { d, el, marker, size: d.size, anchor: d.anchor, kind: d.kind, off: [0, 0], offKey: '0,0' });
  }

  const setOff = (m, off) => {
    const key = Math.round(off[0]) + ',' + Math.round(off[1]);
    m.off = [Math.round(off[0]), Math.round(off[1])];
    m.po = { x: m.p.x + m.off[0], y: m.p.y + m.off[1] };
    if (key !== m.offKey) { m.offKey = key; m.marker.setOffset(m.off); }
  };

  /**
   * Anchors (zones, Aculeo) never cluster; two that land closer than ANCHOR_SEP_PX on screen
   * (Z1/Z2 at the national zoom) are pushed apart along the line between them, the southern one
   * downwards when they coincide.
   */
  function spreadAnchors() {
    const an = [...markers.values()].filter((m) => m.anchor);
    const off = new Map(an.map((m) => [m, [0, 0]]));
    for (let it = 0; it < 4; it++) {
      let moved = false;
      for (let i = 0; i < an.length; i++) {
        for (let j = i + 1; j < an.length; j++) {
          const a = an[i], b = an[j], oa = off.get(a), ob = off.get(b);
          const dx = (b.p.x + ob[0]) - (a.p.x + oa[0]), dy = (b.p.y + ob[1]) - (a.p.y + oa[1]);
          const dist = Math.hypot(dx, dy);
          if (dist >= ANCHOR_SEP_PX) continue;
          let ux = 0, uy = b.d.lat < a.d.lat ? 1 : -1;
          if (dist > 0.5) { ux = dx / dist; uy = dy / dist; }
          const push = (ANCHOR_SEP_PX - dist) / 2;
          oa[0] -= ux * push; oa[1] -= uy * push;
          ob[0] += ux * push; ob[1] += uy * push;
          moved = true;
        }
      }
      if (!moved) break;
    }
    for (const m of an) setOff(m, off.get(m));
  }

  // Screen box of each label pill (geometry mirrors .cm-tag/.cm-lead/.cm-pill in CSS): the pill
  // is 22 px tall, its bottom 7 px above the dot, offset by the 22 px leader; flipped to the left.
  const boxOf = (m) => {
    if (!m.pw) m.pw = m.el.querySelector('.cm-pill').offsetWidth || 0;
    const w = m.pw || 170, off = m.size * 0.3 + 22, flip = m.el.classList.contains('flip');
    const x0 = flip ? m.po.x - off - w : m.po.x + off;
    return { x0: x0 - 4, x1: x0 + w + 4, y0: m.po.y - 29 - 3, y1: m.po.y - 7 + 3 };
  };

  /**
   * Which labels show: zones always; the selected, hovered and focused markers; Aculeo from
   * AUTO_LABEL_ZOOM and cases from CASE_LABEL_ZOOM. Wanted labels are accepted by priority
   * (selection > hover/focus > zone > site > case) and dropped when they overlap an accepted one.
   * Labels near the right edge flip to the left side of their dot.
   */
  function layoutLabels() {
    const z = map.getZoom();
    const w = map.getContainer().clientWidth;
    for (const m of markers.values()) { m.p = map.project([m.d.lon, m.d.lat]); m.po = { x: m.p.x + m.off[0], y: m.p.y + m.off[1] }; }
    spreadAnchors();
    // validation cases only from CASES_MIN_ZOOM (a selected one always shows)
    const casesOn = z >= CASES_MIN_ZOOM;
    for (const m of markers.values()) m.zh = m.kind === 'caso' && !casesOn && m.d.id !== selectedId;
    // zone labels are always on: place them first so case bubbles can keep clear of them
    for (const m of markers.values()) if (m.kind === 'zona') { m.el.classList.toggle('flip', m.po.x > w - 230); m.box = boxOf(m); }
    layoutClusters();
    const cands = [];
    for (const m of markers.values()) {
      const id = m.d.id;
      const always = m.kind === 'zona' ||
        (m.kind === 'caso' ? z >= CASE_LABEL_ZOOM : z >= AUTO_LABEL_ZOOM);
      const want = !isHidden() && !m.clustered && !m.zh && (always || id === selectedId || id === hoverId || id === focusId);
      m.el.classList.toggle('flip', m.po.x > w - 230);
      if (!want) { m.show = false; continue; }
      const pri = (id === selectedId ? 2000 : 0) + (id === hoverId || id === focusId ? 1000 : 0) + m.d.pri;
      cands.push({ m, pri });
    }
    cands.sort((a, b) => b.pri - a.pri);
    const hit = (a, b) => a.x0 < b.x1 && b.x0 < a.x1 && a.y0 < b.y1 && b.y0 < a.y1;
    const accepted = [];
    for (const { m } of cands) {
      m.box = boxOf(m);
      const clash = accepted.some((o) => hit(o.box, m.box) || Math.hypot(o.po.x - m.po.x, o.po.y - m.po.y) < LABEL_GAP_PX * 0.5);
      m.show = !clash;
      if (!clash) accepted.push(m);
    }
    for (const m of markers.values()) {
      m.el.classList.toggle('lbl', !!m.show);
      m.el.classList.toggle('sel', m.d.id === selectedId);
      m.el.classList.toggle('clu', !!m.clustered);
      m.el.classList.toggle('zh', !!m.zh);
      if (m.clustered || m.zh) m.el.tabIndex = -1; else if (!isHidden()) m.el.tabIndex = 0;
      if (m.zh || isHidden()) m.el.setAttribute('aria-hidden', 'true'); else m.el.removeAttribute('aria-hidden');
      // selected > anchors (zones, Aculeo) > cluster bubbles > labelled > the rest
      m.el.style.zIndex = m.d.id === selectedId ? '6' : (m.anchor ? '5' : (m.show ? '3' : '2'));
    }
  }

  /** Single-linkage groups (indices into `pts`) of screen points closer than `px`. */
  function groupsOf(pts, px) {
    const parent = pts.map((_, i) => i);
    const root = (i) => (parent[i] === i ? i : (parent[i] = root(parent[i])));
    for (let i = 0; i < pts.length; i++) {
      for (let j = i + 1; j < pts.length; j++) {
        if (Math.hypot(pts[i].x - pts[j].x, pts[i].y - pts[j].y) < px) parent[root(i)] = root(j);
      }
    }
    const g = new Map();
    pts.forEach((_, i) => { const r = root(i); if (!g.has(r)) g.set(r, []); g.get(r).push(i); });
    return [...g.values()];
  }

  /**
   * Below SPREAD_ZOOM, non-anchor markers (cases) whose dots are closer than CLUSTER_PX collapse
   * into one bubble at their mean position, showing the count; bubbles are pushed clear of the
   * anchors and reused by member set, so they do not flicker while zooming. From SPREAD_ZOOM on
   * nothing clusters: markers that still overlap (some DGA acts are a few hundred metres apart)
   * fan out on a small circle around their mean point. Hidden in lagoon / zone mode.
   */
  function layoutClusters() {
    const free = isHidden() ? [] : [...markers.values()].filter((m) => !m.anchor && !m.zh);
    for (const m of markers.values()) m.clustered = false;
    const live = new Set();
    const spread = map.getZoom() >= SPREAD_ZOOM;
    const groups = groupsOf(free.map((m) => m.p), spread ? SPREAD_R * 1.6 : CLUSTER_PX).map((g) => g.map((i) => free[i]));
    for (const m of markers.values()) if (!m.anchor) setOff(m, [0, 0]);
    const anchors = [...markers.values()].filter((m) => m.anchor);
    for (const g of groups) {
      if (g.length < 2) continue;
      if (spread) {
        const cx = g.reduce((s, m) => s + m.p.x, 0) / g.length, cy = g.reduce((s, m) => s + m.p.y, 0) / g.length;
        const r = SPREAD_R * (g.length > 2 ? 1.25 : 1);
        g.slice().sort((a, b) => (a.d.id < b.d.id ? -1 : 1)).forEach((m, k) => {
          const ang = (-90 + (360 * k) / g.length) * Math.PI / 180;
          setOff(m, [cx + r * Math.cos(ang) - m.p.x, cy + r * Math.sin(ang) - m.p.y]);
        });
        continue;
      }
      g.forEach((m) => { m.clustered = true; });
      const ids = g.map((m) => m.d.id).sort();
      const key = ids.join('|');
      live.add(key);
      let c = clusters.get(key);
      const lon = g.reduce((s, m) => s + m.d.lon, 0) / g.length;
      const lat = g.reduce((s, m) => s + m.d.lat, 0) / g.length;
      if (!c) {
        c = makeCluster(g, ids);
        c.marker.setLngLat([lon, lat]).addTo(map);
        c.el.setAttribute('aria-label', c.el.dataset.aria); // Marker.addTo() writes 'Map marker'
        clusters.set(key, c);
      }
      // move the bubble clear of nearby anchors and their (always-on zone) labels: smallest
      // offset that clears them all, trying west (the ocean side) first
      const p = map.project([lon, lat]);
      const R = 18; // ~bubble radius + margin
      const clearOf = (x, y) => anchors.every((a) => Math.hypot(x - a.po.x, y - a.po.y) >= ANCHOR_CLEAR_PX &&
        !(a.kind === 'zona' && a.box && x > a.box.x0 - R && x < a.box.x1 + R && y > a.box.y0 - R && y < a.box.y1 + R));
      let off = [0, 0];
      if (!clearOf(p.x, p.y)) {
        search:
        for (let r = 12; r <= 84; r += 6) {
          for (const deg of [180, 210, 150, 240, 120, 270, 90, 0]) {
            const ox = r * Math.cos(deg * Math.PI / 180), oy = r * Math.sin(deg * Math.PI / 180);
            if (clearOf(p.x + ox, p.y + oy)) { off = [Math.round(ox), Math.round(oy)]; break search; }
          }
        }
      }
      c.marker.setOffset(off);
    }
    for (const [key, c] of clusters) {
      if (!live.has(key)) { c.marker.remove(); clusters.delete(key); }
    }
    // a lone case dot hidden under a zone halo is nudged out to the halo's edge
    for (const m of free) {
      if (m.clustered || m.off[0] || m.off[1]) continue;
      for (const a of anchors) {
        const dx = m.p.x - a.po.x, dy = m.p.y - a.po.y, dist = Math.hypot(dx, dy);
        const need = (a.size + 14) / 2 + m.size / 2 + 3;
        if (dist >= need) continue;
        const ux = dist > 0.5 ? dx / dist : -1, uy = dist > 0.5 ? dy / dist : 0;
        setOff(m, [a.po.x + ux * need - m.p.x, a.po.y + uy * need - m.p.y]);
        break;
      }
    }
  }

  function makeCluster(group, ids) {
    const el = document.createElement('button');
    el.type = 'button';
    el.className = 'cc';
    const allCases = group.every((m) => m.kind === 'caso');
    const zpx = Math.min(36, 22 + 2 * group.length);
    el.style.setProperty('--z', zpx + 'px');
    el.style.setProperty('--c', allCases ? RED : sevColor(Math.max(...group.map((m) => +m.d.orig.loss || 0))));
    el.style.zIndex = '4';
    const names = group.map((m) => (m.kind === 'caso' ? m.d.orig.expediente : m.d.orig.name)).sort();
    const noun = allCases ? 'casos' : 'sitios';
    el.innerHTML = '<span class="cc-b" aria-hidden="true"></span><span class="cc-tip" aria-hidden="true"></span>';
    el.querySelector('.cc-b').textContent = String(group.length);
    el.querySelector('.cc-tip').textContent = `${group.length} ${noun}${allCases ? ' sancionados' : ''} · acercar`;
    el.addEventListener('click', (ev) => {
      ev.stopPropagation();
      if (isHidden()) return;
      zoomToMembers(ids);
    });
    const marker = skipTerrainOcclusion(new maplibregl.Marker({ element: el, anchor: 'center', opacityWhenCovered: '0.5' }));
    el.dataset.aria = `${group.length} ${noun}: ${names.join(', ')}. Acercar`;
    return { el, marker, ids };
  }

  /** Zoom in on a cluster's members (keeps pitch and bearing) until they separate or fan out. */
  function zoomToMembers(ids) {
    const pts = ids.map((id) => markers.get(id)).filter(Boolean).map((m) => [m.d.lon, m.d.lat]);
    if (!pts.length) return Promise.resolve();
    const lons = pts.map((p) => p[0]), lats = pts.map((p) => p[1]);
    const bbox = [Math.min(...lons), Math.min(...lats), Math.max(...lons), Math.max(...lats)];
    const minZ = Math.min(MAX_ZOOM, map.getZoom() + 1.2); // always zoom in at least a bit
    return api.flyToBounds(bbox, { padding: 120, duration: 1400, maxZoom: SPREAD_ZOOM + 0.6, minZoom: minZ });
  }
  let layoutRaf = 0;
  const scheduleLayout = () => { if (!layoutRaf) layoutRaf = requestAnimationFrame(() => { layoutRaf = 0; layoutLabels(); }); };
  map.on('move', scheduleLayout);
  map.on('resize', scheduleLayout);
  layoutLabels();
  // pill widths change once the web fonts arrive: re-measure
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(() => { for (const m of markers.values()) m.pw = 0; layoutLabels(); });

  // ---------- DGA fiscalization points ----------
  let fiscPopup = null;
  const whenStyle = (fn) => { let ok = false; try { ok = !!map.getLayer('fisc'); } catch (_) { /* style not parsed yet */ } if (ok) fn(); else map.once('load', fn); };
  function setFiscVisible(on) {
    whenStyle(() => { try { map.setLayoutProperty('fisc', 'visibility', on ? 'visible' : 'none'); } catch (_) { /* no layer */ } });
    if (!on && fiscPopup) { fiscPopup.remove(); }
  }
  fetchJSON(FISC_URL, 8000).then((fc) => {
    // the 10 validation cases already have their own markers
    const feats = ((fc && fc.features) || []).filter((f) => f && f.geometry && f.geometry.type === 'Point' && !(f.properties && f.properties.es_caso))
      .map((f) => ({ type: 'Feature', geometry: f.geometry, properties: { ...(f.properties || {}), etiqueta: String((f.properties || {}).etiqueta || 'otro') } }));
    if (!feats.length) { if (fc === null) console.info('[map] data/zonas/fiscalizaciones.geojson no disponible'); return; }
    whenStyle(() => {
      const src = map.getSource('fisc');
      if (src && typeof src.setData === 'function') src.setData({ type: 'FeatureCollection', features: feats });
      if (isHidden()) setFiscVisible(false);
    });
  });
  if (!coarse) {
    fiscPopup = new maplibregl.Popup({ closeButton: false, closeOnClick: false, className: 'cf-pop', offset: 8, maxWidth: 'none' });
    map.on('mousemove', 'fisc', (e) => {
      const f = e.features && e.features[0];
      if (!f || isHidden()) return;
      const p = f.properties || {};
      const et = String(p.etiqueta || 'otro');
      const node = document.createElement('div');
      node.style.setProperty('--c', FISC_COLOR[et] || GREY);
      const b = document.createElement('b'); b.textContent = p.expediente || 'Fiscalización DGA';
      const line1 = document.createElement('div'); line1.append(b, document.createTextNode(p.comuna ? ' · ' + titleCase(p.comuna) : ''));
      const line2 = document.createElement('div');
      const i = document.createElement('i'); i.textContent = FISC_LABEL[et] || et;
      line2.append(document.createTextNode((p.fecha_inspeccion ? fmtDate(p.fecha_inspeccion) + ' · ' : '')), i,
        document.createTextNode(Number.isFinite(+p.multa_utm) && +p.multa_utm > 0 ? ' · ' + fmtUTM(p.multa_utm) : ''));
      node.append(line1, line2);
      fiscPopup.setLngLat(f.geometry.coordinates).setDOMContent(node).addTo(map);
      map.getCanvas().style.cursor = 'default';
    });
    map.on('mouseleave', 'fisc', () => { fiscPopup.remove(); map.getCanvas().style.cursor = ''; });
  }

  function setMarkersOff(off) {
    for (const m of markers.values()) {
      m.el.classList.toggle('off', off);
      m.el.tabIndex = off || m.clustered || m.zh ? -1 : 0;
      if (off || m.zh) m.el.setAttribute('aria-hidden', 'true'); else m.el.removeAttribute('aria-hidden');
    }
    for (const c of clusters.values()) c.el.classList.toggle('off', off);
    whenStyle(() => { try { map.setPaintProperty('site-glow', 'circle-opacity', off ? 0 : 0.32); } catch (_) { /* style not ready */ } });
    setFiscVisible(!off);
  }

  if ('ResizeObserver' in window) {
    let rt = 0;
    new ResizeObserver(() => {
      map.resize();
      clearTimeout(rt);
      rt = setTimeout(() => { try { applyLimits(); } catch (_) { /* ignore */ } }, 150);
    }).observe(container);
  }

  function move(cam, { duration = 2200, curve = 1.42 } = {}) {
    return new Promise((resolve) => {
      let done = false;
      const finish = () => { if (done) return; done = true; clearTimeout(timer); map.off('moveend', finish); resolve(); };
      const dur = reduced ? 0 : Math.max(0, duration);
      const timer = setTimeout(finish, dur + 1200); // in case the flight is interrupted without a moveend
      map.on('moveend', finish);
      if (dur === 0) map.jumpTo(cam);
      else map.flyTo({ ...cam, duration: dur, curve, essential: true });
    });
  }

  /** "z1" | "Z1" | "aculeo" | "caso-FD-0501-181" | "FD-0501-181" | "petorca" -> marker id or null */
  function resolveId(id) {
    if (id == null) return null;
    const s = String(id);
    if (markers.has(s)) return s;
    if (markers.has(s.toLowerCase())) return s.toLowerCase();
    if (markers.has(caseId(s))) return caseId(s);
    if (s === 'petorca' && markers.has('z1')) return 'z1';
    return null;
  }

  const api = {
    map,
    /** URL the map would download for satellite tile z/x/y (null = nothing to download). For preloading. */
    satTileUrl: (z, x, y) => satUrlFor(SAT.local, z, x, y),
    /** Zones as shown on the map: [{ id, codigo, name, casos, lon, lat, bbox }] */
    zonas: data.filter((d) => d.kind === 'zona').map((d) => d.orig),
    /** The validation cases the map shows (normalized: zona lower-case, lon/lat numbers). */
    casos,
    select(id) {
      const rid = resolveId(id);
      if (id !== null && !rid) return;
      selectedId = rid;
      layoutLabels();
    },
    /** Fly to a marker. opts: { center, zoom = 7, pitch (keeps current), bearing (keeps current), duration } */
    flyToSite(id, opts = {}) {
      const m = markers.get(resolveId(id));
      if (!m) return Promise.resolve();
      const cam = {
        center: opts.center || [m.d.lon, m.d.lat],
        zoom: opts.zoom ?? 7,
        pitch: opts.pitch ?? map.getPitch(),
        bearing: opts.bearing ?? map.getBearing()
      };
      return move(cam, { duration: opts.duration ?? 2200 });
    },
    /** Fly back to the national view (upright Chile, gently tilted). */
    flyHome(opts = {}) {
      return move(homeCamera(), { duration: opts.duration ?? 2400 }).then(() => restoreLimits());
    },
    /** The national landing camera { center, zoom, pitch, bearing } for the current viewport. */
    getHomeCamera() {
      return homeCamera();
    },
    /**
     * Far-out globe camera (planet with Chile visible) for the intro. Side effect: lifts the
     * zoom-out floor and pan limits; they come back when a move ends at the home zoom range,
     * on flyHome() or on setMarkersVisible(true).
     */
    introStartCamera() {
      liftLimits();
      applyProjection();
      return { center: INTRO_CENTER.slice(), zoom: introZoom(), pitch: 0, bearing: 0 };
    },
    /** false hides every marker, cluster bubble, site glow and fiscalization point (intro). */
    setMarkersVisible(on) {
      setHidden('intro', !on);
      if (on) restoreLimits();
    },
    /**
     * Fly so a [w, s, e, n] box fills the viewport. opts: { pitch (keeps current), bearing
     * (keeps current), duration = 2400, padding = 60 (number or {top,bottom,left,right}),
     * maxZoom = MAX_ZOOM, minZoom }.
     */
    flyToBounds(bbox, opts = {}) {
      if (!Array.isArray(bbox) || bbox.length < 4 || !bbox.every(Number.isFinite)) return Promise.resolve();
      const [w, s, e, n] = bbox;
      const pitch = opts.pitch ?? map.getPitch();
      const bearing = opts.bearing ?? map.getBearing();
      let center = [(w + e) / 2, (s + n) / 2], zoom = 10;
      try {
        const cam = map.cameraForBounds([[w, s], [e, n]], {
          padding: opts.padding ?? 60, bearing, maxZoom: opts.maxZoom ?? MAX_ZOOM
        });
        if (cam && cam.center && Number.isFinite(cam.zoom)) {
          const c = maplibregl.LngLat.convert(cam.center);
          center = [c.lng, c.lat];
          zoom = cam.zoom;
        }
      } catch (_) { /* degenerate box / tiny viewport: keep the centre fallback */ }
      if (Number.isFinite(opts.minZoom)) zoom = Math.max(zoom, opts.minZoom);
      zoom = Math.min(zoom, opts.maxZoom ?? MAX_ZOOM);
      return move({ center, zoom, pitch, bearing }, { duration: opts.duration ?? 2400 });
    },
    /** Hide (true) or restore (false) the markers and fiscalization points, for the lagoon close-up. */
    setLagoon(on) { setHidden('lagoon', on); },
    /** Hide (true) or restore (false) the markers and fiscalization points, for the zone 3D view. */
    setValley(on) { setHidden('valley', on); }
  };

  function setHidden(which, on) {
    on = !!on;
    const before = isHidden();
    if (which === 'lagoon') lagoon = on; else if (which === 'intro') intro = on; else valley = on;
    const now = isHidden();
    if (now === before) return;
    if (now) { hoverId = null; focusId = null; }
    setMarkersOff(now);
    layoutLabels();
  }

  // ---------- relief exaggeration follows the zoom ----------
  // MapLibre 4/5 have no zoom expression for terrain exaggeration and setTerrain() rebuilds the
  // terrain (heavy), so update the live Terrain's exaggeration in place while zooming; fall back
  // to setTerrain() once the zoom settles if that private field is not there.
  let lastExag = terrainExag(map.getZoom());
  function updateTerrain(final) {
    const ex = terrainExag(map.getZoom());
    if (Math.abs(ex - lastExag) < 0.01) return;
    const t = map.terrain;
    if (t && typeof t.exaggeration === 'number') {
      t.exaggeration = ex;
      if (t.options) t.options.exaggeration = ex;
      lastExag = ex;
      map.triggerRepaint();
    } else if (final && t) {
      try { map.setTerrain({ source: 'dem', exaggeration: ex }); lastExag = ex; } catch (_) { /* style not ready */ }
    }
  }
  map.on('zoom', () => updateTerrain(false));
  map.on('zoomend', () => updateTerrain(true));
  map.once('load', () => { lastExag = -1; updateTerrain(true); skipGpuWaits(map); });
  return api;
}
