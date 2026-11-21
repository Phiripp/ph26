// Caudal · index chart (Sentinel-2 NDVI/NDMI vs secano reference, dry windows shaded, optional inspection line).
import { fmtNum, fmtDate, fmtDateNum, fmtComuna, dryWindowStats, seriesFailed } from './zona-data.js';

const ymOf = s => { const [y, m] = String(s).split('-').map(Number); return { y, m }; };

/** Time frame covering the series (whole calendar years), extended to include any mark dates. */
function frame(rows, marks) {
  let y0 = Infinity, y1 = -Infinity;
  for (const r of rows) { const { y } = ymOf(r.fecha); if (y < y0) y0 = y; if (y > y1) y1 = y; }
  for (const mk of marks) { const { y } = ymOf(mk.fecha); if (y < y0) y0 = y; if (y > y1) y1 = y; }
  if (!Number.isFinite(y0)) { y0 = 2022; y1 = 2024; }
  return { T0: y0, NM: (y1 - y0 + 1) * 12 };
}

/**
 * Builds the inner markup of an SVG chart for one predio.
 * opts: {W, H, ndmi:true, compact:false, marks:[{fecha:'2024-04-02', label:'Inspección DGA'}], highlight:{inicio, fin}}
 */
export function seriesChartSVG(data, id, opts = {}) {
  const { W = 960, H = 300, ndmi = true, compact = false, marks = [], highlight = null } = opts;
  const own = data.series?.predios?.[id] || [];
  const ref = data.series?.referencia_secano?.serie || [];
  const { T0, NM } = frame([...own, ...ref], marks);
  const tOfMonth = ym => { const { y, m } = ymOf(ym); return (y - T0) * 12 + (m - 1) + 0.5; };
  const tOfDay = (iso, end) => {
    const [y, m, d] = String(iso).slice(0, 10).split('-').map(Number);
    const dim = new Date(y, m, 0).getDate();
    return (y - T0) * 12 + (m - 1) + (d - (end ? 0 : 1)) / dim;
  };
  const pl = compact ? 34 : 44, pr = compact ? 8 : 18, pt = compact ? 14 : 22, pb = compact ? 24 : 34;
  const vmin = ndmi ? -0.3 : 0, vmax = 0.9;
  const X = t => pl + (t / NM) * (W - pl - pr);
  const Y = v => pt + (1 - (Math.max(vmin, Math.min(vmax, v)) - vmin) / (vmax - vmin)) * (H - pt - pb);
  // gaps up to 2 months are bridged (cloudy months); longer gaps break the line
  const path = (rows, k) => {
    let d = '', last = null;
    for (const r of rows) {
      if (r[k] == null) continue;
      const t = tOfMonth(r.fecha);
      d += (last != null && t - last <= 3 ? 'L' : 'M') + X(t).toFixed(1) + ' ' + Y(r[k]).toFixed(1);
      last = t;
    }
    return d;
  };
  let s = '';
  for (const w of (data.clima?.ventanas_secas || []).filter(w => w.inicio && w.fin && (w.dias ?? 10) >= 10)) {
    const a = Math.max(0, tOfDay(w.inicio)), b = Math.min(NM, tOfDay(w.fin, true));
    if (b <= a) continue;
    const hi = highlight && w.inicio === highlight.inicio && w.fin === highlight.fin;
    s += `<rect class="pc-dry${hi ? ' pc-dry-hi' : ''}" x="${X(a).toFixed(1)}" y="${pt}" width="${(X(b) - X(a)).toFixed(1)}" height="${H - pt - pb}"><title>Ventana seca ${fmtDate(w.inicio)} – ${fmtDate(w.fin)}${w.dias ? ` (${w.dias} días)` : ''}</title></rect>`;
  }
  const ticks = ndmi ? [-0.2, 0, 0.2, 0.4, 0.6, 0.8] : [0, 0.2, 0.4, 0.6, 0.8];
  for (const v of ticks) {
    s += `<line class="c-grid${v === 0 ? ' pc-zero' : ''}" x1="${pl}" x2="${W - pr}" y1="${Y(v).toFixed(1)}" y2="${Y(v).toFixed(1)}"/>`;
    s += `<text class="c-axis" x="${pl - 6}" y="${(Y(v) + 4).toFixed(1)}" text-anchor="end">${fmtNum(v, 1)}</text>`;
  }
  const years = NM / 12;
  for (let y = 0; y < years; y++) {
    s += `<line class="c-grid" x1="${X(y * 12)}" x2="${X(y * 12)}" y1="${pt}" y2="${H - pb}"/>`;
    const lab = years > 6 && compact ? `’${String(T0 + y).slice(2)}` : T0 + y;
    s += `<text class="c-axis" x="${X(y * 12 + 6)}" y="${H - (compact ? 7 : 10)}" text-anchor="middle">${lab}</text>`;
  }
  s += `<path class="pc-ref" d="${path(ref, 'ndvi')}"/>`;
  if (ndmi) s += `<path class="pc-ref pc-dash" d="${path(ref, 'ndmi')}"/>`;
  if (ndmi) s += `<path class="pc-ndmi" d="${path(own, 'ndmi')}"/>`;
  s += `<path class="pc-ndvi" d="${path(own, 'ndvi')}"/>`;
  for (const mk of marks) {
    if (!mk?.fecha) continue;
    const t = tOfDay(mk.fecha), x = X(t).toFixed(1);
    const right = t > NM * 0.72;
    s += `<g class="pc-mark"><line x1="${x}" x2="${x}" y1="${pt - 4}" y2="${H - pb}"/>` +
      `<text x="${(+x + (right ? -4 : 4)).toFixed(1)}" y="${pt + 6}" text-anchor="${right ? 'end' : 'start'}">${mk.label || 'Inspección'} ${fmtDateNum(mk.fecha)}</text>` +
      `<title>${mk.label || 'Inspección'} ${fmtDate(mk.fecha)}</title></g>`;
  }
  if (!own.length) s += `<text class="pc-empty" x="${(W / 2).toFixed(0)}" y="${(H / 2).toFixed(0)}" text-anchor="middle">${seriesFailed(data, id) ? 'No se pudo cargar la serie · vuelve a abrir el predio' : 'Sin serie satelital para este predio'}</text>`;
  return s;
}

export function chartLegendHTML({ ndmi = true, mark = false } = {}) {
  return `<span class="pc-key"><i class="k-ndvi"></i>NDVI predio</span>` +
    (ndmi ? `<span class="pc-key"><i class="k-ndmi"></i>NDMI</span>` : '') +
    `<span class="pc-key"><i class="k-ref"></i>Secano</span>` +
    `<span class="pc-key"><i class="k-dry"></i>Sin lluvia ≥10 días</span>` +
    (mark ? `<span class="pc-key"><i class="k-mark"></i>Inspección DGA</span>` : '');
}
