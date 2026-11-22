// Caudal · bloque "Por qué está en alerta" (docs/spec-demo.md, F2 y F4).
// Las frases, las fuentes y los límites vienen de la API (scripts/models/explicacion.py, la misma función
// que usa el expediente PDF); aquí solo se muestran. Tres preguntas, en este orden: qué vimos (hasta 4
// razones, cada una con su fuente), qué tan seguros estamos y qué no sabemos.
import { api, REPO_URL } from './config.js';
import { esc } from './zona-data.js';

const TITULO = { alta: 'Por qué está en alerta', media: 'Por qué está en alerta', baja: 'Por qué está en alerta', sin_alerta: 'Por qué no está en alerta' };

const fmtDia = (iso) => {
  // una fecha sin hora ("2026-03-28") se lee al mediodía: a medianoche UTC caería en el día anterior en Chile
  const d = new Date(/^\d{4}-\d{2}-\d{2}$/.test(iso) ? `${iso}T12:00:00` : iso);
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleDateString('es-CL', { day: 'numeric', month: 'short', year: 'numeric' });
};
const repoLink = (ruta, texto) => (ruta ? `<a href="${esc(REPO_URL + encodeURI(ruta))}" target="_blank" rel="noopener">${esc(texto)}</a>` : '');

function razonHTML(r) {
  const fuente = r.referencia
    ? `<a href="${esc(r.referencia)}" target="_blank" rel="noopener">${esc(r.fuente)}</a>`
    : esc(r.fuente || '');
  const al = r.dato_al ? ` · datos al ${esc(fmtDia(r.dato_al))}` : '';
  return `<li><b>${esc(r.titulo)}.</b> ${esc(r.texto)}<small class="pn-why-src">Fuente: ${fuente}${al}</small></li>`;
}

/**
 * @param {object} x explicación de la API (razones, confianza, confianza_motivos, limites, calculado…)
 * @param {{ titulo?: string, respaldo?: boolean, datoAl?: string }} opts
 */
function explicacionHTML(x, { titulo, respaldo, datoAl } = {}) {
  const motivos = (x.confianza_motivos || []).map((m) => esc(m)).join('. ');
  const pie = [
    x.calculado ? `Calculado el ${esc(fmtDia(x.calculado))}` : '',
    datoAl ? `datos al ${esc(fmtDia(datoAl))}` : '',
    repoLink(x.metodo, 'ver método'),
    repoLink(x.validacion, 'validación'),
    respaldo ? 'datos de respaldo' : '',
  ].filter(Boolean).join(' · ');
  return `
    <h4 class="pn-why-h">${esc(titulo || TITULO[x.banda] || TITULO.alta)}</h4>
    <ul class="pn-why-l">${(x.razones || []).map(razonHTML).join('')}</ul>
    <p class="pn-why-p"><b>Qué tan seguros estamos:</b> confianza ${esc(x.confianza || 's/d')}${motivos ? `. ${motivos}.` : '.'}</p>
    <p class="pn-why-p"><b>Qué no sabemos:</b> ${(x.limites || []).map((l) => esc(l)).join(' ')}</p>
    <p class="pn-foot">${pie}</p>`;
}

/**
 * Llena `host` con la explicación que entrega `ruta` de la API (o su respaldo estático).
 * @param {HTMLElement} host contenedor vacío dentro de la ficha
 * @param {string} ruta "/api/predios/{id}" o "/api/casos/{expediente}"
 * @param {{ titulo?: (x: object) => string, datoAl?: boolean }} opts título propio (el caso muestra la temporada
 *   previa) y si el pie lleva la fecha de la última imagen (en un caso no: cada razón trae la suya)
 */
export async function mountExplicacion(host, ruta, { titulo, datoAl = true } = {}) {
  if (!host) return;
  host.dataset.ruta = ruta;
  host.innerHTML = '<p class="pn-why-p pn-why-wait">Cargando las razones…</p>';
  const vigente = () => host.isConnected && host.dataset.ruta === ruta;
  try {
    const { data, respaldo } = await api(ruta);
    if (!vigente()) return;
    const x = data?.explicacion;
    if (!x) { host.hidden = true; return; }
    host.innerHTML = explicacionHTML(x, { titulo: titulo?.(x), respaldo, datoAl: datoAl ? data.dato_al : null });
  } catch {
    if (vigente()) host.innerHTML = '<p class="pn-why-p pn-why-wait">Sin el detalle de las razones: el servidor no respondió y este predio no está en el respaldo.</p>';
  }
}
