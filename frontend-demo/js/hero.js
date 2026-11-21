// Caudal · vista 3D de la laguna: terreno DEM + imagenes satelitales por año + agua (SDF limpio, interpolado entre años)
// + particulas de agua perdida.
// Camara fija (norte arriba, ~50° desde la vertical). enter()/exit() animan el descenso desde / el regreso hacia el mapa nacional.
import * as THREE from 'three';

const BG = 0x05080b;
const EXAG = 2.5;
const SEG = 256;
const MAX_PARTICLES = 3200;

const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
const smooth = (t) => t * t * (3 - 2 * t);
const easeInOutCubic = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);

function loadImage(url) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.crossOrigin = 'anonymous';
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error('No se pudo cargar ' + url));
    img.src = url;
  });
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
  // clean signed-distance water fields (8-bit, 128 = shoreline, 2 units per px at 512 px wide, + inside water)
  uniform sampler2D uSdfA;
  uniform sampler2D uSdfB;
  uniform sampler2D uSdfBase;
  uniform float uWaterAmt;
  uniform float uTime;
  uniform vec3 uBg;
  uniform float uFogNear;
  uniform float uFogFar;
  uniform vec3 uLightDir;
  varying vec2 vUv;
  varying vec3 vNormalW;
  varying vec3 vPosW;

  float sdfAt(sampler2D t, vec2 uv) { return (texture2D(t, uv).r * 255.0 - 128.0) * 0.5; }

  void main() {
    vec3 col = mix(texture2D(uTexA, vUv).rgb, texture2D(uTexB, vUv).rgb, uMix);

    // hillshade
    vec3 n = normalize(vNormalW);
    float diff = clamp(dot(n, normalize(uLightDir)), 0.0, 1.0);
    float shade = 0.55 + 0.65 * diff;
    col *= shade;

    // water of the current (float) year: interpolated SDFs morph the shoreline continuously while scrubbing
    // (outside distance clamped short so thin/small water bodies don't vanish early in the morph)
    float sCur = mix(max(sdfAt(uSdfA, vUv), -10.0), max(sdfAt(uSdfB, vUv), -10.0), uMix);
    float sBase = sdfAt(uSdfBase, vUv);
    float aa = max(fwidth(sCur), 0.05);
    float water = smoothstep(-aa * 1.2, aa * 1.2, sCur); // ~1-2 screen px antialiased edge

    if (uWaterAmt > 0.001) {
      // receded area (water in the baseline year, not now): very light warm/dry wash, soft gradients only
      float dry = smoothstep(-2.0, 5.0, sBase) * (1.0 - smoothstep(-6.0, 0.0, sCur));
      vec3 dryCol = col * vec3(1.10, 0.99, 0.84) + vec3(0.035, 0.022, 0.0);
      col = mix(col, dryCol, dry * 0.45 * uWaterAmt);

      // water: darken + cool deep-teal tint, a touch lighter in the shallows near the edge
      float depth = smoothstep(0.0, 16.0, sCur);
      float lum = dot(col, vec3(0.299, 0.587, 0.114));
      vec3 shallow = mix(col, vec3(lum), 0.35) * vec3(0.70, 0.86, 0.90) + vec3(0.0, 0.018, 0.026);
      vec3 deep = vec3(0.020, 0.085, 0.105) * (0.75 + 0.35 * shade) + col * 0.22;
      vec3 wcol = mix(shallow, deep, 0.35 + 0.55 * depth);
      col = mix(col, wcol, water * 0.88 * uWaterAmt);
    }

    // edge dissolve + distance fog -> fade to transparent so the national map shows behind the terrain
    vec2 e = smoothstep(vec2(0.0), vec2(0.08), vUv) * smoothstep(vec2(0.0), vec2(0.08), 1.0 - vUv);
    float edgeF = e.x * e.y;
    float dist = length(vPosW - cameraPosition);
    float fog = smoothstep(uFogNear, uFogFar, dist);
    float alpha = 1.0 - clamp(fog + (1.0 - edgeF), 0.0, 1.0);
    if (alpha < 0.003) discard;

    gl_FragColor = vec4(col, alpha);
    #include <colorspace_fragment>
    gl_FragColor.rgb *= gl_FragColor.a; // premultiplied output (canvas is transparent, no blending on terrain)
  }
`;

const PART_VS = /* glsl */`
  attribute float aPhase;
  attribute float aSpeed;
  uniform float uTime;
  uniform float uRise;
  uniform float uSize;
  uniform float uPixelRatio;
  varying float vAlpha;
  void main() {
    float t = fract(uTime * aSpeed + aPhase);
    vec3 p = position;
    p.y += t * uRise;
    p.x += sin(t * 6.2831 + aPhase * 20.0) * 0.06;
    p.z += cos(t * 6.2831 + aPhase * 13.0) * 0.06;
    vAlpha = sin(t * 3.14159) * (1.0 - t * 0.4);
    vec4 mv = modelViewMatrix * vec4(p, 1.0);
    gl_PointSize = uSize * uPixelRatio * (8.0 / -mv.z) * (0.6 + 0.4 * (1.0 - t));
    gl_Position = projectionMatrix * mv;
  }
`;

const PART_FS = /* glsl */`
  uniform vec3 uColor;
  uniform float uOpacity;
  varying float vAlpha;
  void main() {
    vec2 c = gl_PointCoord - 0.5;
    float d = length(c);
    float a = smoothstep(0.5, 0.0, d);
    a = a * a;
    gl_FragColor = vec4(uColor * (1.0 + a), a * vAlpha * uOpacity);
  }
`;

export async function initHero({ canvas, manifestUrl, autoplay = false }) {
  if (!canvas) throw new Error('initHero: falta el canvas');
  let manifest;
  try {
    const res = await fetch(manifestUrl);
    if (!res.ok) throw new Error('HTTP ' + res.status);
    manifest = await res.json();
  } catch (err) {
    throw new Error(`initHero: no se pudo cargar el manifest (${manifestUrl}): ${err.message}`);
  }
  const baseUrl = new URL('.', new URL(manifestUrl, location.href)).href;
  const url = (f) => new URL(f, baseUrl).href;

  const years = [...(manifest.years || [])].sort((a, b) => a - b);
  if (!years.length) throw new Error('initHero: el manifest no tiene años');
  const baselineYear = manifest.baselineYear ?? years[0];
  const lastYear = years[years.length - 1];
  const bbox = manifest.bbox;

  // ---------- area / loss ----------
  const waterYears = years.filter((y) => manifest.water && manifest.water[y] && isFinite(manifest.water[y].km2));
  const areaAt = (yf) => {
    if (!waterYears.length) return 0;
    if (yf <= waterYears[0]) return manifest.water[waterYears[0]].km2;
    const last = waterYears[waterYears.length - 1];
    if (yf >= last) return manifest.water[last].km2;
    for (let i = 0; i < waterYears.length - 1; i++) {
      const a = waterYears[i], b = waterYears[i + 1];
      if (yf >= a && yf <= b) {
        const t = (yf - a) / (b - a || 1);
        return manifest.water[a].km2 + (manifest.water[b].km2 - manifest.water[a].km2) * t;
      }
    }
    return 0;
  };
  const baselineArea = areaAt(baselineYear) || 1;
  const lossAt = (yf) => Math.max(0, Math.round((1 - areaAt(yf) / baselineArea) * 100));
  // year with the least water: the (user-started) playback descends to it, then continues to the last year (recovery)
  const peakYear = waterYears.length
    ? waterYears.reduce((m, y) => (manifest.water[y].km2 < manifest.water[m].km2 ? y : m), waterYears[0])
    : lastYear;

  const bracket = (yf) => {
    yf = clamp(yf, years[0], lastYear);
    for (let i = 0; i < years.length - 1; i++) {
      if (yf <= years[i + 1]) {
        const a = years[i], b = years[i + 1];
        return { a, b, t: (yf - a) / (b - a || 1) };
      }
    }
    return { a: lastYear, b: lastYear, t: 0 };
  };

  // ---------- load assets ----------
  // clean water SDFs (scripts/clean_masks.py): 8-bit, 128 = shoreline, + inside water
  const sdfFileFor = (y) => (manifest.waterSdf && manifest.waterSdf[y]) || `water-${y}.png`;
  const [demImg, satImgs, sdfImgs] = await Promise.all([
    manifest.dem ? loadImage(url(manifest.dem.file || 'dem.png')).catch(() => null) : Promise.resolve(null),
    Promise.all(years.map((y) => loadImage(url(`sat-${y}.jpg`)))),
    Promise.all(years.map((y) => loadImage(url(sdfFileFor(y))).catch(() => null))),
  ]);

  const satTex = {}, sdfTex = {}, sdfPix = {};
  // fallback: encoded 0 = far outside water (dry)
  const blank = new THREE.DataTexture(new Uint8Array([0, 0, 0, 255]), 1, 1);
  blank.needsUpdate = true;
  years.forEach((y, i) => {
    satTex[y] = texFromImage(satImgs[i], true);
    if (sdfImgs[i]) {
      const t = new THREE.Texture(sdfImgs[i]);
      t.minFilter = t.magFilter = THREE.LinearFilter; // the field is smooth; no mips so the edge stays crisp
      t.generateMipmaps = false;
      t.wrapS = t.wrapT = THREE.ClampToEdgeWrapping;
      t.needsUpdate = true;
      sdfTex[y] = t;
      sdfPix[y] = imageData(sdfImgs[i], 256);
    } else {
      sdfTex[y] = blank;
    }
  });
  const isWaterPx = (pix, x, y) => pix.data[(y * pix.w + x) * 4] >= 128;

  // ---------- geometry (km units) ----------
  const latMid = ((bbox.north + bbox.south) / 2) * Math.PI / 180;
  const W = ((bbox.east - bbox.west) * 111.32 * Math.cos(latMid)) || 20;
  const H = ((bbox.north - bbox.south) * 110.54) || 20;

  let heightAt = () => 0;
  let dem = null, hs = null, mn = 0;
  if (demImg) {
    dem = imageData(demImg, 512);
    hs = new Float32Array(dem.w * dem.h);
    mn = Infinity;
    for (let i = 0; i < hs.length; i++) {
      const r = dem.data[i * 4], g = dem.data[i * 4 + 1], b = dem.data[i * 4 + 2];
      const v = r * 256 + g + b / 256 - 32768;
      hs[i] = v;
      if (v < mn && v > -500) mn = v;
    }
    if (!isFinite(mn)) mn = 0;
    // u: 0..1 west->east, v: 0..1 south->north
    heightAt = (u, v) => {
      const x = clamp(u, 0, 1) * (dem.w - 1);
      const y = (1 - clamp(v, 0, 1)) * (dem.h - 1);
      const x0 = Math.floor(x), y0 = Math.floor(y);
      const x1 = Math.min(x0 + 1, dem.w - 1), y1 = Math.min(y0 + 1, dem.h - 1);
      const fx = x - x0, fy = y - y0;
      const s = (xx, yy) => Math.max(hs[yy * dem.w + xx], mn);
      const h = (s(x0, y0) * (1 - fx) + s(x1, y0) * fx) * (1 - fy) + (s(x0, y1) * (1 - fx) + s(x1, y1) * fx) * fy;
      return ((h - mn) / 1000) * EXAG;
    };
  }

  const geo = new THREE.PlaneGeometry(W, H, SEG, SEG);
  geo.rotateX(-Math.PI / 2);
  {
    const pos = geo.attributes.position, uv = geo.attributes.uv;
    for (let i = 0; i < pos.count; i++) pos.setY(i, heightAt(uv.getX(i), uv.getY(i)));
    pos.needsUpdate = true;
    geo.computeVertexNormals();
  }
  const uvToWorld = (u, v, lift = 0) => new THREE.Vector3((u - 0.5) * W, heightAt(u, v) + lift, (0.5 - v) * H);

  // ---------- lagoon extent (from the clean baseline water field) ----------
  let lagoon = { u0: 0.3, u1: 0.7, v0: 0.3, v1: 0.7, cu: 0.5, cv: 0.5 };
  const bm = sdfPix[baselineYear];
  if (bm) {
    let u0 = 1, u1 = 0, v0 = 1, v1 = 0, su = 0, sv = 0, n = 0;
    for (let y = 0; y < bm.h; y++) for (let x = 0; x < bm.w; x++) {
      if (isWaterPx(bm, x, y)) {
        const u = (x + 0.5) / bm.w, v = 1 - (y + 0.5) / bm.h;
        u0 = Math.min(u0, u); u1 = Math.max(u1, u); v0 = Math.min(v0, v); v1 = Math.max(v1, v);
        su += u; sv += v; n++;
      }
    }
    if (n > 10) lagoon = { u0, u1, v0, v1, cu: su / n, cv: sv / n };
  }
  const lagoonCenter = uvToWorld(lagoon.cu, lagoon.cv);
  const waterLevel = lagoonCenter.y;
  const lagoonSpan = Math.max((lagoon.u1 - lagoon.u0) * W, (lagoon.v1 - lagoon.v0) * H, 2);

  // ---------- renderer / scene ----------
  // transparent canvas: the (dimmed) national map shows around the terrain
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
    uSdfA: { value: sdfTex[lastYear] },
    uSdfB: { value: sdfTex[lastYear] },
    uSdfBase: { value: sdfTex[baselineYear] || blank },
    uWaterAmt: { value: 0 },
    uTime: { value: 0 },
    uBg: { value: new THREE.Color(BG) },
    uFogNear: { value: span * 0.55 },
    uFogFar: { value: span * 1.35 },
    uLightDir: { value: new THREE.Vector3(-0.6, 0.9, 0.35) },
  };
  const terrain = new THREE.Mesh(geo, new THREE.ShaderMaterial({ uniforms, vertexShader: TERRAIN_VS, fragmentShader: TERRAIN_FS }));
  scene.add(terrain);

  // ---------- particles ----------
  const pGeo = new THREE.BufferGeometry();
  const pPos = new Float32Array(MAX_PARTICLES * 3);
  const pPhase = new Float32Array(MAX_PARTICLES);
  const pSpeed = new Float32Array(MAX_PARTICLES);
  for (let i = 0; i < MAX_PARTICLES; i++) { pPhase[i] = Math.random(); pSpeed[i] = 0.12 + Math.random() * 0.22; }
  pGeo.setAttribute('position', new THREE.BufferAttribute(pPos, 3));
  pGeo.setAttribute('aPhase', new THREE.BufferAttribute(pPhase, 1));
  pGeo.setAttribute('aSpeed', new THREE.BufferAttribute(pSpeed, 1));
  pGeo.setDrawRange(0, 0);
  const pUniforms = {
    uTime: { value: 0 },
    uRise: { value: Math.max(1.2, lagoonSpan * 0.35) },
    uSize: { value: 1.6 },
    uPixelRatio: { value: 1 },
    uColor: { value: new THREE.Color(0xffa940) },
    uOpacity: { value: 0 },
  };
  const points = new THREE.Points(pGeo, new THREE.ShaderMaterial({
    uniforms: pUniforms, vertexShader: PART_VS, fragmentShader: PART_FS,
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
  }));
  points.frustumCulled = false;
  points.renderOrder = 2;
  scene.add(points);

  let particleYear = null;
  function rebuildParticles(year) {
    if (year === particleYear) return;
    particleYear = year;
    const base = sdfPix[baselineYear], cur = sdfPix[year];
    if (!base) { pGeo.setDrawRange(0, 0); return; }
    const cand = [];
    const cw = cur ? cur.w : 0, ch = cur ? cur.h : 0;
    for (let y = 0; y < base.h; y++) for (let x = 0; x < base.w; x++) {
      if (!isWaterPx(base, x, y)) continue;
      const u = (x + 0.5) / base.w, v = 1 - (y + 0.5) / base.h;
      let isWater = false;
      if (cur) {
        const cx = Math.min(cw - 1, Math.floor(u * cw)), cy = Math.min(ch - 1, Math.floor((1 - v) * ch));
        isWater = isWaterPx(cur, cx, cy);
      }
      if (!isWater) cand.push(u, v);
    }
    const nCand = cand.length / 2;
    const loss = lossAt(year);
    const n = nCand ? Math.min(MAX_PARTICLES, Math.round(MAX_PARTICLES * clamp(loss / 70, 0, 1))) : 0;
    const du = 1 / base.w, dv = 1 / base.h;
    for (let i = 0; i < n; i++) {
      const k = Math.floor(Math.random() * nCand);
      const u = cand[k * 2] + (Math.random() - 0.5) * du, v = cand[k * 2 + 1] + (Math.random() - 0.5) * dv;
      const p = uvToWorld(u, v, 0.03);
      pPos[i * 3] = p.x; pPos[i * 3 + 1] = p.y; pPos[i * 3 + 2] = p.z;
    }
    pGeo.attributes.position.needsUpdate = true;
    pGeo.setDrawRange(0, n);
  }

  // ---------- HTML HUD overlay ----------
  const host = canvas.parentElement || document.body;
  if (getComputedStyle(host).position === 'static') host.style.position = 'relative';
  const vignette = document.createElement('div');
  vignette.setAttribute('aria-hidden', 'true');
  Object.assign(vignette.style, {
    position: 'absolute', inset: '0', zIndex: '1', pointerEvents: 'none', opacity: '0', transition: 'opacity .7s ease',
    // subtle, fully transparent in the centre so the map behind stays visible
    background: 'radial-gradient(ellipse 80% 75% at 50% 48%, rgba(5,8,11,0) 60%, rgba(5,8,11,0.35) 100%)',
  });
  host.appendChild(vignette);
  const hud = document.createElement('div');
  hud.setAttribute('aria-hidden', 'true');
  hud.innerHTML = `
    <span style="position:absolute;left:0;top:0;width:14px;height:14px;border-left:1.5px solid currentColor;border-top:1.5px solid currentColor"></span>
    <span style="position:absolute;right:0;top:0;width:14px;height:14px;border-right:1.5px solid currentColor;border-top:1.5px solid currentColor"></span>
    <span style="position:absolute;left:0;bottom:0;width:14px;height:14px;border-left:1.5px solid currentColor;border-bottom:1.5px solid currentColor"></span>
    <span style="position:absolute;right:0;bottom:0;width:14px;height:14px;border-right:1.5px solid currentColor;border-bottom:1.5px solid currentColor"></span>
    <span data-l style="position:absolute;left:0;bottom:100%;margin-bottom:8px;white-space:nowrap;font:500 11px/1.2 'IBM Plex Mono',ui-monospace,monospace;letter-spacing:.08em;padding:4px 7px;background:rgba(5,8,11,.72);border:1px solid currentColor"></span>`;
  Object.assign(hud.style, {
    position: 'absolute', left: '0', top: '0', zIndex: '2', pointerEvents: 'none', color: '#ff5b3d',
    opacity: '0', transition: 'opacity .5s ease', textShadow: '0 0 8px rgba(255,91,61,.6)',
    boxShadow: 'inset 0 0 24px rgba(255,91,61,.08)',
  });
  host.appendChild(hud);
  const hudLabel = hud.querySelector('[data-l]');
  const hudCorners = [
    [lagoon.u0, lagoon.v0], [lagoon.u1, lagoon.v0], [lagoon.u0, lagoon.v1], [lagoon.u1, lagoon.v1],
  ].map(([u, v]) => new THREE.Vector3((u - 0.5) * W, waterLevel, (0.5 - v) * H));
  const tmpV = new THREE.Vector3();
  let hudText = '';
  function updateHud(loss) {
    const show = loss > 25 && !(anim && anim.kind === 'exit');
    hud.style.opacity = show ? '1' : '0';
    if (!show) return;
    const rw = host.clientWidth, rh = host.clientHeight;
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const c of hudCorners) {
      tmpV.copy(c).project(camera);
      const x = (tmpV.x * 0.5 + 0.5) * rw, y = (-tmpV.y * 0.5 + 0.5) * rh;
      x0 = Math.min(x0, x); x1 = Math.max(x1, x); y0 = Math.min(y0, y); y1 = Math.max(y1, y);
    }
    const pad = 10;
    hud.style.transform = `translate(${(x0 - pad).toFixed(1)}px, ${(y0 - pad).toFixed(1)}px)`;
    hud.style.width = `${(x1 - x0 + pad * 2).toFixed(1)}px`;
    hud.style.height = `${(y1 - y0 + pad * 2).toFixed(1)}px`;
    const t = `ANOMALÍA DETECTADA · −${loss}% SUPERFICIE`;
    if (t !== hudText) { hudText = t; hudLabel.textContent = t; }
  }

  // ---------- state ----------
  const reduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const state = { year: lastYear, maskOn: false, autoplay: !!autoplay && !reduced, ghostOn: false };
  let waterAmt = 0;
  let clockT = 0, timelineT = 0;
  const listeners = [];
  let lastKey = '';

  function emit(force = false) {
    const areaKm2 = Math.round(areaAt(state.year) * 100) / 100;
    const lossPct = lossAt(state.year);
    const key = `${state.year.toFixed(2)}|${areaKm2}|${state.maskOn}|${state.autoplay}|${state.ghostOn}`;
    if (!force && key === lastKey) return;
    lastKey = key;
    const payload = { year: Math.round(state.year * 100) / 100, areaKm2, lossPct, maskOn: state.maskOn, autoplay: state.autoplay, ghostOn: state.ghostOn };
    listeners.forEach((cb) => { try { cb(payload); } catch (e) { console.error(e); } });
  }

  // playback (only when the user presses play): baseline -> driest year -> hold -> recovery to last year -> hold -> rewind -> hold
  const startIdx = Math.max(0, years.indexOf(baselineYear));
  const yStart = years[startIdx] ?? years[0];
  const PH = { dry: 4.5, hold1: 2.0, recover: 4.0, hold2: 2.2, rewind: 1.6, hold3: 0.8 };
  const TL_TOTAL = Object.values(PH).reduce((a, b) => a + b, 0);
  function runTimeline(t) {
    let x = t % TL_TOTAL;
    if (x < PH.dry) { state.year = yStart + (peakYear - yStart) * smooth(x / PH.dry); return; }
    x -= PH.dry;
    if (x < PH.hold1) { state.year = peakYear; return; }
    x -= PH.hold1;
    if (x < PH.recover) { state.year = peakYear + (lastYear - peakYear) * smooth(x / PH.recover); return; }
    x -= PH.recover;
    if (x < PH.hold2) { state.year = lastYear; return; }
    x -= PH.hold2;
    if (x < PH.rewind) { state.year = lastYear - (lastYear - yStart) * smooth(x / PH.rewind); return; }
    state.year = yStart;
  }

  // ---------- camera (fixed, north-up; no orbit / parallax) ----------
  // Scene axes: +x east, -z north. Azimuth 0 puts the camera south of the target looking north (north-up, like the map at bearing 0).
  const target = lagoonCenter.clone();
  const baseRadius = clamp(lagoonSpan * 2.4, span * 0.35, span * 0.75);
  const FINAL = { pol: THREE.MathUtils.degToRad(50), r: baseRadius };
  const START = { pol: THREE.MathUtils.degToRad(25), r: baseRadius * 2.6 };
  const fogNear0 = uniforms.uFogNear.value, fogFar0 = uniforms.uFogFar.value;
  const cam = { pol: START.pol, r: START.r };
  function placeCamera() {
    camera.position.set(target.x, target.y + cam.r * Math.cos(cam.pol), target.z + cam.r * Math.sin(cam.pol));
    camera.lookAt(target);
    // keep the fog band relative to the lagoon so the terrain stays visible while the camera is far away
    const off = cam.r - baseRadius;
    uniforms.uFogNear.value = fogNear0 + off;
    uniforms.uFogFar.value = fogFar0 + off;
  }
  placeCamera();

  // camera transition: { from, to, t0, dur, kind, resolve }
  let anim = null;
  function startAnim(to, dur, kind) {
    if (anim) { const r = anim.resolve; anim = null; r(); } // a new transition supersedes the old one
    return new Promise((resolve) => {
      if (reduced || dur <= 0) { cam.pol = to.pol; cam.r = to.r; placeCamera(); resolve(); finishAnim(kind); return; }
      anim = { from: { pol: cam.pol, r: cam.r }, to, t0: performance.now(), dur, kind, resolve };
    });
  }
  function stepAnim(now) {
    if (!anim) return;
    const k = clamp((now - anim.t0) / anim.dur, 0, 1);
    const e = easeInOutCubic(k);
    cam.pol = anim.from.pol + (anim.to.pol - anim.from.pol) * e;
    cam.r = anim.from.r + (anim.to.r - anim.from.r) * e;
    if (k >= 1) {
      const { resolve, kind } = anim;
      anim = null;
      resolve();
      finishAnim(kind);
    }
  }
  function finishAnim(kind) {
    if (kind === 'enter') {
      // No autoplay: the view stays on the current (latest) year; the user scrubs back in time.
      emit();
    } else if (kind === 'exit') {
      setActive(false);
    }
  }

  // ---------- resize / visibility ----------
  function resize() {
    const w = Math.max(1, host.clientWidth), h = Math.max(1, host.clientHeight);
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    renderer.setPixelRatio(dpr);
    renderer.setSize(w, h, false);
    canvas.style.width = '100%';
    canvas.style.height = '100%';
    pUniforms.uPixelRatio.value = dpr;
    camera.aspect = w / h;
    camera.fov = w / h < 0.9 ? 52 : 38;
    camera.updateProjectionMatrix();
  }
  resize();
  new ResizeObserver(resize).observe(host);

  let visible = true;
  new IntersectionObserver((entries) => { visible = entries.some((e) => e.isIntersecting); }, { threshold: 0 }).observe(canvas);

  // ---------- loop ----------
  let prev = performance.now();
  let active = false, rafId = 0;
  function renderOnce() {
    placeCamera();
    renderer.render(scene, camera);
  }
  function setActive(on) {
    on = !!on;
    if (on === active) return;
    active = on;
    if (on) {
      prev = performance.now();
      vignette.style.opacity = '1';
      rafId = requestAnimationFrame(frame);
    } else {
      cancelAnimationFrame(rafId);
      rafId = 0;
      hud.style.opacity = '0';
      vignette.style.opacity = '0';
    }
  }
  function frame(now) {
    if (!active) return;
    rafId = requestAnimationFrame(frame);
    const dt = Math.min(0.1, (now - prev) / 1000);
    prev = now;
    stepAnim(now); // runs even when off-screen so enter()/exit() always resolve
    if (!active) return; // exit finished inside stepAnim
    if (!visible || document.hidden) return;
    clockT += dt;
    if (state.autoplay) { timelineT += dt; runTimeline(timelineT); }

    const { a, b, t } = bracket(state.year);
    uniforms.uTexA.value = satTex[a];
    uniforms.uTexB.value = satTex[b];
    uniforms.uSdfA.value = sdfTex[a];
    uniforms.uSdfB.value = sdfTex[b];
    uniforms.uMix.value = t;

    uniforms.uTime.value = clockT;

    // water overlay: on while the lagoon view is active, fades out during exit
    const waterTarget = anim && anim.kind === 'exit' ? 0 : 1;
    waterAmt += clamp(waterTarget - waterAmt, -dt * 2, dt * 1.2);
    uniforms.uWaterAmt.value = waterAmt;

    const nearest = t < 0.5 ? a : b;
    rebuildParticles(nearest);
    const loss = lossAt(state.year);
    const targetOp = clamp(loss / 40, 0, 1) * (reduced ? 0.5 : 1);
    pUniforms.uOpacity.value += (targetOp - pUniforms.uOpacity.value) * Math.min(1, dt * 3);
    pUniforms.uTime.value = reduced ? 0.37 : clockT;

    renderOnce();
    updateHud(loss);
    emit();
  }
  renderOnce(); // first frame at the START pose (the page keeps the canvas hidden until it fades it in)

  // ---------- controller ----------
  const controller = {
    years: years.slice(),
    setYear(yf) {
      state.autoplay = false;
      state.year = clamp(Number(yf) || lastYear, years[0], lastYear);
      emit();
    },
    // MNDWI overlay removed: kept as a harmless no-op for compatibility (maskOn is always false)
    setMask() {},
    setAutoplay(on) {
      on = !!on;
      if (on === state.autoplay) return;
      state.autoplay = on;
      if (on) {
        // resume timeline from the phase that matches the current year (start of cycle)
        timelineT = 0;
      }
      emit();
    },
    isAutoplay() { return state.autoplay; },
    // ghost lagoon removed: kept as harmless no-ops for compatibility with the page
    ghost: null,
    setGhost() {},
    enter({ duration = 2200 } = {}) {
      if (!active) waterAmt = 0; // water overlay fades in with the descent
      setActive(true);
      state.autoplay = false;
      vignette.style.opacity = '1';
      return startAnim(FINAL, duration, 'enter');
    },
    exit({ duration = 1400 } = {}) {
      state.autoplay = false;
      emit();
      vignette.style.opacity = '0';
      hud.style.opacity = '0';
      if (!active) { if (anim) { const r = anim.resolve; anim = null; r(); } cam.pol = START.pol; cam.r = START.r; placeCamera(); return Promise.resolve(); }
      return startAnim(START, duration, 'exit');
    },
    setActive,
    /**
     * Upload every year's imagery to the GPU now (one texture per task) instead of on the first frame
     * that needs it: the year slider and the autoplay never stall on a texture upload afterwards.
     */
    async prewarm() {
      for (const t of [...Object.values(satTex), ...Object.values(sdfTex)]) {
        if (!t || !t.image) continue;
        try { renderer.initTexture(t); } catch (err) { console.warn('[hero] prewarm:', err && err.message); return; }
        await new Promise((r) => setTimeout(r, 0));
      }
    },
    onUpdate(cb) {
      if (typeof cb === 'function') { listeners.push(cb); lastKey = ''; emit(true); }
    },
  };
  emit(true);
  return controller;
}
