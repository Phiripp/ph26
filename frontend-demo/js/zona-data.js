// Caudal · zone data loader (Z1 Petorca, Z2 Aconcagua bajo) + shared formatting helpers.
// Principle: "el sistema prioriza, no acusa" — IDs/rol only, ranges only, bands provisional until M5.

const ROOT = 'data/zonas/';
const cache = new Map();

async function getJSON(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`[Caudal] ${url}: HTTP ${r.status}`);
  return r.json();
}
const optJSON = url => getJSON(url).catch(err => { console.warn(String(err.message || err)); return null; });

function once(key, fn) {
  if (cache.has(key)) return cache.get(key);
  const p = fn();
  p.catch(() => cache.delete(key));
  cache.set(key, p);
  return p;
}

export const loadZonas = () => once('index', () => getJSON(ROOT + 'index.json'));
export const loadCasos = () => once('casos', async () => {
  const c = await getJSON(ROOT + 'casos.json');
  return (Array.isArray(c) ? c : c.casos || []).map(x => ({ ...x, predio_id: x.predio_id == null ? null : String(x.predio_id) }));
});
export const loadFiscalizaciones = () => once('fisc', () => getJSON(ROOT + 'fiscalizaciones.geojson'));
/**
 * Small landing summary (scripts/build_zonas_web.py): per-zone predio/band counts + route, and the demo
 * case series. Lets the landing page skip the full zone data. null when the file is not there.
 */
export const loadResumen = () => once('resumen', () => optJSON(ROOT + 'resumen.json'));

/* ---------- per-predio series, loaded by block on demand ---------- */
/** Block of a predio id. Same hash as scripts/build_zonas_web.py (bloque_de): h = h*31 + code, 32 bits. */
export function serieBlock(id, nBlocks) {
  let h = 0;
  const str = String(id);
  for (let i = 0; i < str.length; i++) h = (Math.imul(h, 31) + str.charCodeAt(i)) >>> 0;
  return h % nBlocks;
}
const blockFile = n => `b${String(n).padStart(2, '0')}.json`;
/** {ndvi:[…], ndmi:[…]} aligned to `meses` -> [{fecha, ndvi, ndmi}] (months without any value are skipped). */
function rowsOf(cols, meses) {
  const out = [];
  for (let i = 0; i < meses.length; i++) {
    const ndvi = cols.ndvi?.[i] ?? null, ndmi = cols.ndmi?.[i] ?? null;
    if (ndvi != null || ndmi != null) out.push({ fecha: meses[i], ndvi, ndmi });
  }
  return out;
}
/**
 * Series store of a zone. `predios` starts empty and is filled block by block by ensureSeries(); chart.js
 * and dryWindowStats() keep reading data.series.predios[id] synchronously once the block is in.
 * Falls back to the full series.json (everything in memory at once) when series/index.json is missing.
 */
async function loadSeriesStore(base) {
  const index = await optJSON(base + 'series/index.json');
  if (index && Array.isArray(index.meses) && index.bloques > 0) {
    return {
      predios: {},
      referencia_secano: index.referencia_secano || { serie: [] },
      lazy: { base: base + 'series/', meses: index.meses, bloques: index.bloques, loaded: new Map(), failed: new Set() },
    };
  }
  const full = await optJSON(base + 'series.json');
  return { predios: full?.predios || {}, referencia_secano: full?.referencia_secano || { serie: [] }, lazy: null };
}
/**
 * Make sure the series of these predio ids are in data.series.predios (fetches their blocks once).
 * Never rejects: a block that fails to load is remembered (seriesFailed) so the panels can say the
 * series could not be loaded instead of "no data", and is retried the next time it is asked for.
 */
export async function ensureSeries(data, ids) {
  const lazy = data?.series?.lazy;
  if (!lazy) return data;
  const list = (Array.isArray(ids) ? ids : [ids]).filter(id => id != null).map(String);
  const blocks = [...new Set(list.filter(id => !(id in data.series.predios)).map(id => serieBlock(id, lazy.bloques)))];
  await Promise.all(blocks.map(n => {
    if (!lazy.loaded.has(n)) {
      lazy.loaded.set(n, getJSON(lazy.base + blockFile(n)).then(j => {
        lazy.failed.delete(n);
        for (const [id, cols] of Object.entries(j.predios || {})) data.series.predios[id] = rowsOf(cols, lazy.meses);
      }).catch(err => { console.warn(String(err.message || err)); lazy.failed.add(n); lazy.loaded.delete(n); }));
    }
    return lazy.loaded.get(n);
  }));
  return data;
}

const zonaKey = id => String(id || '').toLowerCase();

/** Everything one zone needs: predios (scores merged), clima, ruta, its cases, counts. Series: see ensureSeries(). */
export function loadZona(id) {
  const key = zonaKey(id);
  return once('zona:' + key, async () => {
    const [index, casosAll] = await Promise.all([loadZonas(), loadCasos().catch(() => [])]);
    const zona = (index.zonas || []).find(z => zonaKey(z.id) === key || zonaKey(z.codigo) === key);
    if (!zona) throw new Error(`[Caudal] zona desconocida: ${id}`);
    let base = zona.data || `${ROOT}${key}/`;
    if (!base.endsWith('/')) base += '/';
    const [geo, scores, series, clima, ruta] = await Promise.all([
      getJSON(base + 'predios.geojson'),
      // lite = only the fields used here; the full scores.json (with per-season history) is the fallback
      optJSON(base + 'scores.lite.json').then(j => j || optJSON(base + 'scores.json')),
      loadSeriesStore(base),
      optJSON(base + 'clima.json'),
      optJSON(base + 'ruta.json'),
    ]);
    const sc = scores?.predios || {};
    const predios = (geo.features || []).map(f => {
      const p = f.properties || {};
      const pid = String(p.id ?? p.predio_id);
      const s = sc[pid] || {};
      const props = {
        ...p,
        id: pid,
        m3_derecho: p.m3_derecho_rol ?? p.m3_derecho ?? null,
        m3_estimado_min: s.m3_estimado_min ?? null,
        m3_estimado_max: s.m3_estimado_max ?? null,
        indice: s.indice ?? null,
        banda: BANDS.includes(s.banda) ? s.banda : 'sin_dato',
        confianza: s.confianza ?? null,
        confianza_motivos: s.confianza_motivos || [],
        ndvi_seca: s.ndvi_seca ?? null,
        ndvi_ref: s.ndvi_ref ?? null,
        provisional: scores?.provisional !== false,
      };
      if (!props.centroid) props.centroid = centroidOf(f.geometry);
      return { ...f, properties: props };
    });
    const byId = new Map(predios.map(f => [f.properties.id, f]));
    const casos = casosAll.filter(c => zonaKey(c.zona) === key || zonaKey(c.zona) === zonaKey(zona.codigo));
    // case → predio link (either side may carry it)
    for (const c of casos) {
      if (c.predio_id && byId.has(c.predio_id)) byId.get(c.predio_id).properties.caso ??= c.expediente;
    }
    const casoByPredio = new Map();
    for (const f of predios) if (f.properties.caso) casoByPredio.set(f.properties.id, f.properties.caso);
    for (const c of casos) if (!c.predio_id) {
      const pid = [...casoByPredio].find(([, e]) => e === c.expediente)?.[0];
      if (pid) c.predio_id = pid;
    }
    const counts = { alta: 0, media: 0, baja: 0, sin_alerta: 0, sin_dato: 0 };
    for (const f of predios) counts[f.properties.banda]++;
    return {
      id: key, zona, base, predios, byId, casos, casoByPredio, counts,
      scoresMeta: scores ? { provisional: scores.provisional !== false, metodo: scores.metodo, temporada: scores.temporada } : null,
      series,
      clima: clima || { ventanas_secas: [] },
      ruta,
      gpxUrl: base + 'ruta.gpx',
    };
  });
}

function centroidOf(g) {
  if (!g) return null;
  if (g.type === 'Point') return g.coordinates;
  const ring = g.type === 'Polygon' ? g.coordinates[0] : g.type === 'MultiPolygon' ? g.coordinates[0][0] : null;
  if (!ring?.length) return null;
  const n = ring.length;
  return [ring.reduce((a, c) => a + c[0], 0) / n, ring.reduce((a, c) => a + c[1], 0) / n];
}

/** Case (with its predio feature) by expediente, from a loaded zone. */
export function casoOf(data, expediente) {
  const c = data.casos.find(x => x.expediente === expediente);
  if (!c) return null;
  return { caso: c, feature: c.predio_id ? data.byId.get(c.predio_id) || null : null };
}

/** true when the series of this predio is missing because its block failed to download (not "no data"). */
export function seriesFailed(data, id) {
  const lazy = data?.series?.lazy;
  return !!lazy && id != null && !(String(id) in data.series.predios) && lazy.failed.has(serieBlock(id, lazy.bloques));
}
export const SERIES_FAILED_TEXT = 'No se pudo cargar la serie satelital. Vuelve a abrir el predio para reintentar.';

/* ---------- labels ---------- */
export const BANDS = ['alta', 'media', 'baja', 'sin_alerta', 'sin_dato'];
export const BAND_LABEL = { alta: 'Prioridad alta', media: 'Prioridad media', baja: 'Prioridad baja', sin_alerta: 'Sin indicio', sin_dato: 'Sin dato' };
export const BAND_SHORT = { alta: 'Alta', media: 'Media', baja: 'Baja', sin_alerta: 'Sin indicio', sin_dato: 'Sin dato' };
export const CONF_LABEL = { alta: 'Confianza alta', media: 'Confianza media', baja: 'Confianza baja' };

/* ---------- formatting ---------- */
const nf = (d = 0) => new Intl.NumberFormat('es-CL', { minimumFractionDigits: d, maximumFractionDigits: d });
export const fmtNum = (v, d = 0) => (v == null || Number.isNaN(+v) ? '—' : nf(d).format(v));
/** thousands of m³, e.g. 241000 -> "241" ; 135500 -> "135,5" ; 4200 -> "4,2" */
export function fmtMil(v) {
  if (v == null || Number.isNaN(+v)) return '—';
  const k = v / 1000;
  return fmtNum(k, Math.abs(k) < 100 && Math.round(k) !== k ? 1 : 0);
}
/** "241–419 mil m³/año" ; "—" if no estimate */
export function fmtRange(min, max, unit = 'mil m³/año') {
  if (min == null || max == null) return '—';
  return `${fmtMil(min)}–${fmtMil(max)}${unit ? ' ' + unit : ''}`;
}
/** exceso range vs derecho; lower bound clamped at 0. Percentages null when there is no right. */
export function excesoRange(p) {
  const der = +(p.m3_derecho ?? p.m3_derecho_rol ?? 0) || 0;
  if (p.m3_estimado_min == null || p.m3_estimado_max == null) return { lo: null, hi: null, loPct: null, hiPct: null };
  const lo = Math.max(0, p.m3_estimado_min - der);
  const hi = Math.max(0, p.m3_estimado_max - der);
  return { lo, hi, loPct: der ? lo / der : null, hiPct: der ? hi / der : null };
}
export function fmtCoord(lon, lat) {
  return `${fmtNum(Math.abs(lat), 5)}° S, ${fmtNum(Math.abs(lon), 5)}° O`;
}
const MESES = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic'];
export function fmtDate(iso) {
  if (!iso) return '—';
  const [y, m, d] = String(iso).slice(0, 10).split('-').map(Number);
  return d ? `${d} ${MESES[m - 1]} ${y}` : `${MESES[m - 1]} ${y}`;
}
/** "02-04-2024" */
export function fmtDateNum(iso) {
  if (!iso) return '—';
  const [y, m, d] = String(iso).slice(0, 10).split('-');
  return d ? `${d}-${m}-${y}` : `${m}-${y}`;
}
export function fmtMin(min) {
  const h = Math.floor(min / 60), m = Math.round(min % 60);
  return h ? `${h} h ${String(m).padStart(2, '0')} min` : `${m} min`;
}
/** "CABILDO" -> "Cabildo", "LA LIGUA" -> "La Ligua" */
export function fmtComuna(s) {
  return String(s || '').toLowerCase().replace(/(^|\s)\p{L}/gu, c => c.toUpperCase());
}
/** "FD-0501-181" -> "FD-181" */
export const expShort = e => String(e || '').replace(/^(\w+)-\d+-(\d+)$/, '$1-$2');
/** label used for a predio: rol if present, else id */
export const predioLabel = p => (p.rol ? `Rol ${p.rol}` : `Predio ${p.id}`);
export const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

/* ---------- dry-window evidence ---------- */
function monthsOf(w) {
  const out = new Set();
  const [y0, m0] = w.inicio.split('-').map(Number), [y1, m1] = w.fin.split('-').map(Number);
  for (let y = y0, m = m0; y < y1 || (y === y1 && m <= m1); m === 12 ? (y++, m = 1) : m++) out.add(`${y}-${String(m).padStart(2, '0')}`);
  return out;
}
const mean = (arr, k, ms) => { const v = arr.filter(r => ms.has(r.fecha) && r[k] != null).map(r => r[k]); return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null; };

/**
 * Most telling dry window for a predio: the one where it is greenest relative to the secano reference.
 * sel: a year (number) | {from, to} ISO dates (window must overlap) | {before: iso, months: 18}.
 * Falls back to any window if nothing matches the selection.
 */
export function dryWindowStats(data, id, sel = null) {
  const own = data.series?.predios?.[id] || [], ref = data.series?.referencia_secano?.serie || [];
  if (!own.length) return null;
  const stats = w => { const ms = monthsOf(w); return { win: w, ndvi: mean(own, 'ndvi', ms), ndmi: mean(own, 'ndmi', ms), refNdvi: mean(ref, 'ndvi', ms), refNdmi: mean(ref, 'ndmi', ms) }; };
  const wins = (data.clima?.ventanas_secas || []).filter(w => w.inicio && w.fin);
  const pick = list => list.map(stats).filter(s => s.ndvi != null && s.refNdvi != null)
    .sort((a, b) => (b.ndvi - b.refNdvi) - (a.ndvi - a.refNdvi))[0];
  let match = () => true;
  if (typeof sel === 'number') match = w => w.inicio.startsWith(String(sel)) || w.fin.startsWith(String(sel));
  else if (sel?.before) {
    const end = sel.before.slice(0, 10), d = new Date(end); d.setMonth(d.getMonth() - (sel.months || 18));
    const start = d.toISOString().slice(0, 10);
    match = w => w.fin <= end && w.fin >= start;
  } else if (sel?.from || sel?.to) match = w => (!sel.to || w.inicio <= sel.to) && (!sel.from || w.fin >= sel.from);
  const long = wins.filter(w => (w.dias ?? 0) >= 20);
  return pick(long.filter(match)) || pick(wins.filter(match)) || (sel?.before ? null : pick(long) || pick(wins)) || null;
}
