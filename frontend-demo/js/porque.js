// Caudal · bloque "Por qué está en alerta" (docs/spec-demo.md, F2 y F4).
// Muestra las razones, la confianza y los límites que arma explicacion.py: el mismo texto que usa el
// expediente PDF. Se pide a la API (con respaldo estático); si no hay datos, el bloque queda oculto.
import { api } from './config.js';
import { esc } from './zona-data.js';

const MAX_RAZONES = 4;
const MAX_LIMITES = 2;

const fmtDia = (iso) => {
  const d = new Date(`${String(iso).slice(0, 10)}T12:00:00`);
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleDateString('es-CL', { day: 'numeric', month: 'short', year: 'numeric' }).replace(/\./g, '');
};

const razonHTML = (r) => `<li${r.fuente ? ` title="Fuente: ${esc(r.fuente)}"` : ''}><b>${esc(r.titulo)}</b><span>${esc(r.texto)}</span></li>`;

function confianzaHTML(expl) {
  if (!expl.confianza) return '';
  const motivos = (expl.confianza_motivos || []).map((m) => m.replace(/\.$/, '')).join('. ');
  return `<p class="pn-why-conf"><b>Confianza ${esc(expl.confianza)}.</b>${motivos ? ` ${esc(motivos)}.` : ''}</p>`;
}

function pieHTML(sello) {
  // a case is explained with the season before its inspection: say which one instead of today's data date
  const datos = sello.previa
    ? sello.temporada && `datos de la temporada ${sello.temporada}, previa a la inspección`
    : sello.dato_al && `datos al ${fmtDia(sello.dato_al)}`;
  const partes = [sello.calculado && `Calculado el ${fmtDia(sello.calculado)}`, datos].filter(Boolean);
  return partes.length ? `<p class="pn-why-foot">${esc(partes.join(' · '))}</p>` : '';
}

/**
 * @param {object} expl bloque `explicacion` de la API
 * @param {{ titulo: string, calculado?: string, dato_al?: string, previa?: boolean, temporada?: string }} sello título y fechas del dato
 * @returns {string} HTML del bloque, o '' si no hay razones
 */
export function porQueHTML(expl, sello) {
  const razones = (expl?.razones || []).slice(0, MAX_RAZONES);
  if (!razones.length) return '';
  const limites = (expl.limites || []).slice(0, MAX_LIMITES);
  return `<h4 class="pn-why-h">${esc(sello.titulo)}</h4>
    <ul class="pn-why-l">${razones.map(razonHTML).join('')}</ul>
    ${confianzaHTML(expl)}
    ${limites.length ? `<p class="pn-why-lim">${limites.map(esc).join(' ')}</p>` : ''}
    ${pieHTML(sello)}`;
}

/**
 * Fills `host` with the block once the data arrives; leaves it hidden when there is none.
 * @param {HTMLElement|null} host empty, hidden container already in the ficha
 * @param {string} ruta API route whose answer carries `explicacion` ("/api/predios/123", "/api/casos/FO-…")
 * @param {{ titulo?: string, previa?: boolean }} [opts] previa: explicación de la temporada anterior a una inspección
 * @returns {Promise<void>}
 */
export async function mountPorQue(host, ruta, { titulo = 'Por qué está en alerta', previa = false } = {}) {
  if (!host) return;
  try {
    const { data } = await api(ruta);
    if (!host.isConnected) return; // the panel moved on to another view
    const sello = { titulo, previa, calculado: data?.calculado, dato_al: data?.dato_al, temporada: data?.explicacion?.temporada };
    const html = porQueHTML(data?.explicacion, sello);
    if (!html) return;
    host.innerHTML = html;
    host.hidden = false;
  } catch (err) {
    console.warn('[Caudal] sin explicación para', ruta, err.message);
  }
}
