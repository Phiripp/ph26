// Caudal · worker que recorta tiles al polígono de Chile fuera del hilo principal.
// Mensajes: { type: 'init', rings }  ·  { id, kind: 'sat' | 'dem', buf, z, x, y }
// Respuesta: { id, buf }  (buf null = tile fuera de Chile)  ·  { id, error }
import { clipSatTile, clipDemTile } from './tile-clip.js';

let rings = null;

self.onmessage = async (ev) => {
  const m = ev.data || {};
  if (m.type === 'init') { rings = m.rings; return; }
  try {
    const out = m.kind === 'dem' ? await clipDemTile(m.buf, m.z, m.x, m.y, rings) : await clipSatTile(m.buf, m.z, m.x, m.y, rings);
    self.postMessage({ id: m.id, buf: out }, out ? [out] : []);
  } catch (err) {
    self.postMessage({ id: m.id, error: String((err && err.message) || err) });
  }
};
