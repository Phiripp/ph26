// Caudal · Petorca valley data loader + shared formatting helpers.
// Principle: "el sistema prioriza, no acusa" — IDs only, ranges only.

const cache = new Map();

async function getJSON(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`[Caudal] ${url}: HTTP ${r.status}`);
  return r.json();
}

export function loadPetorca(base = 'data/petorca/') {
  if (!base.endsWith('/')) base += '/';
  if (cache.has(base)) return cache.get(base);
  const p = (async () => {
    const [geo, series, clima, ruta] = await Promise.all([
      getJSON(base + 'predios.geojson'),
      getJSON(base + 'series.json'),
      getJSON(base + 'clima.json'),
      getJSON(base + 'ruta.json'),
    ]);
    const predios = geo.features || [];
    const byId = new Map(predios.map(f => [f.properties.id, f]));
    const counts = { alta: 0, media: 0, baja: 0, sin_alerta: 0 };
    for (const f of predios) {
      const b = f.properties.banda;
      if (b in counts) counts[b]++;
    }
    return { base, predios, byId, series, clima, ruta, counts, gpxUrl: base + 'ruta.gpx' };
  })();
  p.catch(() => cache.delete(base));
  cache.set(base, p);
  return p;
}

/* ---------- formatting ---------- */
export const BANDS = ['alta', 'media', 'baja', 'sin_alerta'];
export const BAND_LABEL = { alta: 'Prioridad alta', media: 'Prioridad media', baja: 'Prioridad baja', sin_alerta: 'Sin indicio' };
export const BAND_SHORT = { alta: 'Alta', media: 'Media', baja: 'Baja', sin_alerta: 'Sin indicio' };
export const CONF_LABEL = { alta: 'Confianza alta', media: 'Confianza media', baja: 'Confianza baja' };

const nf = (d = 0) => new Intl.NumberFormat('es-CL', { minimumFractionDigits: d, maximumFractionDigits: d });
export const fmtNum = (v, d = 0) => (v == null || Number.isNaN(v) ? '—' : nf(d).format(v));
/** thousands of m³, e.g. 241000 -> "241" ; 135500 -> "135,5" */
export function fmtMil(v) {
  const k = v / 1000;
  return fmtNum(k, Math.abs(k) < 100 && Math.round(k) !== k ? 1 : 0);
}
/** "241–419 mil m³/año" */
export function fmtRange(min, max, unit = 'mil m³/año') {
  return `${fmtMil(min)}–${fmtMil(max)} ${unit}`;
}
/** exceso range vs derecho; lower bound clamped at 0 */
export function excesoRange(p) {
  const lo = Math.max(0, p.m3_estimado_min - p.m3_derecho);
  const hi = Math.max(0, p.m3_estimado_max - p.m3_derecho);
  return { lo, hi, loPct: lo / p.m3_derecho, hiPct: hi / p.m3_derecho };
}
export function fmtCoord(lon, lat) {
  return `${fmtNum(Math.abs(lat), 5)}° S, ${fmtNum(Math.abs(lon), 5)}° O`;
}
const MESES = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic'];
export function fmtDate(iso) {
  const [y, m, d] = iso.split('-').map(Number);
  return d ? `${d} ${MESES[m - 1]} ${y}` : `${MESES[m - 1]} ${y}`;
}
export function fmtMin(min) {
  const h = Math.floor(min / 60), m = Math.round(min % 60);
  return h ? `${h} h ${String(m).padStart(2, '0')} min` : `${m} min`;
}
export const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

/** Most telling dry window (>=20 days, the ones the method uses) in `year` (fallback: any year):
 *  the one where the predio is greenest relative to the secano reference. */
export function dryWindowStats(data, id, year = 2024) {
  const own = data.series.predios[id] || [], ref = data.series.referencia_secano?.serie || [];
  const monthsOf = w => {
    const out = new Set();
    const [y0, m0] = w.inicio.split('-').map(Number), [y1, m1] = w.fin.split('-').map(Number);
    for (let y = y0, m = m0; y < y1 || (y === y1 && m <= m1); m === 12 ? (y++, m = 1) : m++) out.add(`${y}-${String(m).padStart(2, '0')}`);
    return out;
  };
  const mean = (arr, k, ms) => { const v = arr.filter(r => ms.has(r.fecha) && r[k] != null).map(r => r[k]); return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null; };
  const stats = w => { const ms = monthsOf(w); return { win: w, ndvi: mean(own, 'ndvi', ms), ndmi: mean(own, 'ndmi', ms), refNdvi: mean(ref, 'ndvi', ms), refNdmi: mean(ref, 'ndmi', ms), z: mean(own, 'z_verdor', ms) }; };
  const all = (data.clima.ventanas_secas || []).filter(w => w.dias >= 20);
  const pick = list => list.map(stats).filter(s => s.ndvi != null && s.refNdvi != null)
    .sort((a, b) => (b.ndvi - b.refNdvi) - (a.ndvi - a.refNdvi))[0];
  return pick(all.filter(w => !year || w.inicio.startsWith(String(year)))) || pick(all) || null;
}
