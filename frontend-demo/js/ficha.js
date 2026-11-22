// Caudal · ranking list + ficha de predio. "El sistema prioriza, no acusa."
import { BAND_LABEL, BAND_SHORT, CONF_LABEL, fmtNum, fmtMil, fmtRange, fmtDate, fmtComuna, expShort, dryWindowStats, seriesFailed, SERIES_FAILED_TEXT, esc } from './zona-data.js';
import { mountSeriesChart, chartLegendHTML } from './chart.js';
import { mountExplicacion } from './explicacion.js';

const pill = b => `<span class="pn-pill pn-${b}">${esc(BAND_SHORT[b] || b)}</span>`;
const casoTag = e => `<span class="pn-caso" title="Caso sancionado por la DGA · ${esc(e)}">Caso ${esc(expShort(e))}</span>`;
const rank = (a, c) => (c.properties.indice ?? -1) - (a.properties.indice ?? -1) || (c.properties.m3_estimado_max ?? 0) - (a.properties.m3_estimado_max ?? 0);
export const temporadaOf = data => data.scoresMeta?.temporada || '2025-26';
/** dry-season months of a temporada "2025-26" -> {from:'2025-12-01', to:'2026-03-31'} */
export function seasonRange(t) {
  const y = parseInt(String(t), 10) || 2025;
  return { from: `${y}-12-01`, to: `${y + 1}-03-31` };
}

/* ---------- ranking: rows are mounted in batches as the list scrolls ---------- */
// With thousands of predios, one <button> per predio up front meant ~28k DOM nodes and a 0.4 s freeze every
// time the list was (re)built. A group mounts ROWS_FIRST rows and more when its sentinel scrolls into view.
const ROWS_FIRST = 60;
const ROWS_STEP = 120;
const groupsCache = new WeakMap(); // zone data -> predios grouped by band, each group ranked

function groupsOf(data) {
  let g = groupsCache.get(data);
  if (!g) {
    g = { alta: [], media: [], baja: [], sin_alerta: [], sin_dato: [] };
    for (const f of data.predios) (g[f.properties.banda] || g.sin_dato).push(f);
    for (const k in g) g[k].sort(rank);
    groupsCache.set(data, g);
  }
  return g;
}

function rowHTML(f, withPill, selectedId) {
  const p = f.properties;
  const meta = p.banda === 'sin_dato' ? '<span class="pn-row-meta">sin dato</span>' : `<span class="pn-row-meta pn-range">${fmtRange(p.m3_estimado_min, p.m3_estimado_max, '')}</span>`;
  return `<li><button type="button" class="pn-row pn-r-${p.banda}${p.id === selectedId ? ' is-sel' : ''}" data-id="${esc(p.id)}" aria-pressed="${p.id === selectedId}" title="Predio ${esc(p.id)} · ${esc(fmtComuna(p.comuna))}">
      <span class="pn-row-top"><b class="pn-id">${esc(p.rol || p.id)}</b>${withPill ? pill(p.banda) : ''}${p.caso ? casoTag(p.caso) : ''}${meta}</span>
    </button></li>`;
}

/**
 * Fills a <ul> with `items` in batches. Returns { reveal(id) } which mounts rows up to that predio.
 * state = { selectedId } is read when each batch is mounted, so late rows get the current selection.
 */
function mountRows(ul, items, { withPill, state, root }) {
  let mounted = 0;
  let sentinel = null, io = null;
  const dispose = () => { io?.disconnect(); io = null; };
  const more = (upTo) => {
    const to = Math.min(items.length, Math.max(upTo, mounted));
    if (to > mounted) {
      const html = items.slice(mounted, to).map(f => rowHTML(f, withPill, state.selectedId)).join('');
      if (sentinel) sentinel.insertAdjacentHTML('beforebegin', html); else ul.insertAdjacentHTML('beforeend', html);
      mounted = to;
    }
    if (mounted >= items.length && sentinel) { io?.disconnect(); sentinel.remove(); sentinel = null; }
  };
  if (items.length > ROWS_FIRST) {
    sentinel = document.createElement('li');
    sentinel.className = 'pn-rows-more';
    sentinel.setAttribute('aria-hidden', 'true');
    sentinel.style.cssText = 'height:1px;margin:0;padding:0;list-style:none';
    ul.appendChild(sentinel);
    if ('IntersectionObserver' in window) {
      io = new IntersectionObserver(es => { if (es.some(e => e.isIntersecting)) more(mounted + ROWS_STEP); }, { root, rootMargin: '600px 0px' });
      io.observe(sentinel);
    }
  }
  more('IntersectionObserver' in window ? ROWS_FIRST : items.length);
  return {
    dispose,
    reveal(id) {
      const i = items.findIndex(f => f.properties.id === id);
      if (i >= mounted) more(i + 1 + ROWS_STEP / 2);
      return i >= 0;
    },
  };
}

/** Marks `id` (or nothing) as the selected row of a ranking built by renderRanking(), mounting it if needed. */
export function selectRankingRow(el, id, { scroll = true } = {}) {
  const st = el?._rank;
  if (!st) return;
  st.state.selectedId = id || null;
  el.querySelectorAll('.pn-row.is-sel').forEach(x => { x.classList.remove('is-sel'); x.setAttribute('aria-pressed', 'false'); });
  if (!id) return;
  st.lists.some(l => l.reveal(id));
  const sel = el.querySelector(`.pn-row[data-id="${CSS.escape(id)}"]`);
  if (!sel) return;
  sel.classList.add('is-sel'); sel.setAttribute('aria-pressed', 'true');
  sel.closest('details')?.setAttribute('open', '');
  if (scroll) sel.scrollIntoView({ block: 'nearest' });
}

/** "usa 25–44 veces su derecho" / "sin derecho de agua" — the consumption vs. right, in words. */
function vsDerecho(p) {
  const der = +(p.m3_derecho_rol ?? p.m3_derecho ?? NaN);
  if (p.m3_estimado_min == null) return '';
  if (Number.isNaN(der)) return 'sin cruce con derechos';
  if (der <= 0) return '<b>sin derecho de agua</b> registrado';
  const lo = p.m3_estimado_min / der, hi = p.m3_estimado_max / der;
  if (hi < 1.5) return 'cerca de su derecho';
  const f = v => fmtNum(v, v < 10 ? 1 : 0);
  return `usa <b>${f(lo)}–${f(hi)} veces</b> su derecho`;
}

/** The 3-minute version of the ranking: one sentence, a proportion bar, the top 5 and a button to the route. */
function storyHTML(data, groups, sinInd, routeN) {
  const c = data.counts;
  const total = (c.alta || 0) + (c.media || 0) + (c.baja || 0) + sinInd;
  const pct = n => total ? (100 * n / total).toFixed(2) : 0;
  const top = groups.alta.length ? groups.alta.slice(0, 5) : [...groups.media, ...groups.baja].slice(0, 5);
  const card = (f, i) => {
    const p = f.properties;
    const what = [p.cultivo && p.cultivo !== 'sin catastro' ? p.cultivo : null, `${fmtNum(p.area_ha, 1)} ha`, fmtComuna(p.comuna)].filter(Boolean).map(esc).join(' · ');
    return `<li><button type="button" class="pn-row pn-top pn-r-${p.banda}" data-id="${esc(p.id)}" title="Predio ${esc(p.id)}">
        <span class="pn-top-n">${i + 1}</span>
        <span class="pn-top-main"><b class="pn-id">Rol ${esc(p.rol || p.id)}</b>${p.caso ? casoTag(p.caso) : ''}<small>${what}</small><span class="pn-top-vs">${vsDerecho(p)}</span></span>
        <span class="pn-top-go" aria-hidden="true">›</span>
      </button></li>`;
  };
  return `
    <header class="pn-story">
      <p class="pn-story-h">De <b>${fmtNum(total, 0)}</b> predios, <b class="pn-hot">${fmtNum(c.alta || 0, 0)}</b> tienen señal alta de riego por sobre su derecho.</p>
      <div class="pn-bar" role="img" aria-label="Alta ${c.alta || 0}, media ${c.media || 0}, baja ${c.baja || 0}, sin indicio ${sinInd}">
        <i class="pn-alta" style="width:${pct(c.alta || 0)}%"></i><i class="pn-media" style="width:${pct(c.media || 0)}%"></i><i class="pn-baja" style="width:${pct(c.baja || 0)}%"></i><i class="pn-sin_alerta" style="flex:1"></i>
      </div>
      <p class="pn-bar-k"><span class="pn-alta">● alta ${fmtNum(c.alta || 0, 0)}</span><span class="pn-media">● media ${fmtNum(c.media || 0, 0)}</span><span class="pn-sin_alerta">● resto ${fmtNum((c.baja || 0) + sinInd, 0)}</span></p>
    </header>
    <h4 class="pn-gh pn-top-h">Inspeccionar primero</h4>
    <ol class="pn-list pn-toplist">${top.map(card).join('')}</ol>
    ${routeN ? `<button type="button" class="btn primary pn-cta" data-act="ruta">Ver la ruta de inspección →</button>` : ''}`;
}

export function renderRanking(el, data, { onSelect, selectedId, onRuta } = {}) {
  if (!el) return;
  const groups = groupsOf(data);
  const state = { selectedId: selectedId || null };
  const root = el.closest('.vp-body') || null;
  const c = data.counts;
  const sinInd = (c.sin_alerta || 0) + (c.sin_dato || 0);
  const lists = []; // [{ key, items, withPill }] in DOM order
  const nPrio = groups.alta.length + groups.media.length;
  let h = storyHTML(data, groups, sinInd, !!onRuta)
    + `<details class="pn-all"><summary>Ver los ${fmtNum(nPrio, 0)} predios priorizados</summary>`;
  for (const b of ['alta', 'media']) {
    if (!groups[b].length) continue;
    lists.push({ key: b, items: groups[b], withPill: false });
    h += `<section class="pn-group pn-g-${b}"><h4 class="pn-gh"><span class="pn-dot pn-${b}"></span>${esc(BAND_LABEL[b])}<span class="pn-count">${groups[b].length}</span></h4><ul class="pn-list" data-list="${b}"></ul></section>`;
  }
  const rest = [...groups.baja, ...groups.sin_alerta, ...groups.sin_dato];
  if (rest.length) {
    const open = !groups.alta.length && !groups.media.length;
    lists.push({ key: 'rest', items: rest, withPill: true });
    h += `<details class="pn-group pn-g-rest pn-more"${open ? ' open' : ''}><summary class="pn-gh"><span class="pn-dot pn-sin_alerta"></span>Otros predios<span class="pn-count">${rest.length}</span></summary><ul class="pn-list" data-list="rest"></ul></details>`;
  }
  h += `<p class="pn-foot">Consumo estimado ${esc(temporadaOf(data))} en mil m³ (rango). Bandas del modelo M5.</p></details>`;
  el._rank?.lists.forEach(l => l.dispose()); // observers of the previous render of this element
  el.innerHTML = h;
  el._rank = {
    state,
    lists: lists.map(l => mountRows(el.querySelector(`[data-list="${l.key}"]`), l.items, { withPill: l.withPill, state, root })),
  };
  el.onclick = e => {
    if (e.target.closest('[data-act="ruta"]')) { onRuta?.(); return; }
    const b = e.target.closest('.pn-row');
    if (!b || !el.contains(b)) return;
    selectRankingRow(el, b.dataset.id, { scroll: false });
    onSelect?.(b.dataset.id);
  };
  if (state.selectedId) selectRankingRow(el, state.selectedId);
}

/** "Derecho del rol · DGA" value: real m³, or the reason there is none. */
export function derechoHTML(p) {
  const v = p.m3_derecho_rol ?? p.m3_derecho;
  if (v == null) return `<dd class="pn-dd-txt">sin cruce</dd>`;
  if (+v === 0) return `<dd class="pn-dd-txt pn-loss" title="${esc(p.estado_derechos || '')}">sin derechos en el rol</dd>`;
  return `<dd>${fmtMil(v)} <small>mil m³</small></dd>`;
}

export function renderFicha(el, feature, data, { onExpediente, onBack, onCaso } = {}) {
  if (!el || !feature) return;
  const p = feature.properties;
  const caso = p.caso ? data.casos?.find(c => c.expediente === p.caso) : null;
  const flagged = ['alta', 'media', 'baja'].includes(p.banda);
  const temporada = temporadaOf(data);
  const st = dryWindowStats(data, p.id, seasonRange(temporada));
  const marks = caso ? [{ fecha: caso.fecha_inspeccion, label: 'Inspección DGA' }] : [];
  const sub = [p.cultivo && p.cultivo !== 'sin catastro' ? p.cultivo : 'cultivo sin catastro', `${fmtNum(p.area_ha, 1)} ha`, fmtComuna(p.comuna), p.confianza ? (CONF_LABEL[p.confianza] || p.confianza).toLowerCase() : null].filter(Boolean);
  let note;
  if (seriesFailed(data, p.id)) note = SERIES_FAILED_TEXT;
  else if (p.banda === 'sin_dato') note = 'Sin serie satelital suficiente para estimar el consumo.';
  else if (st && st.ndvi != null && st.refNdvi != null) note = `${st.ndvi - st.refNdvi >= 0.1 ? 'Verde sin lluvia = riego probable. ' : ''}Ventana seca ${fmtDate(st.win.inicio)}–${fmtDate(st.win.fin)}: NDVI ${fmtNum(st.ndvi, 2)} vs. ${fmtNum(st.refNdvi, 2)} del secano.`;
  else note = flagged ? 'Verde cuando no llueve = riego probable. Indicio para priorizar, no prueba.' : 'Sin consumo sobre el derecho. No se propone inspección.';

  el.innerHTML = `
    <button type="button" class="pn-back" data-act="back">← Ranking</button>
    <header class="pn-fh">
      <h3 class="pn-title">${esc(p.rol ? `Rol ${p.rol}` : `Predio ${p.id}`)} ${pill(p.banda)}</h3>
      <p class="pn-sub">${sub.map(esc).join(' · ')}</p>
    </header>
    ${caso ? `<button type="button" class="pn-caselink" data-act="caso"><span class="pn-caso">Caso</span><b>${esc(caso.expediente)}</b><span>sancionado por la DGA · ${fmtNum(caso.multa_utm, 1)} UTM</span><i aria-hidden="true">→</i></button>` : ''}
    <dl class="pn-kpis">
      <div><dt>Consumo estimado ${esc(temporada)}</dt><dd class="pn-water">${p.m3_estimado_min == null ? '—' : `${fmtMil(p.m3_estimado_min)}–${fmtMil(p.m3_estimado_max)} <small>mil m³</small>`}</dd></div>
      <div><dt>Derecho del rol · DGA</dt>${derechoHTML(p)}</div>
    </dl>
    <section class="pn-why" data-why></section>
    <figure class="pn-chart">
      <figcaption>Verdor (NDVI) vs. secano · franjas = sin lluvia</figcaption>
      <svg data-series viewBox="0 0 560 230" role="img" aria-label="Serie NDVI y NDMI del predio ${esc(p.id)} frente a la referencia de secano, con ventanas secas sombreadas"></svg>
      <div class="pn-legend">${chartLegendHTML({ mark: !!caso })}</div>
    </figure>
    <p class="pn-note">${esc(note)}</p>
    <div class="pn-actions">
      <button type="button" class="btn primary" data-act="exp"${flagged ? '' : ' disabled'}>Preparar expediente</button>
    </div>`;
  mountSeriesChart(el.querySelector('svg[data-series]'), data, p.id, { W: 560, H: 230, compact: true, marks, highlight: st?.win });
  if (p.banda === 'sin_dato') el.querySelector('[data-why]').hidden = true;
  else mountExplicacion(el.querySelector('[data-why]'), `/api/predios/${encodeURIComponent(p.id)}`);
  el.onclick = e => {
    const a = e.target.closest('[data-act]')?.dataset.act;
    if (a === 'back') onBack?.();
    else if (a === 'exp') onExpediente?.(p.id);
    else if (a === 'caso') onCaso?.(caso.expediente);
  };
  el.scrollTop = 0;
}
