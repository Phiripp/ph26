// Caudal · ranking list + ficha de predio. "El sistema prioriza, no acusa."
import { BANDS, BAND_LABEL, BAND_SHORT, CONF_LABEL, fmtNum, fmtMil, fmtRange, excesoRange, esc } from './petorca-data.js';
import { seriesChartSVG, chartLegendHTML } from './chart.js';

const pill = b => `<span class="pn-pill pn-${b}">${esc(BAND_SHORT[b] || b)}</span>`;
const conf = c => `<span class="pn-conf pn-conf-${c}" title="${esc(CONF_LABEL[c] || c)}">${esc(CONF_LABEL[c] || c)}</span>`;

export function renderRanking(el, data, { onSelect, selectedId } = {}) {
  if (!el) return;
  const groups = {};
  for (const b of BANDS) groups[b] = [];
  for (const f of data.predios) (groups[f.properties.banda] || (groups[f.properties.banda] = [])).push(f);
  for (const b of BANDS) groups[b].sort((a, c) => c.properties.indice - a.properties.indice);

  const row = f => {
    const p = f.properties;
    return `<li><button type="button" class="pn-row${p.id === selectedId ? ' is-sel' : ''}" data-id="${esc(p.id)}" aria-pressed="${p.id === selectedId}">
      <span class="pn-row-top"><b class="pn-id">${esc(p.id)}</b>${pill(p.banda)}<span class="pn-row-meta pn-range">${fmtRange(p.m3_estimado_min, p.m3_estimado_max)}</span></span>
    </button></li>`;
  };
  const c = data.counts;
  let h = `<div class="pn-sum" role="list">
      ${['alta', 'media', 'baja'].map(b => `<span role="listitem" class="pn-sum-i pn-${b}"><b>${c[b]}</b>${esc(BAND_SHORT[b])}</span>`).join('')}
      <span role="listitem" class="pn-sum-i pn-sin_alerta"><b>${c.sin_alerta}</b>Sin indicio</span>
    </div>`;
  for (const b of ['alta', 'media']) {
    if (!groups[b].length) continue;
    h += `<section class="pn-group"><h4 class="pn-gh"><span class="pn-dot pn-${b}"></span>${esc(BAND_LABEL[b])}<span class="pn-count">${groups[b].length}</span></h4><ul class="pn-list">${groups[b].map(row).join('')}</ul></section>`;
  }
  const rest = [...groups.baja, ...groups.sin_alerta];
  if (rest.length) {
    h += `<details class="pn-group pn-more"><summary class="pn-gh"><span class="pn-dot pn-sin_alerta"></span>Otros predios<span class="pn-count">${rest.length}</span></summary><ul class="pn-list">${rest.map(row).join('')}</ul></details>`;
  }
  h += `<p class="pn-foot">Consumo estimado 2024 en rangos. Derechos de agua ilustrativos en esta demo.</p>`;
  el.innerHTML = h;
  el.onclick = e => {
    const b = e.target.closest('.pn-row');
    if (!b || !el.contains(b)) return;
    el.querySelectorAll('.pn-row.is-sel').forEach(x => { x.classList.remove('is-sel'); x.setAttribute('aria-pressed', 'false'); });
    b.classList.add('is-sel'); b.setAttribute('aria-pressed', 'true');
    onSelect?.(b.dataset.id);
  };
  if (selectedId) el.querySelector(`.pn-row[data-id="${CSS.escape(selectedId)}"]`)?.scrollIntoView({ block: 'nearest' });
}

export function renderFicha(el, feature, data, { onExpediente, onBack } = {}) {
  if (!el || !feature) return;
  const p = feature.properties;
  const ex = excesoRange(p);
  const motivos = (p.confianza_motivos || []);
  const flagged = p.banda !== 'sin_alerta';
  el.innerHTML = `
    <button type="button" class="pn-back" data-act="back">← Ranking</button>
    <header class="pn-fh">
      <h3 class="pn-title">${esc(p.id)} ${pill(p.banda)}</h3>
      <p class="pn-sub">${esc(p.cultivo)} · ${fmtNum(p.area_ha, 1)} ha · ${esc((CONF_LABEL[p.confianza] || p.confianza).toLowerCase())}</p>
    </header>
    <dl class="pn-kpis">
      <div><dt>Consumo estimado</dt><dd class="pn-water">${fmtMil(p.m3_estimado_min)}–${fmtMil(p.m3_estimado_max)} <small>mil m³</small></dd></div>
      <div><dt>Derecho <em class="pn-illus">ilustrativo</em></dt><dd>${fmtMil(p.m3_derecho)} <small>mil m³</small></dd></div>
    </dl>
    <figure class="pn-chart">
      <figcaption>Verdor (NDVI) vs. secano · franjas = sin lluvia</figcaption>
      <svg viewBox="0 0 560 230" role="img" aria-label="Serie NDVI y NDMI del predio ${esc(p.id)} frente a la referencia de secano, con ventanas secas sombreadas">${seriesChartSVG(data, p.id, { W: 560, H: 230, compact: true })}</svg>
      <div class="pn-legend">${chartLegendHTML()}</div>
    </figure>
    <p class="pn-note">${flagged
      ? 'Verde cuando no llueve = riego probable. Indicio para priorizar, no prueba.'
      : 'Sin consumo sobre el derecho. No se propone inspección.'}</p>
    <div class="pn-actions">
      <button type="button" class="btn primary" data-act="exp"${flagged ? '' : ' disabled'}>Preparar expediente</button>
    </div>`;
  el.onclick = e => {
    const a = e.target.closest('[data-act]')?.dataset.act;
    if (a === 'back') onBack?.();
    else if (a === 'exp') onExpediente?.(p.id);
  };
  el.scrollTop = 0;
}
