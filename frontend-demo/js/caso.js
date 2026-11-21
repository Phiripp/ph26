// Caudal · panel de caso de validación (casos resueltos por la DGA, con multa).
// Un caso sancionado sí se puede nombrar como tal; los predios sin resolver nunca.
import { fmtNum, fmtDate, fmtDateNum, fmtComuna, expShort, dryWindowStats, esc } from './zona-data.js';
import { seriesChartSVG, chartLegendHTML } from './chart.js';

const IMG_LABEL = { seca_previa: 'Antes de la inspección', seca_2025_26: 'Seca 2025-26', reciente: 'Reciente' };

/** Predio outline over a Sentinel-2 crop, mapped with the crop's corner coords (≈ axis-aligned). */
function outlineSVG(feature, esquinas) {
  const g = feature?.geometry;
  if (!g || !esquinas?.length) return '';
  const rings = g.type === 'Polygon' ? [g.coordinates[0]] : g.type === 'MultiPolygon' ? g.coordinates.map(p => p[0]) : [];
  if (!rings.length) return '';
  const lons = esquinas.map(c => c[0]), lats = esquinas.map(c => c[1]);
  const w = Math.min(...lons), e = Math.max(...lons), s = Math.min(...lats), n = Math.max(...lats);
  const d = rings.map(r => r.map((c, i) => `${i ? 'L' : 'M'}${((c[0] - w) / (e - w) * 100).toFixed(2)} ${((n - c[1]) / (n - s) * 100).toFixed(2)}`).join('') + 'Z').join('');
  return `<svg class="pn-img-ol" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true"><path d="${d}"/></svg>`;
}

/** One-line takeaway: what the signal looked like in the dry window before the inspection. */
export function casoTakeaway(caso, data) {
  const id = caso.predio_id;
  if (!id || !data.series?.predios?.[id]?.length) return { st: null, text: 'Sin serie satelital para este predio antes de la inspección.' };
  const st = dryWindowStats(data, id, { before: caso.fecha_inspeccion, months: 14 });
  if (!st) return { st: null, text: 'La serie no cubre una ventana seca anterior a la inspección.' };
  const diff = st.ndvi - st.refNdvi;
  const lead = diff >= 0.1 ? 'Antes de la inspección ya se veía riego sin lluvia' : diff >= 0.03 ? 'Antes de la inspección había una señal débil' : 'Antes de la inspección la señal no destacaba';
  return { st, text: `${lead}: ${fmtDate(st.win.inicio)}–${fmtDate(st.win.fin)}, NDVI ${fmtNum(st.ndvi, 2)} vs. ${fmtNum(st.refNdvi, 2)} del secano.` };
}

export function renderCaso(el, caso, zonaData, { onPredio, onExpediente, onBack } = {}) {
  if (!el || !caso) return;
  const data = zonaData;
  const f = caso.predio_id ? data.byId.get(caso.predio_id) : null;
  const p = f?.properties || {};
  const rol = p.rol || caso.rol;
  const area = p.area_ha ?? caso.area_ha;
  const { st, text } = casoTakeaway(caso, data);
  const marks = [{ fecha: caso.fecha_inspeccion, label: 'Inspección' }];
  const imgs = (caso.imagenes || []).filter(i => i.rgb || i.ndvi);
  const sub = [fmtComuna(caso.comuna), rol ? `rol ${rol}` : null, area != null ? `${fmtNum(area, 1)} ha` : null].filter(Boolean);

  el.innerHTML = `
    <button type="button" class="pn-back" data-act="back">← Casos</button>
    <header class="pn-fh">
      <p class="pn-kicker">Caso sancionado por la DGA</p>
      <h3 class="pn-title">${esc(caso.expediente)}</h3>
      <p class="pn-sub">${sub.map(esc).join(' · ')}</p>
    </header>
    <dl class="pn-kpis pn-kpis3">
      <div><dt>Inspección</dt><dd>${esc(fmtDateNum(caso.fecha_inspeccion))}</dd></div>
      <div><dt>Decisión</dt><dd class="pn-dd-txt">${esc(caso.decision || '—')}</dd></div>
      <div><dt>Multa</dt><dd class="pn-loss">${fmtNum(caso.multa_utm, 1)} <small>UTM</small></dd></div>
    </dl>
    <figure class="pn-chart">
      <figcaption>Verdor (NDVI) del predio vs. secano · línea = inspección</figcaption>
      <svg viewBox="0 0 560 230" role="img" aria-label="Serie NDVI y NDMI del predio del caso ${esc(caso.expediente)} con la fecha de inspección DGA">${seriesChartSVG(data, caso.predio_id, { W: 560, H: 230, compact: true, marks, highlight: st?.win })}</svg>
      <div class="pn-legend">${chartLegendHTML({ mark: true })}</div>
    </figure>
    <p class="pn-note">${esc(text)}</p>
    ${imgs.length ? `
    <section class="pn-imgs" data-mode="rgb">
      <div class="pn-imgs-h"><span>Sentinel-2 · recorte del predio</span>
        <span class="pn-seg" role="group" aria-label="Tipo de imagen"><button type="button" data-mode="rgb" aria-pressed="true">Color</button><button type="button" data-mode="ndvi" aria-pressed="false">NDVI</button></span>
      </div>
      <div class="pn-img-grid" style="--n:${Math.min(3, imgs.length)}">
        ${imgs.slice(0, 3).map(i => `<figure class="pn-img">
          <div class="pn-img-box">
            ${i.rgb ? `<img class="pn-i-rgb" src="${esc(i.rgb)}" alt="Color natural ${esc(fmtDate(i.fecha))}" loading="lazy">` : ''}
            ${i.ndvi ? `<img class="pn-i-ndvi" src="${esc(i.ndvi)}" alt="NDVI ${esc(fmtDate(i.fecha))}" loading="lazy">` : ''}
            ${outlineSVG(f, i.esquinas)}
          </div>
          <figcaption><b>${esc(IMG_LABEL[i.etiqueta] || i.etiqueta || '')}</b>${esc(fmtDateNum(i.fecha))}</figcaption>
        </figure>`).join('')}
      </div>
    </section>` : ''}
    <div class="pn-actions">
      ${f ? '<button type="button" class="btn primary" data-act="predio">Ver predio</button>' : ''}
      ${f && onExpediente ? '<button type="button" class="btn" data-act="exp">Expediente</button>' : ''}
    </div>
    <p class="pn-foot">${esc(caso.tipo_infraccion || 'Extracción no autorizada de aguas')}${caso.resolucion ? ` · Res. ${esc(caso.resolucion)}` : ''}. Fuente: planilla de fiscalización DGA.</p>`;

  el.onclick = e => {
    const seg = e.target.closest('.pn-seg button');
    if (seg) {
      const box = el.querySelector('.pn-imgs');
      box.dataset.mode = seg.dataset.mode;
      box.querySelectorAll('.pn-seg button').forEach(b => b.setAttribute('aria-pressed', String(b === seg)));
      return;
    }
    const a = e.target.closest('[data-act]')?.dataset.act;
    if (a === 'back') onBack?.();
    else if (a === 'predio') onPredio?.(caso.predio_id);
    else if (a === 'exp') onExpediente?.(caso.predio_id);
  };
  el.scrollTop = 0;
}

/** "Casos (n)" tab: one line per case of the zone. */
export function renderCasosList(el, zonaData, { onSelect, selected } = {}) {
  if (!el) return;
  const casos = (zonaData.casos || []).slice().sort((a, b) => String(b.fecha_inspeccion).localeCompare(String(a.fecha_inspeccion)));
  if (!casos.length) { el.innerHTML = '<p class="pn-note">Sin casos de validación en esta zona.</p>'; return; }
  const total = casos.reduce((a, c) => a + (+c.multa_utm || 0), 0);
  el.innerHTML = `
    <p class="pn-lede">${casos.length} casos resueltos por la DGA · ${fmtNum(total, 0)} UTM en multas.</p>
    <ul class="pn-list">${casos.map(c => {
      const b = c.predio_id ? zonaData.byId.get(c.predio_id)?.properties.banda : null;
      return `<li><button type="button" class="pn-row pn-r-caso${c.expediente === selected ? ' is-sel' : ''}" data-exp="${esc(c.expediente)}" title="${esc(c.expediente)}">
        <span class="pn-row-top"><b class="pn-id">${esc(expShort(c.expediente))}</b><span class="pn-row-c">${esc(fmtComuna(c.comuna))} · ${esc(fmtDateNum(c.fecha_inspeccion))}</span>${b && b !== 'sin_dato' ? `<span class="pn-pill pn-${b}" title="Banda provisional actual del predio">${esc(b === 'sin_alerta' ? 'Sin ind.' : b)}</span>` : ''}<span class="pn-row-meta">${fmtNum(c.multa_utm, 0)} UTM</span></span>
      </button></li>`;
    }).join('')}</ul>
    <p class="pn-foot">Casos ya sancionados: sirven para comprobar si la señal satelital aparecía antes de la inspección.</p>`;
  el.onclick = e => {
    const b = e.target.closest('.pn-row');
    if (b && el.contains(b)) onSelect?.(b.dataset.exp);
  };
}
