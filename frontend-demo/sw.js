// Caudal · service worker: caché persistente para que la segunda visita (y la demo) no dependa de la red.
//
//   pesado e inmutable de otros orígenes (tiles EOX/Esri/AWS, librerías, fuentes)  -> caché primero
//   pesado local (tiles/, assets/)   -> caché al tiro y se revalida en segundo plano (a lo más una
//                                       recarga de atraso si alguien regenera una imagen)
//   código y datos locales (html, js, css, json)  -> red primero, con la caché como respaldo si la red
//                                       falla o tarda más de NETWORK_TIMEOUT_MS (siempre revalida con el
//                                       servidor; con red lenta puede servir la copia guardada)
//
// La caché no tiene tope ni expiración: crece con los tiles que se visitan (decenas de MB en la demo).
// Apagarlo: abrir la página con ?sw=0 (js/main.js lo desregistra y borra las cachés).
// Al cambiar las reglas de este archivo, subir VERSION: la caché anterior se borra al activar.

const VERSION = 'v3'; // v3: imagen de zonas ampliada al área de todos los predios
const CACHE = `caudal-${VERSION}`;
const NETWORK_TIMEOUT_MS = 2500;
const HEAVY_LOCAL = /\/(tiles|assets)\//;
const REMOTE_HOSTS = [
  'tiles.maps.eox.at', 'server.arcgisonline.com', 's3.amazonaws.com',
  'unpkg.com', 'cdn.jsdelivr.net', 'cdnjs.cloudflare.com', 'fonts.googleapis.com', 'fonts.gstatic.com',
];

self.addEventListener('install', (event) => { event.waitUntil(self.skipWaiting()); });

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    const names = await caches.keys();
    await Promise.all(names.filter((n) => n.startsWith('caudal-') && n !== CACHE).map((n) => caches.delete(n)));
    await self.clients.claim();
  })());
});

// only responses whose status can be read: an opaque one could be an error page cached forever
const cacheable = (res) => !!res && res.ok;

async function put(request, res) {
  if (!cacheable(res)) return;
  try {
    const cache = await caches.open(CACHE);
    await cache.put(request, res);
  } catch (err) {
    // quota exceeded or similar: the page keeps working from the network
    console.warn('[sw] no se pudo guardar', request.url, err && err.message);
  }
}

async function cacheFirst(request) {
  const hit = await caches.match(request);
  if (hit) return hit;
  // <script>/<link> without crossorigin ask in no-cors mode (opaque answer): these hosts all allow
  // CORS, so ask again in a mode whose status can be checked before keeping the answer
  if (request.mode === 'no-cors') {
    try {
      const res = await fetch(request.url, { mode: 'cors', credentials: 'omit' });
      if (res.ok) { put(request, res.clone()); return res; }
    } catch (_) { /* falls through to the plain request */ }
    return fetch(request);
  }
  const res = await fetch(request);
  put(request, res.clone());
  return res;
}

async function staleWhileRevalidate(event) {
  const { request } = event;
  const hit = await caches.match(request);
  const fresh = fetch(request, { cache: 'no-cache' }).then((res) => { put(request, res.clone()); return res; });
  if (!hit) return fresh;
  event.waitUntil(fresh.catch(() => {}));
  return hit;
}

async function networkFirst(request) {
  const hit = await caches.match(request, { ignoreSearch: request.mode === 'navigate' });
  // no-cache: always revalidate with the server (a static server sends no Cache-Control, and the
  // browser would otherwise reuse its own copy of an edited file for a while)
  const fresh = fetch(request, { cache: 'no-cache' }).then((res) => { put(request, res.clone()); return res; });
  if (!hit) return fresh;
  fresh.catch(() => {});
  const timeout = new Promise((resolve) => setTimeout(() => resolve(null), NETWORK_TIMEOUT_MS));
  const res = await Promise.race([fresh.catch(() => null), timeout]);
  return res && res.ok ? res : hit;
}

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);
  if (url.protocol !== 'http:' && url.protocol !== 'https:') return;
  if (request.headers.has('range')) return;
  if (url.origin === self.location.origin) {
    event.respondWith(HEAVY_LOCAL.test(url.pathname) ? staleWhileRevalidate(event) : networkFirst(request));
  } else if (REMOTE_HOSTS.includes(url.hostname)) {
    event.respondWith(cacheFirst(request));
  }
});

// The page sends what it loaded before this worker took control (first visit), so the shell is cached too.
self.addEventListener('message', (event) => {
  const msg = event.data || {};
  if (msg.type !== 'cache-urls' || !Array.isArray(msg.urls)) return;
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE);
    const own = msg.urls.filter((u) => typeof u === 'string' && new URL(u, self.location.href).origin === self.location.origin);
    await Promise.all(own.map(async (u) => {
      try {
        if (await cache.match(u)) return;
        const res = await fetch(u);
        if (res.ok) await cache.put(u, res);
      } catch (_) { /* sin red: se guardará en la próxima visita */ }
    }));
  })());
});
