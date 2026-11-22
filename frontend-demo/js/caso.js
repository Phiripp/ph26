// Caudal · panel de caso de validación (casos resueltos por la DGA, con multa).
// Un caso sancionado sí se puede nombrar como tal; los predios sin resolver nunca.
import { fmtNum, fmtDate, fmtDateNum, fmtComuna, expShort, dryWindowStats, seriesFailed, SERIES_FAILED_TEXT, esc } from './zona-data.js';
import { mountSeriesChart, mountTimeline, chartLegendHTML, historialLegendHTML, seasonStart } from './chart.js';
import { mountExplicacion } from './explicacion.js';

/**
 * Valor UTM para pasar la multa a pesos: impacto.json -> supuestos.utm_clp (scripts/models/impacto.py).
 * Mientras no llega, la multa se muestra solo en UTM.
 */
const UTM_FUENTE = 'supuesto de impacto.json';
let utmClp = NaN;

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
  if (id && seriesFailed(data, id)) return { st: null, text: SERIES_FAILED_TEXT };
  if (!id || !data.series?.predios?.[id]?.length) return { st: null, text: 'Sin serie satelital para este predio antes de la inspección.' };
  const st = dryWindowStats(data, id, { before: caso.fecha_inspeccion, months: 14 });
  if (!st) return { st: null, text: 'La serie no cubre una ventana seca anterior a la inspección.' };
  const diff = st.ndvi - st.refNdvi;
  const lead = diff >= 0.1 ? 'Antes de la inspección ya se veía riego sin lluvia' : diff >= 0.03 ? 'Antes de la inspección había una señal débil' : 'Antes de la inspección la señal no destacaba';
  return { st, text: `${lead}: ${fmtDate(st.win.inicio)}–${fmtDate(st.win.fin)}, NDVI ${fmtNum(st.ndvi, 2)} vs. ${fmtNum(st.refNdvi, 2)} del secano.` };
}

/* ---------- banda por temporada + adelanto (F4) ---------- */
const CSS_ID = 'caso-tl-css';
function ensureCSS() {
  if (document.getElementById(CSS_ID)) return;
  const st = document.createElement('style');
  st.id = CSS_ID;
  st.textContent = `
.cs-adel{margin:14px 0 0;padding:10px 12px;border-left:3px solid var(--crit);background:color-mix(in srgb,var(--crit) 8%,transparent);font:500 13.5px/1.45 var(--f-body);color:var(--ink)}
.cs-adel b{font-family:var(--f-mono);font-weight:600;font-variant-numeric:tabular-nums}
.cs-adel small{display:block;margin-top:4px;font:12px/1.4 var(--f-body);color:var(--dim)}
.cs-adel.is-no{border-left-color:var(--rule-2);background:none;color:var(--dim);font-weight:400}
.cs-tl{margin:10px 0 0}
.cs-tl figcaption{font:10px var(--f-mono);letter-spacing:.08em;text-transform:uppercase;color:var(--dim);margin-bottom:2px}
.cs-tl svg{display:block;width:100%;height:auto}
.cs-tl .pn-legend{margin-top:2px}
.pn-kpis dd small.cs-clp{display:block;margin-top:3px;font:11px var(--f-mono);color:var(--dim)}`;
  document.head.appendChild(st);
}

/** Season rows of a case predio, sorted. Accepts {predios:{id:[…]}} or {id:[…]} and rows as array or {temporada:{…}}. */
export function historialOf(data, id) {
  const h = data?.historial;
  if (!h || id == null) return null;
  let rows = h.predios?.[id] ?? h[id] ?? h.predios?.[String(id)] ?? h[String(id)];
  if (!rows) return null;
  if (!Array.isArray(rows)) rows = Object.entries(rows).map(([temporada, v]) => ({ temporada, ...v }));
  rows = rows.filter(r => r && r.temporada).slice().sort((a, b) => String(a.temporada).localeCompare(String(b.temporada)));
  return rows.length ? rows : null;
}

/**
 * historial.json of the zone, if the loader did not bring it (T1 may expose it as data.historial).
 * Fetched once per zone; null when the file does not exist. Never rejects.
 */
function loadHistorial(data) {
  if (data.historial !== undefined) return Promise.resolve(data.historial);
  if (!data.base) return Promise.resolve(null);
  data._historialP ??= fetch(data.base + 'historial.json')
    .then(r => (r.ok ? r.json() : null)).catch(() => null)
    .then(j => { if (data.historial === undefined) data.historial = j; return data.historial; });
  return data._historialP;
}

/** m³ over the right between first alert and inspection (casos.json m3_antes_inspeccion): number or {min, central, max}. */
function m3AntesText(v) {
  if (v == null) return '';
  const o = typeof v === 'object' ? v : { central: +v };
  const lo = o.min ?? o.m3_exceso_min, hi = o.max ?? o.m3_exceso_max ?? o.central ?? o.m3_exceso_central;
  const mil = x => fmtNum(x / 1000, x >= 100000 ? 0 : 1);
  if (lo != null && hi != null && +hi > 0) return `Entre la primera alerta y la inspección, Caudales estima ${mil(+lo)} a ${mil(+hi)} mil m³ extraídos sobre el derecho.`;
  if (hi != null && +hi > 0) return `Entre la primera alerta y la inspección, Caudales estima unos ${mil(+hi)} mil m³ extraídos sobre el derecho (estimación central).`;
  return '';
}

/** keeps "2019-20" and dates on one line */
const nb = s => esc(s).replace(/-/g, '\u2011');
const BAND_RANK = { alta: 3, media: 2, baja: 1, sin_alerta: 0 };
const BAND_TXT = { media: 'media', baja: 'baja' };

/**
 * Highlighted sentence. Positive claim only from casos.json (primera_alerta / anos_adelanto, impacto.py adelanto()).
 * When the historial shows no "alta" season before the inspection, say so plainly. Otherwise, no claim.
 */
function adelantoHTML(caso, rows) {
  const insp = caso.fecha_inspeccion;
  if (!insp) return '';
  const pa = caso.primera_alerta, anos = caso.anos_adelanto == null ? null : +caso.anos_adelanto;
  if (pa && Number.isFinite(anos) && anos > 0) {
    // the series starts in 2019-20: an alert in the first season is a lower bound ("al menos")
    const censurado = caso.censurado ?? (rows?.length ? pa === rows[0].temporada : pa === '2019-20');
    const m3 = m3AntesText(caso.m3_antes_inspeccion);
    return `<p class="cs-adel">Caudales: alerta alta desde <b>${nb(pa)}</b> · Inspección DGA: <b>${nb(fmtDateNum(insp))}</b> · ${censurado ? 'al menos ' : ''}<b>${fmtNum(anos, 1)} años</b> antes${m3 ? `<small>${esc(m3)}</small>` : ''}</p>`;
  }
  const prev = (rows || []).filter(r => seasonStart(r.temporada) < String(insp).slice(0, 10));
  if (!prev.length || prev.some(r => r.banda === 'alta')) return '';
  const best = prev.reduce((a, r) => ((BAND_RANK[r.banda] ?? 0) > (BAND_RANK[a.banda] ?? 0) ? r : a), prev[0]);
  const max = BAND_TXT[best.banda] ? ` Lo más alto antes de la inspección fue banda ${BAND_TXT[best.banda]} en ${nb(best.temporada)}.` : '';
  const span = prev.length > 1 ? `temporadas ${nb(prev[0].temporada)} a ${nb(prev[prev.length - 1].temporada)}` : `temporada ${nb(prev[0].temporada)}`;
  return `<p class="cs-adel is-no">Caudales no tenía este predio en alerta alta antes de la inspección (${span}).${max} Este caso no cuenta como detección anticipada.</p>`;
}

function timelineHTML(caso, rows) {
  if (!rows) return '';
  return `<figure class="cs-tl">
      <figcaption>Banda de Caudales por temporada</figcaption>
      <svg data-timeline viewBox="0 0 380 64" role="img" aria-label="Banda de prioridad de Caudales por temporada para el predio del caso ${esc(caso.expediente)}, con la fecha de inspección DGA"></svg>
      <div class="pn-legend">${historialLegendHTML(rows)}</div>
    </figure>`;
}

/** "$143,7 millones" */
function fmtClp(v) {
  if (!Number.isFinite(v)) return '—';
  return v >= 1e6 ? `$${fmtNum(v / 1e6, 1)} millones` : `$${fmtNum(v, 0)}`;
}

export function renderCaso(el, caso, zonaData, { onPredio, onExpediente, onBack } = {}) {
  if (!el || !caso) return;
  ensureCSS();
  const data = zonaData;
  const rows = historialOf(data, caso.predio_id);
  const multaClp = Number.isFinite(+caso.multa_utm) && caso.multa_utm != null ? +caso.multa_utm * utmClp : NaN;
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
      <div><dt>Multa</dt><dd class="pn-loss">${fmtNum(caso.multa_utm, 1)} <small>UTM</small><small class="cs-clp" data-clp>${Number.isFinite(multaClp) ? "≈ " + esc(fmtClp(multaClp)) : ""}</small></dd></div>
    </dl>
    <div class="cs-hist" data-hist>${adelantoHTML(caso, rows)}${timelineHTML(caso, rows)}</div>
    <figure class="pn-chart">
      <figcaption>Verdor (NDVI) del predio vs. secano · línea = inspección</figcaption>
      <svg data-series viewBox="0 0 560 230" role="img" aria-label="Serie NDVI y NDMI del predio del caso ${esc(caso.expediente)} con la fecha de inspección DGA"></svg>
      <div class="pn-legend">${chartLegendHTML({ mark: true })}</div>
    </figure>
    <p class="pn-note">${esc(text)}</p>
    <section class="pn-why" data-why></section>
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
    <p class="pn-foot">${esc(caso.tipo_infraccion || 'Extracción no autorizada de aguas')}${caso.resolucion ? ` · Res. ${esc(caso.resolucion)}` : ''}. Fuente: planilla de fiscalización DGA. <span data-utm>${Number.isFinite(utmClp) ? "Multa en pesos con UTM a $" + fmtNum(utmClp, 0) + " (" + UTM_FUENTE + ")." : ""}</span> Banda por temporada: puntaje de Caudales (M5).</p>`;

  mountSeriesChart(el.querySelector('svg[data-series]'), data, caso.predio_id, { W: 560, H: 230, compact: true, marks, highlight: st?.win });
  // Lo que Caudal veía con los datos previos a la inspección (misma explicación de la ficha y del PDF)
  mountExplicacion(el.querySelector('[data-why]'), `/api/casos/${encodeURIComponent(caso.expediente)}`,
    { titulo: x => `Qué veía Caudales antes de la inspección (temporada ${x.temporada})`, datoAl: false });
  const mountTl = r => mountTimeline(el.querySelector('svg[data-timeline]'), r, { fecha: caso.fecha_inspeccion });
  if (rows) mountTl(rows);
  // Late data, filled in place while this case is still on screen: historial.json and the UTM value of impacto.json.
  const still = () => el.isConnected && el.querySelector('[data-hist]') && el.dataset.caso === caso.expediente;
  el.dataset.caso = caso.expediente;
  if (!rows && caso.predio_id) {
    loadHistorial(data).then(() => {
      const r = historialOf(data, caso.predio_id);
      if (r && still()) { el.querySelector('[data-hist]').innerHTML = adelantoHTML(caso, r) + timelineHTML(caso, r); mountTl(r); }
    });
  }
  import('./zona-data.js').then(Z => (typeof Z.loadImpacto === 'function' ? Z.loadImpacto() : null)).catch(() => null).then(imp => {
    const v = +imp?.supuestos?.utm_clp;
    if (!Number.isFinite(v) || v <= 0 || v === utmClp) return;
    utmClp = v;
    if (!still()) return;
    const clp = el.querySelector('[data-clp]'), u = el.querySelector('[data-utm]');
    if (clp && Number.isFinite(+caso.multa_utm)) clp.textContent = `≈ ${fmtClp(+caso.multa_utm * v)}`;
    if (u) u.textContent = `Multa en pesos con UTM a $${fmtNum(v, 0)} (${UTM_FUENTE}).`;
  });

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
        <span class="pn-row-top"><b class="pn-id">${esc(expShort(c.expediente))}</b><span class="pn-row-c">${esc(fmtComuna(c.comuna))} · ${esc(fmtDateNum(c.fecha_inspeccion))}</span>${b && b !== 'sin_dato' ? `<span class="pn-pill pn-${b}" title="Banda actual de Caudales para el predio (temporada 2025-26)">${esc(b === 'sin_alerta' ? 'Sin ind.' : b)}</span>` : ''}<span class="pn-row-meta">${fmtNum(c.multa_utm, 0)} UTM</span></span>
      </button></li>`;
    }).join('')}</ul>
    <p class="pn-foot">Casos ya sancionados: sirven para comprobar si la señal satelital aparecía antes de la inspección.</p>`;
  el.onclick = e => {
    const b = e.target.closest('.pn-row');
    if (b && el.contains(b)) onSelect?.(b.dataset.exp);
  };
}
