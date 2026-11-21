// Caudal · ranking list + ficha de predio. "El sistema prioriza, no acusa."
import { BAND_LABEL, BAND_SHORT, CONF_LABEL, fmtNum, fmtMil, fmtRange, fmtDate, fmtComuna, expShort, dryWindowStats, esc } from './zona-data.js';
import { seriesChartSVG, chartLegendHTML } from './chart.js';

const pill = b => `<span class="pn-pill pn-${b}">${esc(BAND_SHORT[b] || b)}</span>`;
const casoTag = e => `<span class="pn-caso" title="Caso sancionado por la DGA · ${esc(e)}">Caso ${esc(expShort(e))}</span>`;
const rank = (a, c) => (c.properties.indice ?? -1) - (a.properties.indice ?? -1) || (c.properties.m3_estimado_max ?? 0) - (a.properties.m3_estimado_max ?? 0);
export const temporadaOf = data => data.scoresMeta?.temporada || '2025-26';
/** dry-season months of a temporada "2025-26" -> {from:'2025-12-01', to:'2026-03-31'} */
export function seasonRange(t) {
  const y = parseInt(String(t), 10) || 2025;
  return { from: `${y}-12-01`, to: `${y + 1}-03-31` };
}

export function renderRanking(el, data, { onSelect, selectedId } = {}) {
  if (!el) return;
  const groups = { alta: [], media: [], baja: [], sin_alerta: [], sin_dato: [] };
  for (const f of data.predios) (groups[f.properties.banda] || groups.sin_dato).push(f);
  for (const k in groups) groups[k].sort(rank);

  const row = (f, withPill = false) => {
    const p = f.properties;
    const meta = p.banda === 'sin_dato' ? '<span class="pn-row-meta">sin dato</span>' : `<span class="pn-row-meta pn-range">${fmtRange(p.m3_estimado_min, p.m3_estimado_max, '')}</span>`;
    return `<li><button type="button" class="pn-row pn-r-${p.banda}${p.id === selectedId ? ' is-sel' : ''}" data-id="${esc(p.id)}" aria-pressed="${p.id === selectedId}" title="Predio ${esc(p.id)} · ${esc(fmtComuna(p.comuna))}">
      <span class="pn-row-top"><b class="pn-id">${esc(p.rol || p.id)}</b>${withPill ? pill(p.banda) : ''}${p.caso ? casoTag(p.caso) : ''}${meta}</span>
    </button></li>`;
  };
  const c = data.counts;
  const sinInd = (c.sin_alerta || 0) + (c.sin_dato || 0);
  let h = `<div class="pn-sum" role="list">
      ${['alta', 'media', 'baja'].map(b => `<span role="listitem" class="pn-sum-i pn-${b}"><b>${c[b] || 0}</b>${esc(BAND_SHORT[b])}</span>`).join('')}
      <span role="listitem" class="pn-sum-i pn-sin_alerta"><b>${sinInd}</b>Sin indicio</span>
    </div>`;
  for (const b of ['alta', 'media']) {
    if (!groups[b].length) continue;
    h += `<section class="pn-group pn-g-${b}"><h4 class="pn-gh"><span class="pn-dot pn-${b}"></span>${esc(BAND_LABEL[b])}<span class="pn-count">${groups[b].length}</span></h4><ul class="pn-list">${groups[b].map(f => row(f)).join('')}</ul></section>`;
  }
  const rest = [...groups.baja, ...groups.sin_alerta, ...groups.sin_dato];
  if (rest.length) {
    const open = !groups.alta.length && !groups.media.length;
    h += `<details class="pn-group pn-g-rest pn-more"${open ? ' open' : ''}><summary class="pn-gh"><span class="pn-dot pn-sin_alerta"></span>Otros predios<span class="pn-count">${rest.length}</span></summary><ul class="pn-list">${rest.map(f => row(f, true)).join('')}</ul></details>`;
  }
  h += `<p class="pn-foot">Consumo estimado ${esc(temporadaOf(data))} en mil m³ (rango). Bandas provisionales hasta el modelo M5.</p>`;
  el.innerHTML = h;
  el.onclick = e => {
    const b = e.target.closest('.pn-row');
    if (!b || !el.contains(b)) return;
    el.querySelectorAll('.pn-row.is-sel').forEach(x => { x.classList.remove('is-sel'); x.setAttribute('aria-pressed', 'false'); });
    b.classList.add('is-sel'); b.setAttribute('aria-pressed', 'true');
    onSelect?.(b.dataset.id);
  };
  if (selectedId) {
    const sel = el.querySelector(`.pn-row[data-id="${CSS.escape(selectedId)}"]`);
    sel?.closest('details')?.setAttribute('open', '');
    sel?.scrollIntoView({ block: 'nearest' });
  }
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
  if (p.banda === 'sin_dato') note = 'Sin serie satelital suficiente para estimar el consumo.';
  else if (st && st.ndvi != null && st.refNdvi != null) note = `${st.ndvi - st.refNdvi >= 0.1 ? 'Verde sin lluvia = riego probable. ' : ''}Ventana seca ${fmtDate(st.win.inicio)}–${fmtDate(st.win.fin)}: NDVI ${fmtNum(st.ndvi, 2)} vs. ${fmtNum(st.refNdvi, 2)} del secano.`;
  else note = flagged ? 'Verde cuando no llueve = riego probable. Indicio para priorizar, no prueba.' : 'Sin consumo sobre el derecho. No se propone inspección.';

  el.innerHTML = `
    <button type="button" class="pn-back" data-act="back">← Ranking</button>
    <header class="pn-fh">
      <h3 class="pn-title">${esc(p.rol ? `Rol ${p.rol}` : `Predio ${p.id}`)} ${pill(p.banda)}${p.banda !== 'sin_dato' ? '<em class="pn-prov" title="Banda provisional hasta el modelo M5">provisional</em>' : ''}</h3>
      <p class="pn-sub">${sub.map(esc).join(' · ')}</p>
    </header>
    ${caso ? `<button type="button" class="pn-caselink" data-act="caso"><span class="pn-caso">Caso</span><b>${esc(caso.expediente)}</b><span>sancionado por la DGA · ${fmtNum(caso.multa_utm, 1)} UTM</span><i aria-hidden="true">→</i></button>` : ''}
    <dl class="pn-kpis">
      <div><dt>Consumo estimado ${esc(temporada)}</dt><dd class="pn-water">${p.m3_estimado_min == null ? '—' : `${fmtMil(p.m3_estimado_min)}–${fmtMil(p.m3_estimado_max)} <small>mil m³</small>`}</dd></div>
      <div><dt>Derecho del rol · DGA</dt>${derechoHTML(p)}</div>
    </dl>
    <figure class="pn-chart">
      <figcaption>Verdor (NDVI) vs. secano · franjas = sin lluvia</figcaption>
      <svg viewBox="0 0 560 230" role="img" aria-label="Serie NDVI y NDMI del predio ${esc(p.id)} frente a la referencia de secano, con ventanas secas sombreadas">${seriesChartSVG(data, p.id, { W: 560, H: 230, compact: true, marks, highlight: st?.win })}</svg>
      <div class="pn-legend">${chartLegendHTML({ mark: !!caso })}</div>
    </figure>
    <p class="pn-note">${esc(note)}</p>
    <div class="pn-actions">
      <button type="button" class="btn primary" data-act="exp"${flagged ? '' : ' disabled'}>Preparar expediente</button>
    </div>`;
  el.onclick = e => {
    const a = e.target.closest('[data-act]')?.dataset.act;
    if (a === 'back') onBack?.();
    else if (a === 'exp') onExpediente?.(p.id);
    else if (a === 'caso') onCaso?.(caso.expediente);
  };
  el.scrollTop = 0;
}
