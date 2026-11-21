// Caudal · recorte de tiles al polígono de Chile. Sin dependencias del DOM: lo usan el worker
// (js/tile-clip-worker.js) y, como respaldo, el hilo principal (js/map.js).
//
// rings = [{ poly, w, e, s, n }]: cada polígono de Chile ([anilloExterior, ...huecos], pares [lon, lat])
// con su caja envolvente (ver ringsOfChile).

const lon2tx = (lon, z) => ((lon + 180) / 360) * 2 ** z;
const lat2ty = (lat, z) => {
  const r = (lat * Math.PI) / 180;
  return ((1 - Math.log(Math.tan(r) + 1 / Math.cos(r)) / Math.PI) / 2) * 2 ** z;
};

/** Polygons of a GeoJSON FeatureCollection -> rings with their lon/lat bounding box. */
export function ringsOfChile(fc) {
  const polys = [];
  for (const f of (fc && fc.features) || []) {
    const g = f && f.geometry;
    if (!g) continue;
    if (g.type === 'Polygon') polys.push(g.coordinates);
    else if (g.type === 'MultiPolygon') polys.push(...g.coordinates);
  }
  return polys.map((poly) => {
    let w = 180, e = -180, s = 90, n = -90;
    for (const [lo, la] of poly[0]) { if (lo < w) w = lo; if (lo > e) e = lo; if (la < s) s = la; if (la > n) n = la; }
    return { poly, w, e, s, n };
  });
}

function makeCanvas(size) {
  if (typeof OffscreenCanvas === 'function') return new OffscreenCanvas(size, size);
  if (typeof document === 'undefined') throw new Error('sin canvas en este contexto');
  return Object.assign(document.createElement('canvas'), { width: size, height: size });
}
const toPng = async (c) => {
  const blob = c.convertToBlob ? await c.convertToBlob({ type: 'image/png' }) : await new Promise((r) => c.toBlob(r, 'image/png'));
  return blob.arrayBuffer();
};
/** Rings whose bounding box touches tile z/x/y. */
function hitsOf(rings, z, x, y) {
  const n2 = 2 ** z;
  const w = (x / n2) * 360 - 180, e = ((x + 1) / n2) * 360 - 180;
  const merc = (t) => (Math.atan(Math.sinh(Math.PI * (1 - (2 * t) / n2))) * 180) / Math.PI;
  const nLat = merc(y), sLat = merc(y + 1);
  return rings.filter((r) => r.e >= w && r.w <= e && r.n >= sLat && r.s <= nLat);
}
function tracePolys(g, hits, z, x, y, S) {
  g.beginPath();
  for (const { poly } of hits) {
    for (const ring of poly) {
      for (let i = 0; i < ring.length; i++) {
        const px = (lon2tx(ring[i][0], z) - x) * S, py = (lat2ty(ring[i][1], z) - y) * S;
        if (i) g.lineTo(px, py); else g.moveTo(px, py);
      }
      g.closePath();
    }
  }
}
async function drawTile(buf) {
  const bmp = await createImageBitmap(new Blob([buf]));
  const S = bmp.width || 256;
  const c = makeCanvas(S);
  const g = c.getContext('2d');
  g.drawImage(bmp, 0, 0, S, S);
  if (bmp.close) bmp.close();
  return { c, g, S };
}

/** Satellite tile: keep only the pixels inside Chile. Returns PNG bytes, or null if the tile is outside. */
export async function clipSatTile(buf, z, x, y, rings) {
  if (!rings) return buf;
  const hits = hitsOf(rings, z, x, y);
  if (!hits.length) return null;
  const { c, g, S } = await drawTile(buf);
  g.globalCompositeOperation = 'destination-in';
  tracePolys(g, hits, z, x, y, S);
  g.fillStyle = '#000';
  g.fill('evenodd');
  return toPng(c);
}

/**
 * Hillshade DEM tile: outside Chile the elevation becomes flat 0 m (Terrarium rgb(128,0,0)), so no
 * relief (ocean floor, Argentine Andes) is ever shaded there. Always returns PNG bytes.
 */
export async function clipDemTile(buf, z, x, y, rings) {
  if (!rings) return buf;
  const hits = hitsOf(rings, z, x, y);
  const { c, g, S } = await drawTile(buf);
  g.globalCompositeOperation = 'destination-in';
  tracePolys(g, hits, z, x, y, S);
  g.fillStyle = '#000';
  if (hits.length) g.fill('evenodd'); else g.clearRect(0, 0, S, S);
  g.globalCompositeOperation = 'destination-over';
  g.fillStyle = 'rgb(128,0,0)';
  g.fillRect(0, 0, S, S);
  return toPng(c);
}
