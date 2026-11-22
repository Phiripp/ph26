// Caudal · expediente PDF en vivo (docs/spec-demo.md, F3).
// Pide el expediente a caudal-api, muestra los pasos reales que informa el backend y abre el PDF en un
// visor dentro del panel, con descarga. Si el backend falla o deja de responder, abre el PDF de respaldo
// (data/respaldo/expedientes/) y dice de cuándo es. No hay progreso simulado.
import { apiUrl } from './config.js';
import { esc } from './zona-data.js';

// Sin expediente en este tiempo, se usa el respaldo. El spec (F3) dice 20 s; para la demo va en 5 s, para que la
// pantalla nunca se quede esperando: el del candidato sale del servidor en ~2 s, y uno nuevo (15 a 24 s) pasa
// al respaldo o a "Reintentar".
const CONNECT_MS = 5000;
const BACKUP_DIR = 'data/respaldo/expedientes';
const PDF_TYPE = 'application/pdf';
const VIEW_PARAMS = '#toolbar=0&navpanes=0&view=FitH';

const fmtCuando = (iso) => {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  return d.toLocaleString('es-CL', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false });
};

/** fetch that gives up after `ms` (and when the caller aborts). */
async function fetchWithTimeout(url, ms, signal) {
  const ctl = new AbortController();
  const stop = () => ctl.abort();
  const timer = setTimeout(stop, ms);
  signal?.addEventListener('abort', stop, { once: true });
  try {
    const res = await fetch(url, { signal: ctl.signal });
    if (!res.ok) throw new Error(`${res.status} en ${url}`);
    return res;
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener('abort', stop);
  }
}

/** The PDF as a local blob URL: the viewer and the download share it, and the type is forced to PDF. */
async function pdfBlobUrl(url, signal) {
  const res = await fetchWithTimeout(url, CONNECT_MS, signal);
  const bytes = await res.arrayBuffer();
  return URL.createObjectURL(new Blob([bytes], { type: PDF_TYPE }));
}

/**
 * Asks the backend for the expediente and reports each real step.
 * @returns {Promise<object>} the backend's answer (id, url_pdf, creado, reutilizado, segundos…)
 */
function requestLive(predioId, { onPaso, signal }) {
  return new Promise((resolve, reject) => {
    const es = new EventSource(apiUrl(`/api/expediente/eventos?predio_id=${encodeURIComponent(predioId)}`));
    let timer = 0;
    const done = (fn, value) => { clearTimeout(timer); es.close(); fn(value); };
    const fail = (msg) => done(reject, new Error(msg));
    const parse = (e) => { try { return JSON.parse(e.data); } catch { return null; } };
    timer = setTimeout(() => fail(`el servidor no respondió en ${CONNECT_MS / 1000} s`), CONNECT_MS);
    es.addEventListener('paso', (e) => { const d = parse(e); if (d?.texto) onPaso(d.texto); });
    es.addEventListener('listo', (e) => { const d = parse(e); if (d?.url_pdf) done(resolve, d); else fail('respuesta sin PDF'); });
    es.addEventListener('falla', (e) => fail(parse(e)?.detail || 'la generación falló'));
    es.onerror = () => fail('no hay conexión con el servidor');
    signal?.addEventListener('abort', () => fail('cancelado'), { once: true });
  });
}

/** The pregenerated PDF of this predio, if the static backup has one. */
async function requestBackup(predioId, signal) {
  const sinRespaldo = 'este predio no tiene PDF de respaldo';
  const index = await fetchWithTimeout(`${BACKUP_DIR}/indice.json`, CONNECT_MS, signal)
    .then((res) => res.json())
    .catch(() => { throw new Error(sinRespaldo); });
  const entry = index?.[String(predioId)];
  if (!entry?.archivo) throw new Error(sinRespaldo);
  return { ...entry, url: await pdfBlobUrl(`${BACKUP_DIR}/${entry.archivo}`, signal) };
}

function liveNote(meta) {
  const cuando = fmtCuando(meta.creado);
  if (meta.reutilizado) return `Generado el ${cuando} · mismos insumos, el servidor lo reutiliza`;
  return `Generado ahora en el servidor${meta.segundos ? ` en ${String(meta.segundos).replace('.', ',')} s` : ''}${cuando ? ` · ${cuando}` : ''}`;
}

const TEMPLATE = `
  <h4 class="pn-pdf-h">Expediente PDF <em class="pn-tag" data-part="tag"></em></h4>
  <ol class="pn-steps" data-part="steps" aria-live="polite"></ol>
  <p class="pn-pdf-note" data-part="note" role="status"></p>
  <div class="pn-actions" data-part="actions" hidden>
    <a class="btn primary" data-part="download">Descargar PDF ↓</a>
    <a class="btn" data-part="open" target="_blank" rel="noopener">Abrir aparte ↗</a>
  </div>
  <iframe class="pn-pdf-view" data-part="view" title="Expediente en PDF" hidden></iframe>
  <div class="pn-actions" data-part="retry" hidden>
    <button type="button" class="btn" data-act="pdf-retry">Reintentar</button>
  </div>`;

/**
 * Mounts the live expediente in `host` and starts generating it.
 * @param {HTMLElement} host empty container inside the expediente view
 * @param {{ predioId: number|string, fileName: string }} opts
 * @returns {{ destroy: () => void }} destroy cancels the request and frees the PDF
 */
export function mountExpedientePdf(host, { predioId, fileName }) {
  const ctl = new AbortController();
  let blobUrl = null;
  host.innerHTML = TEMPLATE;
  const part = (name) => host.querySelector(`[data-part="${name}"]`);
  const alive = () => !ctl.signal.aborted && host.isConnected;

  const addStep = (text) => {
    const steps = part('steps');
    steps.querySelector('.is-now')?.classList.remove('is-now');
    steps.insertAdjacentHTML('beforeend', `<li class="is-now">${esc(text)}</li>`);
  };
  const setState = (state, tag, note) => {
    host.dataset.state = state;
    part('tag').textContent = tag;
    part('note').textContent = note;
    part('steps').querySelector('.is-now')?.classList.remove('is-now');
    part('retry').hidden = state !== 'error';
  };
  const show = (url) => {
    blobUrl = url;
    part('view').src = url + VIEW_PARAMS;
    part('view').hidden = false;
    Object.assign(part('download'), { href: url, download: fileName });
    part('open').href = url;
    part('actions').hidden = false;
  };

  async function run() {
    part('steps').innerHTML = '';
    setState('working', 'generando', 'Pidiendo el expediente al servidor…');
    let liveError;
    try {
      const meta = await requestLive(predioId, { onPaso: (t) => alive() && addStep(t), signal: ctl.signal });
      const url = await pdfBlobUrl(apiUrl(meta.url_pdf), ctl.signal);
      if (!alive()) { URL.revokeObjectURL(url); return; }
      setState('ready', meta.reutilizado ? 'del servidor' : 'en vivo', liveNote(meta));
      show(url);
      return;
    } catch (err) {
      liveError = err;
    }
    if (!alive()) return;
    try {
      const backup = await requestBackup(predioId, ctl.signal);
      if (!alive()) { URL.revokeObjectURL(backup.url); return; }
      setState('ready', 'respaldo', `El servidor no respondió (${liveError.message}). PDF de respaldo, generado el ${fmtCuando(backup.creado)}`);
      show(backup.url);
    } catch (err) {
      if (!alive()) return;
      setState('error', 'sin PDF', `No se pudo generar el expediente: ${liveError.message}; ${err.message}`);
    }
  }

  host.addEventListener('click', (e) => {
    if (e.target.closest('[data-act="pdf-retry"]')) run();
  });
  run();

  return {
    destroy() {
      ctl.abort();
      if (blobUrl) URL.revokeObjectURL(blobUrl);
    },
  };
}
