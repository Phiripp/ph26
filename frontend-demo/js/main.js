// Caudal · landing orchestration.
// Modes on #stage: landing | to-lagoon | lagoon | to-valle | valle | to-landing.
// Every module is imported dynamically so a failure in one (or in its CDN deps) cannot take down the page.
const initHero = async opts => (await import('./hero.js')).initHero(opts);
const initMap = async opts => (await import('./map.js')).initMap(opts);
const initValle = async opts => (await import('./valle.js')).initValle(opts);
const loadPetorca = async () => (await import('./petorca-data.js')).loadPetorca(PETORCA_DATA);
// panel modules (ficha / expediente / ruta): cached, but retried if a load fails
let panelsCache = null;
const panels = () => (panelsCache ??= Promise.all([
  import('./ficha.js'), import('./expediente.js'), import('./ruta-panel.js'),
]).then(([ficha, expediente, ruta]) => ({ ...ficha, ...expediente, ...ruta }))
  .catch(err => { panelsCache = null; throw err; }));

const $ = id => document.getElementById(id);
const RM = matchMedia('(prefers-reduced-motion: reduce)').matches;
const MOBILE = matchMedia('(max-width: 760px)');
const MANIFEST_URL = 'assets/aculeo/manifest.json';
const ASSET_DIR = 'assets/aculeo/';
const LAGOON_ID = 'aculeo';
const VALLE_ID = 'petorca';
const VALLE_ASSETS = 'assets/petorca/';
const PETORCA_DATA = 'data/petorca/';
const VALLE_BBOX_FALLBACK = [-71.06, -32.31, -70.89, -32.22];
const LAGOON_CAM = { center: [-70.914, -33.843], zoom: 11.3, pitch: 50, bearing: 0, duration: 2600 };
const SITE_ZOOM = 7;
const ENTER_MS = 2200, EXIT_MS = 1400;
const ROUTE_MS = 16000;
const nf1 = new Intl.NumberFormat('es-CL', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const MINUS = '−';
const sleep = ms => new Promise(r => setTimeout(r, ms));
const SVGNS = 'http://www.w3.org/2000/svg';
const BIG_LOSS = 0.5;   // a year is flagged amber when it holds < 50% of the baseline water
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const isValleSite = s => !!s && (!!s.valle || s.id === VALLE_ID);

function dms(v, pos, neg) {
  const s = v < 0 ? neg : pos; v = Math.abs(v);
  const d = Math.floor(v), mf = (v - d) * 60, m = Math.floor(mf), sec = Math.round((mf - m) * 60) % 60;
  return `${d}°${String(m).padStart(2, '0')}′${String(sec).padStart(2, '0')}″${s}`;
}

function showFallback(host, text) {
  if (!host) return;
  const d = document.createElement('div');
  d.className = 'fallback';
  d.setAttribute('role', 'status');
  d.innerHTML = `<span>${text}</span>`;
  host.appendChild(d);
}

function loadImage(src) {
  return new Promise((res, rej) => {
    const im = new Image();
    im.decoding = 'async';
    im.onload = () => res(im);
    im.onerror = () => rej(new Error('No se pudo cargar ' + src));
    im.src = src;
  });
}

/* ---------- reveal on scroll (content visible at rest without JS) ---------- */
function setupReveal() {
  if (RM || !('IntersectionObserver' in window)) return;
  document.documentElement.classList.add('reveal-ready');
  const io = new IntersectionObserver(es => es.forEach(e => {
    if (e.isIntersecting) { e.target.classList.add('in'); io.unobserve(e.target); }
  }), { threshold: .12, rootMargin: '0px 0px -5% 0px' });
  document.querySelectorAll('.reveal').forEach(el => io.observe(el));
  // Safety net: never leave content hidden.
  setTimeout(() => document.querySelectorAll('.reveal:not(.in)').forEach(el => {
    const r = el.getBoundingClientRect();
    if (r.top < innerHeight) el.classList.add('in');
  }), 2500);
}

/* ---------- manifest (shared by hero labels + Aculeo thumbnails) ---------- */
let manifestP = null;
const getManifest = () => (manifestP ??= fetch(MANIFEST_URL).then(r => {
  if (!r.ok) throw new Error('manifest ' + r.status);
  return r.json();
}));

/* ---------- hero (3D lagoon): init once at startup so textures preload ---------- */
async function setupHero() {
  const canvas = $('hero-canvas');
  const play = $('play'), scrub = $('scrub');
  const elYr = $('yr'), elArea = $('area'), elDelta = $('delta'), elScene = $('scene');
  let ctl;
  try {
    ctl = await initHero({ canvas, manifestUrl: MANIFEST_URL, autoplay: false });
    if (!ctl || !Array.isArray(ctl.years) || !ctl.years.length) throw new Error('controlador inválido');
    if (typeof ctl.enter !== 'function' || typeof ctl.exit !== 'function') throw new Error('hero sin enter()/exit()');
  } catch (err) {
    console.error('[Caudal] hero:', err);
    canvas.style.display = 'none';
    [play, scrub].forEach(el => { el.disabled = true; });
    $('wh').hidden = true;
    play.querySelector('.txt').textContent = 'Sin imagen';
    return null;
  }

  const years = ctl.years;
  const y0 = years[0], y1 = years[years.length - 1];
  scrub.min = y0; scrub.max = y1;
  scrub.value = y1;   // opens on the latest year; the user scrubs back
  getManifest().then(m => { if (m.baselineYear) $('base-yr').textContent = m.baselineYear; }).catch(() => { $('base-yr').textContent = y0; });

  /* year ticks under the slider */
  const ticks = $('scrub-ticks');
  const tickEls = years.map(y => {
    const t = document.createElement('span');
    t.textContent = y;
    t.style.left = (y1 > y0 ? (y - y0) / (y1 - y0) * 100 : 0) + '%';
    ticks.appendChild(t);
    return t;
  });

  const goYear = y => {
    if (ctl.isAutoplay()) { ctl.setAutoplay(false); setPlayUI(false); }
    ctl.setYear(y);
    scrub.value = y;
  };
  const wh = setupWaterHistory(years, goYear);

  let last = '';
  const setPlayUI = auto => {
    play.setAttribute('aria-pressed', String(auto));
    play.querySelector('.txt').textContent = auto ? 'Pausar' : 'Reproducir';
  };
  ctl.onUpdate(st => {
    const yr = Math.round(st.year);
    const loss = Math.max(0, Math.round(st.lossPct || 0));
    const area = Number.isFinite(st.areaKm2) ? nf1.format(st.areaKm2) : '—';
    const key = `${yr}|${area}|${loss}`;
    if (key !== last) {
      last = key;
      elYr.textContent = yr;
      scrub.setAttribute('aria-valuetext', String(yr));
      tickEls.forEach((t, i) => t.classList.toggle('on', years[i] === yr));
      elArea.textContent = area;
      elDelta.textContent = loss <= 0 ? '0%' : `${MINUS}${loss}%`;
      elScene.textContent = `Escena ${yr} · Sentinel-2 L2A`;
    }
    if (st.autoplay && document.activeElement !== scrub) scrub.value = st.year;
    wh.update(st.year);
    setPlayUI(!!st.autoplay);
  });

  scrub.addEventListener('input', () => ctl.setYear(parseFloat(scrub.value)));
  play.addEventListener('click', () => {
    const next = !ctl.isAutoplay();
    ctl.setAutoplay(next);
    setPlayUI(next);
  });
  setPlayUI(ctl.isAutoplay());
  wh.update(y1);
  return ctl;
}

/* ---------- water history mini-chart (km² per year, in the lagoon bar) ---------- */
function setupWaterHistory(years, onPick) {
  const svg = $('wh-svg'), labels = $('wh-yrs'), fig = $('wh');
  const W = 220, H = 40, PAD = 2, n = years.length;
  const slot = (W - PAD * 2) / n, bw = Math.min(18, slot * 0.62);
  const cx = i => PAD + slot * (i + 0.5);
  const el = (tag, attrs) => { const e = document.createElementNS(SVGNS, tag); for (const k in attrs) e.setAttribute(k, attrs[k]); return e; };
  svg.setAttribute('preserveAspectRatio', 'none');
  let bars = [], yrEls = [], marker = null, curYr = null, km = [];

  const yrPct = i => cx(i) / W * 100 + '%';
  years.forEach((y, i) => {
    const s = document.createElement('span');
    s.textContent = "'" + String(y).slice(-2);
    s.style.left = yrPct(i);
    labels.appendChild(s);
    yrEls.push(s);
  });

  getManifest().then(m => {
    const val = y => { const w = m.water?.[y]; if (!w) return NaN; return Number.isFinite(w.km2Clean) ? w.km2Clean : w.km2; };
    const base = m.baselineYear ?? years[0];
    const baseKm = val(base);
    km = years.map(val);
    const max = Math.max(...km.filter(Number.isFinite), 0.001);
    svg.appendChild(el('line', { class: 'axis', x1: 0, x2: W, y1: H - 0.5, y2: H - 0.5 }));
    years.forEach((y, i) => {
      const v = km[i];
      const h = Number.isFinite(v) ? Math.max(1.5, (v / max) * (H - 4)) : 0;
      const kind = y === base ? 'base' : (Number.isFinite(v) && Number.isFinite(baseKm) && v < baseKm * BIG_LOSS ? 'lost' : 'ok');
      const r = el('rect', { class: 'bar ' + kind, x: cx(i) - bw / 2, y: H - 1 - h, width: bw, height: h });
      r.dataset.kind = kind;
      const hit = el('rect', { class: 'hit', x: cx(i) - slot / 2, y: 0, width: slot, height: H, tabindex: '0', role: 'button' });
      const label = `${y}: ${Number.isFinite(v) ? nf1.format(v) + ' km²' : 'sin dato'}`;
      hit.setAttribute('aria-label', 'Ir a ' + label);
      const t = el('title', {}); t.textContent = label; hit.appendChild(t);
      hit.addEventListener('click', () => onPick(y));
      hit.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onPick(y); } });
      svg.appendChild(r); svg.appendChild(hit);
      bars.push(r);
    });
    marker = el('line', { class: 'mk', x1: 0, x2: 0, y1: 0, y2: H, 'vector-effect': 'non-scaling-stroke' });
    svg.appendChild(marker);
    svg.setAttribute('aria-label', 'Superficie de agua por año (km²): ' + years.map((y, i) => `${y} ${Number.isFinite(km[i]) ? nf1.format(km[i]) : '—'}`).join(', '));
    curYr = null;
    update(lastFloat);
  }).catch(err => { console.error('[Caudal] water history:', err); fig.hidden = true; });

  let lastFloat = years[n - 1];
  function update(yf) {
    if (!Number.isFinite(yf)) return;
    lastFloat = yf;
    const f = Math.min(Math.max(yf - years[0], 0), years[n - 1] - years[0]);
    let i = 0;
    while (i < n - 2 && years[i + 1] - years[0] <= f) i++;
    const span = n > 1 ? (years[i + 1] - years[i]) : 1;
    const t = n > 1 ? (f - (years[i] - years[0])) / span : 0;
    const x = n > 1 ? cx(i) + (cx(i + 1) - cx(i)) * Math.min(Math.max(t, 0), 1) : cx(0);
    if (marker) { marker.setAttribute('x1', x); marker.setAttribute('x2', x); }
    const yr = Math.round(yf);
    if (yr === curYr || !bars.length) return;
    curYr = yr;
    bars.forEach((b, k) => { b.setAttribute('class', 'bar ' + (years[k] === yr ? 'cur' : b.dataset.kind)); });
    yrEls.forEach((s, k) => s.classList.toggle('on', years[k] === yr));
  }
  return { update };
}

/* ---------- section 02: Petorca summary (counts + top alta predios + route) ---------- */
async function setupVallesSummary() {
  const list = $('vs-list');
  try {
    const [data, fmt] = await Promise.all([loadPetorca(), import('./petorca-data.js')]);
    const c = data.counts || {};
    $('vs-alta').textContent = c.alta ?? '—';
    $('vs-media').textContent = c.media ?? '—';
    $('vs-baja').textContent = c.baja ?? '—';
    $('vs-sin').textContent = c.sin_alerta ?? '—';
    $('vs-total').textContent = data.predios.length;
    $('vh-count').textContent = data.predios.length;
    const n = $('vt-predios-n'); if (n) n.textContent = `· ${data.predios.length}`;
    const top = data.predios.map(f => f.properties)
      .filter(p => p.banda === 'alta')
      .sort((a, b) => (b.indice ?? 0) - (a.indice ?? 0))
      .slice(0, 5);
    list.innerHTML = top.length ? top.map(p => `<li><span class="id">${esc(p.id)}</span><span class="cu">${esc(p.cultivo || '—')} · ${esc(fmt.fmtNum(p.area_ha, 1))} ha</span><span class="m3">${esc(fmt.fmtRange(p.m3_estimado_min, p.m3_estimado_max))}</span></li>`).join('')
      : '<li class="note">Sin predios en banda alta.</li>';
    const r = data.ruta;
    if (r && Array.isArray(r.paradas)) {
      const h = Math.floor(r.duracion_min / 60), m = Math.round(r.duracion_min % 60);
      $('vs-route').textContent = `Ruta de inspección: ${r.paradas.length} paradas · ${nf1.format(r.distancia_km)} km · ${h} h ${String(m).padStart(2, '0')} min · sale ${r.inicio?.hora || '08:30'} desde ${r.inicio?.nombre || 'Plaza de Petorca'}`;
    }
  } catch (err) {
    console.error('[Caudal] petorca summary:', err);
    list.innerHTML = '<li class="note">No se pudieron cargar los datos de Petorca.</li>';
  }
}

/* ---------- section 02: other (illustrative) signals on the map ---------- */
function setupOthers(sites, onPick) {
  const list = $('sites');
  const others = sites.filter(s => !isValleSite(s));
  $('count').textContent = others.length;
  others.slice().sort((a, b) => b.loss - a.loss).forEach(s => {
    const b = document.createElement('button');
    b.type = 'button'; b.className = 'site'; b.dataset.id = s.id;
    b.setAttribute('aria-pressed', 'false');
    const tag = s.id === LAGOON_ID ? '<span class="tag">3D · contexto</span>' : '';
    b.innerHTML = `<span>${esc(s.name)}${tag}<small>${esc(s.region)} · ${esc(s.type)}</small></span><span class="bar"><i class="${s.loss >= 85 ? 'crit' : ''}" style="width:${+s.loss || 0}%"></i></span><span class="pct">${+s.loss || 0}%</span>`;
    b.addEventListener('click', () => onPick(s.id));
    list.appendChild(b);
  });
  return {
    mark(id) { list.querySelectorAll('.site').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.id === id))); },
  };
}

/* ---------- Aculeo context thumbnails (before / driest year) ---------- */
let cropP = null;
async function getCrop(m) {
  const W = m.size.w, H = m.size.h, aspect = 16 / 9;
  const fallback = () => {
    const w = Math.min(W * .7, H * .7 * aspect), h = w / aspect;
    return { x: (W - w) / 2, y: (H - h) / 2, w, h };
  };
  try {
    const wInfo = m.water && m.water[String(m.baselineYear)];
    if (!wInfo || !wInfo.maskFile) return fallback();
    const im = await loadImage(ASSET_DIR + wInfo.maskFile);
    const mw = 256, mh = Math.max(1, Math.round(256 * im.naturalHeight / im.naturalWidth));
    const c = document.createElement('canvas'); c.width = mw; c.height = mh;
    const g = c.getContext('2d', { willReadFrequently: true }); g.drawImage(im, 0, 0, mw, mh);
    const d = g.getImageData(0, 0, mw, mh).data;
    let x0 = mw, y0 = mh, x1 = -1, y1 = -1;
    for (let y = 0; y < mh; y++) for (let x = 0; x < mw; x++) {
      if (d[(y * mw + x) * 4] > 127) { if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y; }
    }
    if (x1 < 0) return fallback();
    const sx = W / mw, sy = H / mh;
    const cx = (x0 + x1 + 1) / 2 * sx, cy = (y0 + y1 + 1) / 2 * sy;
    let w = Math.max((x1 - x0 + 1) * sx, (y1 - y0 + 1) * sy * aspect) * 1.35;
    w = Math.min(w, W, H * aspect); const h = w / aspect;
    return { x: Math.min(Math.max(0, cx - w / 2), W - w), y: Math.min(Math.max(0, cy - h / 2), H - h), w, h };
  } catch { return fallback(); }
}

/* "After" = the driest year (2020 for Aculeo), not the last one: the lagoon partially recovered by 2024. */
function driestYear(m) {
  let best = null, bestKm = Infinity;
  for (const y of m.years) {
    const km = m.water?.[y]?.km2;
    if (Number.isFinite(km) && km < bestKm) { bestKm = km; best = y; }
  }
  return best ?? m.years[m.years.length - 1];
}

async function drawThumbs() {
  const ca = $('th-a'), cb = $('th-b'), capA = $('th-a-c'), capB = $('th-b-c'), msg = $('ac-msg');
  try {
    const m = await getManifest();
    const base = m.baselineYear ?? m.years[0];
    const low = driestYear(m);
    const lastY = m.years[m.years.length - 1];
    capA.textContent = `Línea base · ${base}`;
    capB.textContent = `Mínimo · ${low}`;
    const [ia, ib, crop] = await Promise.all([
      loadImage(`${ASSET_DIR}sat-${base}.jpg`),
      loadImage(`${ASSET_DIR}sat-${low}.jpg`),
      (cropP ??= getCrop(m)),
    ]);
    for (const [cv, im, yr, km] of [[ca, ia, base, m.water?.[base]?.km2], [cb, ib, low, m.water?.[low]?.km2]]) {
      const g = cv.getContext('2d');
      g.imageSmoothingQuality = 'high';
      const kx = im.naturalWidth / m.size.w, ky = im.naturalHeight / m.size.h;
      g.drawImage(im, crop.x * kx, crop.y * ky, crop.w * kx, crop.h * ky, 0, 0, cv.width, cv.height);
      stamp(g, cv, `${yr}${Number.isFinite(km) ? ' · ' + nf1.format(km) + ' km²' : ''}`);
    }
    const lastKm = m.water?.[lastY]?.km2;
    msg.textContent = m.synthetic
      ? 'Imágenes sintéticas de respaldo en este prototipo.'
      : `Imágenes Sentinel-2 cloudless reales (EOX), superficie medida con MNDWI. En ${lastY} la laguna recuperó parte del agua${Number.isFinite(lastKm) ? ` (${nf1.format(lastKm)} km²)` : ''}.`;
  } catch (err) {
    console.error('[Caudal] thumbnails:', err);
    for (const cv of [ca, cb]) {
      const g = cv.getContext('2d');
      g.fillStyle = '#0a1015'; g.fillRect(0, 0, cv.width, cv.height);
      g.fillStyle = '#8b9ba4'; g.font = '500 20px "IBM Plex Mono", monospace'; g.textAlign = 'center';
      g.fillText('Imagen no disponible', cv.width / 2, cv.height / 2);
    }
  }
}

function stamp(g, cv, text) {
  g.save();
  g.font = '500 18px "IBM Plex Mono", monospace';
  const w = g.measureText(text).width + 18;
  g.fillStyle = 'rgba(5,8,11,.78)'; g.fillRect(10, cv.height - 40, w, 30);
  g.fillStyle = '#e4ebee'; g.textBaseline = 'middle'; g.fillText(text, 19, cv.height - 25);
  g.strokeStyle = 'rgba(69,214,238,.8)'; g.lineWidth = 2;
  const L = 22, p = 8;
  g.beginPath();
  g.moveTo(p, p + L); g.lineTo(p, p); g.lineTo(p + L, p);
  g.moveTo(cv.width - p - L, p); g.lineTo(cv.width - p, p); g.lineTo(cv.width - p, p + L);
  g.stroke();
  g.restore();
}

function lazyOnView(el, fn) {
  if (!el) return;
  if (!('IntersectionObserver' in window)) { fn(); return; }
  const io = new IntersectionObserver(es => { if (es.some(e => e.isIntersecting)) { io.disconnect(); fn(); } }, { rootMargin: '200px' });
  io.observe(el);
}

/* ---------- valley side panel: ranking -> ficha -> expediente  |  ruta ---------- */
function setupVallePanel({ getValle }) {
  const panel = $('valle-panel');
  const panePredios = $('vp-predios'), paneRuta = $('vp-ruta'), body = $('vp-body');
  const tabs = { predios: $('vt-predios'), ruta: $('vt-ruta') };
  const grip = $('vp-grip');
  const st = { tab: 'predios', view: 'ranking', selectedId: null, playing: false, rutaCtl: null, rutaRendered: false };
  let dataP = null;
  const data = () => (dataP ??= loadPetorca().catch(err => { dataP = null; throw err; }));

  const fail = (el, err, what) => {
    console.error(`[Caudal] panel ${what}:`, err);
    el.innerHTML = `<p class="vp-error">No se pudo cargar ${esc(what)}. Revisa la consola.</p>`;
  };
  const valleCall = (fn, ...args) => {
    const v = getValle();
    if (v && typeof v[fn] === 'function') { try { return v[fn](...args); } catch (e) { console.error(`[Caudal] valle.${fn}:`, e); } }
    return undefined;
  };

  async function showRanking() {
    st.view = 'ranking';
    try {
      const [d, P] = await Promise.all([data(), panels()]);
      if (st.view !== 'ranking') return;
      P.renderRanking(panePredios, d, { selectedId: st.selectedId, onSelect: id => selectPredio(id, { from: 'panel' }) });
    } catch (err) { fail(panePredios, err, 'el ranking de predios'); }
  }

  async function showFicha(id) {
    st.view = 'ficha';
    try {
      const [d, P] = await Promise.all([data(), panels()]);
      if (st.view !== 'ficha' || st.selectedId !== id) return;
      const f = d.byId.get(id);
      if (!f) { showRanking(); return; }
      P.renderFicha(panePredios, f, d, {
        onExpediente: pid => showExpediente(pid || id),
        onBack: () => deselect(),
      });
      body.scrollTop = 0;
    } catch (err) { fail(panePredios, err, 'la ficha del predio'); }
  }

  async function showExpediente(id) {
    st.view = 'expediente';
    try {
      const [d, P] = await Promise.all([data(), panels()]);
      if (st.view !== 'expediente') return;
      const f = d.byId.get(id);
      if (!f) { showRanking(); return; }
      P.renderExpediente(panePredios, f, d, { onBack: () => showFicha(id) });
      body.scrollTop = 0;
    } catch (err) { fail(panePredios, err, 'el expediente'); }
  }

  async function showRuta() {
    if (st.rutaRendered) return;
    try {
      const [d, P] = await Promise.all([data(), panels()]);
      if (st.rutaRendered) return;
      st.rutaCtl = P.renderRuta(paneRuta, d, {
        onPlay: () => playRoute(),
        onStop: pid => { if (pid) { st.selectedId = pid; valleCall('selectPredio', pid); } },
        onGPX: () => {},
      }) || null;
      st.rutaRendered = true;
    } catch (err) { fail(paneRuta, err, 'la ruta de inspección'); }
  }

  async function playRoute() {
    if (st.playing) return;
    const v = getValle();
    if (!v || typeof v.playRoute !== 'function') return;
    st.playing = true;
    panel.classList.add('playing');
    valleCall('showRoute', true);
    try { await v.playRoute({ duration: ROUTE_MS }); }
    catch (err) { console.error('[Caudal] playRoute:', err); }
    st.playing = false;
    panel.classList.remove('playing');
  }

  function setTab(tab, { focus = false } = {}) {
    st.tab = tab;
    for (const [k, b] of Object.entries(tabs)) {
      const on = k === tab;
      b.setAttribute('aria-selected', String(on));
      b.tabIndex = on ? 0 : -1;
    }
    panePredios.hidden = tab !== 'predios';
    paneRuta.hidden = tab !== 'ruta';
    body.scrollTop = 0;
    if (tab === 'ruta') showRuta();
    valleCall('showRoute', tab === 'ruta' || st.playing);
    if (focus) tabs[tab].focus();
  }

  function selectPredio(id, { from = 'panel' } = {}) {
    if (!id) { deselect({ from }); return; }
    st.selectedId = id;
    if (from !== 'valle') valleCall('selectPredio', id);
    if (st.tab !== 'predios') setTab('predios');
    showFicha(id);
  }

  function deselect({ from = 'panel' } = {}) {
    st.selectedId = null;
    if (from !== 'valle') valleCall('selectPredio', null);
    showRanking();
  }

  tabs.predios.addEventListener('click', () => setTab('predios'));
  tabs.ruta.addEventListener('click', () => setTab('ruta'));
  for (const b of Object.values(tabs)) {
    b.addEventListener('keydown', e => {
      if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
      e.preventDefault();
      setTab(st.tab === 'predios' ? 'ruta' : 'predios', { focus: true });
    });
  }
  grip.addEventListener('click', () => {
    const ex = panel.classList.toggle('expanded');
    grip.setAttribute('aria-expanded', String(ex));
    syncInsets();
  });

  /* tell the 3D view how much of the canvas the panel covers so it frames the scene in the visible part */
  function insets() {
    if (panel.hidden) return { right: 0, bottom: 0 };
    const r = panel.getBoundingClientRect();
    const stage = $('top').getBoundingClientRect();
    return MOBILE.matches
      ? { right: 0, bottom: Math.max(0, stage.bottom - r.top) }
      : { right: Math.max(0, stage.right - r.left), bottom: 0 };
  }
  function syncInsets() { valleCall('setInsets', insets()); }
  if ('ResizeObserver' in window) new ResizeObserver(() => { if (!panel.hidden) syncInsets(); }).observe(panel);

  return {
    open() {
      panel.hidden = false;
      setTab('predios');
      if (st.selectedId) showFicha(st.selectedId); else showRanking();
      syncInsets();
    },
    close() {
      panel.hidden = true;
      panel.classList.remove('expanded', 'playing');
      grip.setAttribute('aria-expanded', 'false');
      st.selectedId = null; st.view = 'ranking'; st.playing = false;
      st.rutaRendered = false; st.rutaCtl = null;
      paneRuta.innerHTML = '<p class="vp-loading">Cargando ruta…</p>';
    },
    // predicted insets for map padding before the panel is visible
    predictedPadding() {
      if (MOBILE.matches) return { top: 110, bottom: Math.round(innerHeight * 0.48), left: 24, right: 24 };
      return { top: 120, bottom: 60, left: 60, right: Math.min(460, Math.round(innerWidth * 0.45)) };
    },
    predictedInsets() {
      return MOBILE.matches ? { right: 0, bottom: Math.round(innerHeight * 0.46) } : { right: Math.min(424, innerWidth - 32), bottom: 0 };
    },
    syncInsets,
    // valle.js callbacks
    onValleSelect(arg) {
      const id = arg && typeof arg === 'object' ? arg.id : arg;
      if (!id) { if (st.selectedId) deselect({ from: 'valle' }); return; }
      if (id === st.selectedId && st.view !== 'ranking' && st.tab === 'predios') return;
      selectPredio(id, { from: 'valle' });
    },
    onRouteStop(orden, parada) {
      try { st.rutaCtl?.setActiveStop?.(orden, parada); } catch (e) { console.error(e); }
    },
    onRouteProgress(t) {
      try { st.rutaCtl?.setProgress?.(t); } catch (e) { console.error(e); }
    },
  };
}

/* ---------- stage: landing (national map) <-> lagoon (Aculeo) <-> valle (Petorca) ---------- */
function setupStage({ sites, others, heroP }) {
  const stage = $('top'), heroCanvas = $('hero-canvas'), valleCanvas = $('valle-canvas');
  const back = $('back'), bar = $('lagoon-bar'), hint = $('hint');
  const card = $('site-card');
  const byId = new Map(sites.map(s => [s.id, s]));
  const valleSite = sites.find(isValleSite) || null;
  const VALLE_SITE_ID = valleSite ? valleSite.id : VALLE_ID;
  let mapCtl = null;
  let hero = null, heroFailed = false;
  let valle = null, valleFailed = false, valleP = null;

  const vpanel = setupVallePanel({ getValle: () => valle });

  heroP.then(h => { hero = h; heroFailed = !h; updateHint(); });

  // valle 3D: init once (lazily, right after boot) so textures load while the map is on screen
  function getValleP() {
    return (valleP ??= initValle({
      canvas: valleCanvas,
      base: VALLE_ASSETS,
      dataBase: PETORCA_DATA,
      onSelectPredio: arg => vpanel.onValleSelect(arg),
      onRouteStop: (orden, parada) => vpanel.onRouteStop(orden, parada),
      onRouteProgress: t => vpanel.onRouteProgress(t),
    }).then(v => {
      if (!v || typeof v.enter !== 'function' || typeof v.exit !== 'function') throw new Error('valle sin enter()/exit()');
      valle = v;
      return v;
    }).catch(err => {
      console.error('[Caudal] valle:', err);
      valleFailed = true;
      valleCanvas.style.display = 'none';
      updateHint();
      return null;
    }));
  }

  function updateHint() {
    const parts = [];
    if (!valleFailed) parts.push('Toca <b>Valle de Petorca</b> para ver la priorización');
    if (!heroFailed) parts.push('Aculeo: vista 3D');
    hint.innerHTML = '<span class="rec" aria-hidden="true"></span>' + (parts.length ? parts.join(' · ') : 'Toca un punto para ver la señal');
  }

  let mode = 'landing';
  const busy = () => mode.startsWith('to-');
  function setMode(m) {
    mode = m;
    stage.dataset.mode = m;
    back.hidden = m !== 'lagoon' && m !== 'valle';
    bar.hidden = m !== 'lagoon';
  }

  /* floating card for a generic site on the map */
  function showCard(s) {
    const crit = s.loss >= 85;
    const bd = $('c-badge');
    const isValle = isValleSite(s);
    bd.textContent = isValle ? 'Valle priorizado' : (crit ? 'Crítico' : 'En observación');
    bd.className = 'badge ' + (isValle ? 'water' : (crit ? 'crit' : 'warn'));
    $('c-name').textContent = s.name;
    $('c-meta').textContent = `${s.type} · ${s.region}`;
    const loss = $('c-loss');
    loss.textContent = Number.isFinite(+s.loss) ? `${MINUS}${s.loss}%` : '';
    loss.className = 'c-loss' + (crit ? ' crit' : '');
    $('c-since').textContent = s.since ? `desde ${s.since}` : '';
    const isLagoon = s.id === LAGOON_ID;
    const enter = $('c-enter');
    enter.hidden = !(isLagoon && !heroFailed);
    enter.textContent = 'Ver laguna en 3D';
    $('c-note').textContent = isLagoon
      ? (heroFailed ? 'Vista satelital 3D no disponible en este momento.' : 'Contexto: lo que ya pasó. ' + (s.note ? s.note + '.' : ''))
      : isValle
        ? 'Vista 3D del valle no disponible en este momento. Revisa el resumen más abajo.'
        : 'Señal en observación · cifras ilustrativas en este prototipo.';
    card.hidden = false;
    hint.hidden = true;
  }
  function hideCard() { card.hidden = true; hint.hidden = false; }

  /* ---- lagoon (Aculeo, context hook) ---- */
  async function enterLagoon() {
    if (mode !== 'landing' || heroFailed) return;
    setMode('to-lagoon');
    hideCard();
    others.mark(LAGOON_ID);
    try {
      if (mapCtl) { mapCtl.select(LAGOON_ID); mapCtl.setLagoon(true); }
      const fly = mapCtl ? mapCtl.flyToSite(LAGOON_ID, { ...LAGOON_CAM, duration: RM ? 0 : LAGOON_CAM.duration }) : Promise.resolve();
      const [, h] = await Promise.all([fly, heroP]);
      if (!h) throw new Error('hero no disponible');
      try {
        const latest = h.years[h.years.length - 1];
        h.setYear(latest);
        $('scrub').value = latest;
      } catch (_) { /* opcional */ }
      heroCanvas.classList.add('on');
      await h.enter({ duration: ENTER_MS });
      setMode('lagoon');
      back.focus({ preventScroll: true });
    } catch (err) {
      console.error('[Caudal] lagoon enter:', err);
      heroCanvas.classList.remove('on');
      if (mapCtl) mapCtl.setLagoon(false);
      setMode('landing');
      const s = byId.get(LAGOON_ID); if (s) showCard(s);
    }
  }

  async function exitLagoon({ home = true } = {}) {
    if (mode !== 'lagoon') return;
    setMode('to-landing');
    try {
      const ex = Promise.resolve().then(() => hero.exit({ duration: EXIT_MS })).catch(e => console.error('[Caudal] hero.exit:', e));
      await sleep(RM ? 0 : EXIT_MS * 0.55);
      heroCanvas.classList.remove('on');
      let fly = Promise.resolve();
      if (mapCtl) {
        mapCtl.setLagoon(false);
        if (home) fly = mapCtl.flyHome({ duration: RM ? 0 : 2400 });
      }
      await Promise.all([ex, fly]);
    } catch (err) {
      console.error('[Caudal] lagoon exit:', err);
      heroCanvas.classList.remove('on');
      if (mapCtl) mapCtl.setLagoon(false);
    }
    setMode('landing');
    if (home) hint.focus({ preventScroll: true });
  }

  /* ---- valle (Petorca, main flow) ---- */
  const mapSetValley = on => {
    if (!mapCtl) return;
    try {
      if (typeof mapCtl.setValley === 'function') mapCtl.setValley(on);
      else if (typeof mapCtl.setLagoon === 'function') mapCtl.setLagoon(on);
    } catch (e) { console.error('[Caudal] map.setValley:', e); }
  };

  function flyToValle(v) {
    if (!mapCtl) return Promise.resolve();
    const bbox = Array.isArray(v?.bbox) && v.bbox.length === 4 ? v.bbox : VALLE_BBOX_FALLBACK;
    const duration = RM ? 0 : 2400;
    if (typeof mapCtl.flyToBounds === 'function') {
      return Promise.resolve(mapCtl.flyToBounds(bbox, { pitch: 50, bearing: 0, duration, padding: vpanel.predictedPadding() }));
    }
    const center = [(bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2];
    return Promise.resolve(mapCtl.flyToSite(VALLE_SITE_ID, { center, zoom: 11.6, pitch: 50, bearing: 0, duration }));
  }

  async function enterValle() {
    if (mode !== 'landing') return;
    if (valleFailed) { if (valleSite) showCard(valleSite); return; }
    setMode('to-valle');
    hideCard();
    try {
      if (mapCtl) mapCtl.select(VALLE_SITE_ID);
      mapSetValley(true);
      const v = await getValleP();
      if (!v) throw new Error('valle no disponible');
      try { v.setInsets?.(vpanel.predictedInsets()); } catch (_) { /* opcional */ }
      await flyToValle(v);
      valleCanvas.classList.add('on');
      await v.enter({ duration: RM ? 0 : ENTER_MS });
      setMode('valle');
      vpanel.open();
      back.focus({ preventScroll: true });
    } catch (err) {
      console.error('[Caudal] valle enter:', err);
      valleCanvas.classList.remove('on');
      mapSetValley(false);
      vpanel.close();
      setMode('landing');
      if (valleSite) showCard(valleSite);
    }
  }

  async function exitValle({ home = true } = {}) {
    if (mode !== 'valle') return;
    setMode('to-landing');
    vpanel.close();
    try {
      const ex = Promise.resolve().then(() => valle.exit({ duration: RM ? 0 : EXIT_MS })).catch(e => console.error('[Caudal] valle.exit:', e));
      await sleep(RM ? 0 : EXIT_MS * 0.55);
      valleCanvas.classList.remove('on');
      mapSetValley(false);
      let fly = Promise.resolve();
      if (mapCtl) {
        mapCtl.select(null);
        if (home) fly = mapCtl.flyHome({ duration: RM ? 0 : 2400 });
      }
      await Promise.all([ex, fly]);
    } catch (err) {
      console.error('[Caudal] valle exit:', err);
      valleCanvas.classList.remove('on');
      mapSetValley(false);
    }
    if (location.hash === '#' + VALLE_ID) history.replaceState(null, '', location.pathname + location.search);
    setMode('landing');
    if (home) hint.focus({ preventScroll: true });
  }

  async function exitAny(opts) {
    if (mode === 'lagoon') await exitLagoon(opts);
    else if (mode === 'valle') await exitValle(opts);
  }

  async function selectSite(id, { scroll = false } = {}) {
    const s = byId.get(id);
    if (busy()) return;
    if (scroll) window.scrollTo({ top: 0, behavior: RM ? 'auto' : 'smooth' });
    if ((s && isValleSite(s)) || id === VALLE_ID) {
      if (mode === 'valle') return;
      await exitAny({ home: false });
      if (mode === 'landing') await enterValle();
      return;
    }
    if (!s) return;
    others.mark(id);
    if (id === LAGOON_ID && !heroFailed) {
      if (mode === 'lagoon') return;
      await exitAny({ home: false });
      if (mode === 'landing') await enterLagoon();
      return;
    }
    await exitAny({ home: false });
    if (mode !== 'landing') return;
    if (mapCtl) mapCtl.select(id);
    showCard(s);
    if (mapCtl) await mapCtl.flyToSite(id, { zoom: SITE_ZOOM, duration: RM ? 0 : 2200 });
  }

  async function closeCard() {
    hideCard();
    if (mapCtl && mode === 'landing') {
      mapCtl.select(null);
      await mapCtl.flyHome({ duration: RM ? 0 : 2000 });
    }
  }

  function goBack() {
    if (mode === 'lagoon') exitLagoon();
    else if (mode === 'valle') exitValle();
  }

  hint.addEventListener('click', () => {
    if (!valleFailed) selectSite(VALLE_SITE_ID);
    else if (!heroFailed) enterLagoon();
  });
  back.addEventListener('click', goBack);
  $('c-enter').addEventListener('click', () => enterLagoon());
  $('card-close').addEventListener('click', closeCard);
  document.addEventListener('keydown', e => {
    if (e.key !== 'Escape' || e.defaultPrevented) return;
    const t = e.target;
    // never throw away what the person is typing in the expediente
    if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || t.isContentEditable)) return;
    if (mode === 'lagoon' || mode === 'valle') goBack();
    else if (mode === 'landing' && !card.hidden) closeCard();
  });

  // Pause the 3D render loops while the stage is scrolled out of view.
  if ('IntersectionObserver' in window) {
    new IntersectionObserver(es => {
      const vis = es.some(e => e.isIntersecting);
      const ctl = mode === 'lagoon' ? hero : mode === 'valle' ? valle : null;
      if (ctl && typeof ctl.setActive === 'function') {
        try { ctl.setActive(vis); } catch (e) { console.error(e); }
      }
    }, { threshold: 0.02 }).observe(stage);
  }
  MOBILE.addEventListener?.('change', () => { if (mode === 'valle') vpanel.syncInsets(); });

  return {
    selectSite,
    warmValle: () => getValleP(),
    setMap(ctl) { mapCtl = ctl; },
    get mode() { return mode; },
  };
}

async function setupMap(sites, onSelect) {
  const container = $('map');
  try {
    const ctl = await initMap({ container, sites, onSelect });
    if (!ctl || typeof ctl.select !== 'function' || typeof ctl.flyToSite !== 'function') throw new Error('controlador inválido');
    return ctl;
  } catch (err) {
    console.error('[Caudal] map:', err);
    container.querySelectorAll('canvas').forEach(c => { c.style.display = 'none'; });
    showFallback(container, 'Mapa 3D no disponible en este momento. Usa el resumen de valles más abajo para explorar.');
    document.querySelectorAll('.map-legend').forEach(el => { el.hidden = true; });
    return null;
  }
}

/* ---------- boot ---------- */
async function boot() {
  setupReveal();

  // "Cómo funciona" chart: real Petorca NDVI (chart.js).
  import('./chart.js')
    .then(m => m.renderChart($('chart'), $('callout')))
    .catch(err => console.error('[Caudal] chart:', err));

  setupVallesSummary();
  lazyOnView($('th-a'), drawThumbs);

  // Start the hero right away so its textures preload while the map is on screen.
  const heroP = setupHero().catch(err => { console.error('[Caudal] hero setup:', err); return null; });

  let sites = [];
  try {
    const r = await fetch('data/sites.json');
    if (!r.ok) throw new Error('sites ' + r.status);
    const j = await r.json();
    sites = Array.isArray(j) ? j : (j.sites || []);
  } catch (err) {
    console.error('[Caudal] sites:', err);
    showFallback($('map'), 'No se pudieron cargar los sitios. Sirve la carpeta con un servidor local (python3 -m http.server).');
  }
  $('hud-count').textContent = sites.length || '—';

  let stage = null;
  const others = setupOthers(sites, id => stage && stage.selectSite(id, { scroll: true }));
  stage = setupStage({ sites, others, heroP });

  // Section links (#petorca / #aculeo) enter the 3D views; keep them from jumping the scroll.
  for (const a of [$('vs-open'), $('ac-open')]) {
    a?.addEventListener('click', e => {
      e.preventDefault();
      const id = a.getAttribute('href').slice(1);
      if (location.hash !== '#' + id) history.pushState(null, '', '#' + id);
      stage.selectSite(id, { scroll: true });
    });
  }

  if (sites.length) {
    const mapCtl = await setupMap(sites, site => {
      if (!site || !site.id) return;
      stage.selectSite(site.id);
    });
    if (mapCtl) stage.setMap(mapCtl);
  }
  // Load the valley scene in the background once the map is up.
  stage.warmValle();

  // Deep links for demos: #petorca opens the valley, #aculeo the 3D lagoon.
  const fromHash = () => {
    const h = location.hash.slice(1);
    if (h === VALLE_ID) stage.selectSite(VALLE_ID, { scroll: true });
    else if (h === LAGOON_ID && sites.length) { heroP.then(() => stage.selectSite(LAGOON_ID, { scroll: true })); }
  };
  fromHash();
  addEventListener('hashchange', fromHash);
}

boot();
