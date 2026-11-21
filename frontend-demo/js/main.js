// Caudal · landing orchestration.
// Modes on #stage: landing | to-lagoon | lagoon | to-zona | zona | to-landing.
// Zones (spec v2): Z1 Petorca, Z2 Aconcagua bajo, with the 10 validation cases (resolved DGA cases).
// Every module is imported dynamically so a failure in one (or in its CDN deps) cannot take down the page.
const initHero = async opts => (await import('./hero.js')).initHero(opts);
const initMap = async opts => (await import('./map.js')).initMap(opts);
const initValle = async opts => (await import('./valle.js')).initValle(opts);
const Zmod = () => import('./zona-data.js');
// panel modules (ficha / expediente / ruta / caso): cached, but retried if a load fails.
// caso.js is optional: if it fails the case panel falls back to a minimal summary.
let panelsCache = null;
const panels = () => (panelsCache ??= Promise.all([
  import('./ficha.js'), import('./expediente.js'), import('./ruta-panel.js'),
  import('./caso.js').catch(err => { console.error('[Caudal] caso.js:', err); return {}; }),
  Zmod(),
]).then(([ficha, expediente, ruta, caso, Z]) => ({ ...ficha, ...expediente, ...ruta, ...caso, Z }))
  .catch(err => { panelsCache = null; throw err; }));

const $ = id => document.getElementById(id);
const RM = matchMedia('(prefers-reduced-motion: reduce)').matches;
const MOBILE = matchMedia('(max-width: 760px)');
const MANIFEST_URL = 'assets/aculeo/manifest.json';
const ASSET_DIR = 'assets/aculeo/';
const LAGOON_ID = 'aculeo';
const ZONA_IDS = ['z1', 'z2'];
const HASH_ALIAS = { petorca: 'z1', aconcagua: 'z2' };
const LAGOON_CAM = { center: [-70.914, -33.843], zoom: 11.3, pitch: 50, bearing: 0, duration: 2600 };
const ENTER_MS = 2200, EXIT_MS = 1400;
const ROUTE_MS = 16000;
const BACK_LABEL = { chile: 'Volver a Chile', zona: 'Ver toda la zona' };
const MAX_VALLES = 3;             // 3D zone scenes kept built at once (one WebGL context each)
const SW_URL = 'sw.js';
const HERO_TIMEOUT_MS = 20000;   // max wait for the lagoon scene before giving the stage back
const nf1 = new Intl.NumberFormat('es-CL', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const nf0 = new Intl.NumberFormat('es-CL', { maximumFractionDigits: 0 });
const MINUS = '−';
const sleep = ms => new Promise(r => setTimeout(r, ms));
const SVGNS = 'http://www.w3.org/2000/svg';
const BIG_LOSS = 0.5;   // a year is flagged amber when it holds < 50% of the baseline water
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const comunaFmt = s => String(s || '').toLowerCase().replace(/(^|\s)\p{L}/gu, c => c.toUpperCase());
const dateNum = iso => { if (!iso) return '—'; const [y, m, d] = String(iso).slice(0, 10).split('-'); return d ? `${d}-${m}-${y}` : `${m}-${y}`; };
const expShortL = e => String(e || '').replace(/^(\w+)-\d+-(\d+)$/, '$1-$2');
const zkey = id => { const k = String(id || '').toLowerCase(); return HASH_ALIAS[k] || k; };

/* ---------- static fallbacks while the team data lands (sites.json carries Z1/Z2 + the 10 cases) ---------- */
let sitesJson = { sites: [], casos: [] };

/** Zone index: data/zonas/index.json, else built from sites.json + data/zonas/bbox.json. */
let indexP = null;
function getIndex() {
  return (indexP ??= Zmod().then(Z => Z.loadZonas()).catch(async err => {
    console.warn('[Caudal] index.json no disponible, uso sites.json:', err?.message || err);
    let bbox = {};
    try { const r = await fetch('data/zonas/bbox.json'); if (r.ok) bbox = await r.json(); } catch (_) { /* opcional */ }
    const zonas = (sitesJson.sites || []).filter(s => s.kind === 'zona').map(s => ({
      id: s.zona || s.id, codigo: s.codigo || String(s.id).toUpperCase(), nombre: s.name, comunas: s.comunas || [],
      bbox_escena: bbox[s.zona || s.id] || null, centro: [s.lon, s.lat],
      base: `assets/zonas/${s.zona || s.id}/`, data: `data/zonas/${s.zona || s.id}/`,
      casos: (sitesJson.casos || []).filter(c => c.zona === (s.zona || s.id)).map(c => c.expediente),
    }));
    return { zonas, _fallback: true };
  }));
}
const zonaMeta = async id => (await getIndex()).zonas.find(z => zkey(z.id) === zkey(id) || zkey(z.codigo) === zkey(id)) || null;

/** All 10 cases: data/zonas/casos.json, else the sites.json backup. */
let casosP = null;
function getCasos() {
  return (casosP ??= Zmod().then(Z => Z.loadCasos()).catch(err => {
    console.warn('[Caudal] casos.json no disponible, uso sites.json:', err?.message || err);
    return (sitesJson.casos || []).map(c => ({ ...c }));
  }));
}
const loadZonaData = async id => (await Zmod()).loadZona(zkey(id));

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

/* ---------- hero (3D lagoon): created on first use (boot -> getHero), not at startup ---------- */
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

/* ---------- section 02: Zonas summary (Z1/Z2 cards + the 10-case list) ---------- */
async function setupZonasSummary() {
  const cards = $('zonas-cards'), list = $('casos-list');
  let index = null, casos = [];
  try { [index, casos] = await Promise.all([getIndex(), getCasos()]); }
  catch (err) { console.error('[Caudal] zonas summary:', err); }

  // 10-case list (links enter the zone and open the case)
  if (list) {
    const rows = (casos || []).slice().sort((a, b) => (a.zona || '').localeCompare(b.zona || '') || String(b.fecha_inspeccion).localeCompare(String(a.fecha_inspeccion)));
    list.innerHTML = rows.length ? rows.map(c => `<li><a href="#caso-${esc(c.expediente)}" data-caso="${esc(c.expediente)}">
        <span class="cl-z">${esc(String(c.zona || '').toUpperCase())}</span>
        <span class="cl-exp">${esc(c.expediente)}${c.papel === 'demo_principal' ? '<i>demo</i>' : ''}</span>
        <span class="cl-c">${esc(comunaFmt(c.comuna))} · inspección ${esc(dateNum(c.fecha_inspeccion))} · ${esc(c.decision || '—')}</span>
        <span class="cl-m">${Number.isFinite(+c.multa_utm) ? nf1.format(+c.multa_utm) : '—'} UTM</span>
      </a></li>`).join('') : '<li class="note">No se pudieron cargar los casos.</li>';
    const n = $('casos-n'); if (n) n.textContent = rows.length || '—';
  }

  if (!cards) return;
  const zonas = index?.zonas || [];
  if (!zonas.length) { cards.innerHTML = '<p class="note">No se pudieron cargar las zonas.</p>'; return; }
  cards.innerHTML = zonas.map(z => {
    const id = zkey(z.id);
    const nCasos = (casos || []).filter(c => zkey(c.zona) === id).length || (z.casos || []).length;
    return `<article class="panel zc" id="zc-${esc(id)}" aria-labelledby="zc-${esc(id)}-t">
      <span class="badge water">Zona ${esc(z.codigo || id.toUpperCase())}</span>
      <h3 id="zc-${esc(id)}-t">${esc(z.nombre || id)}</h3>
      <p class="p-loc">${esc((z.comunas || []).map(comunaFmt).join(' · '))}</p>
      <p class="zc-meta"><span data-k="predios">— predios</span> · <b>${nCasos} casos DGA</b></p>
      <dl class="stats stats-4" aria-label="Predios por banda (provisional)">
        <div><dt>Alta</dt><dd class="b-alta" data-k="alta">—</dd></div>
        <div><dt>Media</dt><dd class="b-media" data-k="media">—</dd></div>
        <div><dt>Baja</dt><dd class="b-baja" data-k="baja">—</dd></div>
        <div><dt>Sin indicio</dt><dd data-k="sin">—</dd></div>
      </dl>
      <p class="vs-route" data-k="ruta">Ruta de inspección: —</p>
      <div class="row"><a class="btn primary" href="#${esc(id)}" data-zona="${esc(id)}">Ver zona en 3D ↑</a></div>
    </article>`;
  }).join('');

  // fill counts per zone from the small summary file; without it, from the full zone data
  // (a zone that fails keeps its dashes)
  const resumen = await Zmod().then(Z => Z.loadResumen()).catch(() => null);
  const fromZona = d => ({
    predios: d.predios.length, counts: d.counts || {},
    ruta: d.ruta && Array.isArray(d.ruta.paradas) && d.ruta.paradas.length
      ? { paradas: d.ruta.paradas.length, distancia_km: d.ruta.distancia_km, duracion_min: d.ruta.duracion_min, inicio: d.ruta.inicio }
      : null,
  });
  for (const z of zonas) {
    const id = zkey(z.id), card = $('zc-' + id);
    const known = resumen?.zonas?.[id];
    (known ? Promise.resolve(known) : loadZonaData(id).then(fromZona)).then(d => {
      const c = d.counts || {}, set = (k, v) => { const e = card.querySelector(`[data-k="${k}"]`); if (e) e.textContent = v; };
      set('predios', `${d.predios} predios`);
      set('alta', c.alta ?? 0); set('media', c.media ?? 0); set('baja', c.baja ?? 0);
      set('sin', (c.sin_alerta || 0) + (c.sin_dato || 0));
      const r = d.ruta;
      if (r && r.paradas) {
        const h = Math.floor(r.duracion_min / 60), m = Math.round(r.duracion_min % 60);
        set('ruta', `Ruta: ${r.paradas} paradas · ${nf1.format(r.distancia_km)} km · ${h} h ${String(m).padStart(2, '0')} min · desde ${r.inicio?.nombre || 'la plaza'}`);
      } else set('ruta', 'Ruta de inspección: en preparación');
    }).catch(err => console.error(`[Caudal] zona ${id} summary:`, err));
  }
}

/* ---------- zone side panel: Predios (ranking -> ficha -> expediente) | Casos (lista -> caso) | Ruta ---------- */
function setupZonaPanel({ getValle, onFocusChange }) {
  const panel = $('valle-panel');
  const panes = { predios: $('vp-predios'), casos: $('vp-casos'), ruta: $('vp-ruta') };
  const tabs = { predios: $('vt-predios'), casos: $('vt-casos'), ruta: $('vt-ruta') };
  const TAB_ORDER = ['predios', 'casos', 'ruta'];
  const body = $('vp-body'), grip = $('vp-grip');
  const st = { zona: null, tab: 'predios', view: 'ranking', caseView: 'list', selectedId: null, selectedCaso: null, playing: false, rutaCtl: null, rutaRendered: false };
  let dataP = null;
  const data = () => (dataP ??= loadZonaData(st.zona).catch(err => { dataP = null; throw err; }));

  const fail = (el, err, what) => {
    console.error(`[Caudal] panel ${what}:`, err);
    el.innerHTML = `<p class="vp-error">No se pudo cargar ${esc(what)}. Revisa la consola.</p>`;
  };
  const valleCall = (fn, ...args) => {
    const v = getValle();
    if (v && typeof v[fn] === 'function') { try { return v[fn](...args); } catch (e) { console.error(`[Caudal] valle.${fn}:`, e); } }
    return undefined;
  };
  // the stage's back button depends on whether the 3D view is zoomed on something
  const focusChanged = () => { try { onFocusChange?.(); } catch (e) { console.error(e); }
  };

  /* --- Predios --- */
  // The pane holds two parts: the ranking, kept alive while the zone is open (rebuilding thousands of
  // rows on every "← Ranking" froze the panel), and the detail (ficha / expediente) shown in its place.
  const parts = { rank: null, detail: null, rankFor: null, rankScroll: 0 };
  function prediosParts() {
    if (!parts.rank || !panes.predios.contains(parts.rank)) {
      parts.rank = document.createElement('div');
      parts.detail = document.createElement('div');
      parts.detail.hidden = true;
      parts.rankFor = null; parts.rankScroll = 0;
      panes.predios.replaceChildren(parts.rank, parts.detail);
    }
    return parts;
  }
  /** Detail container (ranking hidden, its scroll position remembered). */
  function detailPart() {
    const p = prediosParts();
    if (!p.rank.hidden) { p.rankScroll = body.scrollTop; p.rank.hidden = true; }
    p.detail.hidden = false;
    return p.detail;
  }

  async function showRanking() {
    st.view = 'ranking';
    try {
      const [d, P] = await Promise.all([data(), panels()]);
      if (st.view !== 'ranking') return;
      const p = prediosParts();
      const wasHidden = p.rank.hidden;
      p.detail.hidden = true; p.detail.replaceChildren(); p.detail.onclick = null;
      p.rank.hidden = false;
      if (p.rankFor !== d || typeof P.selectRankingRow !== 'function') {
        P.renderRanking(p.rank, d, { selectedId: st.selectedId, onSelect: id => selectPredio(id, { from: 'panel' }) });
        p.rankFor = d;
      } else {
        if (wasHidden && st.tab === 'predios') body.scrollTop = p.rankScroll;
        P.selectRankingRow(p.rank, st.selectedId, { scroll: !wasHidden });
      }
    } catch (err) { fail(panes.predios, err, 'el ranking de predios'); }
  }

  async function showFicha(id) {
    st.view = 'ficha';
    try {
      const [d, P] = await Promise.all([data(), panels()]);
      if (st.view !== 'ficha' || st.selectedId !== id) return;
      const f = d.byId.get(id);
      if (!f) { showRanking(); return; }
      await P.Z.ensureSeries(d, id);
      if (st.view !== 'ficha' || st.selectedId !== id) return;
      P.renderFicha(detailPart(), f, d, {
        onExpediente: pid => showExpediente(pid || id),
        onBack: () => deselect(),
        onCaso: exp => showCaso(exp),
      });
      body.scrollTop = 0;
    } catch (err) { fail(panes.predios, err, 'la ficha del predio'); }
  }

  async function showExpediente(id) {
    st.view = 'expediente';
    if (st.tab !== 'predios') setTab('predios', { render: false });
    try {
      const [d, P] = await Promise.all([data(), panels()]);
      if (st.view !== 'expediente') return;
      const f = d.byId.get(id);
      if (!f) { showRanking(); return; }
      await P.Z.ensureSeries(d, id);
      if (st.view !== 'expediente') return;
      st.selectedId = id;
      P.renderExpediente(detailPart(), f, d, { onBack: () => showFicha(id) });
      body.scrollTop = 0;
    } catch (err) { fail(panes.predios, err, 'el expediente'); }
  }

  function selectPredio(id, { from = 'panel' } = {}) {
    if (!id) { deselect({ from }); return; }
    st.selectedId = id;
    // any way of choosing a predio (ranking row, its polygon or its dot on the terrain) flies to it
    valleCall('selectPredio', id, { focus: true });
    focusChanged();
    if (st.tab !== 'predios') setTab('predios', { render: false });
    showFicha(id);
  }

  function deselect({ from = 'panel' } = {}) {
    st.selectedId = null;
    if (from !== 'valle') valleCall('selectPredio', null);
    if (getValle()?.isFocused?.()) valleCall('resetView');
    focusChanged();
    showRanking();
  }

  /** One step back inside the zone: from a predio or a case to the list it came from, zooming out. */
  function stepBack() {
    if (st.tab === 'casos' && st.caseView === 'caso') {
      st.selectedCaso = null;
      if (getValle()?.isFocused?.()) valleCall('resetView');
      focusChanged();
      showCasos();
      return;
    }
    deselect({ from: 'panel' });
  }

  /* --- Casos --- */
  async function showCasos() {
    st.caseView = 'list';
    try {
      const [d, P] = await Promise.all([data(), panels()]);
      if (st.caseView !== 'list') return;
      const onSelect = exp => showCaso(exp);
      if (typeof P.renderCasosList === 'function') P.renderCasosList(panes.casos, d, { onSelect, selected: st.selectedCaso });
      else casosListFallback(panes.casos, d, onSelect);
    } catch (err) { fail(panes.casos, err, 'los casos de la zona'); }
  }

  async function showCaso(exp, { from = 'panel' } = {}) {
    if (!exp) return;
    st.caseView = 'caso';
    st.selectedCaso = exp;
    if (st.tab !== 'casos') setTab('casos', { render: false });
    try {
      const [d, P] = await Promise.all([data(), panels()]);
      if (st.caseView !== 'caso' || st.selectedCaso !== exp) return;
      const caso = d.casos.find(c => c.expediente === exp);
      if (!caso) { showCasos(); return; }
      if (caso.predio_id) {
        await P.Z.ensureSeries(d, caso.predio_id);
        if (st.caseView !== 'caso' || st.selectedCaso !== exp) return;
      }
      if (from !== 'valle') {
        if (getValle()?.selectCaso) valleCall('selectCaso', exp, { focus: true });
        else if (caso.predio_id) valleCall('selectPredio', caso.predio_id, { focus: true });
      }
      if (caso.predio_id) st.selectedId = caso.predio_id;
      focusChanged();
      const opts = {
        onPredio: id => selectPredio(id, { from: 'panel' }),
        onExpediente: id => showExpediente(id || caso.predio_id),
        onBack: stepBack,
      };
      if (typeof P.renderCaso === 'function') P.renderCaso(panes.casos, caso, d, opts);
      else casoFallback(panes.casos, caso, opts);
      body.scrollTop = 0;
    } catch (err) { fail(panes.casos, err, 'el caso'); }
  }

  function casosListFallback(el, d, onSelect) {
    el.innerHTML = `<ul class="pn-list">${d.casos.map(c => `<li><button type="button" class="pn-row" data-exp="${esc(c.expediente)}"><span class="pn-row-top"><b class="pn-id">${esc(expShortL(c.expediente))}</b><span>${esc(comunaFmt(c.comuna))} · ${esc(dateNum(c.fecha_inspeccion))}</span><span class="pn-row-meta">${Number.isFinite(+c.multa_utm) ? nf0.format(+c.multa_utm) : '—'} UTM</span></span></button></li>`).join('')}</ul>`;
    el.onclick = e => { const b = e.target.closest('.pn-row'); if (b) onSelect(b.dataset.exp); };
  }
  function casoFallback(el, c, { onPredio, onBack }) {
    el.innerHTML = `<button type="button" class="pn-back" data-act="back">← Casos</button>
      <header class="pn-fh"><h3 class="pn-title">Caso ${esc(c.expediente)}</h3>
      <p class="pn-sub">${esc(comunaFmt(c.comuna))} · Caso sancionado por la DGA</p></header>
      <dl class="pn-kpis"><div><dt>Inspección</dt><dd>${esc(dateNum(c.fecha_inspeccion))}</dd></div><div><dt>Multa</dt><dd>${Number.isFinite(+c.multa_utm) ? nf1.format(+c.multa_utm) : '—'} <small>UTM</small></dd></div></dl>
      <p class="pn-note">${esc(c.decision || '')}</p>
      ${c.predio_id ? '<div class="pn-actions"><button type="button" class="btn" data-act="predio">Ver predio</button></div>' : ''}`;
    el.onclick = e => {
      const a = e.target.closest('[data-act]')?.dataset.act;
      if (a === 'back') onBack(); else if (a === 'predio') onPredio(c.predio_id);
    };
  }

  /* --- Ruta --- */
  async function showRuta() {
    if (st.rutaRendered) return;
    try {
      const [d, P] = await Promise.all([data(), panels()]);
      if (st.rutaRendered) return;
      st.rutaCtl = P.renderRuta(panes.ruta, d, {
        onPlay: () => playRoute(),
        onStop: pid => { if (pid) { st.selectedId = String(pid); valleCall('selectPredio', String(pid)); } },
        onGPX: () => {},
      }) || null;
      st.rutaRendered = true;
    } catch (err) { fail(panes.ruta, err, 'la ruta de inspección'); }
  }

  // only on an explicit click of the "Recorrer" button: nothing plays by itself in 3D
  async function playRoute() {
    if (st.playing) return;
    const v = getValle();
    if (!v || typeof v.playRoute !== 'function') return;
    st.playing = true;
    panel.classList.add('playing');
    valleCall('showRoute', true);
    // the route is a whole-zone story: leave a predio close-up before playing it
    if (v.isFocused?.()) { try { await v.resetView(); } catch (_) { /* opcional */ } }
    try { await v.playRoute({ duration: ROUTE_MS }); }
    catch (err) { console.error('[Caudal] playRoute:', err); }
    st.playing = false;
    panel.classList.remove('playing');
  }

  /* --- tabs --- */
  function setTab(tab, { focus = false, render = true } = {}) {
    st.tab = tab;
    for (const [k, b] of Object.entries(tabs)) {
      const on = k === tab;
      b.setAttribute('aria-selected', String(on));
      b.tabIndex = on ? 0 : -1;
    }
    for (const [k, p] of Object.entries(panes)) p.hidden = k !== tab;
    body.scrollTop = 0;
    if (tab === 'ruta') showRuta();
    if (render && tab === 'casos') { if (st.selectedCaso) showCaso(st.selectedCaso); else showCasos(); }
    if (render && tab === 'predios' && st.view === 'ranking') showRanking();
    valleCall('showRoute', tab === 'ruta' || st.playing);
    if (focus) tabs[tab].focus();
  }

  for (const k of TAB_ORDER) tabs[k].addEventListener('click', () => setTab(k));
  for (const b of Object.values(tabs)) {
    b.addEventListener('keydown', e => {
      if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
      e.preventDefault();
      const i = TAB_ORDER.indexOf(st.tab), n = TAB_ORDER.length;
      setTab(TAB_ORDER[(i + (e.key === 'ArrowRight' ? 1 : n - 1)) % n], { focus: true });
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

  function reset() {
    st.selectedId = null; st.selectedCaso = null; st.view = 'ranking'; st.caseView = 'list'; st.playing = false;
    st.rutaRendered = false; st.rutaCtl = null;
    panes.predios.innerHTML = '<p class="vp-loading">Cargando predios…</p>';
    panes.casos.innerHTML = '<p class="vp-loading">Cargando casos…</p>';
    panes.ruta.innerHTML = '<p class="vp-loading">Cargando ruta…</p>';
  }

  return {
    get zona() { return st.zona; },
    /** Point the panel at a zone (before it opens): headings + counts. */
    prepare(meta, n = {}) {
      const id = zkey(meta?.id);
      if (st.zona !== id) { st.zona = id; dataP = null; reset(); }
      const name = `${meta?.codigo || id.toUpperCase()} · ${meta?.nombre || ''}`;
      $('vp-kicker').textContent = `${name} · priorización provisional`;
      $('vp-grip-l').textContent = `Priorización · ${meta?.nombre || id.toUpperCase()}`;
      panel.setAttribute('aria-label', `Priorización de la zona ${name}`);
      $('vt-predios-n').textContent = n.predios ? `· ${n.predios}` : '';
      $('vt-casos-n').textContent = `(${n.casos ?? (meta?.casos || []).length})`;
    },
    open({ caso = null } = {}) {
      panel.hidden = false;
      if (caso) { setTab('casos', { render: false }); showCaso(caso); }
      else { setTab('predios', { render: false }); if (st.selectedId) showFicha(st.selectedId); else showRanking(); }
      syncInsets();
    },
    close() {
      panel.hidden = true;
      panel.classList.remove('expanded', 'playing');
      grip.setAttribute('aria-expanded', 'false');
      reset();
    },
    showCaso,
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
      const sid = String(id);
      if (sid === st.selectedId && st.view !== 'ranking' && st.tab === 'predios') return;
      selectPredio(sid, { from: 'valle' });
    },
    onValleCaso(exp) { if (exp) showCaso(String(exp), { from: 'valle' }); },
    stepBack,
    onRouteStop(orden, parada) {
      try { st.rutaCtl?.setActiveStop?.(orden, parada); } catch (e) { console.error(e); }
    },
    onRouteProgress(t) {
      try { st.rutaCtl?.setProgress?.(t); } catch (e) { console.error(e); }
    },
  };
}

/* ---------- stage: landing (national map) <-> lagoon (Aculeo) <-> zona (Z1 / Z2) ---------- */
function setupStage({ getHero }) {
  const stage = $('top'), heroCanvas = $('hero-canvas'), firstValleCanvas = $('valle-canvas');
  const back = $('back'), bar = $('lagoon-bar'), hint = $('hint');
  const card = $('site-card');
  const sites = sitesJson.sites || [];
  const byId = new Map(sites.map(s => [s.id, s]));
  let mapCtl = null;
  let hero = null, heroFailed = false;
  // one built 3D scene per zone (up to MAX_VALLES), each on its own canvas: switching zone is free
  const valles = new Map();   // zone id -> { ctl, canvas }
  let valle = null, valleCanvas = firstValleCanvas, valleFailed = false;
  let valleQueue = Promise.resolve();
  let curZona = null;

  const zp = setupZonaPanel({ getValle: () => valle, onFocusChange: () => syncBack() });

  // Aculeo is a side view: its scene (7 satellite images, DEM, a WebGL context) loads on first use,
  // or a moment earlier when the pointer/focus reaches one of its entry points.
  const ensureHero = () => getHero().then(h => {
    hero = h; heroFailed = !h;
    // the card may already be up offering "Ver laguna en 3D": redraw it without the button
    if (!h && !card.hidden && mode === 'landing') { const s = byId.get(LAGOON_ID); if (s) showCard(s); }
    return h;
  });
  const preloadHero = () => { ensureHero().catch(() => {}); };
  $('map').addEventListener('pointerover', e => { if (e.target.closest?.(`[data-id="${LAGOON_ID}"]`)) preloadHero(); });
  for (const ev of ['pointerenter', 'focus']) $('ac-open')?.addEventListener(ev, preloadHero);

  function updateHint() {
    hint.innerHTML = '<span class="rec" aria-hidden="true"></span>' + (valleFailed
      ? 'Toca un caso para ver su señal · 10 casos sancionados por la DGA'
      : 'Toca una <b>zona</b> para ver la priorización · 10 casos sancionados por la DGA');
  }

  let mode = 'landing';
  const busy = () => mode.startsWith('to-');
  function setMode(m) {
    mode = m;
    stage.dataset.mode = m;
    back.hidden = m !== 'lagoon' && m !== 'zona';
    bar.hidden = m !== 'lagoon';
    syncBack();
  }
  // Inside a zone, while the 3D view is zoomed on a predio or a case, "back" first returns to the
  // whole zone; only from there it leaves to the national map.
  const zoomedIn = () => mode === 'zona' && !!valle?.isFocused?.();
  function syncBack() {
    const label = zoomedIn() ? BACK_LABEL.zona : BACK_LABEL.chile;
    if (back.dataset.label === label) return;
    back.dataset.label = label;
    back.innerHTML = `<span aria-hidden="true">←</span> ${label}`;
  }

  /* --- 3D zone scenes: one per zone while they fit (MAX_VALLES); past that, the oldest is rebuilt --- */
  function newValleCanvas() {
    if (!valles.size) return firstValleCanvas;
    const c = firstValleCanvas.cloneNode(false);
    c.removeAttribute('id');
    c.removeAttribute('style');
    c.className = 'valle-canvas';
    firstValleCanvas.after(c);
    return c;
  }
  async function buildValle(id, data, meta) {
    const canvas = newValleCanvas();
    try {
      const v = await initValle({
        canvas,
        zona: data,
        base: meta?.base || `assets/zonas/${id}/`,
        dataBase: meta?.data || `data/zonas/${id}/`,   // older valle.js loads predios/ruta itself
        onSelectPredio: arg => zp.onValleSelect(arg),
        onSelectCaso: exp => zp.onValleCaso(exp),
        onRouteStop: (orden, parada) => zp.onRouteStop(orden, parada),
        onRouteProgress: t => zp.onRouteProgress(t),
      });
      if (!v || typeof v.enter !== 'function' || typeof v.exit !== 'function') throw new Error('valle sin enter()/exit()');
      return { ctl: v, canvas };
    } catch (err) {
      if (canvas !== firstValleCanvas) canvas.remove();
      throw err;
    }
  }
  /**
   * Scene of zone `id`. adopt: make it the current one (entering the zone). Without adopt it is only
   * built ahead of time, and never at the expense of a scene that is already built.
   */
  function ensureValle(id, data, meta, { adopt = true } = {}) {
    const run = async () => {
      if (!adopt && mode !== 'landing') return null;   // queued behind another build: the person moved on
      let slot = valles.get(id);
      if (!slot && valles.size >= MAX_VALLES) {
        if (!adopt) return null;
        const [oldId, old] = valles.entries().next().value;
        if (typeof old.ctl.setZona !== 'function') throw new Error('valle sin setZona()');
        await old.ctl.setZona(data);
        valles.delete(oldId);
        slot = old;
        valles.set(id, slot);
      }
      if (!slot) {
        slot = await buildValle(id, data, meta);
        valles.set(id, slot);
      }
      if (adopt) { valle = slot.ctl; valleCanvas = slot.canvas; }
      return slot.ctl;
    };
    const p = valleQueue.then(run, run);
    valleQueue = p.catch(() => {});
    return p;
  }

  /** Background warm-up: load the zone data + build its scene while the national map is on screen. */
  async function warm(id = 'z1') {
    try {
      const [data, meta] = await Promise.all([loadZonaData(id), zonaMeta(id)]);
      if (mode === 'landing' && !valleFailed) await ensureValle(zkey(id), data, meta, { adopt: false });
      return data;
    } catch (err) { console.warn('[Caudal] warm-up zona:', err?.message || err); return null; }
  }
  /** Background warm-up of the lagoon: scene + every year's imagery already on the GPU. */
  async function warmHero() {
    const h = await ensureHero().catch(() => null);
    if (h && typeof h.prewarm === 'function') await h.prewarm();
    return !!h;
  }

  /* --- floating card (Aculeo, or a zone whose 3D failed) --- */
  function showCard(s) {
    const bd = $('c-badge');
    const isZona = s.kind === 'zona';
    const isLagoon = s.id === LAGOON_ID;
    bd.textContent = isZona ? `Zona ${s.codigo || ''}` : 'Contexto · lo que ya pasó';
    bd.className = 'badge ' + (isZona ? 'water' : 'warn');
    $('c-name').textContent = s.name;
    $('c-meta').textContent = isZona ? (s.comunas || []).map(comunaFmt).join(' · ') : `${s.type} · ${s.region}`;
    const loss = $('c-loss');
    loss.textContent = isZona ? `${s.casos ?? '—'} casos DGA` : (Number.isFinite(+s.loss) ? `${MINUS}${s.loss}%` : '');
    loss.className = 'c-loss' + (isZona ? '' : ' crit');
    $('c-since').textContent = !isZona && s.since ? `desde ${s.since}` : '';
    const enter = $('c-enter');
    enter.hidden = !(isLagoon && !heroFailed);
    enter.textContent = 'Ver laguna en 3D';
    $('c-note').textContent = isLagoon
      ? (heroFailed ? 'Vista satelital 3D no disponible en este momento.' : 'Contexto: lo que ya pasó. ' + (s.note ? s.note + '.' : ''))
      : 'Vista 3D de la zona no disponible en este momento. Revisa el resumen de zonas más abajo.';
    card.hidden = false;
    hint.hidden = true;
    if (isLagoon && !heroFailed) preloadHero();
  }
  function hideCard() { card.hidden = true; hint.hidden = false; }

  /* ---- lagoon (Aculeo, context hook) ---- */
  async function enterLagoon() {
    if (mode !== 'landing' || heroFailed) return;
    setMode('to-lagoon');
    hideCard();
    try {
      if (mapCtl) { mapCtl.select(LAGOON_ID); mapCtl.setLagoon(true); }
      const fly = mapCtl ? mapCtl.flyToSite(LAGOON_ID, { ...LAGOON_CAM, duration: RM ? 0 : LAGOON_CAM.duration }) : Promise.resolve();
      // the scene now loads here (not at boot): never keep the stage locked in "to-lagoon" on a hung download
      const [, h] = await Promise.all([fly, Promise.race([ensureHero(), sleep(HERO_TIMEOUT_MS).then(() => null)])]);
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
        mapCtl.select(null);
        if (home) fly = mapCtl.flyHome({ duration: RM ? 0 : 2400 });
      }
      await Promise.all([ex, fly]);
    } catch (err) {
      console.error('[Caudal] lagoon exit:', err);
      heroCanvas.classList.remove('on');
      if (mapCtl) mapCtl.setLagoon(false);
    }
    clearHash(h => h === LAGOON_ID);
    setMode('landing');
    if (home) hint.focus({ preventScroll: true });
  }

  /* ---- zona (Z1 / Z2, main flow) ---- */
  const mapSetValley = on => {
    if (!mapCtl) return;
    try {
      if (typeof mapCtl.setValley === 'function') mapCtl.setValley(on);
      else if (typeof mapCtl.setLagoon === 'function') mapCtl.setLagoon(on);
    } catch (e) { console.error('[Caudal] map.setValley:', e); }
  };
  const validBbox = b => Array.isArray(b) && b.length === 4 && b.every(Number.isFinite);

  function flyToZona(meta, v) {
    if (!mapCtl) return Promise.resolve();
    const bbox = validBbox(meta?.bbox_escena) ? meta.bbox_escena : validBbox(v?.bbox) ? v.bbox : null;
    const duration = RM ? 0 : 2400;
    if (bbox && typeof mapCtl.flyToBounds === 'function') {
      return Promise.resolve(mapCtl.flyToBounds(bbox, { pitch: 50, bearing: 0, duration, padding: zp.predictedPadding() }));
    }
    const center = bbox ? [(bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2] : meta?.centro;
    return Promise.resolve(mapCtl.flyToSite(zkey(meta?.id), { center, zoom: 11.6, pitch: 50, bearing: 0, duration }));
  }

  function setZonaHud(meta, data) {
    const nP = data?.predios?.length, nC = data?.casos?.length ?? (meta?.casos || []).length;
    $('hz-name').textContent = `${meta?.codigo || ''} · ${meta?.nombre || ''}`;
    $('hz-count').textContent = `${nP ?? '—'} predios · ${nC} casos DGA`;
    const c = Array.isArray(meta?.centro) ? meta.centro : null;
    $('hz-coords').textContent = c ? `${dms(c[1], 'N', 'S')} ${dms(c[0], 'E', 'O')} · Valparaíso · 10 m/px` : 'Valparaíso · 10 m/px';
  }

  async function enterZona(id, { caso = null } = {}) {
    if (mode !== 'landing') return;
    id = zkey(id);
    const site = byId.get(id);
    if (valleFailed) { if (site) showCard(site); return; }
    setMode('to-zona');
    hideCard();
    try {
      if (mapCtl) mapCtl.select(caso ? 'caso-' + caso : id);
      const meta = await zonaMeta(id);
      if (!meta) throw new Error('zona desconocida: ' + id);
      const data = await loadZonaData(id);
      zp.prepare(meta, { predios: data.predios.length, casos: data.casos.length });
      setZonaHud(meta, data);
      mapSetValley(true);
      const flyP = flyToZona(meta, null);
      const v = await ensureValle(id, data, meta);
      try { v.setInsets?.(zp.predictedInsets()); } catch (_) { /* opcional */ }
      await flyP;
      valleCanvas.classList.add('on');
      await v.enter({ duration: RM ? 0 : ENTER_MS });
      curZona = id;
      setMode('zona');
      zp.open({ caso });
      const h = caso ? 'caso-' + caso : id;
      if (location.hash !== '#' + h) history.replaceState(null, '', '#' + h);
      back.focus({ preventScroll: true });
    } catch (err) {
      console.error('[Caudal] zona enter:', err);
      if (/valle|initValle|WebGL/i.test(String(err?.message))) { valleFailed = true; valleCanvas.style.display = 'none'; updateHint(); }
      valleCanvas.classList.remove('on');
      mapSetValley(false);
      zp.close();
      setMode('landing');
      if (site) showCard(site);
    }
  }

  async function exitZona({ home = true } = {}) {
    if (mode !== 'zona') return;
    setMode('to-landing');
    zp.close();
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
      console.error('[Caudal] zona exit:', err);
      valleCanvas.classList.remove('on');
      mapSetValley(false);
    }
    curZona = null;
    clearHash(h => ZONA_IDS.includes(zkey(h)) || h.startsWith('caso-'));
    setMode('landing');
    if (home) hint.focus({ preventScroll: true });
  }

  function clearHash(test) {
    const h = location.hash.slice(1);
    if (h && test(h)) history.replaceState(null, '', location.pathname + location.search);
  }

  async function exitAny(opts) {
    if (mode === 'lagoon') await exitLagoon(opts);
    else if (mode === 'zona') await exitZona(opts);
  }

  /* ---- public navigation ---- */
  async function goZona(id, { caso = null, scroll = false } = {}) {
    if (busy()) return;
    id = zkey(id);
    if (scroll) window.scrollTo({ top: 0, behavior: RM ? 'auto' : 'smooth' });
    if (mode === 'zona' && curZona === id) {
      if (caso) { zp.showCaso(caso); history.replaceState(null, '', '#caso-' + caso); }
      return;
    }
    await exitAny({ home: false });
    if (mode === 'landing') await enterZona(id, { caso });
  }

  async function goCaso(exp, { zona = null, scroll = false } = {}) {
    if (!exp) return;
    let z = zona;
    if (!z) {
      const c = (await getCasos()).find(x => x.expediente === exp);
      z = c?.zona;
    }
    if (!z) { console.warn('[Caudal] caso desconocido:', exp); return; }
    return goZona(z, { caso: exp, scroll });
  }

  async function goLagoon({ scroll = false } = {}) {
    if (busy()) return;
    if (scroll) window.scrollTo({ top: 0, behavior: RM ? 'auto' : 'smooth' });
    if (heroFailed) { if (mode === 'landing') { const s = byId.get(LAGOON_ID); if (s) showCard(s); } return; }
    if (mode === 'lagoon') return;
    await exitAny({ home: false });
    if (mode === 'landing') await enterLagoon();
  }

  /** Map marker → navigation. site = {kind:"zona", zona} | {kind:"caso", expediente, zona} | {id:"aculeo"} */
  function onMapSelect(site) {
    if (!site) return;
    if (site.kind === 'zona') goZona(site.zona || site.id);
    else if (site.kind === 'caso') goCaso(site.expediente, { zona: site.zona });
    else if (site.id === LAGOON_ID) goLagoon();
    else if (ZONA_IDS.includes(zkey(site.id))) goZona(site.id);
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
    else if (zoomedIn()) zp.stepBack();
    else if (mode === 'zona') exitZona();
  }

  hint.addEventListener('click', () => {
    if (!valleFailed) goZona('z1');
    else if (!heroFailed) goLagoon();
  });
  back.addEventListener('click', goBack);
  $('c-enter').addEventListener('click', () => enterLagoon());
  $('card-close').addEventListener('click', closeCard);
  document.addEventListener('keydown', e => {
    if (e.key !== 'Escape' || e.defaultPrevented) return;
    const t = e.target;
    // never throw away what the person is typing in the expediente
    if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || t.isContentEditable)) return;
    if (mode === 'lagoon' || mode === 'zona') goBack();
    else if (mode === 'landing' && !card.hidden) closeCard();
  });

  // Pause the 3D render loops while the stage is scrolled out of view.
  if ('IntersectionObserver' in window) {
    new IntersectionObserver(es => {
      const vis = es.some(e => e.isIntersecting);
      const ctl = mode === 'lagoon' ? hero : mode === 'zona' ? valle : null;
      if (ctl && typeof ctl.setActive === 'function') {
        try { ctl.setActive(vis); } catch (e) { console.error(e); }
      }
    }, { threshold: 0.02 }).observe(stage);
  }
  MOBILE.addEventListener?.('change', () => { if (mode === 'zona') zp.syncInsets(); });
  updateHint();

  return {
    goZona, goCaso, goLagoon, onMapSelect, warm, warmHero,
    get busy() { return busy(); },
    setMap(ctl) { mapCtl = ctl; },
    get mode() { return mode; },
  };
}

async function setupMap(onSelect) {
  const container = $('map');
  try {
    const ctl = await initMap({ container, sites: sitesJson.sites || [], casos: sitesJson.casos || [], onSelect });
    if (!ctl || typeof ctl.select !== 'function' || typeof ctl.flyToSite !== 'function') throw new Error('controlador inválido');
    return ctl;
  } catch (err) {
    console.error('[Caudal] map:', err);
    container.querySelectorAll('canvas').forEach(c => { c.style.display = 'none'; });
    showFallback(container, 'Mapa 3D no disponible en este momento. Usa el resumen de zonas más abajo para explorar.');
    document.querySelectorAll('.map-legend').forEach(el => { el.hidden = true; });
    return null;
  }
}

/* ---------- persistent cache (sw.js). ?sw=0 turns it off and clears it. ---------- */
async function setupServiceWorker() {
  if (!('serviceWorker' in navigator)) return;
  try {
    if (new URLSearchParams(location.search).get('sw') === '0') {
      const regs = await navigator.serviceWorker.getRegistrations();
      await Promise.all(regs.map(r => r.unregister()));
      const names = await caches.keys();
      await Promise.all(names.filter(n => n.startsWith('caudal-')).map(n => caches.delete(n)));
      return;
    }
    await navigator.serviceWorker.register(SW_URL);
    const reg = await navigator.serviceWorker.ready;
    // What loaded before the worker took control (first visit) goes to its cache too, once the
    // preload is over so it never competes with the intro.
    const sendLoaded = () => {
      const urls = [location.href.split('#')[0], ...performance.getEntriesByType('resource').map(e => e.name)];
      reg.active?.postMessage({ type: 'cache-urls', urls });
    };
    if (document.documentElement.dataset.warm === 'done') sendLoaded();
    else window.addEventListener('caudal:warm', sendLoaded, { once: true });
  } catch (err) {
    console.warn('[Caudal] service worker:', err?.message || err);
  }
}

/* ---------- boot ---------- */
async function boot() {
  setupReveal();
  setupServiceWorker();

  try {
    const r = await fetch('data/sites.json');
    if (!r.ok) throw new Error('sites ' + r.status);
    const j = await r.json();
    sitesJson = Array.isArray(j) ? { sites: j, casos: [] } : { sites: j.sites || [], casos: j.casos || [] };
  } catch (err) {
    console.error('[Caudal] sites:', err);
    showFallback($('map'), 'No se pudieron cargar los sitios. Sirve la carpeta con un servidor local (python3 -m http.server).');
  }
  getCasos().then(c => { $('hud-count').textContent = c.length || '—'; }).catch(() => {});

  // "Cómo funciona" chart: the demo case predio vs secano, with its inspection date (chart.js).
  import('./chart.js')
    .then(m => m.renderChart($('chart'), $('callout')))
    .catch(err => console.error('[Caudal] chart:', err));

  setupZonasSummary();
  lazyOnView($('th-a'), drawThumbs);

  // The lagoon scene is not part of the landing: it used to load here (3.7 MB of imagery + a WebGL
  // context) for a view most visits never open.
  let heroP = null;
  const getHero = () => (heroP ??= setupHero().catch(err => { console.error('[Caudal] hero setup:', err); return null; }));

  const stage = setupStage({ getHero });

  // intro controller (null until/unless the intro runs). hideTitle(): navigation removes the title;
  // if it happens mid-flight (e.g. browser back to a #z1 link) the intro is skipped first.
  let introP = Promise.resolve(null);
  let introFinished = false;
  function hideTitle() {
    introP.then(i => {
      if (!i) return;
      if (!introFinished && typeof i.skip === 'function') { try { i.skip(); } catch (_) { /* opcional */ } }
      const hide = () => {
        if (typeof i.hideTitle === 'function') i.hideTitle();
        else i.title?.hide?.('external');
      };
      hide();
      // the title may only exist once the (skipped) intro settles
      Promise.resolve(i.done).then(r => { hide(); r?.title?.hide?.('external'); }).catch(() => {});
    }).catch(() => {});
  }

  // In-page links (#z1 / #z2 / #caso-… / #aculeo) enter the 3D views; keep them from jumping the scroll.
  document.addEventListener('click', e => {
    const a = e.target.closest('a[href^="#"]');
    if (!a) return;
    const t = parseHash(a.getAttribute('href').slice(1));
    if (!t) return;
    e.preventDefault();
    go(t, { scroll: true });
  });

  const mapCtl = await setupMap(site => {
    hideTitle();   // a marker click opens a view: the title goes away
    stage.onMapSelect(site);
  });
  if (mapCtl) stage.setMap(mapCtl);
  // Load the main zone's scene in the background once the map is up (unless a deep link takes over).
  const first = parseHash(location.hash.slice(1));
  if (first) {
    // deep link: no intro and no title
    $('top').classList.remove('is-intro', 'intro-pending');
    go(first, { scroll: true });
  } else {
    const introDone = startIntro(mapCtl);
    // the 3D scenes warm up only after the flight, so they never compete with it for the GPU
    preloadAll(Promise.race([introDone, sleep(15000)]));
  }
  if (first) preloadAll(sleep(4000));

  /** Everything the demo can open, made ready in the background (js/preload.js). */
  function preloadAll(scenesAfter) {
    Promise.all([import('./preload.js'), Zmod(), getIndex()]).then(([pre, Z, index]) => pre.startPreload({
      zonas: (index.zonas || []).map(z => ({ id: zkey(z.id), bbox: z.bbox_escena || null, base: z.base || `assets/zonas/${zkey(z.id)}/` })),
      lagoon: { bbox: pre.bboxAround(LAGOON_CAM.center), base: ASSET_DIR },
      loadZona: loadZonaData,
      ensureSeries: Z.ensureSeries,
      warmZona: id => stage.warm(id),
      warmLagoon: () => stage.warmHero(),
      isBusy: () => stage.busy,
      tileUrl: mapCtl && typeof mapCtl.satTileUrl === 'function' ? mapCtl.satTileUrl : null,
      scenesAfter,
    })).catch(err => console.warn('[Caudal] precarga:', err?.message || err));
  }

  /* ---- intro satelital (js/intro.js) + título. Only when the page opens without a hash. ---- */
  function startIntro(ctl) {
    const top = $('top');
    const clear = () => top.classList.remove('is-intro', 'intro-pending');
    const map = ctl ? ctl.map || globalThis.__caudalMap || null : null;
    // reduced motion (or no map): no flight, static title over the home view
    if (RM || !ctl) {
      clear();
      introP = import('./intro.js')
        .then(m => {
          const t = m.showTitle({ stage: top, map });
          return { done: Promise.resolve({ title: t, reason: RM ? 'reduced-motion' : 'fallback' }), hideTitle: () => t?.hide?.('external'), title: t };
        })
        .catch(err => { console.error('[Caudal] title:', err); return null; });
      return introP.then(i => i?.done);
    }
    // move to the far-out globe camera and hide the markers before the map is shown (intro.js does it
    // too; doing it here guarantees the first visible frame is already the planet)
    try {
      ctl.setMarkersVisible?.(false);
      const cam = ctl.introStartCamera?.();
      if (cam && map) map.jumpTo(cam);
    } catch (e) { console.warn('[Caudal] intro start camera:', e); }
    introP = import('./intro.js')
      .then(m => m.initIntro({
        stage: top,
        mapCtl: ctl,
        map,                              // older intro.js signature
        nav: top.querySelector('.nav'),
        skip: false,
        onDone: () => { introFinished = true; },
      }))
      .then(i => {
        requestAnimationFrame(() => top.classList.remove('intro-pending'));
        if (i?.done) i.done.then(() => { introFinished = true; }, () => { introFinished = true; });
        else introFinished = true;
        return i;
      })
      .catch(err => {
        console.error('[Caudal] intro:', err);
        introFinished = true;
        clear();
        try { ctl.setMarkersVisible?.(true); ctl.flyHome?.({ duration: 0 }); } catch (_) { /* opcional */ }
        return null;
      });
    // safety net: never leave the map hidden
    setTimeout(() => top.classList.remove('intro-pending'), 4000);
    return introP.then(i => i?.done).catch(() => null);
  }

  function parseHash(h) {
    if (!h) return null;
    const k = zkey(h);
    if (ZONA_IDS.includes(k)) return { kind: 'zona', zona: k };
    if (/^caso-/i.test(h)) return { kind: 'caso', expediente: decodeURIComponent(h.slice(5)) };
    if (k === LAGOON_ID) return { kind: 'lagoon' };
    return null;
  }
  function go(t, opts) {
    hideTitle();
    if (t.kind === 'zona') return stage.goZona(t.zona, opts);
    if (t.kind === 'caso') return stage.goCaso(t.expediente, opts);
    if (t.kind === 'lagoon') return stage.goLagoon(opts);
  }
  addEventListener('hashchange', () => { const t = parseHash(location.hash.slice(1)); if (t) go(t, { scroll: true }); });
}

boot();
