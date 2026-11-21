// Caudal v2 · vista 3D del valle (Petorca): terreno DEM + imagen satelital + predios drapeados por banda de sospecha
// + ruta de inspección (línea cian drapeada sobre el terreno, paradas numeradas).
// Principio: "prioriza, no acusa" -> solo IDs de predio y rangos de m³, nunca dueños ni cifras únicas.
// Cámara fija (norte arriba, ~50° desde la vertical). enter()/exit() animan el descenso desde / el regreso hacia el mapa.
// Nada se anima solo: la ruta se dibuja con setRouteProgress() o playRoute() (solo cuando el usuario lo pide).
// Overlay dentro de #stage: canvas transparente (<canvas id="valle-canvas">); badges/etiquetas van en canvas.parentElement
// y quedan ocultos (visibility:hidden, sin eventos) cuando la vista no está activa.
// API: initValle({canvas, base, dataBase, onSelectPredio(props|null), onRouteStop(orden, parada), onRouteProgress(t)})
//   -> {enter, exit, setActive, selectPredio, setRouteProgress, playRoute, showRoute, setYear, setInsets,
//       years, predios, ruta, bbox, sceneBbox, getRouteProgress}
import * as THREE from 'three';

const BG = 0x05080b;
const EXAG = 2.2;
const ROUTE_W = 0.16; // km, ancho total de la cinta de la ruta (incluye halo)
const ROUTE_LIFT = 0.025; // km sobre el terreno
const OVERLAY_MAX = 4096; // px, lado mayor de la textura de predios

const BANDS = {
  alta: { fill: [255, 91, 61], fa: 0.5, stroke: '#ff5b3d', sw: 6, label: 'ALTA' },
  media: { fill: [255, 169, 64], fa: 0.42, stroke: '#ffa940', sw: 5, label: 'MEDIA' },
  baja: { fill: [214, 200, 110], fa: 0.24, stroke: 'rgba(222,208,120,.85)', sw: 3.5, label: 'BAJA' },
  sin_alerta: { fill: null, fa: 0, stroke: 'rgba(196,206,212,.6)', sw: 2.5, label: 'SIN ALERTA' },
};
const bandOf = (b) => BANDS[b] || BANDS.sin_alerta;

const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
const easeInOutCubic = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
const easeInOutSine = (t) => -(Math.cos(Math.PI * t) - 1) / 2;
const fmt = (n) => Math.round(n).toLocaleString('es-CL');

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

function texFromImage(img, srgb) {
  const t = new THREE.Texture(img);
  if (srgb) t.colorSpace = THREE.SRGBColorSpace;
  t.anisotropy = 8;
  t.minFilter = THREE.LinearMipmapLinearFilter;
  t.magFilter = THREE.LinearFilter;
  t.wrapS = t.wrapT = THREE.ClampToEdgeWrapping;
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
  uniform vec3 uLightDir;
  varying vec2 vUv;
  varying vec3 vNormalW;
  varying vec3 vPosW;

  void main() {
    vec2 iuv = (vUv - uImgRect.xy) / (uImgRect.zw - uImgRect.xy);
    vec2 cuv = clamp(iuv, 0.0, 1.0);
    vec3 sat = mix(texture2D(uTexA, cuv).rgb, texture2D(uTexB, cuv).rgb, uMix);
    // outside the satellite footprint: dark neutral ground (no imagery there)
    // (soft 1-texel blend at the footprint edge so the terrain cut is not aliased)
    vec2 o = max(-iuv, iuv - 1.0);
    float out1 = max(o.x, o.y);
    float imgK = 1.0 - smoothstep(0.0, 0.004, out1);
    vec3 col = mix(vec3(0.010, 0.016, 0.020), sat, imgK);

    // hillshade
    vec3 n = normalize(vNormalW);
    float diff = clamp(dot(n, normalize(uLightDir)), 0.0, 1.0);
    float shade = 0.55 + 0.65 * diff;
    col *= shade;

    // predios: slightly mute the imagery so band colours read, then composite the overlay
    vec4 ov = texture2D(uOverlay, vUv);
    float lum = dot(col, vec3(0.299, 0.587, 0.114));
    col = mix(col, vec3(lum) * 0.92, 0.22 * uOverlayAmt);
    col = mix(col, ov.rgb * (0.8 + 0.25 * shade), ov.a * uOverlayAmt);
    // no-imagery zone: faint survey grid (every ~500 m) so it reads as a data plinth, not as missing texture
    if (imgK < 0.999) {
      vec2 g = abs(fract(vPosW.xz / 0.5) - 0.5);
      float gl = 1.0 - smoothstep(0.0, 0.035, min(g.x, g.y));
      col += vec3(0.27, 0.84, 0.93) * gl * 0.045 * (1.0 - imgK) * (1.0 - ov.a);
    }

    // edge dissolve + distance fog -> fade to transparent so the map behind shows through
    vec2 e = smoothstep(vec2(0.0), vec2(0.07), vUv) * smoothstep(vec2(0.0), vec2(0.07), 1.0 - vUv);
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
    // not yet travelled: faint dashed preview of the path
    float dash = step(0.45, fract(vDist / 0.22));
    float ahead = (1.0 - drawn) * core * dash * 0.22;
    // bright head right behind the drawing front
    float head = drawn * exp(-max(uDrawn - vDist, 0.0) * 5.0) * step(0.001, uDrawn);
    float a = drawn * (core * 0.95 + halo * 0.38) + ahead + head * halo * 0.6;
    float fog = smoothstep(uFogNear, uFogFar, length(vPosW - cameraPosition));
    a *= uAmt * (1.0 - fog);
    if (a < 0.003) discard;
    vec3 c = mix(uColor, vec3(1.0), core * 0.35 * drawn + head * 0.5);
    // premultiplied; a little extra rgb gives an additive glow
    gl_FragColor = vec4(c * a * 1.15, a);
  }
`;

export async function initValle({
  canvas, base = 'assets/petorca/', dataBase = 'data/petorca/', onSelectPredio, onRouteStop, onRouteProgress,
} = {}) {
  if (!canvas) throw new Error('initValle: falta el canvas');
  const abs = (b) => new URL(b.endsWith('/') ? b : b + '/', location.href).href;
  const assetUrl = (f) => new URL(f, abs(base)).href;
  const dataUrl = (f) => new URL(f, abs(dataBase)).href;

  let manifest, predios, ruta;
  try {
    [manifest, predios, ruta] = await Promise.all([
      loadJson(assetUrl('manifest.json')),
      loadJson(dataUrl('predios.geojson')),
      loadJson(dataUrl('ruta.json')).catch(() => null),
    ]);
  } catch (err) {
    throw new Error('initValle: no se pudieron cargar los datos del valle: ' + err.message);
  }

  const years = [...(manifest.years || [])].sort((a, b) => a - b);
  if (!years.length) throw new Error('initValle: el manifest no tiene años');
  const lastYear = years[years.length - 1];
  const IB = manifest.bbox; // satellite + DEM footprint

  const features = (predios.features || []).filter((f) => ringsOf(f.geometry).length);
  features.forEach((f) => {
    const p = f.properties || (f.properties = {});
    if (!p.id) p.id = f.id;
    let w = Infinity, s = Infinity, e = -Infinity, n = -Infinity;
    for (const r of ringsOf(f.geometry)) for (const [x, y] of r) { w = Math.min(w, x); e = Math.max(e, x); s = Math.min(s, y); n = Math.max(n, y); }
    f._bb = { w, s, e, n };
    if (!p.centroid) p.centroid = [(w + e) / 2, (s + n) / 2];
  });
  const byId = new Map(features.map((f) => [String(f.properties.id), f]));
  const routeCoords = ruta && ruta.geometry && ruta.geometry.type === 'LineString' ? ruta.geometry.coordinates : [];
  const paradas = (ruta && ruta.paradas) || [];

  // ---------- scene extent: imagery footprint ∪ data (some predios / stops can fall outside the imagery) ----------
  const DB = { w: Infinity, s: Infinity, e: -Infinity, n: -Infinity }; // data extent
  const growDB = (x, y) => { DB.w = Math.min(DB.w, x); DB.e = Math.max(DB.e, x); DB.s = Math.min(DB.s, y); DB.n = Math.max(DB.n, y); };
  features.forEach((f) => { growDB(f._bb.w, f._bb.s); growDB(f._bb.e, f._bb.n); });
  routeCoords.forEach(([x, y]) => growDB(x, y));
  if (!isFinite(DB.w)) Object.assign(DB, { w: IB.west, s: IB.south, e: IB.east, n: IB.north });
  // focus extent (what the camera frames and what the map should fly to): route + alta/media predios
  const FB = { w: Infinity, s: Infinity, e: -Infinity, n: -Infinity };
  const growFB = (x, y) => { FB.w = Math.min(FB.w, x); FB.e = Math.max(FB.e, x); FB.s = Math.min(FB.s, y); FB.n = Math.max(FB.n, y); };
  features.filter((f) => f.properties.banda === 'alta' || f.properties.banda === 'media')
    .forEach((f) => { growFB(f._bb.w, f._bb.s); growFB(f._bb.e, f._bb.n); });
  routeCoords.forEach(([x, y]) => growFB(x, y));
  paradas.forEach((s) => growFB(s.lon, s.lat));
  if (!isFinite(FB.w)) Object.assign(FB, DB);
  { const fp = 0.003; FB.w -= fp; FB.e += fp; FB.s -= fp; FB.n += fp; }
  const pad = 0.006;
  const SB = {
    w: Math.min(IB.west, DB.w - pad), e: Math.max(IB.east, DB.e + pad),
    s: Math.min(IB.south, DB.s - pad), n: Math.max(IB.north, DB.n + pad),
  };
  const dLon = SB.e - SB.w, dLat = SB.n - SB.s;
  const latMid = ((SB.n + SB.s) / 2) * Math.PI / 180;
  const W = dLon * 111.32 * Math.cos(latMid);
  const H = dLat * 110.54;
  const toUV = (lon, lat) => [(lon - SB.w) / dLon, (lat - SB.s) / dLat];
  const fromUV = (u, v) => [SB.w + u * dLon, SB.s + v * dLat];
  const imgRect = new THREE.Vector4(
    (IB.west - SB.w) / dLon, (IB.south - SB.s) / dLat, (IB.east - SB.w) / dLon, (IB.north - SB.s) / dLat,
  );
  const outsideImagery = features.filter((f) => {
    const [x, y] = f.properties.centroid;
    return x < IB.west || x > IB.east || y < IB.south || y > IB.north;
  }).map((f) => f.properties.id);
  if (outsideImagery.length) {
    console.warn(`[valle] ${outsideImagery.length} predio(s) fuera de la imagen satelital/DEM (${outsideImagery.join(', ')}); se dibujan sobre terreno sin imagen.`);
  }

  // ---------- assets: DEM + latest year first (other years load on demand) ----------
  const [demImg, lastImg] = await Promise.all([
    manifest.dem ? loadImage(assetUrl(manifest.dem.file || 'dem.png')).catch(() => null) : Promise.resolve(null),
    loadImage(assetUrl(`sat-${lastYear}.jpg`)),
  ]);
  const satTex = { [lastYear]: texFromImage(lastImg, true) };
  const satLoading = {};
  function ensureYear(y) {
    if (satTex[y]) return Promise.resolve(satTex[y]);
    if (!satLoading[y]) {
      satLoading[y] = loadImage(assetUrl(`sat-${y}.jpg`)).then((img) => {
        satTex[y] = texFromImage(img, true);
        dirty = true;
        return satTex[y];
      }).catch((e) => { console.warn('[valle]', e.message); delete satLoading[y]; return null; });
    }
    return satLoading[y];
  }

  // heights: DEM covers the imagery footprint only; outside it the edge is clamped
  let heightAt = () => 0;
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
    // u, v in scene UV (0..1 west->east, south->north)
    // outside the DEM: ease down to the valley-floor base over ~1.2 km instead of stretching the edge pixels
    const IW = (imgRect.z - imgRect.x) * W, IH = (imgRect.w - imgRect.y) * H;
    heightAt = (u, v) => {
      const iu = (u - imgRect.x) / (imgRect.z - imgRect.x);
      const iv = (v - imgRect.y) / (imgRect.w - imgRect.y);
      const h = ((sample(iu, iv) - mn) / 1000) * EXAG;
      const ox = Math.max(0, -iu, iu - 1) * IW, oy = Math.max(0, -iv, iv - 1) * IH;
      const od = Math.hypot(ox, oy);
      if (od <= 0) return h;
      const k = clamp(od / 1.2, 0, 1);
      return h * (1 - k * k * (3 - 2 * k));
    };
  }

  const SEG_X = 320, SEG_Y = Math.max(64, Math.round(320 * H / W));
  const geo = new THREE.PlaneGeometry(W, H, SEG_X, SEG_Y);
  geo.rotateX(-Math.PI / 2);
  {
    const pos = geo.attributes.position, uv = geo.attributes.uv;
    for (let i = 0; i < pos.count; i++) pos.setY(i, heightAt(uv.getX(i), uv.getY(i)));
    pos.needsUpdate = true;
    geo.computeVertexNormals();
  }
  const uvToWorld = (u, v, lift = 0) => new THREE.Vector3((u - 0.5) * W, heightAt(u, v) + lift, (0.5 - v) * H);
  const llToWorld = (lon, lat, lift = 0) => { const [u, v] = toUV(lon, lat); return uvToWorld(u, v, lift); };

  // ---------- predio overlay (canvas texture in scene UV space) ----------
  const OW = W >= H ? OVERLAY_MAX : Math.round(OVERLAY_MAX * W / H);
  const OH = W >= H ? Math.round(OVERLAY_MAX * H / W) : OVERLAY_MAX;
  const ovCanvas = document.createElement('canvas');
  ovCanvas.width = OW; ovCanvas.height = OH;
  const ovCtx = ovCanvas.getContext('2d');
  const ovTex = new THREE.CanvasTexture(ovCanvas);
  ovTex.anisotropy = 8;
  ovTex.minFilter = THREE.LinearMipmapLinearFilter;
  ovTex.magFilter = THREE.LinearFilter;
  ovTex.wrapS = ovTex.wrapT = THREE.ClampToEdgeWrapping;
  ovTex.colorSpace = THREE.SRGBColorSpace; // canvas colours are sRGB, like the satellite imagery

  const pxOf = (lon, lat) => { const [u, v] = toUV(lon, lat); return [u * OW, (1 - v) * OH]; };
  function tracePath(f) {
    ovCtx.beginPath();
    for (const r of ringsOf(f.geometry)) {
      r.forEach(([x, y], i) => { const [px, py] = pxOf(x, y); if (i) ovCtx.lineTo(px, py); else ovCtx.moveTo(px, py); });
      ovCtx.closePath();
    }
  }
  const rgba = (c, a) => `rgba(${c[0]},${c[1]},${c[2]},${a})`;
  let selectedId = null;
  function drawOverlay() {
    ovCtx.clearRect(0, 0, OW, OH);
    ovCtx.lineJoin = 'round';
    ovCtx.lineCap = 'round';
    // low bands first so alta sits on top
    const order = ['sin_alerta', 'baja', 'media', 'alta'];
    const sorted = features.slice().sort((a, b) => order.indexOf(a.properties.banda) - order.indexOf(b.properties.banda));
    for (const f of sorted) {
      const id = String(f.properties.id);
      if (id === selectedId) continue;
      const B = bandOf(f.properties.banda);
      tracePath(f);
      if (B.fill) { ovCtx.fillStyle = rgba(B.fill, selectedId ? B.fa * 0.75 : B.fa); ovCtx.fill('evenodd'); }
      ovCtx.strokeStyle = B.stroke;
      ovCtx.lineWidth = B.sw;
      ovCtx.stroke();
    }
    const sf = selectedId && byId.get(selectedId);
    if (sf) {
      const B = bandOf(sf.properties.banda);
      tracePath(sf);
      ovCtx.save();
      ovCtx.fillStyle = rgba(B.fill || [196, 206, 212], 0.6);
      ovCtx.fill('evenodd');
      ovCtx.shadowColor = B.fill ? rgba(B.fill, 0.95) : 'rgba(255,255,255,.8)';
      ovCtx.shadowBlur = 22;
      ovCtx.strokeStyle = '#ffffff';
      ovCtx.lineWidth = 9;
      ovCtx.stroke();
      ovCtx.restore();
    }
    ovTex.needsUpdate = true;
    dirty = true;
  }

  // ---------- renderer / scene ----------
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, premultipliedAlpha: true, powerPreference: 'high-performance' });
  renderer.setClearColor(BG, 0);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(38, 1, 0.05, 500);

  const span = Math.max(W, H);
  const uniforms = {
    uTexA: { value: satTex[lastYear] },
    uTexB: { value: satTex[lastYear] },
    uMix: { value: 0 },
    uImgRect: { value: imgRect },
    uOverlay: { value: ovTex },
    uOverlayAmt: { value: 0 },
    uFogNear: { value: span },
    uFogFar: { value: span * 2 },
    uLightDir: { value: new THREE.Vector3(-0.6, 0.9, 0.35) },
  };
  const terrain = new THREE.Mesh(geo, new THREE.ShaderMaterial({ uniforms, vertexShader: TERRAIN_VS, fragmentShader: TERRAIN_FS }));
  scene.add(terrain);

  // ---------- route ribbon draped on the terrain ----------
  let routeLen = 0;
  let routeMesh = null;
  let routeSamples = []; // { p: Vector3 (on route), d: km }
  const routeUniforms = {
    uDrawn: { value: 0 },
    uAmt: { value: 0 },
    uColor: { value: new THREE.Color(0x45d6ee) },
    uFogNear: uniforms.uFogNear,
    uFogFar: uniforms.uFogFar,
  };
  if (routeCoords.length > 1) {
    // densify in km space so the ribbon follows the relief between OSRM vertices
    const pts = [];
    const xz = routeCoords.map(([lon, lat]) => { const [u, v] = toUV(lon, lat); return [u, v]; });
    for (let i = 0; i < xz.length; i++) {
      const [u, v] = xz[i];
      if (i) {
        const [pu, pv] = xz[i - 1];
        const dk = Math.hypot((u - pu) * W, (v - pv) * H);
        const n = Math.floor(dk / 0.04);
        for (let k = 1; k <= n; k++) { const t = k / (n + 1); pts.push([pu + (u - pu) * t, pv + (v - pv) * t]); }
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
      const nx = -tz, nz = tx; // horizontal normal
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
    routeMesh = new THREE.Mesh(rg, new THREE.ShaderMaterial({
      uniforms: routeUniforms, vertexShader: ROUTE_VS, fragmentShader: ROUTE_FS,
      transparent: true, depthWrite: false, premultipliedAlpha: true, side: THREE.DoubleSide,
      polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2,
    }));
    routeMesh.renderOrder = 2;
    routeMesh.frustumCulled = false;
    scene.add(routeMesh);
  }
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

  // ---------- HTML layer: stop badges, start pin, labels, tooltip ----------
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
  // insert right after the canvas so page UI (HUD, panels) declared later keeps stacking above
  canvas.after(vignette, layer);
  canvas.style.pointerEvents = 'none';
  // fade, then visibility:hidden so nothing stays clickable / visible when the valley is not shown
  function fadeEl(el, on, ms) {
    clearTimeout(el._hideT);
    el.style.opacity = on ? '1' : '0';
    if (on) el.style.visibility = 'visible';
    else el._hideT = setTimeout(() => { el.style.visibility = 'hidden'; }, ms);
  }
  const showLayer = (on) => fadeEl(layer, on, 480);
  const showVignette = (on) => fadeEl(vignette, on, 720);

  const BAND_HEX = { alta: '#ff5b3d', media: '#ffa940', baja: '#d6c86e', sin_alerta: '#c4ced4' };
  const stops = [];
  let lastIdx = 0;
  for (const s of paradas) {
    const { d, i } = alongRoute(s.lon, s.lat, lastIdx);
    lastIdx = i;
    const el = document.createElement('button');
    el.type = 'button';
    const col = BAND_HEX[s.banda] || '#45d6ee';
    el.setAttribute('aria-label', `Parada ${s.orden}: predio ${s.predio_id}, banda ${s.banda}`);
    el.innerHTML = `<span data-stem style="position:absolute;left:50%;top:100%;width:1px;height:16px;background:${col};opacity:.75"></span>`
      + `<span data-n style="display:grid;place-items:center;width:22px;height:22px;border-radius:50%;border:1.5px solid ${col};background:rgba(5,8,11,.86);color:${col};font:600 11px/1 'IBM Plex Mono',ui-monospace,monospace;transition:background .25s,color .25s,box-shadow .25s">${s.orden}</span>`;
    Object.assign(el.style, {
      position: 'absolute', left: '0', top: '0', padding: '0', margin: '0', border: '0', background: 'none',
      cursor: 'pointer', pointerEvents: 'auto', transform: 'translate(-9999px,-9999px)', willChange: 'transform',
    });
    el.addEventListener('click', (ev) => { ev.stopPropagation(); pick(s.predio_id, true); });
    layer.appendChild(el);
    stops.push({ s, d, el, num: el.querySelector('[data-n]'), col, world: llToWorld(s.lon, s.lat), reached: null });
  }
  let startPin = null;
  if (ruta && ruta.inicio) {
    const el = document.createElement('div');
    el.innerHTML = `<span style="display:block;width:10px;height:10px;margin:0 auto;border-radius:2px;background:#45d6ee;box-shadow:0 0 0 3px rgba(69,214,238,.25),0 0 12px rgba(69,214,238,.8);transform:rotate(45deg)"></span>`
      + `<span style="display:block;margin-top:7px;white-space:nowrap;padding:3px 6px;background:rgba(5,8,11,.78);border:1px solid rgba(69,214,238,.5);color:#45d6ee;letter-spacing:.06em">INICIO · ${String(ruta.inicio.nombre || '').toUpperCase()}${ruta.inicio.hora ? ' · ' + ruta.inicio.hora : ''}</span>`;
    Object.assign(el.style, { position: 'absolute', left: '0', top: '0', transform: 'translate(-9999px,-9999px)', textAlign: 'center' });
    layer.appendChild(el);
    startPin = { el, world: llToWorld(ruta.inicio.lon, ruta.inicio.lat, 0.01) };
  }
  const headDot = document.createElement('div');
  Object.assign(headDot.style, {
    position: 'absolute', left: '-5px', top: '-5px', width: '10px', height: '10px', borderRadius: '50%',
    background: '#eaffff', boxShadow: '0 0 0 3px rgba(69,214,238,.35), 0 0 16px 4px rgba(69,214,238,.85)',
    transform: 'translate(-9999px,-9999px)', opacity: '0', transition: 'opacity .3s',
  });
  layer.appendChild(headDot);

  // selected predio label (anchored to its centroid)
  const selLabel = document.createElement('div');
  Object.assign(selLabel.style, {
    position: 'absolute', left: '0', top: '0', transform: 'translate(-9999px,-9999px)', whiteSpace: 'nowrap',
    padding: '6px 8px', background: 'rgba(5,8,11,.86)', border: '1px solid #fff', color: '#e8eef0',
    letterSpacing: '.04em', lineHeight: '1.45', boxShadow: '0 6px 24px rgba(0,0,0,.45)',
  });
  layer.appendChild(selLabel);
  // hover tooltip (follows the cursor)
  const tip = document.createElement('div');
  Object.assign(tip.style, {
    position: 'absolute', left: '0', top: '0', transform: 'translate(-9999px,-9999px)', whiteSpace: 'nowrap',
    padding: '4px 7px', background: 'rgba(5,8,11,.86)', border: '1px solid rgba(232,238,240,.35)', color: '#e8eef0',
    letterSpacing: '.05em',
  });
  layer.appendChild(tip);

  const rangeTxt = (p) => (isFinite(p.m3_estimado_min) && isFinite(p.m3_estimado_max)
    ? `${Math.round(p.m3_estimado_min / 1000)}–${Math.round(p.m3_estimado_max / 1000)} mil m³/año` : 's/d');
  function renderSelLabel() {
    const f = selectedId && byId.get(selectedId);
    if (!f) { selLabel.style.transform = 'translate(-9999px,-9999px)'; return; }
    const p = f.properties, B = bandOf(p.banda), col = BAND_HEX[p.banda] || '#c4ced4';
    const stop = paradas.find((s) => String(s.predio_id) === selectedId);
    selLabel.style.borderColor = col;
    selLabel.innerHTML = `<div style="display:flex;gap:8px;align-items:center"><b style="font-weight:600;color:#fff">${p.id}</b>`
      + `<span style="color:${col}">● ${B.label}</span>${stop ? `<span style="color:#45d6ee">PARADA ${stop.orden}</span>` : ''}</div>`
      + `<div style="color:#9fb0b6">consumo est. ${p.m3_estimado_anio || ''}: <span style="color:#e8eef0">${rangeTxt(p)}</span></div>`
      + `<div style="color:#9fb0b6">${isFinite(p.area_ha) ? p.area_ha.toLocaleString('es-CL') + ' ha · ' : ''}confianza ${p.confianza || 's/d'}</div>`;
  }

  // ---------- state ----------
  const reduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const state = { year: lastYear, routeT: 0, routeOn: true };
  let dirty = true;
  let overlayAmt = 0;
  let routeAmt = 0;
  let routePlay = null; // { from, to, t0, dur, resolve }
  let hoverId = null;

  // ---------- camera (fixed, north-up) ----------
  const target = new THREE.Vector3();
  {
    const [cu, cv] = toUV((FB.w + FB.e) / 2, (FB.s + FB.n) / 2);
    target.copy(uvToWorld(cu, cv));
    target.y = heightAt(cu, cv) * 0.6;
  }
  const insets = { right: 0, bottom: 0 }; // px covered by page UI (side panel / bottom sheet)
  const FINAL = { pol: THREE.MathUtils.degToRad(50), r: span * 0.7 };
  const START = { pol: THREE.MathUtils.degToRad(25), r: span * 1.8 };
  const cam = { pol: START.pol, r: START.r };
  const tmpV = new THREE.Vector3();
  function project(v) {
    tmpV.copy(v).project(camera);
    return { x: (tmpV.x * 0.5 + 0.5) * host.clientWidth, y: (-tmpV.y * 0.5 + 0.5) * host.clientHeight, ok: tmpV.z < 1 };
  }
  // numeric fit: project the focus points (stops, route, alta/media predios) with the final pose and search the
  // radius + target that makes them fill the visible area (canvas minus side panel / bottom sheet, minus HUD margins)
  let focusPts = null;
  function buildFocusPts() {
    const pts = [];
    stops.forEach((st) => pts.push(st.world));
    if (startPin) pts.push(startPin.world);
    for (let i = 0; i < routeSamples.length; i += 6) pts.push(routeSamples[i].p);
    features.forEach((f) => {
      const bd = f.properties.banda;
      if (bd !== 'alta' && bd !== 'media') return;
      const b = f._bb;
      [[b.w, b.s], [b.e, b.s], [b.w, b.n], [b.e, b.n]].forEach(([x, y]) => pts.push(llToWorld(x, y)));
    });
    if (!pts.length) [[FB.w, FB.s], [FB.e, FB.s], [FB.w, FB.n], [FB.e, FB.n]].forEach(([x, y]) => pts.push(llToWorld(x, y)));
    return pts;
  }
  function fitRadius() {
    if (!focusPts) focusPts = buildFocusPts();
    const fw = Math.max(1, host.clientWidth), fh = Math.max(1, host.clientHeight);
    const small = fw < 700;
    // HUD + badge headroom; extra right margin when the side panel is open so the east-most stops
    // and their badges/labels don't sit against the panel edge
    const m = { l: small ? 20 : 48, r: small ? 20 : (insets.right ? 150 : 48), t: small ? 90 : 120, b: small ? 24 : 60 };
    const vx0 = m.l, vx1 = Math.max(vx0 + 50, fw - Math.min(insets.right, fw * 0.6) - m.r);
    const vy0 = m.t, vy1 = Math.max(vy0 + 50, fh - Math.min(insets.bottom, fh * 0.6) - m.b);
    const vw = vx1 - vx0, vh = vy1 - vy0;
    const save = { pol: cam.pol, r: cam.r };
    cam.pol = FINAL.pol;
    const box = (r) => {
      cam.r = r; placeCamera(); camera.updateMatrixWorld();
      let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
      for (const v of focusPts) {
        const q = project(v);
        x0 = Math.min(x0, q.x); x1 = Math.max(x1, q.x); y0 = Math.min(y0, q.y); y1 = Math.max(y1, q.y);
      }
      return { x0, x1, y0, y1 };
    };
    let r = span * 0.7;
    for (let iter = 0; iter < 4; iter++) {
      let lo = 0.5, hi = span * 4;
      for (let k = 0; k < 22; k++) {
        const mid = (lo + hi) / 2, bb = box(mid);
        if (bb.x1 - bb.x0 <= vw && bb.y1 - bb.y0 <= vh) hi = mid; else lo = mid;
      }
      r = hi;
      // re-centre the target on the projected box (pixel offset -> world offset at the target depth)
      const bb = box(r);
      const dxp = (bb.x0 + bb.x1) / 2 - (vx0 + vx1) / 2, dyp = (bb.y0 + bb.y1) / 2 - (vy0 + vy1) / 2;
      const wpp = (2 * r * Math.tan(THREE.MathUtils.degToRad(camera.fov) / 2)) / fh; // world km per px
      target.x += dxp * wpp;
      target.z += (dyp * wpp) / Math.cos(FINAL.pol);
      if (Math.abs(dxp) < 2 && Math.abs(dyp) < 2) break;
    }
    cam.pol = save.pol; cam.r = save.r; placeCamera();
    return Math.max(r, 1);
  }
  function placeCamera() {
    camera.position.set(target.x, target.y + cam.r * Math.cos(cam.pol), target.z + cam.r * Math.sin(cam.pol));
    camera.lookAt(target);
    // fog band relative to the current distance so the whole valley stays visible while descending
    uniforms.uFogNear.value = cam.r + span * 0.35;
    uniforms.uFogFar.value = cam.r + span * 1.1;
  }

  let anim = null;
  function startAnim(to, dur, kind) {
    if (anim) { const r = anim.resolve; anim = null; r(); }
    return new Promise((resolve) => {
      if (reduced || dur <= 0) { cam.pol = to.pol; cam.r = to.r; placeCamera(); dirty = true; resolve(); finishAnim(kind); return; }
      anim = { from: { pol: cam.pol, r: cam.r }, to, t0: performance.now(), dur, kind, resolve };
    });
  }
  function stepAnim(now) {
    if (!anim) return;
    const k = clamp((now - anim.t0) / anim.dur, 0, 1);
    const e = easeInOutCubic(k);
    cam.pol = anim.from.pol + (anim.to.pol - anim.from.pol) * e;
    cam.r = anim.from.r + (anim.to.r - anim.from.r) * e;
    dirty = true;
    if (k >= 1) {
      const { resolve, kind } = anim;
      anim = null;
      resolve();
      finishAnim(kind);
    }
  }
  let entered = false;
  function finishAnim(kind) {
    if (kind === 'enter') { entered = true; showLayer(true); canvas.style.pointerEvents = 'auto'; }
    else if (kind === 'exit') { setActive(false); renderer.clear(); }
  }

  // ---------- resize ----------
  function resize() {
    const w = Math.max(1, host.clientWidth), h = Math.max(1, host.clientHeight);
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    renderer.setPixelRatio(dpr);
    renderer.setSize(w, h, false);
    canvas.style.width = '100%';
    canvas.style.height = '100%';
    camera.aspect = w / h;
    camera.fov = w / h < 0.9 ? 52 : 38;
    camera.updateProjectionMatrix();
    FINAL.r = fitRadius();
    START.r = FINAL.r * 2.6;
    if (!anim) { cam.r = entered ? FINAL.r : START.r; placeCamera(); }
    dirty = true;
  }
  resize();
  new ResizeObserver(resize).observe(host);

  // ---------- projection of HTML elements ----------
  function updateHtml() {
    const drawn = state.routeT * routeLen;
    const showStops = state.routeOn && entered;
    // stops: ground point -> badge raised on a stem; simple horizontal de-clutter between close badges
    const placed = [];
    for (const st of stops) {
      const g = project(st.world);
      let bx = g.x, by = g.y - 16 - 11;
      for (const q of placed) {
        if (Math.abs(q.x - bx) < 25 && Math.abs(q.y - by) < 25) bx = q.x + (bx >= q.x ? 25 : -25);
      }
      placed.push({ x: bx, y: by });
      st.el.style.transform = showStops && g.ok ? `translate(${(bx - 11).toFixed(1)}px, ${(by - 11).toFixed(1)}px)` : 'translate(-9999px,-9999px)';
      const stem = st.el.firstChild;
      // stem from the badge to the ground point (may lean when de-cluttered)
      const dx = g.x - bx, dy = g.y - (by + 11);
      stem.style.height = `${Math.max(0, Math.hypot(dx, dy)).toFixed(1)}px`;
      stem.style.transformOrigin = '0 0';
      stem.style.transform = `rotate(${(Math.atan2(dx, dy) * -180 / Math.PI).toFixed(1)}deg)`;
      stem.style.top = '22px';
      stem.style.left = '11px';
      const reached = drawn >= st.d - 0.05 && state.routeT > 0;
      const sel = String(st.s.predio_id) === selectedId;
      if (reached !== st.reached || sel !== st.sel) {
        st.reached = reached; st.sel = sel;
        st.num.style.background = reached ? st.col : 'rgba(5,8,11,.86)';
        st.num.style.color = reached ? '#05080b' : st.col;
        st.num.style.boxShadow = sel ? `0 0 0 3px #fff, 0 0 14px ${st.col}` : reached ? `0 0 12px ${st.col}` : 'none';
      }
    }
    if (startPin) {
      const g = project(startPin.world);
      startPin.el.style.transform = showStops && g.ok ? `translate(calc(${g.x.toFixed(1)}px - 50%), ${(g.y - 5).toFixed(1)}px)` : 'translate(-9999px,-9999px)';
    }
    const head = showStops && state.routeT > 0 && state.routeT < 1 ? pointAt(drawn) : null;
    if (head) {
      const g = project(head);
      headDot.style.transform = `translate(${g.x.toFixed(1)}px, ${g.y.toFixed(1)}px)`;
      headDot.style.opacity = '1';
    } else headDot.style.opacity = '0';
    const f = selectedId && byId.get(selectedId);
    if (f && entered) {
      const [lon, lat] = f.properties.centroid;
      const g = project(llToWorld(lon, lat));
      const w = selLabel.offsetWidth || 180;
      const x = clamp(g.x + 18, 8, host.clientWidth - w - 8);
      selLabel.style.transform = `translate(${x.toFixed(1)}px, ${(g.y - 70).toFixed(1)}px)`;
    } else selLabel.style.transform = 'translate(-9999px,-9999px)';
  }

  // ---------- picking ----------
  const raycaster = new THREE.Raycaster();
  const ndc = new THREE.Vector2();
  function predioAtClient(cx, cy) {
    const r = canvas.getBoundingClientRect();
    ndc.set(((cx - r.left) / r.width) * 2 - 1, -((cy - r.top) / r.height) * 2 + 1);
    raycaster.setFromCamera(ndc, camera);
    const hit = raycaster.intersectObject(terrain, false)[0];
    if (!hit || !hit.uv) return null;
    const [lon, lat] = fromUV(hit.uv.x, hit.uv.y);
    for (const f of features) {
      const b = f._bb;
      if (lon < b.w || lon > b.e || lat < b.s || lat > b.n) continue;
      if (pointInRings(lon, lat, ringsOf(f.geometry))) return f;
    }
    return null;
  }
  function pick(id, notify) {
    const nid = id == null ? null : String(id);
    if (nid && !byId.has(nid)) return;
    if (nid !== selectedId) {
      selectedId = nid;
      drawOverlay();
      renderSelLabel();
      stops.forEach((st) => { st.sel = null; });
    }
    if (notify && typeof onSelectPredio === 'function') {
      try { onSelectPredio(nid ? byId.get(nid).properties : null); } catch (e) { console.error(e); }
    }
    dirty = true;
  }
  let pendingMove = null;
  canvas.addEventListener('pointermove', (ev) => { pendingMove = { x: ev.clientX, y: ev.clientY }; });
  canvas.addEventListener('pointerleave', () => { pendingMove = null; setHover(null); });
  function setHover(f, x, y) {
    const id = f ? String(f.properties.id) : null;
    canvas.style.cursor = f ? 'pointer' : '';
    if (!f) { tip.style.transform = 'translate(-9999px,-9999px)'; hoverId = null; return; }
    if (id !== hoverId) {
      hoverId = id;
      const p = f.properties, col = BAND_HEX[p.banda] || '#c4ced4';
      tip.style.borderColor = col;
      tip.innerHTML = `<b style="font-weight:600;color:#fff">${p.id}</b> <span style="color:${col}">· ${bandOf(p.banda).label}</span>`;
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

  // ---------- route callbacks: progress + stops reached (forward crossings only) ----------
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
  let active = false, rafId = 0, prev = performance.now();
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
    if (!active) return;

    // overlay fades in with the descent, out with the exit (transition of a user action, not autoplay)
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
    // year cross-fade between the two bracketing composites (only if both are loaded)
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
    uniforms.uOverlayAmt.value = overlayAmt;
    routeUniforms.uAmt.value = routeAmt;
    routeUniforms.uDrawn.value = state.routeT >= 1 ? routeLen + 1 : state.routeT * routeLen;
    placeCamera();
    renderer.render(scene, camera);
    updateHtml();
  }

  drawOverlay();
  placeCamera();
  renderer.render(scene, camera); // first frame at the START pose

  // ---------- controller ----------
  const controller = {
    years: years.slice(),
    predios: features.map((f) => f.properties),
    ruta,
    outsideImagery,
    bbox: [FB.w, FB.s, FB.e, FB.n], // framed area (route + alta/media predios): use for map.flyToBounds before enter()
    sceneBbox: [SB.w, SB.s, SB.e, SB.n], // full 3D terrain extent
    // px of the canvas covered by page UI (right side panel / bottom sheet); re-frames the camera
    setInsets({ right = 0, bottom = 0 } = {}) {
      insets.right = Math.max(0, +right || 0); insets.bottom = Math.max(0, +bottom || 0);
      resize();
    },
    enter({ duration = 2200 } = {}) {
      if (!active) { overlayAmt = 0; routeAmt = 0; entered = false; }
      setActive(true);
      showVignette(true);
      return startAnim(FINAL, duration, 'enter');
    },
    exit({ duration = 1400 } = {}) {
      if (routePlay) { const r = routePlay.resolve; routePlay = null; r(); }
      entered = false;
      showLayer(false);
      showVignette(false);
      canvas.style.pointerEvents = 'none';
      setHover(null);
      if (!active) {
        if (anim) { const r = anim.resolve; anim = null; r(); }
        cam.pol = START.pol; cam.r = START.r; placeCamera(); renderer.clear();
        return Promise.resolve();
      }
      return startAnim(START, duration, 'exit');
    },
    setActive,
    selectPredio(id) { pick(id, false); },
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
