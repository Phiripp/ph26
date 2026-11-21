// Caudal · real Petorca index chart (Sentinel-2 NDVI/NDMI vs secano reference, dry windows shaded).
import { loadPetorca, fmtNum, fmtDate, dryWindowStats } from './petorca-data.js';

const T0 = 2022, NM = 36;
const tOfMonth = ym => { const [y, m] = ym.split('-').map(Number); return (y - T0) * 12 + (m - 1) + 0.5; };
function tOfDay(iso, end) {
  const [y, m, d] = iso.split('-').map(Number);
  const dim = new Date(y, m, 0).getDate();
  return (y - T0) * 12 + (m - 1) + (d - (end ? 0 : 1)) / dim;
}

/**
 * Builds the inner markup of an SVG chart for one predio.
 * opts: {W, H, ndmi:true, label:true, compact:false, idPrefix}
 */
export function seriesChartSVG(data, id, opts = {}) {
  const { W = 960, H = 300, ndmi = true, compact = false } = opts;
  const pl = compact ? 34 : 44, pr = compact ? 8 : 18, pt = compact ? 12 : 22, pb = compact ? 24 : 34;
  const vmin = ndmi ? -0.3 : 0, vmax = 0.9;
  const X = t => pl + (t / NM) * (W - pl - pr);
  const Y = v => pt + (1 - (v - vmin) / (vmax - vmin)) * (H - pt - pb);
  const own = data.series.predios[id] || [];
  const ref = data.series.referencia_secano?.serie || [];
  const path = (rows, k) => {
    let d = '', pen = false;
    for (const r of rows) {
      if (r[k] == null) { pen = false; continue; }
      d += (pen ? 'L' : 'M') + X(tOfMonth(r.fecha)).toFixed(1) + ' ' + Y(r[k]).toFixed(1);
      pen = true;
    }
    return d;
  };
  let s = '';
  // dry windows
  for (const w of (data.clima.ventanas_secas || []).filter(w => w.dias >= 10)) {
    const a = Math.max(0, tOfDay(w.inicio)), b = Math.min(NM, tOfDay(w.fin, true));
    if (b <= a) continue;
    s += `<rect class="pc-dry" x="${X(a).toFixed(1)}" y="${pt}" width="${(X(b) - X(a)).toFixed(1)}" height="${H - pt - pb}"><title>Ventana seca ${fmtDate(w.inicio)} – ${fmtDate(w.fin)} (${w.dias} días)</title></rect>`;
  }
  const ticks = ndmi ? [-0.2, 0, 0.2, 0.4, 0.6, 0.8] : [0, 0.2, 0.4, 0.6, 0.8];
  for (const v of ticks) {
    s += `<line class="c-grid${v === 0 ? ' pc-zero' : ''}" x1="${pl}" x2="${W - pr}" y1="${Y(v).toFixed(1)}" y2="${Y(v).toFixed(1)}"/>`;
    s += `<text class="c-axis" x="${pl - 6}" y="${(Y(v) + 4).toFixed(1)}" text-anchor="end">${fmtNum(v, 1)}</text>`;
  }
  for (let y = 0; y < 3; y++) {
    s += `<line class="c-grid" x1="${X(y * 12)}" x2="${X(y * 12)}" y1="${pt}" y2="${H - pb}"/>`;
    s += `<text class="c-axis" x="${X(y * 12 + 6)}" y="${H - (compact ? 7 : 10)}" text-anchor="middle">${T0 + y}</text>`;
  }
  s += `<path class="pc-ref" d="${path(ref, 'ndvi')}"/>`;
  if (ndmi) s += `<path class="pc-ref pc-dash" d="${path(ref, 'ndmi')}"/>`;
  if (ndmi) s += `<path class="pc-ndmi" d="${path(own, 'ndmi')}"/>`;
  s += `<path class="pc-ndvi" d="${path(own, 'ndvi')}"/>`;
  return s;
}

export function chartLegendHTML({ ndmi = true } = {}) {
  return `<span class="pc-key"><i class="k-ndvi"></i>NDVI predio</span>` +
    (ndmi ? `<span class="pc-key"><i class="k-ndmi"></i>NDMI predio</span>` : '') +
    `<span class="pc-key"><i class="k-ref"></i>Secano de referencia${ndmi ? ' (NDVI / NDMI)' : ''}</span>` +
    `<span class="pc-key"><i class="k-dry"></i>Ventana seca (≥10 días sin lluvia)</span>`;
}

/** Landing "Cómo funciona" chart: top alta predio vs secano reference. */
export async function renderChart(svgEl, calloutEl) {
  if (!svgEl) return null;
  try {
    const data = await loadPetorca();
    const top = data.predios.filter(f => f.properties.banda === 'alta')
      .sort((a, b) => b.properties.indice - a.properties.indice)[0];
    if (!top) return null;
    const id = top.properties.id;
    svgEl.setAttribute('viewBox', '0 0 960 300');
    svgEl.setAttribute('aria-label', `NDVI mensual Sentinel-2 del predio ${id} frente a vegetación de secano, Valle de Petorca 2022–2024`);
    svgEl.innerHTML = seriesChartSVG(data, id, { W: 960, H: 300, ndmi: false });

    // Update the figure caption in place if the page still has the old one.
    const fig = svgEl.closest('figure');
    const cap = fig?.querySelector('figcaption');
    if (cap) {
      cap.innerHTML = `<span>Valle de Petorca · predio ${id} · NDVI mensual · Sentinel-2 L2A (Element84) · Open-Meteo ERA5</span>` +
        `<span class="keys pc-legend">${chartLegendHTML({ ndmi: false })}</span>`;
    }
    fig?.classList.add('in');

    const st = dryWindowStats(data, id, 2024);
    if (calloutEl && st) {
      calloutEl.innerHTML = `Verde en ventana seca = <strong>riego probable</strong>. Entre ${fmtDate(st.win.inicio)} y ${fmtDate(st.win.fin)} no llovió (${st.win.dias} días); el predio ${id} se mantuvo en NDVI ${fmtNum(st.ndvi, 2)} mientras el secano vecino marcaba ${fmtNum(st.refNdvi, 2)}. Es un indicio para priorizar la inspección, no una prueba.`;
    }
    return { id };
  } catch (err) {
    console.error('[Caudal] chart:', err);
    return null;
  }
}
