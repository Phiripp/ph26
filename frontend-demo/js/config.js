// Caudal · dónde está el backend (caudal-api, docs/spec-demo.md "Backend").
//
// Producción: el servicio de Cloud Run. En localhost: la API local (api/README.md), en el puerto de
// `docker run -p 8080:8080 caudal-api`. Con ?api=http://localhost:PUERTO se apunta a otro puerto local;
// solo se aceptan direcciones locales, para que un enlace no pueda apuntar la página a otro servidor.

const PROD_API = 'https://caudal-api-170658673954.southamerica-west1.run.app';
const LOCAL_API = 'http://localhost:8080';
const LOCAL_HOSTS = ['localhost', '127.0.0.1'];

const isLocal = (hostname) => LOCAL_HOSTS.includes(hostname);

function localOverride() {
  const raw = new URLSearchParams(location.search).get('api');
  if (!raw) return null;
  try {
    const url = new URL(raw);
    return url.protocol === 'http:' && isLocal(url.hostname) ? url.origin : null;
  } catch {
    return null; // not a URL: the default applies
  }
}

/** Origen del backend, sin barra final. */
export const API_BASE = localOverride() || (isLocal(location.hostname) ? LOCAL_API : PROD_API);

/**
 * @param {string} ruta ruta de la API, con la barra inicial ("/api/health")
 * @returns {string} URL completa en el backend
 */
export const apiUrl = (ruta) => API_BASE + ruta;

const API_TIMEOUT_MS = 5000;
const BACKUP_BASE = 'data/respaldo';

async function fetchJson(url, ms) {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), ms);
  try {
    const res = await fetch(url, { signal: ctl.signal });
    if (!res.ok) throw new Error(`${res.status} en ${url}`);
    return await res.json();
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Pide un recurso de lectura a la API; si no responde en 5 s o da error, lee el archivo equivalente del
 * respaldo estático ("/api/zonas/Z2/ranking" -> "data/respaldo/zonas/Z2/ranking.json").
 * @param {string} ruta ruta de la API, con la barra inicial
 * @returns {Promise<{ data: any, respaldo: boolean }>} `respaldo` dice si salió del archivo estático
 */
export async function api(ruta) {
  try {
    return { data: await fetchJson(apiUrl(ruta), API_TIMEOUT_MS), respaldo: false };
  } catch (err) {
    console.warn('[Caudal] API sin respuesta, se usa el respaldo:', ruta, err.message);
    const archivo = `${BACKUP_BASE}${ruta.replace(/^\/api/, '')}.json`;
    return { data: await fetchJson(archivo, API_TIMEOUT_MS), respaldo: true };
  }
}
