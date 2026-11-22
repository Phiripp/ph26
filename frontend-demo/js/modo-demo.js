// Caudal · modo demo (docs/spec-demo.md, F7): los pasos del guion (docs/pitch-demo.md) con una tecla o un enlace.
//
//   Teclas 1 a 5, solo con ?demo=1:  1 portada · 2 zona · 3 caso real · 4 candidato · 5 ruta
//   Enlaces, siempre:                #caso · #candidato · #ruta
//
// Qué zona, caso y candidato abre cada paso sale de data/demo.json (la API lo sirve en /api/demo, con respaldo
// estático): se cambia ahí, no aquí.
import { api, MODO_DEMO } from './config.js';

const TECLAS = { 1: 'portada', 2: 'zona', 3: 'caso', 4: 'candidato', 5: 'ruta' };
const ENLACES = new Set(['caso', 'candidato', 'ruta']);
const CAMPOS = new Set(['INPUT', 'TEXTAREA', 'SELECT']);

let configP = null;
/** @returns {Promise<{ zona: string, caso: string, candidato: number|string }>} */
function config() {
  configP ??= api('/api/demo').then(({ data }) => {
    if (!data?.zona || !data?.caso || data?.candidato == null) throw new Error('data/demo.json incompleto');
    return data;
  });
  configP.catch(() => { configP = null; }); // a failed read is tried again on the next step
  return configP;
}

/**
 * @param {string} hash location.hash without the "#"
 * @returns {string|null} the demo step that link opens, or null
 */
export const pasoDeEnlace = (hash) => (ENLACES.has(String(hash).toLowerCase()) ? String(hash).toLowerCase() : null);

/**
 * @param {{ goHome: Function, goZona: Function, goCaso: Function }} stage navigation of js/main.js
 * @param {() => void} hideTitle removes the landing title (the zones view takes over)
 */
export function initModoDemo(stage, hideTitle) {
  async function ir(paso) {
    try {
      hideTitle();
      if (paso === 'portada') return await stage.goHome();
      const { zona, caso, candidato } = await config();
      if (paso === 'zona') return await stage.goZona(zona, { inicio: true });
      if (paso === 'caso') return await stage.goCaso(caso, { zona });
      if (paso === 'candidato') return await stage.goZona(zona, { predio: String(candidato) });
      if (paso === 'ruta') return await stage.goZona(zona, { tab: 'ruta' });
    } catch (err) {
      console.error('[Caudal] modo demo, paso', paso, err);
    }
    return undefined;
  }

  if (MODO_DEMO) {
    addEventListener('keydown', (e) => {
      const paso = TECLAS[e.key];
      if (!paso || e.defaultPrevented || e.ctrlKey || e.metaKey || e.altKey) return;
      const t = e.target;
      if (t && (CAMPOS.has(t.tagName) || t.isContentEditable)) return; // typing in the expediente form
      e.preventDefault();
      ir(paso);
    });
  }
  return { ir };
}
