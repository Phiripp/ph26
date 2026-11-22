// Caudal · landing orchestration.
// Modes on #stage: landing | to-zona | zona | to-landing.
// Zones (spec v2): Z1 Petorca, Z2 Aconcagua bajo, with the 10 validation cases (resolved DGA cases).
// Every module is imported dynamically so a failure in one (or in its CDN deps) cannot take down the page.
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
const ZONA_IDS = ['z1', 'z2'];
const HASH_ALIAS = { petorca: 'z1', aconcagua: 'z2' };
const ENTER_MS = 2200, EXIT_MS = 1400;
const ROUTE_MS = 14000; // intro swoop + drive + a short stop at each predio + rise back (valle.js chase)
const BACK_LABEL = { chile: 'Volver a Chile', zona: 'Ver toda la zona' };
const TITLE_FOCUS_DELAY_MS = 250;  // map flight to the zones, after the click that dismissed the title
const MAX_VALLES = 3;             // 3D zone scenes kept built at once (one WebGL context each)
const SW_URL = 'sw.js';
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

/* Moving focus after a click/tap (zone enter/exit) should not paint a focus ring; after keyboard use it should. */
let usingKeyboard = false;
addEventListener('keydown', e => { if (e.key === 'Tab' || e.key === 'Enter' || e.key === ' ') usingKeyboard = true; }, true);
addEventListener('pointerdown', () => { usingKeyboard = false; }, true);

function showFallback(host, text) {
  if (!host) return;
  const d = document.createElement('div');
  d.className = 'fallback';
  d.setAttribute('role', 'status');
  d.innerHTML = `<span>${text}</span>`;
  host.appendChild(d);
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
        P.renderRanking(p.rank, d, { selectedId: st.selectedId, onSelect: id => selectPredio(id, { from: 'panel' }), onRuta: () => setTab('ruta', { focus: true }) });
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
    sheetNormal();   // phones: the 3D close-up and the ficha both in view
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
    sheetNormal();
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
        onStop: pid => { if (pid) selectPredio(String(pid)); },   // F5: tapping a stop opens the predio ficha
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
    // phones: fold the sheet down so the camera flight is visible (vp-peek: an even lower sheet, CSS)
    if (MOBILE.matches) { setSheet('normal'); panel.classList.add('vp-peek'); }
    valleCall('showRoute', true);
    // the route is a whole-zone story: leave a predio close-up before playing it
    if (v.isFocused?.()) { try { await v.resetView(); } catch (_) { /* opcional */ } }
    try { await v.playRoute({ duration: ROUTE_MS }); }
    catch (err) { console.error('[Caudal] playRoute:', err); }
    st.playing = false;
    panel.classList.remove('playing', 'vp-peek');
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
    setSheet(panel.classList.contains('expanded') ? 'normal' : 'expanded');
  });
  /** Bottom sheet height (phones): 'normal' (46svh) | 'expanded' (86svh). Drops the playback peek. */
  function setSheet(state) {
    const ex = state === 'expanded';
    panel.classList.toggle('expanded', ex);
    panel.classList.remove('vp-peek');
    grip.setAttribute('aria-expanded', String(ex));
    syncInsets();
  }
  /** Phones: an expanded (or peeking) sheet goes back to its normal height. */
  function sheetNormal() {
    if (MOBILE.matches && (panel.classList.contains('expanded') || panel.classList.contains('vp-peek'))) setSheet('normal');
  }

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
      $('vp-kicker').textContent = `${name} · priorización`;
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
      panel.classList.remove('expanded', 'playing', 'vp-peek');
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
    /** Viewport crossed the phone breakpoint: the sheet states only exist on phones. */
    onLayoutChange() {
      panel.classList.remove('expanded');
      panel.classList.toggle('vp-peek', MOBILE.matches && st.playing);
      grip.setAttribute('aria-expanded', 'false');
      if (!panel.hidden) syncInsets();
    },
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

/* ---------- stage: landing (national map) <-> zona (Z1 / Z2) ---------- */
function setupStage() {
  const stage = $('top'), firstValleCanvas = $('valle-canvas');
  const back = $('back'), hint = $('hint');
  const card = $('site-card');
  const sites = sitesJson.sites || [];
  const byId = new Map(sites.map(s => [s.id, s]));
  let mapCtl = null;
  // one built 3D scene per zone (up to MAX_VALLES), each on its own canvas: switching zone is free
  const valles = new Map();   // zone id -> { ctl, canvas }
  let valle = null, valleCanvas = firstValleCanvas, valleFailed = false;
  let valleQueue = Promise.resolve();
  let curZona = null;

  const zp = setupZonaPanel({ getValle: () => valle, onFocusChange: () => syncBack() });

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
    back.hidden = m !== 'zona';
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
  /* --- floating card (a zone whose 3D view failed) --- */
  function showCard(s) {
    const bd = $('c-badge');
    bd.textContent = `Zona ${s.codigo || ''}`;
    bd.className = 'badge water';
    $('c-name').textContent = s.name;
    $('c-meta').textContent = (s.comunas || []).map(comunaFmt).join(' · ');
    const loss = $('c-loss');
    loss.textContent = `${s.casos ?? '—'} casos DGA`;
    loss.className = 'c-loss';
    $('c-since').textContent = '';
    $('c-note').textContent = 'Vista 3D de la zona no disponible en este momento.';
    card.hidden = false;
    hint.hidden = true;
  }
  function hideCard() { card.hidden = true; hint.hidden = false; }

  /* ---- zona (Z1 / Z2, main flow) ---- */
  const mapSetValley = on => {
    if (!mapCtl) return;
    try {
      if (typeof mapCtl.setValley === 'function') mapCtl.setValley(on);
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
      back.focus({ preventScroll: true, focusVisible: usingKeyboard }); // no ring after a tap/click
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
    if (home) hint.focus({ preventScroll: true, focusVisible: usingKeyboard });
  }

  function clearHash(test) {
    const h = location.hash.slice(1);
    if (h && test(h)) history.replaceState(null, '', location.pathname + location.search);
  }

  async function exitAny(opts) {
    if (mode === 'zona') await exitZona(opts);
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

  /** Map marker → navigation. site = {kind:"zona", zona} | {kind:"caso", expediente, zona} */
  function onMapSelect(site) {
    if (!site) return;
    if (site.kind === 'zona') goZona(site.zona || site.id);
    else if (site.kind === 'caso') goCaso(site.expediente, { zona: site.zona });
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
    if (zoomedIn()) zp.stepBack();
    else if (mode === 'zona') exitZona();
  }

  hint.addEventListener('click', () => {
    if (!valleFailed) goZona('z1');
  });
  back.addEventListener('click', goBack);
  $('card-close').addEventListener('click', closeCard);
  document.addEventListener('keydown', e => {
    if (e.key !== 'Escape' || e.defaultPrevented) return;
    const t = e.target;
    // never throw away what the person is typing in the expediente
    if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || t.isContentEditable)) return;
    if (mode === 'zona') goBack();
    else if (mode === 'landing' && !card.hidden) closeCard();
  });

  // Pause the 3D render loops while the stage is scrolled out of view.
  if ('IntersectionObserver' in window) {
    new IntersectionObserver(es => {
      const vis = es.some(e => e.isIntersecting);
      const ctl = mode === 'zona' ? valle : null;
      if (ctl && typeof ctl.setActive === 'function') {
        try { ctl.setActive(vis); } catch (e) { console.error(e); }
      }
    }, { threshold: 0.02 }).observe(stage);
  }
  // rotating a phone (or resizing across the breakpoint): bottom sheet <-> side panel
  MOBILE.addEventListener?.('change', () => { zp.onLayoutChange(); });
  updateHint();

  return {
    goZona, goCaso, onMapSelect, warm,
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

  const stage = setupStage();

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

  // In-page links (#z1 / #z2 / #caso-…) enter the 3D views; keep them from jumping the scroll.
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
    // deep link: no intro and no title, so "back" lands on the close view of the zones
    $('top').classList.remove('is-intro', 'intro-pending');
    mapCtl?.setHomeMode?.('zonas', { fly: false });
    go(first, { scroll: true });
  } else {
    const introDone = startIntro(mapCtl);
    introP.then(i => focusZonasWhenTitleLeaves(mapCtl, i));
    import('./datos-portada.js').then(m => m.mountPortadaDatos($('facts'))).catch(err => console.error('[Caudal] datos-portada.js:', err));
    // the 3D scenes warm up only after the flight, so they never compete with it for the GPU
    preloadAll(Promise.race([introDone, sleep(15000)]));
  }
  if (first) preloadAll(sleep(4000));

  /** Everything the demo can open, made ready in the background (js/preload.js). */
  function preloadAll(scenesAfter) {
    Promise.all([import('./preload.js'), Zmod(), getIndex()]).then(([pre, Z, index]) => pre.startPreload({
      zonas: (index.zonas || []).map(z => ({ id: zkey(z.id), bbox: z.bbox_escena || null, base: z.base || `assets/zonas/${zkey(z.id)}/` })),
      loadZona: loadZonaData,
      ensureSeries: Z.ensureSeries,
      warmZona: id => stage.warm(id),
      isBusy: () => stage.busy,
      tileUrl: mapCtl && typeof mapCtl.satTileUrl === 'function' ? mapCtl.satTileUrl : null,
      scenesAfter,
    })).catch(err => console.warn('[Caudal] precarga:', err?.message || err));
  }

  /**
   * Once the landing title is gone the map's default view is the close one over both zones. The
   * camera only flies there while the landing is on screen (a marker click is already going elsewhere).
   */
  function focusZonasWhenTitleLeaves(ctl, introCtl) {
    if (!ctl || typeof ctl.setHomeMode !== 'function') return;
    const focus = () => {
      const landing = $('top').dataset.mode === 'landing';
      Promise.resolve(ctl.setHomeMode('zonas', { fly: landing, duration: RM ? 0 : 1800 }))
        .catch(err => console.warn('[Caudal] vista de zonas:', err?.message || err));
    };
    Promise.resolve(introCtl?.done)
      .then(r => {
        const t = r?.title || introCtl?.title;
        // start with the title's exit, but after the click that dismissed it: a pointer press on the map stops any flight
        if (t?.leaving) return t.leaving.then(() => sleep(TITLE_FOCUS_DELAY_MS)).then(focus);
        return t?.hidden ? t.hidden.then(focus) : focus();
      })
      .catch(err => { console.warn('[Caudal] título:', err?.message || err); focus(); });
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
    return null;
  }
  function go(t, opts) {
    hideTitle();
    if (t.kind === 'zona') return stage.goZona(t.zona, opts);
    if (t.kind === 'caso') return stage.goCaso(t.expediente, opts);
  }
  addEventListener('hashchange', () => { const t = parseHash(location.hash.slice(1)); if (t) go(t, { scroll: true }); });
}

boot();
