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
  const own0 = data.series?.predios?.[id] || [];
  // per-scene series (build_m5_web.py) only cover the Dec–Mar seasons: draw one column per season
  if (own0.some(r => String(r.fecha).length > 7)) return seasonSeriesSVG(data, id, opts);
  const { W = 960, H = 300, ndmi = true, compact = false, marks = [], highlight = null } = opts;
  const own = own0;
  // per-scene rows (build_m5_web.py) carry the predio's own secano reference (ref_ndvi / ref_ndmi); else the zone median
  const ownRef = own.some(r => r.ref_ndvi != null) ? own.map(r => ({ fecha: r.fecha, ndvi: r.ref_ndvi ?? null, ndmi: r.ref_ndmi ?? null })) : null;
  const ref = ownRef || data.series?.referencia_secano?.serie || [];
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
  // rows are monthly ('2024-01') or per scene ('2024-01-17'); a scene sits on its day
  const tOf = f => (String(f).length > 7 ? tOfDay(f) + 0.5 / 30 : tOfMonth(f));
  // monthly: gaps up to 2 months are bridged (cloudy months). Per scene: gaps over ~6 weeks (outside the
  // Dec–Mar seasons that were measured) break the line, so nothing is drawn where there is no data.
  const path = (rows, k) => {
    let d = '', last = null;
    for (const r of rows) {
      if (r[k] == null) continue;
      const t = tOf(r.fecha), maxGap = String(r.fecha).length > 7 ? 1.5 : 3;
      d += (last != null && t - last <= maxGap ? 'L' : 'M') + X(t).toFixed(1) + ' ' + Y(r[k]).toFixed(1);
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

/* ---------- per-scene series by season (Dec 1 – Apr 1), one column per season ---------- */
const seasonKey = iso => { const [y, m] = String(iso).split('-').map(Number); return m >= 7 ? y : y - 1; };
const seasonLabel = y => `${y}-${String((y + 1) % 100).padStart(2, '0')}`;

/**
 * Same chart for per-scene rows {fecha:'2024-01-17', ndvi, ndmi, ref_ndvi, ref_ndmi, senal}: the time axis keeps only
 * the measured seasons (Dec–Mar), side by side, so the months without data take no room. Dates outside a season
 * (an inspection in November, say) sit in the gap between the two neighbouring columns.
 */
function seasonSeriesSVG(data, id, opts = {}) {
  const { W = 960, H = 300, ndmi = true, compact = false, marks = [], highlight = null } = opts;
  const own = data.series?.predios?.[id] || [];
  const ref = own.map(r => ({ fecha: r.fecha, ndvi: r.ref_ndvi ?? null, ndmi: r.ref_ndmi ?? null }));
  const keys = [...new Set(own.map(r => seasonKey(r.fecha)))].sort((a, b) => a - b);
  const pl = compact ? 34 : 44, pr = compact ? 8 : 18, pt = compact ? 14 : 22, pb = compact ? 24 : 34;
  const gap = compact ? 8 : 12;
  const n = keys.length, cw = (W - pl - pr - gap * (n - 1)) / n;
  const vmin = ndmi ? -0.3 : 0, vmax = 0.9;
  const Y = v => pt + (1 - (Math.max(vmin, Math.min(vmax, v)) - vmin) / (vmax - vmin)) * (H - pt - pb);
  const win = k => [dayNum(`${k}-12-01`), dayNum(`${k + 1}-04-01`)];
  const colX = i => pl + i * (cw + gap);
  /** x of a date: inside a column, proportional; between columns, centre of the gap; clamped at both ends. */
  const X = iso => {
    const t = dayNum(iso);
    for (let i = 0; i < n; i++) {
      const [a, b] = win(keys[i]);
      if (t < a) return i === 0 ? colX(0) : colX(i) - gap / 2;
      if (t < b) return colX(i) + ((t - a) / (b - a)) * cw;
    }
    return colX(n - 1) + cw;
  };
  const path = (rows, k) => {
    let d = '', lastKey = null;
    for (const r of rows) {
      if (r[k] == null) continue;
      const key = seasonKey(r.fecha);
      d += (key === lastKey ? 'L' : 'M') + X(r.fecha).toFixed(1) + ' ' + Y(r[k]).toFixed(1);
      lastKey = key;
    }
    return d;
  };
  let s = '';
  // dry windows, clipped to each column
  for (const w of (data.clima?.ventanas_secas || []).filter(w => w.inicio && w.fin && (w.dias ?? 10) >= 10)) {
    const hi = highlight && w.inicio === highlight.inicio && w.fin === highlight.fin;
    const w0 = dayNum(w.inicio), w1 = dayNum(w.fin) + 1;
    keys.forEach((k, i) => {
      const [a, b] = win(k), lo = Math.max(a, w0), up = Math.min(b, w1);
      if (up <= lo) return;
      const x0 = colX(i) + ((lo - a) / (b - a)) * cw, x1 = colX(i) + ((up - a) / (b - a)) * cw;
      s += `<rect class="pc-dry${hi ? ' pc-dry-hi' : ''}" x="${x0.toFixed(1)}" y="${pt}" width="${(x1 - x0).toFixed(1)}" height="${H - pt - pb}"><title>Ventana seca ${fmtDate(w.inicio)} – ${fmtDate(w.fin)}${w.dias ? ` (${w.dias} días)` : ''}</title></rect>`;
    });
  }
  const ticks = ndmi ? [-0.2, 0, 0.2, 0.4, 0.6, 0.8] : [0, 0.2, 0.4, 0.6, 0.8];
  for (const v of ticks) {
    keys.forEach((k, i) => { s += `<line class="c-grid${v === 0 ? ' pc-zero' : ''}" x1="${colX(i).toFixed(1)}" x2="${(colX(i) + cw).toFixed(1)}" y1="${Y(v).toFixed(1)}" y2="${Y(v).toFixed(1)}"/>`; });
    s += `<text class="c-axis" x="${pl - 6}" y="${(Y(v) + 4).toFixed(1)}" text-anchor="end">${fmtNum(v, 1)}</text>`;
  }
  keys.forEach((k, i) => {
    s += `<line class="c-grid" x1="${colX(i).toFixed(1)}" x2="${colX(i).toFixed(1)}" y1="${pt}" y2="${H - pb}"/><line class="c-grid" x1="${(colX(i) + cw).toFixed(1)}" x2="${(colX(i) + cw).toFixed(1)}" y1="${pt}" y2="${H - pb}"/>`;
    const lab = compact && n > 5 ? `’${String(k).slice(2)}-${String((k + 1) % 100).padStart(2, '0')}` : seasonLabel(k);
    s += `<text class="c-axis" x="${(colX(i) + cw / 2).toFixed(1)}" y="${H - (compact ? 7 : 10)}" text-anchor="middle">${lab}</text>`;
  });
  s += `<path class="pc-ref" d="${path(ref, 'ndvi')}"/>`;
  if (ndmi) s += `<path class="pc-ref pc-dash" d="${path(ref, 'ndmi')}"/>`;
  if (ndmi) s += `<path class="pc-ndmi" d="${path(own, 'ndmi')}"/>`;
  s += `<path class="pc-ndvi" d="${path(own, 'ndvi')}"/>`;
  for (const mk of marks) {
    if (!mk?.fecha) continue;
    const x = X(mk.fecha), right = x > W * 0.72;
    s += `<g class="pc-mark"><line x1="${x.toFixed(1)}" x2="${x.toFixed(1)}" y1="${pt - 4}" y2="${H - pb}"/>` +
      `<text x="${(x + (right ? -4 : 4)).toFixed(1)}" y="${pt + 6}" text-anchor="${right ? 'end' : 'start'}">${mk.label || 'Inspección'} ${fmtDateNum(mk.fecha)}</text>` +
      `<title>${mk.label || 'Inspección'} ${fmtDate(mk.fecha)}</title></g>`;
  }
  return s;
}

/* ---------- per-season band timeline (historial.json <- puntaje_validacion.parquet) ---------- */
const TL_COLOR = { alta: 'var(--crit)', media: 'var(--loss)', baja: 'var(--water)', sin_alerta: 'var(--rule-2)' };
const TL_LABEL = { alta: 'Alta', media: 'Media', baja: 'Baja', sin_alerta: 'Sin alerta' };
/** Season "2019-20" starts on 2019-12-01 (same convention as scripts/models/impacto.py, adelanto()). */
export const seasonStart = t => `${String(t).slice(0, 4)}-12-01`;
const dayNum = iso => { const [y, m, d] = String(iso).slice(0, 10).split('-').map(Number); return Date.UTC(y, m - 1, d || 1) / 864e5; };

/**
 * Inner SVG markup: one cell per season coloured by Caudal's band, and a vertical line on the inspection date.
 * rows: [{temporada:'2019-20', banda, puntaje, m3_exceso_min, m3_exceso_max}] sorted by season.
 * opts: {W, H, fecha:'2021-11-23', label:'Inspección DGA'}. Static: nothing animates.
 */
export function historialTimelineSVG(rows, opts = {}) {
  const { W = 560, fecha = null, label = 'Inspección DGA' } = opts;
  if (!rows?.length) return '';
  const pl = 4, pr = 4, pt = 20, cellH = 24, gap = 2;
  const n = rows.length, cw = (W - pl - pr) / n;
  const t0 = dayNum(seasonStart(rows[0].temporada));
  const X = iso => pl + ((dayNum(iso) - t0) / 365.25) * cw; // one season = one year from its start
  let s = '';
  rows.forEach((r, i) => {
    const x = pl + i * cw, b = TL_COLOR[r.banda] ? r.banda : 'sin_alerta';
    const tip = [`Temporada ${r.temporada}`, `banda ${TL_LABEL[b].toLowerCase()}`,
      r.puntaje != null ? `puntaje ${fmtNum(r.puntaje, 1)}` : null,
      r.m3_exceso_min != null && r.m3_exceso_max != null && r.m3_exceso_max > 0 ? `exceso estimado ${fmtNum(r.m3_exceso_min / 1000, 0)}–${fmtNum(r.m3_exceso_max / 1000, 0)} mil m³` : null].filter(Boolean).join(' · ');
    s += `<rect x="${(x + gap / 2).toFixed(1)}" y="${pt}" width="${(cw - gap).toFixed(1)}" height="${cellH}" style="fill:${TL_COLOR[b]};fill-opacity:${b === 'sin_alerta' ? 1 : 0.85}"><title>${tip}</title></rect>` +
      `<text class="c-axis" x="${(x + cw / 2).toFixed(1)}" y="${pt + cellH + 14}" text-anchor="middle">${r.temporada}</text>`;
  });
  if (fecha) {
    const x = Math.max(pl, Math.min(pl + n * cw, X(fecha)));
    const right = x > W * 0.6;
    s += `<g class="pc-mark"><line x1="${x.toFixed(1)}" x2="${x.toFixed(1)}" y1="${pt - 16}" y2="${pt + cellH + 3}"/>` +
      `<text x="${(x + (right ? -5 : 5)).toFixed(1)}" y="${pt - 7}" text-anchor="${right ? 'end' : 'start'}">${label} ${fmtDateNum(fecha)}</text>` +
      `<title>${label} ${fmtDate(fecha)}</title></g>`;
  }
  return s;
}

/** Legend of the timeline: only the bands that appear, plus the inspection line. */
export function historialLegendHTML(rows) {
  const seen = new Set((rows || []).map(r => (TL_COLOR[r.banda] ? r.banda : 'sin_alerta')));
  return ['alta', 'media', 'baja', 'sin_alerta'].filter(b => seen.has(b))
    .map(b => `<span class="pc-key"><i style="background:${TL_COLOR[b]};height:9px;width:12px"></i>${TL_LABEL[b]}</span>`).join('') +
    `<span class="pc-key"><i class="k-mark"></i>Inspección DGA</span>`;
}

export function chartLegendHTML({ ndmi = true, mark = false } = {}) {
  return `<span class="pc-key"><i class="k-ndvi"></i>NDVI predio</span>` +
    (ndmi ? `<span class="pc-key"><i class="k-ndmi"></i>NDMI</span>` : '') +
    `<span class="pc-key"><i class="k-ref"></i>Secano</span>` +
    `<span class="pc-key"><i class="k-dry"></i>Sin lluvia ≥10 días</span>` +
    (mark ? `<span class="pc-key"><i class="k-mark"></i>Inspección DGA</span>` : '');
}
