// Caudal — mapa nacional (MapLibre, global UMD)
// export async function initMap({ container, sites, onSelect })
//   -> { map, select(id), flyToSite(id, opts) -> Promise, flyHome(opts) -> Promise,
//        flyToBounds([w,s,e,n], opts) -> Promise, setLagoon(on), setValley(on) }
// select(id) only highlights (no camera move); main.js decides the flights.
// Sites with `valle` (e.g. Petorca) get a cyan "VALLE" marker; they and Aculeo ("3D") are never
// clustered. Other markers whose dots overlap on screen collapse into a count bubble that zooms
// in on its members when clicked.
//
// Base: Chile in Sentinel-2 cloudless imagery with relief; neighbouring countries as dark
// landmasses, the ocean in the page background colour. Imagery comes from the local tile cache
// (tiles/s2, tiles/dem, described by tiles/index.json) up to its max zoom and from EOX / AWS above
// that; without the cache everything is remote. A world polygon with Chile cut out as holes,
// drawn above the imagery, hides the satellite outside Chile.
// Sites are HTML markers (glowing dot + pulse ring + label pill on hover/focus/selection), which
// follow the terrain and never stack like the old extruded columns.

const URL_OF = (p) => new URL(p, import.meta.url).href;
const CHILE_URL = URL_OF('../data/chile.geojson');
const WORLD_URL = URL_OF('../data/world.geojson');
const TILES_INDEX_URL = URL_OF('../tiles/index.json');
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
const ANCHOR_CLEAR_PX = 30;         // cluster bubbles are pushed this far from Aculeo / valley markers

const sevColor = (loss) => (loss >= 85 ? RED : AMBER);

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
function registerLocalProtocol(maplibregl, local) {
  if (registerLocalProtocol.done || typeof maplibregl.addProtocol !== 'function') return;
  registerLocalProtocol.done = true;
  maplibregl.addProtocol('caudal-tile', async (params, abortController) => {
    const m = /^caudal-tile:\/\/(s2|dem)\/(\d+\/\d+\/\d+)/.exec(params.url);
    if (!m) throw new Error('bad tile url ' + params.url);
    const [, kind, key] = m;
    const keys = local[kind] && local[kind].keys;
    if (keys && !keys.has(key)) return { data: await blankTile(kind) };
    const r = await fetch(LOCAL_FILE[kind](key), { signal: abortController && abortController.signal });
    if (!r.ok) return { data: await blankTile(kind) };
    return { data: await r.arrayBuffer() };
  });
}

function buildStyle({ chile, world, local, sitesFC }) {
  const sources = {};
  const layers = [{ id: 'bg', type: 'background', paint: { 'background-color': BG } }];
  const satPaint = {
    'raster-brightness-max': 0.84,  // a touch darker so amber/red markers pop
    'raster-saturation': -0.12,
    'raster-contrast': 0.06,
    'raster-fade-duration': 0
  };

  // ---- relief (terrain + hillshade) ----
  if (local.dem) {
    sources.dem = { type: 'raster-dem', tiles: [LOCAL_DEM], encoding: 'terrarium', tileSize: 256, minzoom: local.dem.minzoom, maxzoom: local.dem.maxzoom, attribution: DEM_ATTR };
    sources['dem-hs'] = { type: 'raster-dem', tiles: [LOCAL_DEM], encoding: 'terrarium', tileSize: 256, minzoom: local.dem.minzoom, maxzoom: local.dem.maxzoom };
  } else {
    sources.dem = { type: 'raster-dem', tiles: DEM_TILES, encoding: 'terrarium', tileSize: 256, maxzoom: 12, attribution: DEM_ATTR };
    sources['dem-hs'] = { type: 'raster-dem', tiles: DEM_TILES, encoding: 'terrarium', tileSize: 256, maxzoom: 12 };
  }

  if (chile) {
    // ---- Chile satellite: local cache (overzoomed past its max) + remote EOX above it ----
    if (local.s2) {
      sources['s2-local'] = { type: 'raster', tiles: [LOCAL_S2], tileSize: 256, minzoom: local.s2.minzoom, maxzoom: local.s2.maxzoom, attribution: EOX_ATTR };
      sources['s2-remote'] = { type: 'raster', tiles: EOX_TILES, tileSize: 256, minzoom: local.s2.maxzoom, maxzoom: 15 };
      layers.push(
        { id: 's2-local', type: 'raster', source: 's2-local', paint: satPaint },
        { id: 's2-remote', type: 'raster', source: 's2-remote', minzoom: local.s2.maxzoom + 0.5, paint: satPaint }
      );
    } else {
      sources['s2-remote'] = { type: 'raster', tiles: EOX_TILES, tileSize: 256, maxzoom: 15, attribution: EOX_ATTR };
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
    // everything outside Chile goes back to the dark background
    sources['world-mask'] = { type: 'geojson', data: worldMinus(chile) };
    layers.push({ id: 'world-mask', type: 'fill', source: 'world-mask', paint: { 'fill-color': BG, 'fill-opacity': 1, 'fill-antialias': false } });
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

  // ---- soft glow under each site (draped on the terrain) ----
  sources.sites = { type: 'geojson', data: sitesFC };
  layers.push({
    id: 'site-glow', type: 'circle', source: 'sites',
    paint: {
      'circle-color': ['case', ['>=', ['get', 'loss'], 85], RED, AMBER],
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
    sky: {
      'sky-color': BG,
      'horizon-color': '#0b1a20',
      'fog-color': BG,
      'sky-horizon-blend': 0.6,
      'horizon-fog-blend': 0.4,
      'fog-ground-blend': 0.85,
      'atmosphere-blend': 0
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
      const src = map.getSource('s2-remote');
      if (src && typeof src.setTiles === 'function') {
        src.attribution = ESRI_ATTR;
        src.setTiles(ESRI_TILES);
        console.warn('[map] EOX no responde; usando Esri World Imagery');
      }
    } catch (err) { console.warn('[map] fallback satelital falló:', err); }
  });
}

const CSS = `
.cm{position:absolute;top:0;left:0;width:30px;height:30px;padding:0;margin:0;border:0;background:none;cursor:pointer;
  -webkit-tap-highlight-color:transparent;color:var(--c);font:inherit;outline:none}
.cm-in{position:absolute;inset:0;transition:opacity .45s ease}
.cm.off .cm-in{opacity:0}
.cm.off{pointer-events:none}
.cm-dot{position:absolute;left:50%;top:50%;width:var(--s);height:var(--s);margin:calc(var(--s) / -2) 0 0 calc(var(--s) / -2);border-radius:50%;
  background:radial-gradient(circle at 50% 50%,#fff 0 16%,var(--c) 44%,var(--c) 100%);
  box-shadow:0 0 0 1.5px rgba(5,8,11,.75),0 0 10px 1px var(--c),0 0 26px 4px color-mix(in srgb,var(--c) 38%,transparent);
  transition:transform .25s cubic-bezier(.2,.8,.2,1),box-shadow .25s}
.cm-ring{position:absolute;left:50%;top:50%;width:var(--s);height:var(--s);margin:calc(var(--s) / -2) 0 0 calc(var(--s) / -2);border-radius:50%;
  border:1.5px solid var(--c);opacity:0;animation:cm-pulse 2.8s cubic-bezier(.2,.6,.3,1) infinite;animation-delay:var(--d,0s)}
@keyframes cm-pulse{0%{transform:scale(1);opacity:.75}80%,100%{transform:scale(2.9);opacity:0}}
.cm-enter .cm-in{animation:cm-in .7s cubic-bezier(.2,.8,.2,1) both;animation-delay:var(--e,0s)}
@keyframes cm-in{from{opacity:0;transform:scale(.4)}to{opacity:1;transform:none}}
.cm:hover .cm-dot,.cm:focus-visible .cm-dot{transform:scale(1.18)}
.cm:focus-visible .cm-dot{box-shadow:0 0 0 2px #05080b,0 0 0 3.5px #fff,0 0 14px 2px var(--c)}
.cm.sel .cm-dot{transform:scale(1.3);box-shadow:0 0 0 2px #05080b,0 0 0 3.5px #fff,0 0 16px 3px var(--c),0 0 34px 8px color-mix(in srgb,var(--c) 45%,transparent)}
.cm.sel .cm-ring{animation-duration:1.8s}
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
@media (prefers-reduced-motion: reduce){
  .cm-ring{animation:none;opacity:.45;transform:scale(1.7)}
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

export async function initMap({ container, sites, onSelect } = {}) {
  const maplibregl = globalThis.maplibregl;
  if (typeof maplibregl === 'undefined' || !maplibregl) {
    throw new Error('[map] maplibregl no está cargado: incluye maplibre-gl@4.7.1 (UMD) antes de main.js');
  }
  if (!container) throw new Error('[map] falta el contenedor');
  injectCSS();

  const list = Array.isArray(sites) ? sites : (sites && Array.isArray(sites.sites) ? sites.sites : []);
  const losses = list.map((s) => s.loss).filter(Number.isFinite);
  const lmin = losses.length ? Math.min(...losses) : 0, lmax = losses.length ? Math.max(...losses) : 100;
  const norm = (loss) => (lmax > lmin ? (loss - lmin) / (lmax - lmin) : 1);
  // north -> south order for the entrance stagger
  const data = list.slice().sort((a, b) => b.lat - a.lat).map((s, i) => ({ ...s, _rank: i }));

  const reduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const coarse = window.matchMedia && window.matchMedia('(pointer: coarse)').matches;

  // Boundary files + tile-cache index in parallel (all small, all local).
  const [chileFC, world, idx] = await Promise.all([
    fetchJSON(CHILE_URL, 8000),
    fetchJSON(WORLD_URL, 8000),
    fetchJSON(TILES_INDEX_URL, 2500)
  ]);
  const chile = polysOf(chileFC).length ? chileFC : null;
  if (!chile) console.warn('[map] chile.geojson no disponible: mapa oscuro sin satélite');
  const local = readIndex(idx);
  if (local.s2 || local.dem) registerLocalProtocol(maplibregl, local);

  const sitesFC = {
    type: 'FeatureCollection',
    features: data.map((d) => ({
      type: 'Feature',
      properties: { id: d.id, loss: d.loss, k: 0.75 + 0.5 * norm(d.loss) },
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
      const tr = map.transform.clone();
      tr.resize(w, h);
      tr.minZoom = 0;
      tr.maxZoom = 22;
      if (typeof tr.setMaxBounds === 'function') tr.setMaxBounds(null);
      tr.pitch = HOME_PITCH;
      tr.bearing = HOME_BEARING;
      const ends = () => [FIT_NORTH, FIT_SOUTH].map((ll) => tr.locationPoint(maplibregl.LngLat.convert(ll)));
      const fits = (z) => {
        tr.zoom = z;
        const [n, s] = ends();
        if (![n.x, n.y, s.x, s.y].every(Number.isFinite)) return false;
        return Math.abs(s.y - n.y) <= h - padTop - padBottom && Math.abs(s.x - n.x) <= w - 2 * padX && n.y < s.y;
      };
      for (let round = 0; round < 4; round++) {
        tr.center = center;
        let lo = 2.5, hi = 7.5;
        if (!fits(lo)) break;
        for (let i = 0; i < 22; i++) {
          const mid = (lo + hi) / 2;
          if (fits(mid)) lo = mid; else hi = mid;
        }
        zoom = lo;
        tr.zoom = zoom;
        const [n, s] = ends();
        const wantY = (padTop + h - padBottom) / 2, wantX = w / 2;
        const dy = (n.y + s.y) / 2 - wantY, dx = (n.x + s.x) / 2 - wantX;
        if (Math.abs(dy) < 2 && Math.abs(dx) < 2) break;
        center = tr.pointLocation(new maplibregl.Point(w / 2 + dx, h / 2 + dy));
      }
    } catch (_) { /* private transform API changed: keep the default camera */ }
    return { center: [center.lng, center.lat], zoom, bearing: HOME_BEARING, pitch: HOME_PITCH };
  }

  /**
   * Zoom-out floor and pan limits follow the home view: the user can zoom out a little past it
   * and pan only a bit east/west (the rest of the continent is just dark land).
   */
  let home = null;
  function applyLimits() {
    home = homeCamera();
    const minZ = Math.max(MIN_ZOOM_FLOOR, home.zoom - ZOOM_OUT_ROOM);
    const c = map.getContainer();
    const w = c.clientWidth || innerWidth;
    // degrees of longitude the (unpitched) viewport spans at the zoom-out floor, plus some slack
    const spanAtMin = (w / (512 * Math.pow(2, minZ))) * 360;
    const half = Math.max(22, spanAtMin * 0.5 + 8);
    map.setMaxBounds(null);
    map.setMinZoom(minZ);
    map.setMaxBounds([[home.center[0] - half, PAN_LAT[0]], [home.center[0] + half, PAN_LAT[1]]]);
  }
  applyLimits();
  map.jumpTo(home);
  globalThis.__caudalMap = map; // debug handle (devtools / headless checks)

  // Wheel at the zoom-out floor scrolls the page instead of being swallowed by the map, so the
  // full-screen hero never traps the scroll.
  container.addEventListener('wheel', (e) => {
    if (e.ctrlKey || e.metaKey) return;
    if (e.deltaY > 0 && map.getZoom() <= map.getMinZoom() + 0.02) e.stopPropagation();
  }, { capture: true, passive: true });

  // ---------- markers ----------
  let selectedId = null;
  let lagoon = false, valley = false;
  const isHidden = () => lagoon || valley;
  let hoverId = null, focusId = null;
  const markers = new Map(); // id -> { d, el, marker, size, anchor, valle }
  const clusters = new Map(); // key (sorted member ids) -> { el, marker, ids }

  for (const d of data) {
    const el = document.createElement('button');
    el.type = 'button';
    el.className = 'cm' + (reduced ? '' : ' cm-enter');
    el.dataset.id = d.id;
    const size = Math.round(10 + 8 * norm(d.loss));
    el.style.setProperty('--s', size + 'px');
    const isValle = !!d.valle;
    const is3d = !isValle && d.id === 'aculeo';
    el.style.setProperty('--c', isValle ? CYAN : sevColor(d.loss));
    el.style.setProperty('--d', ((d._rank * 0.37) % 2.8).toFixed(2) + 's');
    el.style.setProperty('--e', (0.25 + d._rank * 0.08).toFixed(2) + 's');
    if (isValle) el.classList.add('cm-valle');
    const label = isValle
      ? `${d.name}, ${d.region || 'Chile'}: priorización de inspección` + (d.predios ? ` de ${d.predios} predios` : '') + '. Abrir vista del valle'
      : `${d.name}, ${d.type || ''} en ${d.region || 'Chile'}: pérdida de ${d.loss}%` + (is3d ? '. Abrir vista satelital 3D' : '');
    el.innerHTML =
      '<span class="cm-in" aria-hidden="true">' +
        (isValle ? '<span class="cm-halo"></span>' : '') +
        '<span class="cm-ring"></span><span class="cm-dot"></span>' +
        (is3d ? '<span class="cm-badge">3D</span>' : '') +
        (isValle ? '<span class="cm-badge">VALLE</span>' : '') +
        '<span class="cm-tag"><i class="cm-lead"></i><span class="cm-pill"></span></span>' +
      '</span>';
    const pill = el.querySelector('.cm-pill');
    const b = document.createElement('b'); b.textContent = d.name;
    const em = document.createElement('em');
    em.textContent = isValle ? (d.predios ? `${d.predios} predios` : 'priorización') : `−${d.loss}%`;
    pill.append(b, em);
    if (is3d || isValle) { const i = document.createElement('i'); i.textContent = isValle ? 'VALLE' : '3D'; pill.append(i); }

    el.addEventListener('click', (ev) => {
      ev.stopPropagation();
      if (isHidden() || typeof onSelect !== 'function') return;
      const orig = list.find((s) => s.id === d.id) || d;
      try { onSelect(orig); } catch (err) { console.error(err); }
    });
    el.addEventListener('pointerenter', () => { hoverId = d.id; layoutLabels(); });
    el.addEventListener('pointerleave', () => { if (hoverId === d.id) { hoverId = null; layoutLabels(); } });
    el.addEventListener('focus', () => { focusId = d.id; layoutLabels(); });
    el.addEventListener('blur', () => { if (focusId === d.id) { focusId = null; layoutLabels(); } });
    // drop the one-off entrance animation class once it has played
    el.addEventListener('animationend', (ev) => { if (ev.animationName === 'cm-in') el.classList.remove('cm-enter'); });

    const marker = new maplibregl.Marker({ element: el, anchor: 'center', opacityWhenCovered: '0.3' })
      .setLngLat([d.lon, d.lat])
      .addTo(map);
    el.setAttribute('aria-label', label); // Marker.addTo() overwrites it with 'Map marker'
    markers.set(d.id, { d, el, marker, size, anchor: isValle || is3d, valle: isValle });
  }

  /**
   * Which labels show: the selected, hovered and focused sites always want one; from
   * AUTO_LABEL_ZOOM on every site does. Wanted labels are accepted by priority (selection >
   * hover/focus > loss) and dropped when an accepted one is within LABEL_GAP_PX on screen.
   * Labels near the right edge flip to the left side of their dot.
   */
  function layoutLabels() {
    const z = map.getZoom();
    const w = map.getContainer().clientWidth;
    for (const m of markers.values()) m.p = map.project([m.d.lon, m.d.lat]);
    layoutClusters();
    const cands = [];
    for (const m of markers.values()) {
      const id = m.d.id;
      // valley markers keep their label on: they are the main entry point of the landing
      const want = !isHidden() && !m.clustered &&
        (m.valle || id === selectedId || id === hoverId || id === focusId || z >= AUTO_LABEL_ZOOM);
      const p = m.p;
      m.el.classList.toggle('flip', p.x > w - 230);
      if (!want) { m.show = false; continue; }
      const pri = (id === selectedId ? 2000 : 0) + (id === hoverId || id === focusId ? 1000 : 0) + (m.valle ? 500 : 0) + m.d.loss;
      cands.push({ m, pri });
    }
    cands.sort((a, b) => b.pri - a.pri);
    // Screen box of each label pill (geometry mirrors .cm-tag/.cm-lead/.cm-pill in CSS): the pill
    // is 22 px tall, its bottom 7 px above the dot, offset by the 22 px leader; flipped to the left.
    const boxOf = (m) => {
      if (!m.pw) m.pw = m.el.querySelector('.cm-pill').offsetWidth || 0;
      const w = m.pw || 170, off = m.size * 0.3 + 22, flip = m.el.classList.contains('flip');
      const x0 = flip ? m.p.x - off - w : m.p.x + off;
      return { x0: x0 - 4, x1: x0 + w + 4, y0: m.p.y - 29 - 3, y1: m.p.y - 7 + 3 };
    };
    const hit = (a, b) => a.x0 < b.x1 && b.x0 < a.x1 && a.y0 < b.y1 && b.y0 < a.y1;
    const accepted = [];
    for (const { m } of cands) {
      m.box = boxOf(m);
      const clash = accepted.some((o) => hit(o.box, m.box) || Math.hypot(o.p.x - m.p.x, o.p.y - m.p.y) < LABEL_GAP_PX * 0.5);
      m.show = !clash;
      if (!clash) accepted.push(m);
    }
    for (const m of markers.values()) {
      m.el.classList.toggle('lbl', !!m.show);
      m.el.classList.toggle('sel', m.d.id === selectedId);
      m.el.classList.toggle('clu', !!m.clustered);
      if (m.clustered) m.el.tabIndex = -1; else if (!isHidden()) m.el.tabIndex = 0;
      // selected > anchors (Aculeo, valleys) > cluster bubbles > labelled > the rest
      m.el.style.zIndex = m.d.id === selectedId ? '6' : (m.anchor ? '5' : (m.show ? '3' : '2'));
    }
  }

  /**
   * Screen-space clustering: non-anchor markers whose dots are closer than CLUSTER_PX (single
   * linkage) collapse into one bubble at their mean position, showing the count. Anchors
   * (Aculeo, valleys) never cluster and bubbles are pushed clear of them. Hidden in lagoon /
   * valley mode. Bubbles are reused by member set, so they do not flicker while zooming.
   */
  function layoutClusters() {
    const free = isHidden() ? [] : [...markers.values()].filter((m) => !m.anchor);
    const parent = free.map((_, i) => i);
    const root = (i) => (parent[i] === i ? i : (parent[i] = root(parent[i])));
    for (let i = 0; i < free.length; i++) {
      for (let j = i + 1; j < free.length; j++) {
        const a = free[i].p, b = free[j].p;
        if (Math.hypot(a.x - b.x, a.y - b.y) < CLUSTER_PX) parent[root(i)] = root(j);
      }
    }
    const groups = new Map();
    free.forEach((m, i) => { const r = root(i); if (!groups.has(r)) groups.set(r, []); groups.get(r).push(m); });
    for (const m of markers.values()) m.clustered = false;
    const live = new Set();
    const anchors = [...markers.values()].filter((m) => m.anchor);
    for (const g of groups.values()) {
      if (g.length < 2) continue;
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
      // move the bubble clear of nearby anchors: smallest offset that clears them all, trying
      // west (the ocean side) first
      const p = map.project([lon, lat]);
      const clearOf = (x, y) => anchors.every((a) => Math.hypot(x - a.p.x, y - a.p.y) >= ANCHOR_CLEAR_PX);
      let off = [0, 0];
      if (!clearOf(p.x, p.y)) {
        search:
        for (let r = 12; r <= 72; r += 6) {
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
  }

  function makeCluster(group, ids) {
    const el = document.createElement('button');
    el.type = 'button';
    el.className = 'cc';
    const top = group.reduce((a, m) => (m.d.loss > a.d.loss ? m : a), group[0]);
    const zpx = Math.min(38, 24 + 3 * group.length);
    el.style.setProperty('--z', zpx + 'px');
    el.style.setProperty('--c', sevColor(top.d.loss));
    el.style.zIndex = '4';
    const names = group.slice().sort((a, b) => b.d.loss - a.d.loss).map((m) => m.d.name);
    el.innerHTML = '<span class="cc-b" aria-hidden="true"></span><span class="cc-tip" aria-hidden="true"></span>';
    el.querySelector('.cc-b').textContent = String(group.length);
    el.querySelector('.cc-tip').textContent = `${group.length} sitios · acercar`;
    el.addEventListener('click', (ev) => {
      ev.stopPropagation();
      if (isHidden()) return;
      zoomToMembers(ids);
    });
    const marker = new maplibregl.Marker({ element: el, anchor: 'center', opacityWhenCovered: '0.5' });
    el.dataset.aria = `${group.length} sitios: ${names.join(', ')}. Acercar`;
    return { el, marker, ids };
  }

  /** Zoom in on a cluster's members (keeps pitch and bearing) until they separate. */
  function zoomToMembers(ids) {
    const pts = ids.map((id) => markers.get(id)).filter(Boolean).map((m) => [m.d.lon, m.d.lat]);
    if (!pts.length) return Promise.resolve();
    const lons = pts.map((p) => p[0]), lats = pts.map((p) => p[1]);
    const bbox = [Math.min(...lons), Math.min(...lats), Math.max(...lons), Math.max(...lats)];
    const minZ = Math.min(MAX_ZOOM, map.getZoom() + 1.2); // always zoom in at least a bit
    return api.flyToBounds(bbox, { padding: 120, duration: 1400, maxZoom: 8.8, minZoom: minZ });
  }
  let layoutRaf = 0;
  const scheduleLayout = () => { if (!layoutRaf) layoutRaf = requestAnimationFrame(() => { layoutRaf = 0; layoutLabels(); }); };
  map.on('move', scheduleLayout);
  map.on('resize', scheduleLayout);
  layoutLabels();
  // pill widths change once the web fonts arrive: re-measure
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(() => { for (const m of markers.values()) m.pw = 0; layoutLabels(); });

  function setMarkersOff(off) {
    for (const m of markers.values()) {
      m.el.classList.toggle('off', off);
      m.el.tabIndex = off || m.clustered ? -1 : 0;
      if (off) m.el.setAttribute('aria-hidden', 'true'); else m.el.removeAttribute('aria-hidden');
    }
    for (const c of clusters.values()) c.el.classList.toggle('off', off);
    const setGlow = () => { try { map.setPaintProperty('site-glow', 'circle-opacity', off ? 0 : 0.32); } catch (_) { /* style not ready */ } };
    if (map.isStyleLoaded()) setGlow(); else map.once('style.load', setGlow);
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

  const api = {
    map,
    select(id) {
      if (id !== null && !markers.has(id)) return;
      selectedId = id;
      layoutLabels();
    },
    /** Fly to a site. opts: { center, zoom = 7, pitch (keeps current), bearing (keeps current), duration } */
    flyToSite(id, opts = {}) {
      const m = markers.get(id);
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
      return move(homeCamera(), { duration: opts.duration ?? 2400 });
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
    /** Hide (true) or restore (false) the markers, for the lagoon close-up. */
    setLagoon(on) { setHidden('lagoon', on); },
    /** Hide (true) or restore (false) the markers, for the valley view. */
    setValley(on) { setHidden('valley', on); }
  };

  function setHidden(which, on) {
    on = !!on;
    const before = isHidden();
    if (which === 'lagoon') lagoon = on; else valley = on;
    const now = isHidden();
    if (now === before) return;
    if (now) { hoverId = null; focusId = null; }
    setMarkersOff(now);
    layoutLabels();
  }

  // ---------- relief exaggeration follows the zoom ----------
  // MapLibre 4 has no zoom expression for terrain exaggeration and setTerrain() rebuilds the
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
  map.once('load', () => { lastExag = -1; updateTerrain(true); });
  return api;
}
