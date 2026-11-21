// Caudal v2 · vista 3D de una zona de estudio (Z1 Petorca, Z2 Aconcagua bajo): terreno DEM + imagen satelital EOX
// + predios drapeados por banda de prioridad (modelo M5) + casos sancionados por la DGA + ruta de inspección.
// Principio: "prioriza, no acusa" -> solo IDs/rol de predio y rangos de m³, nunca dueños ni cifras únicas.
// Cámara fija (norte arriba, ~50° desde la vertical). enter()/exit() animan el descenso desde / el regreso hacia el mapa.
// Nada se anima solo: la ruta se dibuja con setRouteProgress() o playRoute(); el acercamiento a un predio/caso
// (focus) solo ocurre por una acción del usuario (clic en un caso, selectCaso(..., {focus:true})).
// Overlay dentro de #stage: canvas transparente (<canvas id="valle-canvas">); badges/etiquetas van en canvas.parentElement
// y quedan ocultos (visibility:hidden, sin eventos) cuando la vista no está activa.
//
// API: initValle({canvas, zona, base, onSelectPredio(props|null), onSelectCaso(expediente),
//                 onRouteStop(orden, parada), onRouteProgress(t)})
//   zona = objeto de loadZona(id) (js/zona-data.js): {id, zona:{base, bbox_escena, ...}, predios: Feature[], casos, ruta}
//   -> {setZona(zonaData) -> Promise, enter, exit, setActive, selectPredio(id, {focus}), selectCaso(exp, {focus}),
//       focusPredio(id), resetView(), setRouteProgress, playRoute, showRoute, setYear, setInsets, getRouteProgress,
//       years, predios, ruta, casos, zonaId, bbox, sceneBbox, outsideImagery}
//   setZona() reutiliza el mismo renderer: reconstruye terreno/predios/ruta, deja la cámara en la pose de inicio
//   (entered=false) y el llamador hace enter() después (típicamente tras map.flyToBounds(controller.bbox)).
import * as THREE from 'three';

const BG = 0x05080b;
const OVERLAY_MAX = 4096; // px, lado mayor de la textura de predios

// stroke widths in km (scaled to texture px per zone so a 30 km zone and a 10 km valley look alike)
const BANDS = {
  alta: { fill: [255, 91, 61], fa: 0.55, stroke: '#ff5b3d', sw: 0.030, label: 'ALTA', size: 12 },
  media: { fill: [255, 169, 64], fa: 0.46, stroke: '#ffa940', sw: 0.026, label: 'MEDIA', size: 11 },
  baja: { fill: [214, 200, 110], fa: 0.28, stroke: 'rgba(222,208,120,.9)', sw: 0.018, label: 'BAJA', size: 9 },
  sin_alerta: { fill: null, fa: 0, stroke: 'rgba(196,206,212,.7)', sw: 0.013, label: 'SIN INDICIO', size: 8, hollow: true },
  sin_dato: { fill: null, fa: 0, stroke: 'rgba(150,162,168,.55)', sw: 0.008, label: 'SIN DATO', size: 6, hollow: true },
};
const BAND_ORDER = ['sin_dato', 'sin_alerta', 'baja', 'media', 'alta'];
const BAND_HEX = { alta: '#ff5b3d', media: '#ffa940', baja: '#d6c86e', sin_alerta: '#c4ced4', sin_dato: '#8d9aa0' };
const bandOf = (b) => BANDS[b] || BANDS.sin_dato;
const CASE_COL = '#ffffff';
const CYAN = '#45d6ee';

const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
const easeInOutCubic = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
const easeInOutSine = (t) => -(Math.cos(Math.PI * t) - 1) / 2;
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const expShort = (e) => String(e || '').replace(/^(\w+)-\d+-(\d+)$/, '$1-$2');
const titleCase = (s) => String(s || '').toLowerCase().replace(/(^|\s)\p{L}/gu, (c) => c.toUpperCase());
const nf1 = new Intl.NumberFormat('es-CL', { maximumFractionDigits: 1 });
function fmtMil(v) {
  const k = v / 1000;
  return Math.abs(k) < 100 && Math.round(k) !== k ? nf1.format(k) : Math.round(k).toLocaleString('es-CL');
}

function loadImage(url) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.crossOrigin = 'anonymous';
    img.decoding = 'async';
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error('No se pudo cargar ' + url));
    img.src = url;
  });
}

async function loadJson(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`HTTP ${res.status} en ${url}`);
  return res.json();
}

// Route geometry. The M8 ruta.json (data/processed/ruta_z*.json) carries the stops but no line; the driven
// track (OSRM, closed loop plaza → stops → plaza) lives in ruta.gpx as <trkpt>. The older ruta.json had
// `geometry` inline: use it when present. Returns a shallow copy (zone data objects are shared).
const gpxTrackCache = new Map();
function gpxTrack(url) {
  if (!gpxTrackCache.has(url)) {
    gpxTrackCache.set(url, fetch(url).then((res) => {
      if (!res.ok) throw new Error(`HTTP ${res.status} en ${url}`);
      return res.text();
    }).then((txt) => {
      const coords = [];
      for (const m of txt.matchAll(/<trkpt\b([^>]*)>/g)) {
        const lat = +(/\blat="([^"]+)"/.exec(m[1]) || [])[1], lon = +(/\blon="([^"]+)"/.exec(m[1]) || [])[1];
        if (isFinite(lat) && isFinite(lon)) coords.push([lon, lat]);
      }
      return coords;
    }).catch((e) => { gpxTrackCache.delete(url); throw e; }));
  }
  return gpxTrackCache.get(url);
}
async function withRouteGeometry(ruta, gpxUrl) {
  if (!ruta || (ruta.geometry && ruta.geometry.type === 'LineString') || !gpxUrl) return ruta;
  try {
    const coords = await gpxTrack(gpxUrl);
    if (coords.length > 1) return { ...ruta, geometry: { type: 'LineString', coordinates: coords } };
  } catch (e) { console.warn('[valle] sin trazado de ruta (GPX):', e.message); }
  return ruta;
}

function imageData(img, maxSide = 0) {
  let w = img.naturalWidth, h = img.naturalHeight;
  if (maxSide && Math.max(w, h) > maxSide) {
    const k = maxSide / Math.max(w, h);
    w = Math.max(1, Math.round(w * k));
    h = Math.max(1, Math.round(h * k));
  }
  const c = document.createElement('canvas');
  c.width = w; c.height = h;
  const ctx = c.getContext('2d', { willReadFrequently: true });
  ctx.drawImage(img, 0, 0, w, h);
  return { w, h, data: ctx.getImageData(0, 0, w, h).data };
}

/**
 * Image for a texture, as an ImageBitmap decoded off the main thread from the file's bytes (already
 * flipped for WebGL): uploading it to the GPU is then a plain copy, instead of a synchronous decode
 * + conversion that froze frames. Falls back to a regular <img> load.
 */
async function loadTextureImage(url) {
  if (typeof createImageBitmap === 'function') {
    try {
      const res = await fetch(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await createImageBitmap(await res.blob(), { imageOrientation: 'flipY', premultiplyAlpha: 'none', colorSpaceConversion: 'none' });
    } catch (_) { /* older browser or odd file: the <img> path below reports real failures */ }
  }
  return loadImage(url);
}
const isBitmap = (img) => typeof ImageBitmap !== 'undefined' && img instanceof ImageBitmap;

function texFromImage(img, srgb) {
  const t = new THREE.Texture(img);
  if (isBitmap(img)) t.flipY = false; // the bitmap is already flipped (loadTextureImage)
  if (srgb) t.colorSpace = THREE.SRGBColorSpace;
  t.anisotropy = 8;
  t.minFilter = THREE.LinearMipmapLinearFilter;
  t.magFilter = THREE.LinearFilter;
  t.wrapS = t.wrapT = THREE.ClampToEdgeWrapping;
  t.needsUpdate = true;
  return t;
}
// 1x1 dark ground used when a zone has no imagery yet (assets still being produced)
function blankTex() {
  const t = new THREE.DataTexture(new Uint8Array([10, 16, 20, 255]), 1, 1);
  t.colorSpace = THREE.SRGBColorSpace;
  t.needsUpdate = true;
  return t;
}

// rings of a Polygon / MultiPolygon as arrays of [lon, lat]
function ringsOf(geom) {
  if (!geom) return [];
  if (geom.type === 'Polygon') return geom.coordinates;
  if (geom.type === 'MultiPolygon') return geom.coordinates.flat();
  return [];
}

// even-odd point in polygon over all rings (handles holes)
function pointInRings(x, y, rings) {
  let inside = false;
  for (const r of rings) {
    for (let i = 0, j = r.length - 1; i < r.length; j = i++) {
      const xi = r[i][0], yi = r[i][1], xj = r[j][0], yj = r[j][1];
      if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi || 1e-12) + xi) inside = !inside;
    }
  }
  return inside;
}

const TERRAIN_VS = /* glsl */`
  varying vec2 vUv;
  varying vec3 vNormalW;
  varying vec3 vPosW;
  void main() {
    vUv = uv;
    vNormalW = normalize(mat3(modelMatrix) * normal);
    vec4 wp = modelMatrix * vec4(position, 1.0);
    vPosW = wp.xyz;
    gl_Position = projectionMatrix * viewMatrix * wp;
  }
`;

const TERRAIN_FS = /* glsl */`
  uniform sampler2D uTexA;
  uniform sampler2D uTexB;
  uniform float uMix;
  uniform vec4 uImgRect;      // imagery extent inside the scene UV space (u0, v0, u1, v1)
  uniform sampler2D uOverlay; // predios (straight alpha), scene UV space
  uniform float uOverlayAmt;
  uniform float uFogNear;
  uniform float uFogFar;
  uniform float uGrid;        // km between survey grid lines in the no-imagery zone
  uniform vec3 uLightDir;
  varying vec2 vUv;
  varying vec3 vNormalW;
  varying vec3 vPosW;

  void main() {
    vec2 iuv = (vUv - uImgRect.xy) / (uImgRect.zw - uImgRect.xy);
    vec2 cuv = clamp(iuv, 0.0, 1.0);
    vec3 sat = mix(texture2D(uTexA, cuv).rgb, texture2D(uTexB, cuv).rgb, uMix);
    vec2 o = max(-iuv, iuv - 1.0);
    float out1 = max(o.x, o.y);
    float imgK = 1.0 - smoothstep(0.0, 0.004, out1);
    vec3 col = mix(vec3(0.010, 0.016, 0.020), sat, imgK);

    vec3 n = normalize(vNormalW);
    float diff = clamp(dot(n, normalize(uLightDir)), 0.0, 1.0);
    float shade = 0.55 + 0.65 * diff;
    col *= shade;

    vec4 ov = texture2D(uOverlay, vUv);
    float lum = dot(col, vec3(0.299, 0.587, 0.114));
    col = mix(col, vec3(lum) * 0.92, 0.22 * uOverlayAmt);
    col = mix(col, ov.rgb * (0.8 + 0.25 * shade), ov.a * uOverlayAmt);
    if (imgK < 0.999) {
      vec2 g = abs(fract(vPosW.xz / uGrid) - 0.5);
      float gl = 1.0 - smoothstep(0.0, 0.035, min(g.x, g.y));
      col += vec3(0.27, 0.84, 0.93) * gl * 0.045 * (1.0 - imgK) * (1.0 - ov.a);
    }

    vec2 e = smoothstep(vec2(0.0), vec2(0.05), vUv) * smoothstep(vec2(0.0), vec2(0.05), 1.0 - vUv);
    float edgeF = e.x * e.y;
    float dist = length(vPosW - cameraPosition);
    float fog = smoothstep(uFogNear, uFogFar, dist);
    float alpha = 1.0 - clamp(fog + (1.0 - edgeF), 0.0, 1.0);
    if (alpha < 0.003) discard;

    gl_FragColor = vec4(col, alpha);
    #include <colorspace_fragment>
    gl_FragColor.rgb *= gl_FragColor.a; // premultiplied output
  }
`;

const ROUTE_VS = /* glsl */`
  attribute float aDist;
  attribute float aSide;
  varying float vDist;
  varying float vSide;
  varying vec3 vPosW;
  void main() {
    vDist = aDist;
    vSide = aSide;
    vec4 wp = modelMatrix * vec4(position, 1.0);
    vPosW = wp.xyz;
    gl_Position = projectionMatrix * viewMatrix * wp;
  }
`;

const ROUTE_FS = /* glsl */`
  uniform float uDrawn;   // km drawn so far
  uniform float uAmt;     // route visibility 0..1
  uniform float uDash;    // km dash period of the not-yet-travelled preview
  uniform vec3 uColor;
  uniform float uFogNear;
  uniform float uFogFar;
  varying float vDist;
  varying float vSide;
  varying vec3 vPosW;
  void main() {
    float s = abs(vSide);
    float core = 1.0 - smoothstep(0.10, 0.24, s);
    float halo = exp(-s * s * 7.0);
    float drawn = step(vDist, uDrawn);
    float dash = step(0.45, fract(vDist / uDash));
    float ahead = (1.0 - drawn) * core * dash * 0.22;
    float head = drawn * exp(-max(uDrawn - vDist, 0.0) * 5.0) * step(0.001, uDrawn);
    float a = drawn * (core * 0.95 + halo * 0.38) + ahead + head * halo * 0.6;
    float fog = smoothstep(uFogNear, uFogFar, length(vPosW - cameraPosition));
    a *= uAmt * (1.0 - fog);
    if (a < 0.003) discard;
    vec3 c = mix(uColor, vec3(1.0), core * 0.35 * drawn + head * 0.5);
    gl_FragColor = vec4(c * a * 1.15, a);
  }
`;

// predio markers: screen-space dots at the centroid so tiny predios stay visible at zone scale
const DOT_VS = /* glsl */`
  attribute vec3 aColor;
  attribute float aSize;
  attribute float aHollow;
  attribute float aSel;
  uniform float uDpr;
  uniform float uScale;
  varying vec3 vColor;
  varying float vHollow;
  varying float vSel;
  varying vec3 vPosW;
  void main() {
    vColor = aColor; vHollow = aHollow; vSel = aSel;
    vec4 wp = modelMatrix * vec4(position, 1.0);
    vPosW = wp.xyz;
    gl_Position = projectionMatrix * viewMatrix * wp;
    gl_PointSize = aSize * uScale * uDpr * (1.0 + aSel * 0.7);
  }
`;
const DOT_FS = /* glsl */`
  uniform float uAmt;
  uniform float uFogNear;
  uniform float uFogFar;
  varying vec3 vColor;
  varying float vHollow;
  varying float vSel;
  varying vec3 vPosW;
  void main() {
    float d = length(gl_PointCoord - 0.5) * 2.0;
    if (d > 1.0) discard;
    float aa = 0.12;
    vec3 c; float a;
    if (vSel > 0.5) {
      // selected: white ring around the band colour
      float ring = smoothstep(0.62, 0.62 + aa, d);
      c = mix(vColor, vec3(1.0), ring);
      a = 1.0 - smoothstep(1.0 - aa, 1.0, d);
    } else if (vHollow > 0.5) {
      float ring = smoothstep(0.42, 0.42 + aa, d) * (1.0 - smoothstep(0.78, 0.78 + aa, d));
      float out1 = smoothstep(0.78, 0.78 + aa, d) * (1.0 - smoothstep(1.0 - aa, 1.0, d));
      c = mix(vec3(0.02, 0.03, 0.04), vColor, ring / max(ring + out1 * 0.7, 1e-3));
      a = ring * 0.9 + out1 * 0.55;
    } else {
      float core = 1.0 - smoothstep(0.66, 0.66 + aa, d);
      c = mix(vec3(0.02, 0.03, 0.04), vColor, core);
      a = core + (1.0 - core) * (1.0 - smoothstep(1.0 - aa, 1.0, d)) * 0.8;
    }
    float fog = smoothstep(uFogNear, uFogFar, length(vPosW - cameraPosition));
    a *= uAmt * (1.0 - fog);
    if (a < 0.003) discard;
    gl_FragColor = vec4(c * a, a);
  }
`;

export async function initValle({
  canvas, zona = null, base = null,
  onSelectPredio, onSelectCaso, onRouteStop, onRouteProgress,
} = {}) {
  if (!canvas) throw new Error('initValle: falta el canvas');
  const absDir = (b) => new URL(b.endsWith('/') ? b : b + '/', location.href).href;

  // ---------- renderer / scene (created once, reused across zones) ----------
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, premultipliedAlpha: true, powerPreference: 'high-performance' });
  renderer.debug.checkShaderErrors = false; // no synchronous shader-log queries (see compileAsync below)
  renderer.setClearColor(BG, 0);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(38, 1, 0.05, 800);
  const dpr = () => Math.min(2, window.devicePixelRatio || 1);

  const uniforms = {
    uTexA: { value: null },
    uTexB: { value: null },
    uMix: { value: 0 },
    uImgRect: { value: new THREE.Vector4(0, 0, 1, 1) },
    uOverlay: { value: null },
    uOverlayAmt: { value: 0 },
    uFogNear: { value: 100 },
    uFogFar: { value: 200 },
    uGrid: { value: 0.5 },
    uLightDir: { value: new THREE.Vector3(-0.6, 0.9, 0.35) },
  };
  const terrainMat = new THREE.ShaderMaterial({ uniforms, vertexShader: TERRAIN_VS, fragmentShader: TERRAIN_FS });
  const routeUniforms = {
    uDrawn: { value: 0 },
    uAmt: { value: 0 },
    uDash: { value: 0.22 },
    uColor: { value: new THREE.Color(0x45d6ee) },
    uFogNear: uniforms.uFogNear,
    uFogFar: uniforms.uFogFar,
  };
  const routeMat = new THREE.ShaderMaterial({
    uniforms: routeUniforms, vertexShader: ROUTE_VS, fragmentShader: ROUTE_FS,
    transparent: true, depthWrite: false, premultipliedAlpha: true, side: THREE.DoubleSide,
    polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2,
  });
  const dotUniforms = {
    uDpr: { value: dpr() }, uScale: { value: 1 }, uAmt: { value: 0 },
    uFogNear: uniforms.uFogNear, uFogFar: uniforms.uFogFar,
  };
  const dotMat = new THREE.ShaderMaterial({
    uniforms: dotUniforms, vertexShader: DOT_VS, fragmentShader: DOT_FS,
    transparent: true, depthWrite: false, depthTest: false, premultipliedAlpha: true,
  });

  // ---------- HTML layer ----------
  const host = canvas.parentElement || document.body;
  if (getComputedStyle(host).position === 'static') host.style.position = 'relative';
  const layer = document.createElement('div');
  layer.className = 'valle-layer';
  Object.assign(layer.style, {
    position: 'absolute', inset: '0', zIndex: '3', pointerEvents: 'none', overflow: 'hidden',
    opacity: '0', visibility: 'hidden', transition: 'opacity .45s ease', font: "500 11px/1.2 'IBM Plex Mono',ui-monospace,monospace",
  });
  const vignette = document.createElement('div');
  vignette.setAttribute('aria-hidden', 'true');
  Object.assign(vignette.style, {
    position: 'absolute', inset: '0', zIndex: '1', pointerEvents: 'none', opacity: '0', visibility: 'hidden', transition: 'opacity .7s ease',
    background: 'radial-gradient(ellipse 80% 75% at 50% 48%, rgba(5,8,11,0) 60%, rgba(5,8,11,0.35) 100%)',
  });
  canvas.after(vignette, layer);
  canvas.style.pointerEvents = 'none';
  function fadeEl(el, on, ms) {
    clearTimeout(el._hideT);
    el.style.opacity = on ? '1' : '0';
    if (on) el.style.visibility = 'visible';
    else el._hideT = setTimeout(() => { el.style.visibility = 'hidden'; }, ms);
  }
  const showLayer = (on) => fadeEl(layer, on, 480);
  const showVignette = (on) => fadeEl(vignette, on, 720);
  const OFF = 'translate(-9999px,-9999px)';

  const headDot = document.createElement('div');
  Object.assign(headDot.style, {
    position: 'absolute', left: '-5px', top: '-5px', width: '10px', height: '10px', borderRadius: '50%',
    background: '#eaffff', boxShadow: '0 0 0 3px rgba(69,214,238,.35), 0 0 16px 4px rgba(69,214,238,.85)',
    transform: OFF, opacity: '0', transition: 'opacity .3s', zIndex: '2',
  });
  layer.appendChild(headDot);
  const selLabel = document.createElement('div');
  Object.assign(selLabel.style, {
    position: 'absolute', left: '0', top: '0', transform: OFF, whiteSpace: 'nowrap', zIndex: '4',
    padding: '6px 8px', background: 'rgba(5,8,11,.88)', border: '1px solid #fff', color: '#e8eef0',
    letterSpacing: '.04em', lineHeight: '1.45', boxShadow: '0 6px 24px rgba(0,0,0,.45)',
  });
  layer.appendChild(selLabel);
  const tip = document.createElement('div');
  Object.assign(tip.style, {
    position: 'absolute', left: '0', top: '0', transform: OFF, whiteSpace: 'nowrap', zIndex: '5',
    padding: '4px 7px', background: 'rgba(5,8,11,.88)', border: '1px solid rgba(232,238,240,.35)', color: '#e8eef0',
    letterSpacing: '.05em',
  });
  layer.appendChild(tip);

  // ---------- per-zone state (rebuilt by build()) ----------
  let zonaId = null;
  let manifest = null, years = [], lastYear = 0, IB = null;
  let features = [], byId = new Map(), paradas = [], routeCoords = [], ruta = null;
  let casos = []; // [{exp, predioId|null, lon, lat, el, world}]
  let casoByPredio = new Map();
  let SB = null, FB = null, W = 1, H = 1, dLon = 1, dLat = 1, span = 1, EXAG = 2.2;
  let toUV = () => [0, 0], fromUV = () => [0, 0], heightAt = () => 0;
  let terrain = null, routeMesh = null, dots = null;
  let routeLen = 0, routeSamples = [];
  let ovCanvas = null, ovCtx = null, ovTex = null, OW = 1, OH = 1, pxPerKm = 1;
  let satTex = {}, satLoading = {};
  let stops = [], startPin = null, zoneEls = [];
  let outsideImagery = [];
  let focusPts = null, focusArr = null; // focusArr: the same points as a flat xyz array (fitHome hot loop)
  let sortedFeatures = [], caseFeatures = [], idIndex = new Map(); // overlay paint order, case predios, id -> index in `features`

  const uvToWorld = (u, v, lift = 0) => new THREE.Vector3((u - 0.5) * W, heightAt(u, v) + lift, (0.5 - v) * H);
  const llToWorld = (lon, lat, lift = 0) => { const [u, v] = toUV(lon, lat); return uvToWorld(u, v, lift); };

  // ---------- view state ----------
  const reduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const state = { year: 0, routeT: 0, routeOn: true };
  let dirty = true;
  let overlayAmt = 0, routeAmt = 0;
  let routePlay = null;
  let hoverId = null;
  let selectedId = null;
  let active = false, entered = false, rafId = 0, prev = performance.now();
  let pendingFocus = null; // predio id to focus once the descent finishes

  // camera: current target + polar angle + radius; "home" frames the whole zone, "focus" one predio/case
  const camT = new THREE.Vector3();
  const cam = { pol: THREE.MathUtils.degToRad(25), r: 10 };
  const FINAL_POL = THREE.MathUtils.degToRad(50);
  const START_POL = THREE.MathUtils.degToRad(25);
  const FOCUS_POL = THREE.MathUtils.degToRad(48);
  const home = { target: new THREE.Vector3(), r: 10 };
  let focus = null; // { id, target: Vector3, r }
  const insets = { right: 0, bottom: 0 };
  const startPose = () => ({ pol: START_POL, r: home.r * 2.6, target: home.target.clone() });
  const homePose = () => ({ pol: FINAL_POL, r: home.r, target: home.target.clone() });

  function placeCameraWith(t, pol, r) {
    camera.position.set(t.x, t.y + r * Math.cos(pol), t.z + r * Math.sin(pol));
    camera.lookAt(t);
  }
  function placeCamera() {
    placeCameraWith(camT, cam.pol, cam.r);
    uniforms.uFogNear.value = cam.r + span * 0.45;
    uniforms.uFogFar.value = cam.r + span * 1.2;
    // dots slightly larger when zoomed in on a predio
    dotUniforms.uScale.value = clamp(Math.sqrt(home.r / Math.max(cam.r, 0.1)) * 0.9, 1, 1.6);
  }
  const tmpV = new THREE.Vector3();
  const fitVP = new THREE.Matrix4();
  function project(v) {
    tmpV.copy(v).project(camera);
    return { x: (tmpV.x * 0.5 + 0.5) * host.clientWidth, y: (-tmpV.y * 0.5 + 0.5) * host.clientHeight, ok: tmpV.z < 1 };
  }
  function viewport() {
    const fw = Math.max(1, host.clientWidth), fh = Math.max(1, host.clientHeight);
    const small = fw < 700;
    const m = { l: small ? 20 : 48, r: small ? 20 : (insets.right ? 150 : 60), t: small ? 90 : 120, b: small ? 24 : 60 };
    const vx0 = m.l, vx1 = Math.max(vx0 + 50, fw - Math.min(insets.right, fw * 0.6) - m.r);
    const vy0 = m.t, vy1 = Math.max(vy0 + 50, fh - Math.min(insets.bottom, fh * 0.6) - m.b);
    return { fw, fh, vx0, vx1, vy0, vy1 };
  }
  function buildFocusPts() {
    const pts = [];
    stops.forEach((st) => pts.push(st.world));
    if (startPin) pts.push(startPin.world);
    for (let i = 0; i < routeSamples.length; i += 8) pts.push(routeSamples[i].p);
    features.forEach((f) => { pts.push(llToWorld(f.properties.centroid[0], f.properties.centroid[1])); });
    casos.forEach((c) => pts.push(c.world));
    if (!pts.length && FB) [[FB.w, FB.s], [FB.e, FB.s], [FB.w, FB.n], [FB.e, FB.n]].forEach(([x, y]) => pts.push(llToWorld(x, y)));
    return pts;
  }
  // numeric fit: project focus points with the final pose and search radius + target that fill the visible area
  function fitHome() {
    if (!SB) return;
    if (!focusPts) {
      focusPts = buildFocusPts();
      focusArr = new Float32Array(focusPts.length * 3);
      focusPts.forEach((v, i) => { focusArr[i * 3] = v.x; focusArr[i * 3 + 1] = v.y; focusArr[i * 3 + 2] = v.z; });
    }
    const { fw, fh, vx0, vx1, vy0, vy1 } = viewport();
    const vw = vx1 - vx0, vh = vy1 - vy0;
    const [cu, cv] = toUV((FB.w + FB.e) / 2, (FB.s + FB.n) / 2);
    const t = uvToWorld(cu, cv); t.y = heightAt(cu, cv) * 0.6;
    // terrain perimeter: only constrains the horizontal fit, so an elongated zone (Z1 ~3.2:1) never
    // spills past the left edge / under the side panel; its top/bottom may run off-screen as backdrop
    const edgePts = [];
    // (desktop only: on a phone the zone is tiny already, so the terrain may run past the edges)
    if (host.clientWidth >= 700) for (let i = 0; i <= 8; i++) { const k = i / 8; edgePts.push(uvToWorld(k, 0), uvToWorld(k, 1), uvToWorld(0, k), uvToWorld(1, k)); }
    // case tags hang up-left of their ring (≈ tag width + stem); keep them ≥ 24 px inside the visible area
    // (x: tag left ≥ 24 px from the screen edge; y: tag top stays below the header margin vy0)
    const tagPad = (c) => ({ l: Math.max(60, (c.tag && c.tag.offsetWidth) || 78) + 14 + 24 - vx0, t: ((c.tag && c.tag.offsetHeight) || 16) + 22 });
    const box = (r) => {
      placeCameraWith(t, FINAL_POL, r); camera.updateMatrixWorld();
      let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
      // box() runs ~88 times per fit and there is one focus point per predio: project them inline
      // (same maths as project(), minus a Vector3 and two layout reads per point)
      fitVP.multiplyMatrices(camera.projectionMatrix, camera.matrixWorldInverse);
      const e = fitVP.elements;
      for (let i = 0; i < focusArr.length; i += 3) {
        const X = focusArr[i], Y = focusArr[i + 1], Z = focusArr[i + 2];
        const w = e[3] * X + e[7] * Y + e[11] * Z + e[15];
        const qx = ((e[0] * X + e[4] * Y + e[8] * Z + e[12]) / w * 0.5 + 0.5) * fw;
        const qy = (-(e[1] * X + e[5] * Y + e[9] * Z + e[13]) / w * 0.5 + 0.5) * fh;
        if (qx < x0) x0 = qx; if (qx > x1) x1 = qx; if (qy < y0) y0 = qy; if (qy > y1) y1 = qy;
      }
      for (const c of casos) {
        const q = project(c.world), p = tagPad(c);
        if (!q.ok) continue;
        x0 = Math.min(x0, q.x - Math.max(0, p.l)); y0 = Math.min(y0, q.y - p.t);
      }
      for (const v of edgePts) {
        const q = project(v);
        if (!q.ok) continue;
        x0 = Math.min(x0, q.x); x1 = Math.max(x1, q.x);
      }
      return { x0, x1, y0, y1 };
    };
    let r = span * 0.7;
    for (let iter = 0; iter < 4; iter++) {
      let lo = 0.3, hi = span * 4;
      for (let k = 0; k < 22; k++) {
        const mid = (lo + hi) / 2, bb = box(mid);
        if (bb.x1 - bb.x0 <= vw && bb.y1 - bb.y0 <= vh) hi = mid; else lo = mid;
      }
      r = hi;
      const bb = box(r);
      const dxp = (bb.x0 + bb.x1) / 2 - (vx0 + vx1) / 2, dyp = (bb.y0 + bb.y1) / 2 - (vy0 + vy1) / 2;
      const wpp = (2 * r * Math.tan(THREE.MathUtils.degToRad(camera.fov) / 2)) / fh;
      t.x += dxp * wpp;
      t.z += (dyp * wpp) / Math.cos(FINAL_POL);
      if (Math.abs(dxp) < 2 && Math.abs(dyp) < 2) break;
    }
    home.target.copy(t);
    home.r = Math.max(r, 0.8);
    placeCamera();
  }
  // focus pose for one predio / case point: ~2.5 km wide view, centred in the visible area (minus side panel)
  function focusPoseFor(lon, lat, f) {
    let ext = 0.6;
    if (f) { const b = f._bb; ext = Math.max(ext, (b.e - b.w) * 111.32 * Math.cos(lat * Math.PI / 180) * 3, (b.n - b.s) * 110.54 * 3); }
    const r = clamp(ext * 2.4, 1.6, Math.max(1.6, home.r * 0.6));
    const [u, v] = toUV(lon, lat);
    const t = uvToWorld(u, v);
    const { fw, fh, vx0, vx1, vy0, vy1 } = viewport();
    const wpp = (2 * r * Math.tan(THREE.MathUtils.degToRad(camera.fov) / 2)) / fh;
    const dxp = fw / 2 - (vx0 + vx1) / 2, dyp = fh / 2 - (vy0 + vy1) / 2;
    t.x += dxp * wpp;
    t.z += (dyp * wpp) / Math.cos(FOCUS_POL);
    return { pol: FOCUS_POL, r, target: t };
  }

  let anim = null;
  function cancelAnim() {
    if (!anim) return;
    const { resolve, kind } = anim;
    anim = null;
    if (kind === 'enter') finishAnim('enter'); // a focus interrupting the descent still counts as entered
    resolve();
  }
  function startAnim(to, dur, kind) {
    cancelAnim();
    return new Promise((resolve) => {
      if (reduced || dur <= 0) {
        cam.pol = to.pol; cam.r = to.r; if (to.target) camT.copy(to.target);
        placeCamera(); dirty = true; resolve(); finishAnim(kind); return;
      }
      anim = { from: { pol: cam.pol, r: cam.r, target: camT.clone() }, to, t0: performance.now(), dur, kind, resolve };
    });
  }
  function stepAnim(now) {
    if (!anim) return;
    const k = clamp((now - anim.t0) / anim.dur, 0, 1);
    const e = easeInOutCubic(k);
    cam.pol = anim.from.pol + (anim.to.pol - anim.from.pol) * e;
    cam.r = anim.from.r + (anim.to.r - anim.from.r) * e;
    if (anim.to.target) camT.lerpVectors(anim.from.target, anim.to.target, e);
    dirty = true;
    if (k >= 1) {
      const { resolve, kind } = anim;
      anim = null;
      resolve();
      finishAnim(kind);
    }
  }
  function finishAnim(kind) {
    if (kind === 'enter') {
      entered = true; showLayer(true); canvas.style.pointerEvents = 'auto';
      if (pendingFocus != null) { const id = pendingFocus; pendingFocus = null; doFocus(id); }
    } else if (kind === 'exit') { setActive(false); renderer.clear(); }
  }

  // ---------- resize ----------
  function resize() {
    const w = Math.max(1, host.clientWidth), h = Math.max(1, host.clientHeight);
    renderer.setPixelRatio(dpr());
    dotUniforms.uDpr.value = dpr();
    renderer.setSize(w, h, false);
    canvas.style.width = '100%';
    canvas.style.height = '100%';
    camera.aspect = w / h;
    camera.fov = w / h < 0.9 ? 52 : 38;
    camera.updateProjectionMatrix();
    fitHome();
    if (focus) {
      const p = focusPoseFor(focus.lon, focus.lat, focus.f);
      focus.pose = p;
    }
    if (!anim && SB) {
      const p = entered ? (focus ? focus.pose : homePose()) : startPose();
      cam.pol = p.pol; cam.r = p.r; camT.copy(p.target);
      placeCamera();
    }
    dirty = true;
  }

  // ---------- predio overlay (canvas texture in scene UV space) ----------
  const pxOf = (lon, lat) => { const [u, v] = toUV(lon, lat); return [u * OW, (1 - v) * OH]; };
  function tracePath(f) {
    ovCtx.beginPath();
    for (const r of ringsOf(f.geometry)) {
      r.forEach(([x, y], i) => { const [px, py] = pxOf(x, y); if (i) ovCtx.lineTo(px, py); else ovCtx.moveTo(px, py); });
      ovCtx.closePath();
    }
  }
  const rgba = (c, a) => `rgba(${c[0]},${c[1]},${c[2]},${a})`;
  const kmPx = (km, min = 1) => Math.max(min, km * pxPerKm);
  // Selecting a predio used to repaint every polygon of the zone (twice) on the 4096 px canvas. The base
  // (all predios by band + case outlines) is painted once per zone; a selection change only repaints the
  // rectangles around the previously and newly selected predios.
  const selPad = () => Math.ceil(kmPx(0.08, 6) * 2 + kmPx(0.04, 2.5) + 4); // glow + stroke of the selected predio
  function paintRegion(r) {
    const m = selPad();
    const hit = (f) => !r || (f._px.x1 + m >= r.x && f._px.x0 - m <= r.x + r.w && f._px.y1 + m >= r.y && f._px.y0 - m <= r.y + r.h);
    for (const f of sortedFeatures) {
      if (f.properties.id === selectedId || !hit(f)) continue;
      const B = bandOf(f.properties.banda);
      tracePath(f);
      if (B.fill) { ovCtx.fillStyle = rgba(B.fill, B.fa); ovCtx.fill('evenodd'); }
      ovCtx.strokeStyle = B.stroke;
      ovCtx.lineWidth = kmPx(B.sw, 1.2);
      ovCtx.stroke();
    }
    // case predios: white outline on top so they read as "caso" even when their band is low / sin dato
    for (const f of caseFeatures) {
      if (f.properties.id === selectedId || !hit(f)) continue;
      tracePath(f);
      ovCtx.save();
      ovCtx.setLineDash([kmPx(0.05, 3), kmPx(0.03, 2)]);
      ovCtx.strokeStyle = 'rgba(255,255,255,.95)';
      ovCtx.lineWidth = kmPx(0.022, 1.5);
      ovCtx.stroke();
      ovCtx.restore();
    }
    const sf = selectedId && byId.get(selectedId);
    if (sf && hit(sf)) {
      const B = bandOf(sf.properties.banda);
      tracePath(sf);
      ovCtx.save();
      ovCtx.fillStyle = rgba(B.fill || [196, 206, 212], 0.6);
      ovCtx.fill('evenodd');
      ovCtx.shadowColor = B.fill ? rgba(B.fill, 0.95) : 'rgba(255,255,255,.8)';
      ovCtx.shadowBlur = kmPx(0.08, 6);
      ovCtx.strokeStyle = '#ffffff';
      ovCtx.lineWidth = kmPx(0.04, 2.5);
      ovCtx.stroke();
      ovCtx.restore();
    }
  }
  /** changedIds: predio ids whose look changed (previous + new selection); omit to repaint the whole zone. */
  function drawOverlay(changedIds = null) {
    if (!ovCtx) return;
    ovCtx.lineJoin = 'round';
    ovCtx.lineCap = 'round';
    if (!changedIds) {
      ovCtx.clearRect(0, 0, OW, OH);
      paintRegion(null);
    } else {
      const pad = selPad();
      for (const id of changedIds) {
        const f = id && byId.get(id);
        if (!f) continue;
        const r = { x: Math.floor(f._px.x0 - pad), y: Math.floor(f._px.y0 - pad), w: Math.ceil(f._px.x1 - f._px.x0 + 2 * pad) + 1, h: Math.ceil(f._px.y1 - f._px.y0 + 2 * pad) + 1 };
        ovCtx.save();
        ovCtx.beginPath();
        ovCtx.rect(r.x, r.y, r.w, r.h);
        ovCtx.clip();
        ovCtx.clearRect(r.x, r.y, r.w, r.h);
        paintRegion(r);
        ovCtx.restore();
      }
    }
    ovTex.needsUpdate = true;
    dirty = true;
  }
  /** Selection flag of the predio dots. changedIds: only those dots; omit to rewrite them all. */
  function updateDotSel(changedIds = null) {
    if (!dots) return;
    const a = dots.geometry.getAttribute('aSel');
    if (!changedIds) features.forEach((f, i) => { a.setX(i, f.properties.id === selectedId ? 1 : 0); });
    else for (const id of changedIds) { const i = idIndex.get(id); if (i != null) a.setX(i, id === selectedId ? 1 : 0); }
    a.needsUpdate = true;
  }

  // ---------- zone build ----------
  function disposeZone() {
    if (routePlay) { const r = routePlay.resolve; routePlay = null; r(); }
    if (terrain) { scene.remove(terrain); terrain.geometry.dispose(); terrain = null; }
    if (routeMesh) { scene.remove(routeMesh); routeMesh.geometry.dispose(); routeMesh = null; }
    if (dots) { scene.remove(dots); dots.geometry.dispose(); dots = null; }
    Object.values(satTex).forEach((t) => t && t.dispose());
    satTex = {}; satLoading = {};
    if (ovTex) { ovTex.dispose(); ovTex = null; }
    zoneEls.forEach((el) => el.remove());
    zoneEls = []; stops = []; startPin = null; casos = [];
    selectedId = null; hoverId = null; focus = null; pendingFocus = null; focusPts = null; focusArr = null;
    state.routeT = 0; lastT = 0; lastReached = 0;
    selLabel.style.transform = OFF; tip.style.transform = OFF; headDot.style.opacity = '0';
  }

  // normalise input: zone object from loadZona()
  async function resolveInput(z) {
    if (!z || !Array.isArray(z.predios)) throw new Error('initValle: falta la zona (objeto de loadZona)');
    const zi = z.zona || {};
    const id = String(z.id || zi.id || '').toLowerCase();
    if (!id) throw new Error('initValle: la zona no tiene id');
    const b = (z === zona && base) || zi.base || `assets/zonas/${id}/`;
    return {
      id, zi, assetBase: absDir(b), predios: z.predios,
      ruta: await withRouteGeometry(z.ruta || null, z.gpxUrl || (z.base ? z.base + 'ruta.gpx' : null)),
      casos: Array.isArray(z.casos) ? z.casos : [],
      bboxEscena: Array.isArray(zi.bbox_escena) && zi.bbox_escena.length === 4 ? zi.bbox_escena : null,
    };
  }

  let buildToken = 0;
  async function build(z) {
    const token = ++buildToken;
    const inp = await resolveInput(z);
    const assetUrl = (f) => new URL(f, inp.assetBase).href;
    const man = await loadJson(assetUrl('manifest.json')).catch((e) => { console.warn('[valle] sin manifest de imagen:', e.message); return null; });
    const yrs = man ? [...(man.years || [])].sort((a, b) => a - b) : [];
    const lastY = yrs.length ? yrs[yrs.length - 1] : 0;
    const [demImg, lastImg] = await Promise.all([
      man && man.dem ? loadImage(assetUrl(man.dem.file || 'dem.png')).catch(() => null) : Promise.resolve(null),
      lastY ? loadTextureImage(assetUrl(`sat-${lastY}.jpg`)).catch((e) => { console.warn('[valle]', e.message); return null; }) : Promise.resolve(null),
    ]);
    if (token !== buildToken) return false; // a newer setZona() won

    disposeZone();
    zonaId = inp.id;
    manifest = man;
    years = yrs;
    lastYear = lastY;
    state.year = lastY;

    // features (zone-data features are shared objects: only add a private _bb + centroid if missing)
    features = (inp.predios || []).filter((f) => ringsOf(f.geometry).length);
    features.forEach((f) => {
      const p = f.properties || (f.properties = {});
      if (p.id == null) p.id = f.id != null ? f.id : p.predio_id;
      p.id = String(p.id);
      let w = Infinity, s = Infinity, e = -Infinity, n = -Infinity;
      for (const r of ringsOf(f.geometry)) for (const [x, y] of r) { w = Math.min(w, x); e = Math.max(e, x); s = Math.min(s, y); n = Math.max(n, y); }
      Object.defineProperty(f, '_bb', { value: { w, s, e, n }, configurable: true, writable: true, enumerable: false });
      if (!Array.isArray(p.centroid)) p.centroid = [(w + e) / 2, (s + n) / 2];
      if (!BANDS[p.banda]) p.banda = 'sin_dato';
    });
    byId = new Map(features.map((f) => [String(f.properties.id), f]));
    ruta = inp.ruta;
    routeCoords = ruta && ruta.geometry && ruta.geometry.type === 'LineString' ? ruta.geometry.coordinates : [];
    paradas = (ruta && ruta.paradas) || [];

    // cases: from the zone's case list, plus any predio flagged with `caso`
    const caseList = [];
    const seen = new Set();
    for (const c of inp.casos) {
      const exp = c.expediente;
      if (!exp || seen.has(exp)) continue;
      seen.add(exp);
      let pid = c.predio_id != null ? String(c.predio_id) : null;
      if (pid && !byId.has(pid)) pid = null;
      if (!pid) { const f = features.find((ff) => ff.properties.caso === exp); if (f) pid = String(f.properties.id); }
      const lon = pid ? byId.get(pid).properties.centroid[0] : +c.lon, lat = pid ? byId.get(pid).properties.centroid[1] : +c.lat;
      if (!isFinite(lon) || !isFinite(lat)) continue;
      caseList.push({ exp, predioId: pid, lon, lat, comuna: c.comuna, data: c });
    }
    for (const f of features) {
      const exp = f.properties.caso;
      if (exp && !seen.has(exp)) {
        seen.add(exp);
        caseList.push({ exp, predioId: String(f.properties.id), lon: f.properties.centroid[0], lat: f.properties.centroid[1], comuna: f.properties.comuna, data: null });
      }
    }
    casoByPredio = new Map(caseList.filter((c) => c.predioId).map((c) => [c.predioId, c.exp]));

    // ---------- extents ----------
    const grow = (B, x, y) => { B.w = Math.min(B.w, x); B.e = Math.max(B.e, x); B.s = Math.min(B.s, y); B.n = Math.max(B.n, y); };
    const DB = { w: Infinity, s: Infinity, e: -Infinity, n: -Infinity };
    features.forEach((f) => { grow(DB, f._bb.w, f._bb.s); grow(DB, f._bb.e, f._bb.n); });
    routeCoords.forEach(([x, y]) => grow(DB, x, y));
    caseList.forEach((c) => grow(DB, c.lon, c.lat));
    if (ruta && ruta.inicio) grow(DB, ruta.inicio.lon, ruta.inicio.lat);
    const be = inp.bboxEscena;
    if (man && man.bbox) IB = man.bbox;
    else if (be) IB = { west: be[0], south: be[1], east: be[2], north: be[3] };
    else if (isFinite(DB.w)) IB = { west: DB.w - 0.01, south: DB.s - 0.01, east: DB.e + 0.01, north: DB.n + 0.01 };
    else throw new Error('initValle: la zona no tiene predios ni imagen');
    if (!isFinite(DB.w)) Object.assign(DB, { w: IB.west, s: IB.south, e: IB.east, n: IB.north });
    FB = { ...DB };
    { const fp = 0.003; FB.w -= fp; FB.e += fp; FB.s -= fp; FB.n += fp; }
    const pad = 0.006;
    SB = {
      w: Math.min(IB.west, DB.w - pad), e: Math.max(IB.east, DB.e + pad),
      s: Math.min(IB.south, DB.s - pad), n: Math.max(IB.north, DB.n + pad),
    };
    dLon = SB.e - SB.w; dLat = SB.n - SB.s;
    const latMid = ((SB.n + SB.s) / 2) * Math.PI / 180;
    W = dLon * 111.32 * Math.cos(latMid);
    H = dLat * 110.54;
    span = Math.max(W, H);
    EXAG = span > 20 ? 1.7 : 2.2;
    toUV = (lon, lat) => [(lon - SB.w) / dLon, (lat - SB.s) / dLat];
    fromUV = (u, v) => [SB.w + u * dLon, SB.s + v * dLat];
    const imgRect = uniforms.uImgRect.value.set(
      (IB.west - SB.w) / dLon, (IB.south - SB.s) / dLat, (IB.east - SB.w) / dLon, (IB.north - SB.s) / dLat,
    );
    uniforms.uGrid.value = span > 15 ? 2 : 0.5;
    outsideImagery = features.filter((f) => {
      const [x, y] = f.properties.centroid;
      return x < IB.west || x > IB.east || y < IB.south || y > IB.north;
    }).map((f) => f.properties.id);
    if (outsideImagery.length) console.warn(`[valle] ${outsideImagery.length} predio(s) fuera de la imagen satelital/DEM; se dibujan sobre terreno sin imagen.`);

    // ---------- imagery ----------
    if (lastImg) satTex[lastY] = texFromImage(lastImg, true);
    const blank = blankTex();
    uniforms.uTexA.value = uniforms.uTexB.value = satTex[lastY] || blank;
    uniforms.uMix.value = 0;
    ensureYear = (y) => {
      if (satTex[y]) return Promise.resolve(satTex[y]);
      if (!satLoading[y]) {
        const tk = buildToken;
        satLoading[y] = loadTextureImage(assetUrl(`sat-${y}.jpg`)).then((img) => {
          if (tk !== buildToken) return null;
          satTex[y] = texFromImage(img, true);
          dirty = true;
          return satTex[y];
        }).catch((e) => { console.warn('[valle]', e.message); delete satLoading[y]; return null; });
      }
      return satLoading[y];
    };

    // ---------- heights ----------
    heightAt = () => 0;
    if (demImg) {
      const dem = imageData(demImg, 512);
      const hs = new Float32Array(dem.w * dem.h);
      let mn = Infinity;
      for (let i = 0; i < hs.length; i++) {
        const v = dem.data[i * 4] * 256 + dem.data[i * 4 + 1] + dem.data[i * 4 + 2] / 256 - 32768;
        hs[i] = v;
        if (v < mn && v > -500) mn = v;
      }
      if (!isFinite(mn)) mn = 0;
      const sample = (iu, iv) => {
        const x = clamp(iu, 0, 1) * (dem.w - 1);
        const y = (1 - clamp(iv, 0, 1)) * (dem.h - 1);
        const x0 = Math.floor(x), y0 = Math.floor(y);
        const x1 = Math.min(x0 + 1, dem.w - 1), y1 = Math.min(y0 + 1, dem.h - 1);
        const fx = x - x0, fy = y - y0;
        const s = (xx, yy) => Math.max(hs[yy * dem.w + xx], mn);
        return (s(x0, y0) * (1 - fx) + s(x1, y0) * fx) * (1 - fy) + (s(x0, y1) * (1 - fx) + s(x1, y1) * fx) * fy;
      };
      const IW = (imgRect.z - imgRect.x) * W, IH = (imgRect.w - imgRect.y) * H;
      const ex = EXAG;
      heightAt = (u, v) => {
        const iu = (u - imgRect.x) / (imgRect.z - imgRect.x);
        const iv = (v - imgRect.y) / (imgRect.w - imgRect.y);
        const h = ((sample(iu, iv) - mn) / 1000) * ex;
        const ox = Math.max(0, -iu, iu - 1) * IW, oy = Math.max(0, -iv, iv - 1) * IH;
        const od = Math.hypot(ox, oy);
        if (od <= 0) return h;
        const k = clamp(od / 1.2, 0, 1);
        return h * (1 - k * k * (3 - 2 * k));
      };
    }
    const SEG_X = clamp(Math.round(W / 0.08), 320, 512), SEG_Y = clamp(Math.round(SEG_X * H / W), 64, 512);
    const geo = new THREE.PlaneGeometry(W, H, SEG_X, SEG_Y);
    geo.rotateX(-Math.PI / 2);
    {
      const pos = geo.attributes.position, uv = geo.attributes.uv;
      for (let i = 0; i < pos.count; i++) pos.setY(i, heightAt(uv.getX(i), uv.getY(i)));
      pos.needsUpdate = true;
      geo.computeVertexNormals();
    }
    terrain = new THREE.Mesh(geo, terrainMat);
    scene.add(terrain);

    // ---------- overlay ----------
    OW = W >= H ? OVERLAY_MAX : Math.round(OVERLAY_MAX * W / H);
    OH = W >= H ? Math.round(OVERLAY_MAX * H / W) : OVERLAY_MAX;
    pxPerKm = OW / W;
    // per-zone tables for the overlay and picking: paint order, case predios, pixel bbox, id -> index
    sortedFeatures = features.slice().sort((a, b) => BAND_ORDER.indexOf(a.properties.banda) - BAND_ORDER.indexOf(b.properties.banda));
    caseFeatures = features.filter((f) => casoByPredio.has(f.properties.id));
    idIndex = new Map(features.map((f, i) => [f.properties.id, i]));
    features.forEach((f) => {
      const [x0, y1] = pxOf(f._bb.w, f._bb.s), [x1, y0] = pxOf(f._bb.e, f._bb.n);
      Object.defineProperty(f, '_px', { value: { x0, y0, x1, y1 }, configurable: true, writable: true, enumerable: false });
    });
    if (!ovCanvas) { ovCanvas = document.createElement('canvas'); ovCtx = ovCanvas.getContext('2d'); }
    ovCanvas.width = OW; ovCanvas.height = OH;
    ovTex = new THREE.CanvasTexture(ovCanvas);
    ovTex.anisotropy = 8;
    ovTex.minFilter = THREE.LinearMipmapLinearFilter;
    ovTex.magFilter = THREE.LinearFilter;
    ovTex.wrapS = ovTex.wrapT = THREE.ClampToEdgeWrapping;
    ovTex.colorSpace = THREE.SRGBColorSpace;
    uniforms.uOverlay.value = ovTex;

    // ---------- predio dots ----------
    if (features.length) {
      const n = features.length;
      const pos = new Float32Array(n * 3), col = new Float32Array(n * 3), size = new Float32Array(n), hol = new Float32Array(n), sel = new Float32Array(n);
      const c = new THREE.Color();
      features.forEach((f, i) => {
        const [lon, lat] = f.properties.centroid;
        const p = llToWorld(lon, lat, 0.03);
        pos.set([p.x, p.y, p.z], i * 3);
        const B = bandOf(f.properties.banda);
        // the dot shader writes straight to the sRGB framebuffer (no colorspace chunk): pass sRGB values
        const srgb = {};
        c.set(BAND_HEX[f.properties.banda] || BAND_HEX.sin_dato).getRGB(srgb, THREE.SRGBColorSpace);
        col.set([srgb.r, srgb.g, srgb.b], i * 3);
        size[i] = B.size;
        hol[i] = B.hollow ? 1 : 0;
      });
      const g = new THREE.BufferGeometry();
      g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
      g.setAttribute('aColor', new THREE.BufferAttribute(col, 3));
      g.setAttribute('aSize', new THREE.BufferAttribute(size, 1));
      g.setAttribute('aHollow', new THREE.BufferAttribute(hol, 1));
      g.setAttribute('aSel', new THREE.BufferAttribute(sel, 1));
      dots = new THREE.Points(g, dotMat);
      dots.renderOrder = 3;
      dots.frustumCulled = false;
      scene.add(dots);
    }

    // ---------- route ribbon ----------
    routeLen = 0; routeSamples = [];
    const ROUTE_W = clamp(span * 0.006, 0.12, 0.28), ROUTE_LIFT = 0.025;
    routeUniforms.uDash.value = ROUTE_W * 1.4;
    if (routeCoords.length > 1) {
      const pts = [];
      const xz = routeCoords.map(([lon, lat]) => toUV(lon, lat));
      for (let i = 0; i < xz.length; i++) {
        const [u, v] = xz[i];
        if (i) {
          const [pu, pv] = xz[i - 1];
          const dk = Math.hypot((u - pu) * W, (v - pv) * H);
          const nn = Math.floor(dk / 0.05);
          for (let k = 1; k <= nn; k++) { const t = k / (nn + 1); pts.push([pu + (u - pu) * t, pv + (v - pv) * t]); }
        }
        pts.push([u, v]);
      }
      const N = pts.length;
      const pos = new Float32Array(N * 2 * 3);
      const aDist = new Float32Array(N * 2);
      const aSide = new Float32Array(N * 2);
      const idx = [];
      let d = 0;
      const kx = (u) => (u - 0.5) * W, kz = (v) => (0.5 - v) * H;
      for (let i = 0; i < N; i++) {
        const [u, v] = pts[i];
        if (i) d += Math.hypot((u - pts[i - 1][0]) * W, (v - pts[i - 1][1]) * H);
        const a = pts[Math.max(0, i - 1)], b = pts[Math.min(N - 1, i + 1)];
        let tx = kx(b[0]) - kx(a[0]), tz = kz(b[1]) - kz(a[1]);
        const tl = Math.hypot(tx, tz) || 1; tx /= tl; tz /= tl;
        const nx = -tz, nz = tx;
        const half = ROUTE_W / 2;
        for (let sgn = -1, k = 0; k < 2; sgn += 2, k++) {
          const x = kx(u) + nx * half * sgn, z = kz(v) + nz * half * sgn;
          const su = x / W + 0.5, sv = 0.5 - z / H;
          const j = i * 2 + k;
          pos[j * 3] = x; pos[j * 3 + 1] = heightAt(su, sv) + ROUTE_LIFT; pos[j * 3 + 2] = z;
          aDist[j] = d; aSide[j] = sgn;
        }
        routeSamples.push({ p: uvToWorld(u, v, ROUTE_LIFT), d });
        if (i < N - 1) { const o = i * 2; idx.push(o, o + 1, o + 2, o + 1, o + 3, o + 2); }
      }
      routeLen = d;
      const rg = new THREE.BufferGeometry();
      rg.setAttribute('position', new THREE.BufferAttribute(pos, 3));
      rg.setAttribute('aDist', new THREE.BufferAttribute(aDist, 1));
      rg.setAttribute('aSide', new THREE.BufferAttribute(aSide, 1));
      rg.setIndex(idx);
      routeMesh = new THREE.Mesh(rg, routeMat);
      routeMesh.renderOrder = 2;
      routeMesh.frustumCulled = false;
      scene.add(routeMesh);
    }

    // ---------- HTML: stops, start pin, case badges ----------
    let lastIdx = 0;
    for (const s of paradas) {
      // M8 stops: lon/lat = predio point, acceso_lon/lat = where the road reaches it (that is on the track)
      const onRoad = isFinite(+s.acceso_lon) && isFinite(+s.acceso_lat) && s.acceso_lon != null;
      const { d, i } = alongRoute(onRoad ? +s.acceso_lon : +s.lon, onRoad ? +s.acceso_lat : +s.lat, lastIdx);
      lastIdx = i;
      const el = document.createElement('button');
      el.type = 'button';
      const sb = (byId.get(String(s.predio_id)) || {}).properties?.banda || s.banda;
      const colr = BAND_HEX[sb] || CYAN;
      el.setAttribute('aria-label', `Parada ${s.orden}: predio ${s.predio_id}${sb ? ', prioridad ' + sb : ''}${s.llegada ? ', llegada ' + s.llegada : ''}`);
      el.innerHTML = `<span data-stem style="position:absolute;left:11px;top:22px;width:1px;height:16px;background:${colr};opacity:.75;transform-origin:0 0"></span>`
        + `<span data-n style="display:grid;place-items:center;width:22px;height:22px;border-radius:50%;border:1.5px solid ${colr};background:rgba(5,8,11,.86);color:${colr};font:600 11px/1 'IBM Plex Mono',ui-monospace,monospace;transition:background .25s,color .25s,box-shadow .25s">${esc(s.orden)}</span>`;
      Object.assign(el.style, {
        position: 'absolute', left: '0', top: '0', padding: '0', margin: '0', border: '0', background: 'none', zIndex: '3',
        cursor: 'pointer', pointerEvents: 'auto', transform: OFF, willChange: 'transform',
      });
      el.addEventListener('click', (ev) => { ev.stopPropagation(); pick(String(s.predio_id), true); });
      layer.appendChild(el); zoneEls.push(el);
      stops.push({ s, d, el, num: el.querySelector('[data-n]'), stem: el.querySelector('[data-stem]'), col: colr, world: llToWorld(+s.lon, +s.lat), reached: null });
    }
    if (ruta && ruta.inicio && isFinite(ruta.inicio.lon)) {
      const hIni = ruta.inicio.hora || ruta.hora_inicio;
      const el = document.createElement('div');
      el.innerHTML = `<span style="display:block;width:10px;height:10px;margin:0 auto;border-radius:2px;background:${CYAN};box-shadow:0 0 0 3px rgba(69,214,238,.25),0 0 12px rgba(69,214,238,.8);transform:rotate(45deg)"></span>`
        + `<span style="display:block;margin-top:7px;white-space:nowrap;padding:3px 6px;background:rgba(5,8,11,.78);border:1px solid rgba(69,214,238,.5);color:${CYAN};letter-spacing:.06em">INICIO · ${esc(String(ruta.inicio.nombre || '').toUpperCase())}${hIni ? ' · ' + esc(hIni) : ''}</span>`;
      Object.assign(el.style, { position: 'absolute', left: '0', top: '0', transform: OFF, textAlign: 'center', zIndex: '1' });
      layer.appendChild(el); zoneEls.push(el);
      startPin = { el, world: llToWorld(ruta.inicio.lon, ruta.inicio.lat, 0.01) };
    }
    for (const c of caseList) {
      const el = document.createElement('button');
      el.type = 'button';
      el.setAttribute('aria-label', `Caso sancionado por la DGA ${c.exp}${c.comuna ? ', ' + titleCase(c.comuna) : ''}`);
      el.title = `${c.exp}${c.comuna ? ' · ' + titleCase(c.comuna) : ''} · caso sancionado por la DGA`;
      el.innerHTML = `<span data-ring style="position:absolute;left:0;top:0;width:18px;height:18px;border-radius:50%;border:2px solid ${CASE_COL};box-shadow:0 0 0 1px rgba(5,8,11,.7),0 0 10px rgba(255,255,255,.55);box-sizing:border-box"></span>`
        + `<span data-stem style="position:absolute;left:9px;top:9px;width:1px;background:rgba(255,255,255,.7);transform-origin:0 0"></span>`
        + `<span data-tag style="position:absolute;left:9px;top:9px;white-space:nowrap;padding:2px 5px;background:rgba(5,8,11,.88);border:1px solid ${CASE_COL};color:#fff;font:600 10px/1.2 'IBM Plex Mono',ui-monospace,monospace;letter-spacing:.06em">`
        + `<span style="opacity:.7">CASO</span> ${esc(expShort(c.exp))}</span>`;
      Object.assign(el.style, {
        position: 'absolute', left: '0', top: '0', width: '18px', height: '18px', padding: '0', margin: '-9px 0 0 -9px', border: '0', background: 'none',
        cursor: 'pointer', pointerEvents: 'auto', transform: OFF, willChange: 'transform', zIndex: '4',
      });
      el.addEventListener('click', (ev) => { ev.stopPropagation(); selectCasoInternal(c.exp, { focus: true, notify: true }); });
      el.addEventListener('pointerenter', () => { el.style.zIndex = '6'; });
      el.addEventListener('pointerleave', () => { el.style.zIndex = '4'; });
      layer.appendChild(el); zoneEls.push(el);
      casos.push({ ...c, el, ring: el.querySelector('[data-ring]'), tag: el.querySelector('[data-tag]'), stem: el.querySelector('[data-stem]'), world: llToWorld(c.lon, c.lat, 0.02) });
    }

    drawOverlay();
    updateDotSel();
    renderSelLabel();
    // camera: zone home + start pose (caller runs enter())
    entered = false;
    overlayAmt = 0; routeAmt = 0;
    if (anim) { const r = anim.resolve; anim = null; r(); }
    showLayer(false);
    canvas.style.pointerEvents = 'none';
    resize();
    const sp = startPose();
    cam.pol = sp.pol; cam.r = sp.r; camT.copy(sp.target);
    placeCamera();
    dirty = true;
    if (!active) renderer.clear();
    return true;
  }
  let ensureYear = () => Promise.resolve(null);

  // position along the route (km) of each stop: first close approach searching forward from the previous stop
  function alongRoute(lon, lat, fromIdx) {
    if (!routeSamples.length) return { d: 0, i: 0 };
    const p = llToWorld(lon, lat);
    const dist = (i) => Math.hypot(routeSamples[i].p.x - p.x, routeSamples[i].p.z - p.z);
    let best = -1;
    for (let i = fromIdx; i < routeSamples.length; i++) {
      if (dist(i) < 0.25) { best = i; while (best + 1 < routeSamples.length && dist(best + 1) <= dist(best)) best++; break; }
    }
    if (best < 0) {
      let bd = Infinity;
      for (let i = fromIdx; i < routeSamples.length; i++) { const dd = dist(i); if (dd < bd) { bd = dd; best = i; } }
    }
    if (best < 0) best = routeSamples.length - 1;
    return { d: routeSamples[best].d, i: best };
  }
  function pointAt(dk) {
    if (!routeSamples.length) return null;
    let lo = 0, hi = routeSamples.length - 1;
    while (hi - lo > 1) { const m = (lo + hi) >> 1; if (routeSamples[m].d < dk) lo = m; else hi = m; }
    const a = routeSamples[lo], b = routeSamples[hi];
    const t = clamp((dk - a.d) / ((b.d - a.d) || 1), 0, 1);
    return a.p.clone().lerp(b.p, t);
  }

  // ---------- labels ----------
  const rangeTxt = (p) => {
    const lo = p.m3_estimado_min, hi = p.m3_estimado_max;
    if (lo == null || hi == null || !isFinite(lo) || !isFinite(hi)) return null;
    return `${fmtMil(lo)}–${fmtMil(hi)} mil m³/año`;
  };
  function renderSelLabel() {
    const f = selectedId && byId.get(selectedId);
    if (!f) { selLabel.style.transform = OFF; return; }
    const p = f.properties, B = bandOf(p.banda), col = BAND_HEX[p.banda] || BAND_HEX.sin_dato;
    const stop = paradas.find((s) => String(s.predio_id) === selectedId);
    const exp = casoByPredio.get(selectedId) || p.caso;
    const rng = rangeTxt(p);
    const where = [p.rol ? `rol ${esc(p.rol)}` : null, p.comuna ? esc(titleCase(p.comuna)) : null,
      isFinite(p.area_ha) && p.area_ha != null ? `${(+p.area_ha).toLocaleString('es-CL', { maximumFractionDigits: 1 })} ha` : null].filter(Boolean).join(' · ');
    selLabel.style.borderColor = exp ? '#fff' : col;
    selLabel.innerHTML = `<div style="display:flex;gap:8px;align-items:center"><b style="font-weight:600;color:#fff">${esc(p.id)}</b>`
      + `<span style="color:${col}">● ${B.label}</span>`
      + (exp ? `<span style="color:#fff;border:1px solid #fff;padding:0 4px">CASO ${esc(expShort(exp))}</span>` : '')
      + (stop ? `<span style="color:${CYAN}">PARADA ${esc(stop.orden)}</span>` : '') + '</div>'
      + (where ? `<div style="color:#9fb0b6">${where}</div>` : '')
      + (rng ? `<div style="color:#9fb0b6">consumo est.: <span style="color:#e8eef0">${rng}</span>${p.confianza ? ` · conf. ${esc(p.confianza)}` : ''}</div>` : '');
  }

  // ---------- projection of HTML elements ----------
  function updateHtml() {
    const drawn = state.routeT * routeLen;
    const showStops = state.routeOn && entered;
    const placed = [];
    for (const st of stops) {
      const g = project(st.world);
      let bx = g.x, by = g.y - 16 - 11;
      for (const q of placed) {
        if (Math.abs(q.x - bx) < 25 && Math.abs(q.y - by) < 25) bx = q.x + (bx >= q.x ? 25 : -25);
      }
      placed.push({ x: bx, y: by });
      st.el.style.transform = showStops && g.ok ? `translate(${(bx - 11).toFixed(1)}px, ${(by - 11).toFixed(1)}px)` : OFF;
      const dx = g.x - bx, dy = g.y - (by + 11);
      st.stem.style.height = `${Math.max(0, Math.hypot(dx, dy)).toFixed(1)}px`;
      st.stem.style.transform = `rotate(${(Math.atan2(dx, dy) * -180 / Math.PI).toFixed(1)}deg)`;
      const reached = drawn >= st.d - 0.05 && state.routeT > 0;
      const sel = String(st.s.predio_id) === selectedId;
      if (reached !== st.reached || sel !== st.sel) {
        st.reached = reached; st.sel = sel;
        st.num.style.background = reached ? st.col : 'rgba(5,8,11,.86)';
        st.num.style.color = reached ? '#05080b' : st.col;
        st.num.style.boxShadow = sel ? `0 0 0 3px #fff, 0 0 14px ${st.col}` : reached ? `0 0 12px ${st.col}` : 'none';
      }
    }
    // case badges: ring on the ground point + tag offset up-left (stacked when close; stops sit up-right)
    // stop badges already placed count as obstacles for the case tags
    const tags = showStops ? placed.map((q) => ({ x: q.x - 13, y: q.y - 13, w: 26, h: 26 })) : [];
    if (startPin) {
      const g = project(startPin.world);
      const on = showStops && g.ok;
      startPin.el.style.transform = on ? `translate(calc(${g.x.toFixed(1)}px - 50%), ${(g.y - 5).toFixed(1)}px)` : OFF;
      if (on) { const w = startPin.el.offsetWidth || 200, h = startPin.el.offsetHeight || 30; tags.push({ x: g.x - w / 2, y: g.y - 5, w, h, pin: true }); }
    }
    const maxX = host.clientWidth - Math.min(insets.right, host.clientWidth * 0.6) - 4;
    const order = casos.map((c) => ({ c, g: project(c.world) })).sort((a, b) => a.g.x - b.g.x);
    for (const { c, g } of order) {
      if (!entered || !g.ok) { c.el.style.transform = OFF; continue; }
      const tw = c.tag.offsetWidth || 78, th = c.tag.offsetHeight || 16;
      let tx = -tw - 14, ty = -th - 22;
      if (g.x + tx < 8) tx = 14; // flip to the right near the left edge
      const hitAt = (x, y) => tags.find((q) => g.x + x < q.x + q.w + 4 && g.x + x + tw + 4 > q.x && g.y + y < q.y + q.h + 3 && g.y + y + th + 3 > q.y);
      // try up-left / up-right / down-left / down-right, then stack upwards
      const cands = [[tx, ty], [14, ty], [tx, 14], [14, 14]];
      const free = cands.find(([x, y]) => g.x + x >= 4 && g.x + x + tw <= maxX && !hitAt(x, y))
        || cands.find(([x, y]) => g.x + x >= 4 && g.x + x + tw <= maxX);
      if (free) [tx, ty] = free;
      else for (let k = 0; k < 8; k++) { const hit = hitAt(tx, ty); if (!hit) break; ty = hit.y - g.y - th - 4; }
      tags.push({ x: g.x + tx, y: g.y + ty, w: tw, h: th });
      c.el.style.transform = `translate(${g.x.toFixed(1)}px, ${g.y.toFixed(1)}px)`;
      c.tag.style.transform = `translate(${tx.toFixed(1)}px, ${ty.toFixed(1)}px)`;
      // stem from the ring edge to the tag's bottom-right corner
      const ex = tx < 0 ? tx + tw : tx, ey = ty < 0 ? ty + th : ty;
      const len = Math.hypot(ex, ey), ang = Math.atan2(ey, ex);
      c.stem.style.height = '1px';
      c.stem.style.width = `${Math.max(0, len - 9).toFixed(1)}px`;
      c.stem.style.transform = `rotate(${(ang * 180 / Math.PI).toFixed(1)}deg) translateX(9px)`;
      const sel = c.predioId ? c.predioId === selectedId : selectedCaso === c.exp;
      if (sel !== c.sel) {
        c.sel = sel;
        c.ring.style.boxShadow = sel ? '0 0 0 3px rgba(255,255,255,.35),0 0 16px rgba(255,255,255,.9)' : '0 0 0 1px rgba(5,8,11,.7),0 0 10px rgba(255,255,255,.55)';
        c.tag.style.background = sel ? '#fff' : 'rgba(5,8,11,.88)';
        c.tag.style.color = sel ? '#05080b' : '#fff';
      }
    }
    const head = showStops && state.routeT > 0 && state.routeT < 1 ? pointAt(drawn) : null;
    if (head) {
      const g = project(head);
      headDot.style.transform = `translate(${g.x.toFixed(1)}px, ${g.y.toFixed(1)}px)`;
      headDot.style.opacity = '1';
    } else headDot.style.opacity = '0';
    const f = selectedId && byId.get(selectedId);
    let lp = null;
    if (f && entered) {
      const [lon, lat] = f.properties.centroid;
      const g = project(llToWorld(lon, lat));
      if (g.ok) {
        const w = selLabel.offsetWidth || 180, h = selLabel.offsetHeight || 56;
        const xMax = host.clientWidth - Math.min(insets.right, host.clientWidth * 0.6) - w - 8;
        const yMax = host.clientHeight - Math.min(insets.bottom, host.clientHeight * 0.6) - h - 8;
        // below-right, below-left, above-right, above-left of the predio centroid
        const cands = [[g.x + 18, g.y + 18], [g.x - w - 18, g.y + 18], [g.x + 18, g.y - h - 18], [g.x - w - 18, g.y - h - 18]]
          .map(([x, y]) => [clamp(x, 8, Math.max(8, xMax)), clamp(y, 8, Math.max(8, yMax))]);
        const hits = (x, y, q) => x < q.x + q.w + 6 && x + w + 6 > q.x && y < q.y + q.h + 6 && y + h + 6 > q.y;
        // the route INICIO label must never be covered: hide the selection label if no position clears it
        const pinRect = startPin && showStops && routeAmt > 0 ? tags.find((q) => q.pin) : null;
        lp = cands.find(([x, y]) => !tags.some((q) => hits(x, y, q)))
          || cands.find(([x, y]) => !pinRect || !hits(x, y, pinRect))
          || null;
      }
    }
    selLabel.style.transform = lp ? `translate(${lp[0].toFixed(1)}px, ${lp[1].toFixed(1)}px)` : OFF;
  }

  // ---------- picking ----------
  const raycaster = new THREE.Raycaster();
  const ndc = new THREE.Vector2();
  function predioAtClient(cx, cy) {
    if (!terrain) return null;
    const r = canvas.getBoundingClientRect();
    ndc.set(((cx - r.left) / r.width) * 2 - 1, -((cy - r.top) / r.height) * 2 + 1);
    raycaster.setFromCamera(ndc, camera);
    const hit = raycaster.intersectObject(terrain, false)[0];
    if (hit && hit.uv) {
      const [lon, lat] = fromUV(hit.uv.x, hit.uv.y);
      for (const f of features) {
        const b = f._bb;
        if (lon < b.w || lon > b.e || lat < b.s || lat > b.n) continue;
        if (pointInRings(lon, lat, ringsOf(f.geometry))) return f;
      }
    }
    // fall back to the nearest centroid dot on screen (predios are tiny at zone scale)
    const hr = host.getBoundingClientRect();
    const mx = cx - hr.left, my = cy - hr.top;
    let best = null, bd = 11 * dotUniforms.uScale.value;
    if (!dots) return best;
    // runs on every pointer move: reuse the dot positions (centroids on the terrain) instead of
    // building a Vector3 per predio per frame
    const pa = dots.geometry.getAttribute('position').array;
    const hw = hr.width, hh = hr.height;
    for (let i = 0; i < features.length; i++) {
      tmpV.set(pa[i * 3], pa[i * 3 + 1], pa[i * 3 + 2]).project(camera);
      if (tmpV.z >= 1) continue;
      const d = Math.hypot((tmpV.x * 0.5 + 0.5) * hw - mx, (-tmpV.y * 0.5 + 0.5) * hh - my);
      if (d < bd) { bd = d; best = features[i]; }
    }
    return best;
  }
  let selectedCaso = null;
  function pick(id, notify) {
    const nid = id == null ? null : String(id);
    if (nid && !byId.has(nid)) return false;
    if (nid !== selectedId) {
      const changed = [selectedId, nid];
      selectedId = nid;
      drawOverlay(changed);
      updateDotSel(changed);
      renderSelLabel();
      stops.forEach((st) => { st.sel = null; });
    }
    selectedCaso = nid ? casoByPredio.get(nid) || null : null;
    if (!nid) casos.forEach((x) => { x.sel = null; });
    if (notify && typeof onSelectPredio === 'function') {
      try { onSelectPredio(nid ? byId.get(nid).properties : null); } catch (e) { console.error(e); }
    }
    dirty = true;
    return true;
  }
  function doFocus(target) {
    // target: predio id or {lon, lat}
    let f = null, lon, lat;
    if (target && typeof target === 'object') { lon = target.lon; lat = target.lat; f = target.predioId ? byId.get(target.predioId) : null; }
    else { f = byId.get(String(target)); if (!f) return Promise.resolve(); [lon, lat] = f.properties.centroid; }
    if (!isFinite(lon) || !isFinite(lat)) return Promise.resolve();
    const pose = focusPoseFor(lon, lat, f);
    focus = { lon, lat, f, pose };
    if (!active) { cam.pol = pose.pol; cam.r = pose.r; camT.copy(pose.target); placeCamera(); return Promise.resolve(); }
    return startAnim(pose, 1500, 'focus');
  }
  function selectCasoInternal(exp, { focus: doF = false, notify = false } = {}) {
    const c = casos.find((x) => x.exp === exp);
    if (!c) return false;
    if (c.predioId) pick(c.predioId, false); else pick(null, false);
    selectedCaso = exp;
    casos.forEach((x) => { x.sel = null; });
    if (doF) {
      if (entered) doFocus(c.predioId || { lon: c.lon, lat: c.lat, predioId: null });
      else pendingFocus = c.predioId || { lon: c.lon, lat: c.lat, predioId: null };
    }
    if (notify && typeof onSelectCaso === 'function') { try { onSelectCaso(exp); } catch (e) { console.error(e); } }
    dirty = true;
    return true;
  }

  let pendingMove = null;
  canvas.addEventListener('pointermove', (ev) => { pendingMove = { x: ev.clientX, y: ev.clientY }; });
  canvas.addEventListener('pointerleave', () => { pendingMove = null; setHover(null); });
  function setHover(f, x, y) {
    const id = f ? String(f.properties.id) : null;
    canvas.style.cursor = f ? 'pointer' : '';
    if (!f) { tip.style.transform = OFF; hoverId = null; return; }
    if (id !== hoverId) {
      hoverId = id;
      const p = f.properties, col = BAND_HEX[p.banda] || BAND_HEX.sin_dato;
      const exp = casoByPredio.get(id);
      tip.style.borderColor = col;
      tip.innerHTML = `<b style="font-weight:600;color:#fff">${esc(p.id)}</b> <span style="color:${col}">· ${bandOf(p.banda).label}</span>`
        + (exp ? ` <span style="color:#fff">· CASO ${esc(expShort(exp))}</span>` : '');
    }
    const r = host.getBoundingClientRect();
    tip.style.transform = `translate(${(x - r.left + 14).toFixed(1)}px, ${(y - r.top + 14).toFixed(1)}px)`;
  }
  let downAt = null;
  canvas.addEventListener('pointerdown', (ev) => { downAt = { x: ev.clientX, y: ev.clientY }; });
  canvas.addEventListener('click', (ev) => {
    if (!active || anim || !entered) return;
    if (downAt && Math.hypot(ev.clientX - downAt.x, ev.clientY - downAt.y) > 6) return;
    const f = predioAtClient(ev.clientX, ev.clientY);
    pick(f ? f.properties.id : null, true);
  });

  // ---------- route callbacks ----------
  let lastT = 0, lastReached = 0;
  function checkRoute() {
    const t = state.routeT;
    if (t === lastT) return;
    const forward = t > lastT;
    lastT = t;
    if (typeof onRouteProgress === 'function') { try { onRouteProgress(t); } catch (e) { console.error(e); } }
    const drawn = t * routeLen;
    let n = 0;
    while (n < stops.length && t > 0 && (drawn >= stops[n].d - 0.05 || t >= 0.999)) n++;
    if (forward && n > lastReached && typeof onRouteStop === 'function') {
      for (let i = lastReached; i < n; i++) {
        try { onRouteStop(stops[i].s.orden, stops[i].s); } catch (e) { console.error(e); }
      }
    }
    lastReached = n;
  }

  // ---------- loop ----------
  function setActive(on) {
    on = !!on;
    if (on === active) return;
    active = on;
    if (on) {
      prev = performance.now();
      showVignette(true);
      if (entered) { showLayer(true); canvas.style.pointerEvents = 'auto'; }
      dirty = true;
      rafId = requestAnimationFrame(frame);
    } else {
      cancelAnimationFrame(rafId);
      rafId = 0;
      showLayer(false);
      showVignette(false);
      canvas.style.pointerEvents = 'none';
      setHover(null);
    }
  }
  function frame(now) {
    if (!active) return;
    rafId = requestAnimationFrame(frame);
    const dt = Math.min(0.1, (now - prev) / 1000);
    prev = now;
    stepAnim(now);
    if (!active || !terrain) return;

    const ovTarget = anim && anim.kind === 'exit' ? 0 : 1;
    if (overlayAmt !== ovTarget) { overlayAmt = clamp(overlayAmt + Math.sign(ovTarget - overlayAmt) * dt * 1.4, 0, 1); dirty = true; }
    const rTarget = state.routeOn && entered && !(anim && anim.kind === 'exit') ? 1 : 0;
    if (routeAmt !== rTarget) { routeAmt = clamp(routeAmt + Math.sign(rTarget - routeAmt) * dt * 3, 0, 1); dirty = true; }

    if (routePlay) {
      const k = clamp((now - routePlay.t0) / routePlay.dur, 0, 1);
      state.routeT = routePlay.from + (routePlay.to - routePlay.from) * easeInOutSine(k);
      dirty = true;
      if (k >= 1) { const r = routePlay.resolve; routePlay = null; checkRoute(); r(); }
    }
    checkRoute();

    if (pendingMove && entered && !anim) {
      const m = pendingMove; pendingMove = null;
      setHover(predioAtClient(m.x, m.y), m.x, m.y);
    }

    if (!dirty) return;
    dirty = false;
    if (years.length) {
      let a = lastYear, b = lastYear, t = 0;
      const yf = clamp(state.year, years[0], lastYear);
      for (let i = 0; i < years.length - 1; i++) {
        if (yf <= years[i + 1]) { a = years[i]; b = years[i + 1]; t = (yf - a) / (b - a || 1); break; }
      }
      if (satTex[a] && satTex[b]) {
        uniforms.uTexA.value = satTex[a]; uniforms.uTexB.value = satTex[b]; uniforms.uMix.value = t;
      } else {
        const have = satTex[a] || satTex[b];
        if (have) { uniforms.uTexA.value = uniforms.uTexB.value = have; uniforms.uMix.value = 0; }
      }
    }
    uniforms.uOverlayAmt.value = overlayAmt;
    dotUniforms.uAmt.value = overlayAmt;
    routeUniforms.uAmt.value = routeAmt;
    routeUniforms.uDrawn.value = state.routeT >= 1 ? routeLen + 1 : state.routeT * routeLen;
    placeCamera();
    renderer.render(scene, camera);
    updateHtml();
  }

  new ResizeObserver(() => { if (SB) resize(); }).observe(host);

  // The scene is usually warmed up in the background while the national map is on screen: hand the
  // main thread back between the three heavy steps (context, zone build, first render = shader
  // compile + texture upload) so they are three short tasks instead of one ~0.5 s freeze.
  const breathe = () => new Promise((r) => setTimeout(r, 0));
  await breathe();
  await build(zona);
  await breathe();
  // Compile the shaders without blocking: three.js otherwise links them inside the first render and
  // then asks the driver for the result (checkShaderErrors), a synchronous wait of ~0.2 s per scene.
  if (typeof renderer.compileAsync === 'function') {
    try { await renderer.compileAsync(scene, camera); } catch (err) { console.warn('[3d] compileAsync:', err && err.message); }
  }
  renderer.render(scene, camera); // first frame at the START pose

  // ---------- controller ----------
  const controller = {
    get zonaId() { return zonaId; },
    get years() { return years.slice(); },
    get predios() { return features.map((f) => f.properties); },
    get ruta() { return ruta; },
    get casos() { return casos.map((c) => ({ expediente: c.exp, predio_id: c.predioId, lon: c.lon, lat: c.lat })); },
    get outsideImagery() { return outsideImagery.slice(); },
    // framed area (all predios + cases + route): use for map.flyToBounds before enter()
    get bbox() { return FB ? [FB.w, FB.s, FB.e, FB.n] : null; },
    get sceneBbox() { return SB ? [SB.w, SB.s, SB.e, SB.n] : null; }, // full 3D terrain extent
    /** switch zone (same renderer). Leaves the camera at the start pose; call enter() afterwards. */
    async setZona(zonaData) {
      const ok = await build(zonaData);
      if (ok && active) dirty = true;
      return controller;
    },
    setInsets({ right = 0, bottom = 0 } = {}) {
      insets.right = Math.max(0, +right || 0); insets.bottom = Math.max(0, +bottom || 0);
      resize();
    },
    enter({ duration = 2200 } = {}) {
      if (!active) { overlayAmt = 0; routeAmt = 0; entered = false; }
      if (!entered) { focus = null; const sp = startPose(); if (!anim) { cam.pol = sp.pol; cam.r = sp.r; camT.copy(sp.target); } }
      setActive(true);
      showVignette(true);
      return startAnim(homePose(), duration, 'enter');
    },
    exit({ duration = 1400 } = {}) {
      if (routePlay) { const r = routePlay.resolve; routePlay = null; r(); }
      entered = false;
      focus = null; pendingFocus = null;
      showLayer(false);
      showVignette(false);
      canvas.style.pointerEvents = 'none';
      setHover(null);
      if (!active) {
        if (anim) { const r = anim.resolve; anim = null; r(); }
        const sp = startPose(); cam.pol = sp.pol; cam.r = sp.r; camT.copy(sp.target); placeCamera(); renderer.clear();
        return Promise.resolve();
      }
      const sp = startPose();
      sp.target = camT.clone().lerp(home.target, 0.6);
      return startAnim(sp, duration, 'exit');
    },
    setActive,
    /** select a predio (no callback). {focus:true} also flies the camera to it (user-triggered only). */
    selectPredio(id, { focus: doF = false } = {}) {
      const ok = pick(id, false);
      if (ok && doF && id != null) { if (entered) return doFocus(id); pendingFocus = String(id); }
      return Promise.resolve();
    },
    /** highlight a case (its predio, or its point when the predio geometry is missing); no callback. */
    selectCaso(expediente, opts = {}) { return selectCasoInternal(expediente, { focus: !!opts.focus, notify: false }); },
    focusPredio(id) { if (!entered) { pendingFocus = String(id); return Promise.resolve(); } return doFocus(id); },
    /** back to the whole-zone framing; clears the 3D selection (label, outline, case highlight). */
    resetView({ duration = 1200 } = {}) {
      focus = null; pendingFocus = null;
      pick(null, false);
      selectedCaso = null;
      casos.forEach((x) => { x.sel = null; });
      if (!entered) return Promise.resolve();
      return startAnim(homePose(), duration, 'home');
    },
    isFocused() { return !!focus; },
    setRouteProgress(t) {
      if (routePlay) { const r = routePlay.resolve; routePlay = null; r(); }
      state.routeT = clamp(Number(t) || 0, 0, 1);
      dirty = true;
      if (!active) checkRoute();
    },
    playRoute({ duration = 9000 } = {}) {
      if (routePlay) { const r = routePlay.resolve; routePlay = null; r(); }
      state.routeOn = true;
      const from = state.routeT >= 0.999 ? 0 : state.routeT;
      if (reduced || !active) { state.routeT = 1; dirty = true; checkRoute(); return Promise.resolve(); }
      return new Promise((resolve) => {
        routePlay = { from, to: 1, t0: performance.now(), dur: Math.max(300, duration * (1 - from)), resolve };
      });
    },
    showRoute(on) { state.routeOn = !!on; dirty = true; },
    setYear(y) {
      if (!years.length) return;
      state.year = clamp(Number(y) || lastYear, years[0], lastYear);
      const yf = state.year;
      for (let i = 0; i < years.length; i++) {
        if (Math.abs(years[i] - yf) < 1) ensureYear(years[i]);
      }
      dirty = true;
    },
    getRouteProgress() { return state.routeT; },
  };
  return controller;
}
