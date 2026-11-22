// Landing intro on OUR map (MapLibre GL JS 5, globe projection): the page opens on the live map
// seen as a planet from space, Nico's satellite (./intro/sat3d.js, drawn by ./intro/satlayer.js
// in a transparent three.js canvas over the map) flies south along Chile with its imaging beam
// lighting a swath, while the camera makes ONE continuous flight down to the landing home view.
// Then the animated title (./intro-title.js) appears on the left; it hides itself on the first
// user interaction with the map. No second world, no cross-fade.
//
//   import { initIntro } from './intro.js';
//   const intro = initIntro({ stage, mapCtl, nav, skip: !!location.hash.slice(1), onDone });
//   intro.done.then(({ title, reason }) => ...);   // reason: done | skipped | hash | reduced-motion | fallback
//   intro.skip();                                   // jump to the end state (home view + title)
//   intro.hideTitle();                              // e.g. when a marker / hash link opens a view
//
// mapCtl is the js/map.js controller. Used (all optional, with fallbacks):
//   mapCtl.map, getHomeCamera(), introStartCamera(), setMarkersVisible(bool)
//
// Behaviour:
//   - skip: true (page opened with a hash) -> nothing at all, not even the title.
//   - prefers-reduced-motion -> no flight, no satellite: static title over the home view.
//   - three.js fails to load -> the flight still plays, without the satellite.
//   - "Saltar intro" button and Escape -> camera jumps to home, title appears.
//   - During the intro the stage chrome (nav, HUD, legend), the map controls and the markers are
//     hidden and map input is blocked; everything is restored at the end. After the hand-off
//     nothing keeps animating on its own (the title animates once on entry).
import { showTitle as showTitleImpl, TITLE_CONFIG } from './intro-title.js';

export { TITLE_CONFIG };

/**
 * Animated title on the left of the stage (implementation: js/intro-title.js).
 * @returns {{ el: HTMLElement, hide: (reason?: string) => Promise<void>, hidden: Promise<void> }}
 */
export function showTitle(opts = {}) {
  return showTitleImpl(opts);
}

// ---- timeline (seconds from the first visible frame of the globe, at SPEED 1) ----
// SPEED plays the whole scan faster without retiming every key: 1.45 turns the 6.2 s below into ~4.3 s.
const SPEED = 1.45;
const T = {
  fly: 0.6,                 // camera flight starts
  flyMs: 5200,              // ... and lasts (lands at ~5.8 s)
  satIn: [0, 0.5],          // satellite fades in while entering from the north
  satOut: [5.6, 6.2],       // ... and out while leaving south (the title does not wait for it to cross the screen)
  beamOn: [0.7, 1.3],
  beamOff: [5.3, 5.8],
  tagOn: [0.9, 4.4],        // "SENTINEL-2 · 786 KM"
  end: 6.2,                 // hand-off: chrome, markers, title (right after the camera lands at 5.8)
};
// ground-track latitude of the satellite over time [t, lat]: slows down (in degrees) as the
// camera descends so its on-screen speed stays roughly even, then speeds out to the south
const SAT_LAT = [[0, 27], [1.0, 6], [2.3, -16], [3.5, -28], [4.6, -38], [5.6, -50], [6.7, -71]];
// ground-track longitude by latitude: follows Chile's long axis
const TRACK_LNG = [[40, -71.5], [10, -70.6], [-18, -70.2], [-30, -71.0], [-38, -72.4], [-46, -73.2], [-53, -72.4], [-75, -70.5]];
const SWATH_DEG = 2.6;      // Sentinel-2 swath ~290 km
const DEFAULT_START = { center: [-62, -22], zoom: 1.8, pitch: 0, bearing: 0 };
const READY_LIMIT_MS = 2600; // max wait for the first globe frame before starting anyway
const INTRO_MAP_PIXEL_RATIO = 1;    // the map flies at this density on retina screens, full density once landed
const WARM_VIEW_LIMIT_MS = 1500;   // max wait for each of the two warm-up draws behind the loading veil
const TRACK_SRC = 'intro-track';
const TRACK_LAYERS = ['intro-track-glow', 'intro-track-core'];

const reducedMotion = () => {
  try { return matchMedia('(prefers-reduced-motion: reduce)').matches; } catch (_) { return false; }
};
const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
const smooth = (x) => x * x * (3 - 2 * x);
const span = (t, a, b) => smooth(clamp((t - a) / (b - a), 0, 1));
const lerpTable = (tab, x, desc) => {
  // tab sorted by x ascending (or descending when desc)
  for (let i = 0; i < tab.length - 1; i++) {
    const [x0, y0] = tab[i], [x1, y1] = tab[i + 1];
    const inside = desc ? (x <= x0 && x >= x1) : (x >= x0 && x <= x1);
    if (inside) return y0 + (y1 - y0) * ((x - x0) / (x1 - x0));
  }
  const first = tab[0], last = tab[tab.length - 1];
  return (desc ? x > first[0] : x < first[0]) ? first[1] : last[1];
};
/** Catmull-Rom through the SAT_LAT keys, so the satellite never jerks between keys. */
function satLat(t) {
  const k = SAT_LAT;
  if (t <= k[0][0]) return k[0][1];
  if (t >= k[k.length - 1][0]) {
    const [ta, la] = k[k.length - 2], [tb, lb] = k[k.length - 1];
    return lb + (lb - la) / (tb - ta) * (t - tb);
  }
  let i = 0;
  while (t > k[i + 1][0]) i++;
  const p0 = k[Math.max(0, i - 1)], p1 = k[i], p2 = k[i + 1], p3 = k[Math.min(k.length - 1, i + 2)];
  const u = (t - p1[0]) / (p2[0] - p1[0]);
  const m1 = (p2[1] - p0[1]) / (p2[0] - p0[0]) * (p2[0] - p1[0]);
  const m2 = (p3[1] - p1[1]) / (p3[0] - p1[0]) * (p2[0] - p1[0]);
  const u2 = u * u, u3 = u2 * u;
  return (2 * u3 - 3 * u2 + 1) * p1[1] + (u3 - 2 * u2 + u) * m1 + (-2 * u3 + 3 * u2) * p2[1] + (u3 - u2) * m2;
}
const trackLng = (lat) => lerpTable(TRACK_LNG, lat, true);

function liveCamera(map) {
  const c = map.getCenter();
  return { center: [c.lng, c.lat], zoom: map.getZoom(), pitch: map.getPitch(), bearing: map.getBearing() };
}
const call = (obj, name, ...args) => {
  try { return obj && typeof obj[name] === 'function' ? obj[name](...args) : undefined; } catch (e) { console.warn(`[intro] ${name}:`, e); return undefined; }
};

/**
 * @param {object} o
 * @param {HTMLElement} [o.stage]   header.stage#top
 * @param {object} [o.mapCtl]       js/map.js controller ({ map, getHomeCamera, introStartCamera, setMarkersVisible })
 * @param {object} [o.map]          maplibre Map (only when there is no controller)
 * @param {HTMLElement|null} [o.nav] extra element to hide during the intro (the stage chrome is hidden via .is-intro)
 * @param {boolean} [o.skip=false]  true when the page was opened with a hash: no intro, no title
 * @param {(r:{title:object|null, reason:string}) => void} [o.onDone]
 * @returns {{ done: Promise<{title:object|null, reason:string}>, skip: () => void,
 *             hideTitle: () => void, readonly title: object|null }}
 */
export function initIntro({
  stage = document.getElementById('top'), mapCtl = null, map = null, nav = null, skip = false, onDone,
} = {}) {
  const m = (mapCtl && mapCtl.map) || map || globalThis.__caudalMap || null;

  let title = null;
  let resolveDone;
  const done = new Promise((r) => { resolveDone = r; });
  let settled = false;
  const settle = (reason) => {
    if (settled) return;
    settled = true;
    const res = { title, reason };
    resolveDone(res);
    try { onDone && onDone(res); } catch (e) { console.error('[intro] onDone:', e); }
  };
  const ctl = {
    done,
    skip: () => {},
    hideTitle: () => { if (title) title.hide('external'); },
    get title() { return title; },
  };
  const revealTitle = () => {
    if (!title) title = showTitle({ stage, map: m });
  };

  if (!stage) { settle('no-stage'); return ctl; }
  if (skip) { stage.classList.remove('is-intro'); settle('hash'); return ctl; }
  if (reducedMotion() || !m) {
    stage.classList.remove('is-intro');
    revealTitle();
    settle(m ? 'reduced-motion' : 'fallback');
    return ctl;
  }

  // ---- cameras + limits ----
  // With js/map.js the controller lifts and restores its own zoom/pan limits (introStartCamera /
  // setMarkersVisible(true)); with a bare map we do it here.
  const ownLimits = !(mapCtl && typeof mapCtl.introStartCamera === 'function');
  const saved = { minZoom: m.getMinZoom(), maxBounds: m.getMaxBounds() };
  const home = call(mapCtl, 'getHomeCamera') || liveCamera(m);
  const start = { ...DEFAULT_START, ...(call(mapCtl, 'introStartCamera') || {}) };
  try {
    m.stop();
    if (ownLimits) { m.setMaxBounds(null); m.setMinZoom(0); }
    m.jumpTo(start);
  } catch (e) { console.warn('[intro] start camera:', e); }

  // ---- DOM: overlay (dark cover until the globe has drawn, then an input blocker) ----
  const overlay = document.createElement('div');
  overlay.className = 'intro-overlay';
  overlay.setAttribute('aria-hidden', 'true');
  const canvas = document.createElement('canvas');
  canvas.className = 'intro-canvas';
  const tag = document.createElement('span');
  tag.className = 'intro-tag';
  tag.textContent = 'Sentinel-2 · 786 km';
  overlay.append(canvas, tag);
  const skipBtn = document.createElement('button');
  skipBtn.type = 'button';
  skipBtn.className = 'intro-skip';
  skipBtn.textContent = 'Saltar intro';
  stage.append(overlay, skipBtn);
  stage.classList.add('is-intro');
  stage.dataset.intro = 'loading';
  if (nav) nav.classList.add('intro-nav-hidden');
  call(mapCtl, 'setMarkersVisible', false);

  let phase = 'loading'; // loading -> playing -> gone
  let layer = null;
  let raf = 0;
  let t0 = 0;
  let flying = false;
  let landed = false;
  const timers = [];
  const track = [];
  let trackOn = false;
  let frameN = 0;

  // ---- ground track on the map (temporary MapLibre line under the beam) ----
  const kmWidth = (k) => ['interpolate', ['exponential', 2], ['zoom'], 0, SWATH_DEG * (512 / 360) * k, 10, SWATH_DEG * (512 / 360) * k * 1024];
  const addTrack = () => {
    try {
      if (m.getSource(TRACK_SRC)) return true;
      m.addSource(TRACK_SRC, { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
      m.addLayer({
        id: TRACK_LAYERS[0], type: 'line', source: TRACK_SRC,
        layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: { 'line-color': '#45d6ee', 'line-width': kmWidth(1.9), 'line-blur': kmWidth(1.1), 'line-opacity': 0.22, 'line-opacity-transition': { duration: 600, delay: 0 } },
      });
      m.addLayer({
        id: TRACK_LAYERS[1], type: 'line', source: TRACK_SRC,
        layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: { 'line-color': '#a9f0ff', 'line-width': kmWidth(0.9), 'line-blur': kmWidth(0.35), 'line-opacity': 0.16, 'line-opacity-transition': { duration: 600, delay: 0 } },
      });
      trackOn = true;
      return true;
    } catch (e) { console.warn('[intro] track layer:', e); return false; }
  };
  const setTrack = () => {
    if (!trackOn || track.length < 2) return;
    try { m.getSource(TRACK_SRC).setData({ type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: track } }); } catch (_) { /* style reloading */ }
  };
  const removeTrack = (fadeMs) => {
    if (!trackOn) return;
    trackOn = false;
    const rm = () => {
      try {
        TRACK_LAYERS.forEach((id) => m.getLayer(id) && m.removeLayer(id));
        if (m.getSource(TRACK_SRC)) m.removeSource(TRACK_SRC);
      } catch (_) { /* map gone */ }
    };
    if (!fadeMs) { rm(); return; }
    try { TRACK_LAYERS.forEach((id) => m.setPaintProperty(id, 'line-opacity', 0)); } catch (_) { /* ignore */ }
    setTimeout(rm, fadeMs + 80);
  };

  // ---- hand-off ----
  const restoreMap = () => {
    if (ownLimits) {
      try {
        m.setMinZoom(saved.minZoom);
        if (saved.maxBounds) m.setMaxBounds(saved.maxBounds);
      } catch (e) { console.warn('[intro] restore limits:', e); }
    }
    call(mapCtl, 'setMarkersVisible', true);
  };
  function finish(reason) {
    if (phase === 'gone') return;
    const quick = reason !== 'done';
    phase = 'gone';
    stage.dataset.intro = `gone:${reason}`;
    cancelAnimationFrame(raf);
    timers.forEach(clearTimeout);
    removeEventListener('keydown', onKey);
    removeEventListener('hashchange', onHash);
    setMapDensity(fullDensity);
    removeEventListener('resize', dropOffset);
    removeEventListener('scroll', dropOffset);
    try {
      if (quick) { m.stop(); m.jumpTo(home); }
    } catch (_) { /* ignore */ }
    restoreMap();
    removeTrack(quick ? 0 : 600);
    try { layer && layer.dispose(); } catch (e) { console.warn('[intro] dispose:', e); }
    layer = null;
    overlay.remove();
    skipBtn.remove();
    stage.classList.remove('is-intro');
    if (nav) nav.classList.remove('intro-nav-hidden');
    if (reason !== 'hash') revealTitle();
    settle(reason);
  }

  const onKey = (e) => { if (e.key === 'Escape') ctl.skip(); };
  const onHash = () => { if (location.hash.slice(1)) finish('hash'); };
  ctl.skip = () => {
    if (phase === 'gone') { revealTitle(); return; }
    finish('skipped');
  };
  skipBtn.addEventListener('click', () => ctl.skip());
  addEventListener('keydown', onKey);
  addEventListener('hashchange', onHash);
  // input during the flight is swallowed by the overlay; a wheel would otherwise scroll the page
  overlay.addEventListener('wheel', (e) => e.preventDefault(), { passive: false });

  // ---- per-frame ----
  // measured once per layout change, not per frame (two forced layouts a frame otherwise)
  let offset = null;
  const dropOffset = () => { offset = null; };
  addEventListener('resize', dropOffset);
  addEventListener('scroll', dropOffset, { passive: true });
  const mapOffset = () => {
    if (!offset) {
      const sr = canvas.getBoundingClientRect(), mr = m.getContainer().getBoundingClientRect();
      offset = { x: mr.left - sr.left, y: mr.top - sr.top, w: sr.width, h: sr.height };
    }
    return offset;
  };
  const project = (lng, lat, off) => {
    const p = m.project([lng, lat]);
    return { x: p.x + off.x, y: p.y + off.y };
  };

  function frame(now) {
    if (phase !== 'playing') return;
    const t = (now - t0) / 1000 * SPEED;
    frameN++;

    if (!flying && t >= T.fly) {
      flying = true;
      try {
        m.once('moveend', () => { landed = true; });
        m.flyTo({ ...home, duration: T.flyMs / SPEED, curve: 1.25, essential: true, easing: (x) => (x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2) });
      } catch (e) { console.warn('[intro] flyTo:', e); landed = true; }
    }

    const lat = satLat(t);
    const lng = trackLng(lat);
    const beam = span(t, T.beamOn[0], T.beamOn[1]) * (1 - span(t, T.beamOff[0], T.beamOff[1]));
    const alpha = span(t, T.satIn[0], T.satIn[1]) * (1 - span(t, T.satOut[0], T.satOut[1]));

    // imaged strip: extend while the beam is on
    if (beam > 0.05 && lat < 20 && lat > -58) {
      const last = track[track.length - 1];
      if (!last || Math.abs(last[1] - lat) > 0.25) track.push([lng, lat]);
      if (frameN % 2 === 0) setTrack();
    }

    try {
      const off = mapOffset();
      const g = project(lng, lat, off);
      const cosL = Math.max(0.2, Math.cos(lat * Math.PI / 180));
      const a = project(lng - SWATH_DEG / 2 / cosL, lat, off), b = project(lng + SWATH_DEG / 2 / cosL, lat, off);
      const z = m.getZoom();
      const k = clamp(Math.min(off.w / 1440, off.h / 820), 0.62, 1.15);
      const size = clamp(70 * Math.pow(2, (z - 1.6) * 0.34), 56, 175) * k;
      const alt = size * 1.55;
      const sat = { x: g.x - size * 0.12, y: g.y - alt };
      const swath = Math.max(Math.hypot(b.x - a.x, b.y - a.y), size * 0.3);
      if (layer) layer.render({ sat, ground: g, size, swath, beam, alpha, roll: Math.sin(t * 0.6) * 0.12 });

      const tagOn = t >= T.tagOn[0] && t <= T.tagOn[1] && !!layer;
      tag.classList.toggle('is-on', tagOn);
      if (tagOn) {
        // right of the satellite; flips to its left when it would leave the viewport (phones)
        const tw = tag.offsetWidth || 170;
        let tx = sat.x + size * 0.7;
        if (tx + tw > off.w - 12) tx = sat.x - size * 0.7 - tw;
        tx = clamp(tx, 8, Math.max(8, off.w - tw - 8));
        tag.style.transform = `translate(${Math.round(tx)}px, ${Math.round(Math.max(8, sat.y - size * 0.45))}px)`;
      }
    } catch (_) { /* projection not ready */ }

    if (t >= T.end && (landed || t >= T.end + 2)) {
      if (!landed) { try { m.stop(); m.jumpTo(home); } catch (_) { /* ignore */ } }
      finish('done');
      return;
    }
    raf = requestAnimationFrame(frame);
  }

  // ---- start: globe drawn (or timeout) + three.js loaded (or not) ----
  const mapReady = new Promise((r) => {
    const t = setTimeout(r, READY_LIMIT_MS);
    const go = () => { clearTimeout(t); r(); };
    try {
      if (m.loaded() && m.areTilesLoaded && m.areTilesLoaded()) requestAnimationFrame(() => requestAnimationFrame(go));
      else m.once('idle', go);
    } catch (_) { go(); }
  });
  const layerReady = import('./intro/satlayer.js')
    .then((mod) => { if (phase === 'gone') return; layer = mod.createSatLayer(canvas); })
    .catch((e) => { console.warn('[intro] satellite layer unavailable, flying without it:', e); });

  // On a retina screen the globe + relief at full density is 4x the pixels and the flight drops to
  // ~40 fps on an integrated GPU. Nobody reads detail on a planet that is moving: fly at a lower
  // density and go back to full when the flight ends.
  const fullDensity = (typeof m.getPixelRatio === 'function' && m.getPixelRatio()) || window.devicePixelRatio || 1;
  function setMapDensity(ratio) {
    try { if (typeof m.setPixelRatio === 'function' && m.getPixelRatio() !== ratio) m.setPixelRatio(ratio); }
    catch (e) { console.warn('[intro] pixel ratio:', e); }
  }

  // While the loading veil still covers the map, draw the landing view once and come back: the map
  // compiles its flat-projection shaders and loads the landing tiles now, instead of in the middle
  // of the flight (that was a 150 ms freeze at the globe -> flat switch plus a run of slow frames).
  const mapSettled = (ms) => new Promise((r) => {
    const t = setTimeout(r, ms);
    try { m.once('idle', () => { clearTimeout(t); r(); }); } catch (_) { /* the timeout resolves it */ }
  });
  async function warmLandingView() {
    try {
      m.jumpTo(home);
      await mapSettled(WARM_VIEW_LIMIT_MS);
      if (phase !== 'loading') return;
      m.jumpTo(start);
      await mapSettled(WARM_VIEW_LIMIT_MS);
    } catch (e) { console.warn('[intro] warm-up:', e); }
  }

  Promise.race([Promise.all([mapReady, layerReady]), new Promise((r) => setTimeout(r, READY_LIMIT_MS + 400))]).then(async () => {
    if (phase !== 'loading') return;
    await warmLandingView();
    if (phase !== 'loading') return;
    setMapDensity(Math.min(fullDensity, INTRO_MAP_PIXEL_RATIO));
    addTrack();
    phase = 'playing';
    stage.dataset.intro = 'playing';
    overlay.classList.add('is-clear');
    t0 = performance.now();
    raf = requestAnimationFrame(frame);
  });

  return ctl;
}
