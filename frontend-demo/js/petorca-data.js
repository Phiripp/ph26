// Caudal · legacy Petorca-town illustrative loader (v1 demo). Kept only for backwards compatibility:
// the main flow now uses js/zona-data.js. Formatting helpers are re-exported from there.
export {
  BANDS, BAND_LABEL, BAND_SHORT, CONF_LABEL,
  fmtNum, fmtMil, fmtRange, excesoRange, fmtCoord, fmtDate, fmtDateNum, fmtMin, fmtComuna, expShort, predioLabel, esc,
  dryWindowStats,
} from './zona-data.js';

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
    const counts = { alta: 0, media: 0, baja: 0, sin_alerta: 0, sin_dato: 0 };
    for (const f of predios) {
      const b = f.properties.banda;
      if (b in counts) counts[b]++;
    }
    return { id: 'petorca', base, predios, byId, series, clima, ruta, casos: [], casoByPredio: new Map(), counts, gpxUrl: base + 'ruta.gpx', legacy: true };
  })();
  p.catch(() => cache.delete(base));
  cache.set(base, p);
  return p;
}
