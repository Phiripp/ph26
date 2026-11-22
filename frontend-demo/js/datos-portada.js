// Caudal · datos de la portada: columna izquierda de la vista de zonas (frescura y escala del análisis).
// Los números salen de la API (o de su respaldo estático); nada queda escrito a mano en la página.
import { api } from './config.js';
import { esc } from './zona-data.js';

const nf = new Intl.NumberFormat('es-CL');
const fmtDia = (iso) => {
  const d = new Date(`${String(iso).slice(0, 10)}T12:00:00`);
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleDateString('es-CL', { day: 'numeric', month: 'short', year: 'numeric' }).replace(/\./g, '');
};

function alertaPorZona(impacto, zonas) {
  const nombres = new Map((zonas?.zonas || []).map((z) => [z.zona, z.nombre]));
  return Object.entries(impacto?.candidatos_por_zona || {})
    .map(([zona, n]) => `${nf.format(n)} en ${nombres.get(zona) || zona}`)
    .join(' · ');
}

/** The facts to show; one that cannot be computed from the data is left out. */
function facts({ health, impacto, zonas }) {
  const list = [];
  if (health?.dato_al) list.push({ k: 'Última imagen satelital', ks: 'Última imagen', v: fmtDia(health.dato_al), d: 'Sentinel-2 · el satélite pasa cada 5 días' });
  if (Number.isFinite(health?.predios)) list.push({ k: 'Predios analizados', ks: 'Predios', v: nf.format(health.predios), d: `Temporada ${health.temporada || ''}`.trim() });
  if (Number.isFinite(impacto?.candidatos)) list.push({ k: 'En alerta alta, sin fiscalizar', ks: 'En alerta', v: nf.format(impacto.candidatos), d: alertaPorZona(impacto, zonas) });
  return list;
}

const itemHTML = (f) => `<div class="fact"><dt><span class="k-long">${esc(f.k)}</span><span class="k-short">${esc(f.ks)}</span></dt><dd><b>${esc(f.v)}</b>${f.d ? `<span>${esc(f.d)}</span>` : ''}</dd></div>`;

/**
 * Fills the landing facts column. Leaves it hidden if the data cannot be read.
 * @param {HTMLElement|null} el the #facts container
 * @returns {Promise<void>}
 */
export async function mountPortadaDatos(el) {
  if (!el) return;
  try {
    const [health, impacto, zonas] = await Promise.all(['/api/health', '/api/impacto', '/api/zonas'].map((r) => api(r)));
    const list = facts({ health: health.data, impacto: impacto.data, zonas: zonas.data });
    if (!list.length) return;
    const calculado = health.data?.calculado ? `Calculado el ${fmtDia(health.data.calculado)}` : '';
    const aviso = [health, impacto].some((r) => r.respaldo) ? 'datos de respaldo' : '';
    el.innerHTML = `<dl class="facts-list">${list.map(itemHTML).join('')}</dl>` +
      `<p class="facts-foot">${esc([calculado, aviso].filter(Boolean).join(' · '))}</p>`;
    el.hidden = false;
  } catch (err) {
    console.error('[Caudal] datos de la portada:', err);
  }
}
