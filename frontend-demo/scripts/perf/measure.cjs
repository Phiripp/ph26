#!/usr/bin/env node
// Caudal · medición de rendimiento del frontend demo (carga + intro, y vista de zona con N predios).
//
// Uso (con el servidor local arriba: python3 -m http.server 8000 en frontend-demo/):
//   npm i playwright-core            # en cualquier carpeta; no baja navegadores, usa el Chrome instalado
//   NODE_PATH=<esa carpeta>/node_modules node scripts/perf/measure.cjs --label antes --out antes.json
// Opciones: --base http://localhost:8000  --only landing,zona  --mults 1,20,100  --runs 2  --headed
//
// "mult" multiplica los predios de cada zona en memoria (clones desplazados) para ver cómo escala la vista
// sin tener todavía los datos reales. Los datos de data/zonas/ se sirven desde disco por este script.
const fs = require('fs');
const path = require('path');
const http = require('http');
const { chromium } = require('playwright-core');

const ROOT = path.resolve(__dirname, '..', '..');
const VIEWPORT = { width: 1280, height: 760 };
const LANDING_MS = 24000;
const ZONA_TIMEOUT_MS = 120000;

function parseArgs(argv) {
  const out = { base: 'http://localhost:8000', only: 'landing,zona', mults: '1,20,100', runs: '2', label: 'run', out: '', headed: false };
  for (let i = 2; i < argv.length; i++) {
    const k = argv[i].replace(/^--/, '');
    if (k === 'headed') out.headed = true;
    else out[k] = argv[++i];
  }
  return out;
}

/* ---------- multiplicador de predios (clones desplazados dentro de la zona) ---------- */
const cloneId = (id, k) => (k ? `${id}_${k}` : String(id));
const baseId = (id) => String(id).replace(/_\d+$/, '');
function shift(coords, dx, dy) {
  return typeof coords[0] === 'number' ? [coords[0] + dx, coords[1] + dy] : coords.map((c) => shift(c, dx, dy));
}
function multiplyPredios(geo, mult) {
  const features = [];
  for (const f of geo.features) {
    for (let k = 0; k < mult; k++) {
      if (!k) { features.push(f); continue; }
      const dx = (((k * 37) % 41) - 20) * 0.004, dy = (((k * 17) % 23) - 11) * 0.0035;
      const p = { ...f.properties, id: cloneId(f.properties.id, k), predio_id: cloneId(f.properties.predio_id, k), caso: null };
      if (p.centroid) p.centroid = shift(p.centroid, dx, dy);
      features.push({ ...f, properties: p, geometry: { ...f.geometry, coordinates: shift(f.geometry.coordinates, dx, dy) } });
    }
  }
  return { ...geo, features };
}
function multiplyKeyed(obj, mult) {
  const out = {};
  for (const id of Object.keys(obj)) for (let k = 0; k < mult; k++) out[cloneId(id, k)] = obj[id];
  return out;
}
/** Devuelve el cuerpo (Buffer) de un archivo de data/zonas/, multiplicado si corresponde, o null si no existe. */
function makeDataSource(mult) {
  const cache = new Map();
  return function body(rel) {
    if (cache.has(rel)) return cache.get(rel);
    let file = path.join(ROOT, rel);
    // archivos por predio (series/<id>.json): un clon usa el archivo de su predio original
    const m = /^(.*\/series\/)([^/]+)\.json$/.exec(rel);
    if (m && !fs.existsSync(file)) file = path.join(ROOT, `${m[1]}${baseId(m[2])}.json`);
    if (!fs.existsSync(file)) { cache.set(rel, null); return null; }
    let buf = fs.readFileSync(file);
    if (mult > 1 && /\/z\d+\/(predios\.geojson|scores\.json|series\.json)$/.test(rel)) {
      const j = JSON.parse(buf.toString('utf8'));
      const big = /predios\.geojson$/.test(rel) ? multiplyPredios(j, mult) : { ...j, predios: multiplyKeyed(j.predios || {}, mult) };
      buf = Buffer.from(JSON.stringify(big));
    }
    if (!m) cache.set(rel, buf);
    return buf;
  };
}

/* ---------- colectores dentro de la página ---------- */
function initCollectors() {
  const P = (window.__perf = { long: [], frames: [], modes: [], intro: [], gl: 0, lcp: 0 });
  try {
    new PerformanceObserver((l) => { for (const e of l.getEntries()) P.long.push([Math.round(e.startTime), Math.round(e.duration)]); }).observe({ entryTypes: ['longtask'] });
    new PerformanceObserver((l) => { for (const e of l.getEntries()) P.lcp = Math.round(e.startTime); }).observe({ type: 'largest-contentful-paint', buffered: true });
  } catch (_) { /* observers no disponibles */ }
  let last = performance.now();
  const tick = (now) => { P.frames.push([now, now - last]); last = now; requestAnimationFrame(tick); };
  requestAnimationFrame(tick);
  let lm = '', li = '';
  setInterval(() => {
    const t = document.getElementById('top');
    if (!t) return;
    const m = t.dataset.mode, i = t.dataset.intro || '';
    if (m && m !== lm) { lm = m; P.modes.push([m, Math.round(performance.now())]); }
    if (i !== li) { li = i; P.intro.push([i, Math.round(performance.now())]); }
  }, 25);
  const gc = HTMLCanvasElement.prototype.getContext;
  HTMLCanvasElement.prototype.getContext = function (type, ...a) {
    const c = gc.call(this, type, ...a);
    if (c && /webgl/.test(type) && !this.__counted) { this.__counted = true; P.gl++; }
    return c;
  };
}

function collectLanding(untilMs) {
  const P = window.__perf;
  const res = performance.getEntriesByType('resource');
  const kb = (list) => Math.round(list.reduce((a, r) => a + (r.decodedBodySize || 0), 0) / 1024);
  const grp = (re) => res.filter((r) => re.test(r.name));
  const stats = (a, b) => {
    const f = P.frames.filter((x) => x[0] >= a && x[0] < b).map((x) => x[1]);
    if (!f.length || b <= a) return null;
    const s = f.slice().sort((x, y) => x - y);
    return { fps: +(f.length / ((b - a) / 1000)).toFixed(1), p95: Math.round(s[Math.floor(s.length * 0.95)]), max: Math.round(s[s.length - 1]) };
  };
  const at = (name) => (P.intro.find((x) => x[0].startsWith(name)) || [])[1];
  const play = at('playing'), gone = at('gone');
  const long = P.long.filter((x) => x[0] < untilMs);
  const gl = document.createElement('canvas').getContext('webgl2');
  const ext = gl && gl.getExtension('WEBGL_debug_renderer_info');
  return {
    gpu: ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : 'n/a',
    requests: res.length,
    totalKB: kb(res),
    dataKB: kb(grp(/\/data\//)),
    aculeoKB: kb(grp(/\/assets\/aculeo\//)),
    zonasAssetsKB: kb(grp(/\/assets\/zonas\//)),
    tilesKB: kb(grp(/\/tiles\//)),
    cdnKB: kb(res.filter((r) => !r.name.startsWith(location.origin))),
    lcpMs: P.lcp,
    longTasks: { n: long.length, totalMs: long.reduce((a, x) => a + x[1], 0), maxMs: Math.max(0, ...long.map((x) => x[1])) },
    introMs: play && gone ? gone - play : null,
    introFps: play && gone ? stats(play, gone) : null,
    afterIntroFps: gone ? stats(gone, Math.min(untilMs, gone + 6000)) : null,
    idleFps: stats(untilMs - 4000, untilMs),
    glContexts: P.gl,
    domNodes: document.querySelectorAll('*').length,
    heapMB: performance.memory ? Math.round(performance.memory.usedJSHeapSize / 1048576) : null,
  };
}

async function measureZona() {
  const P = window.__perf, top = document.getElementById('top');
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const raf = () => new Promise((r) => requestAnimationFrame(r));
  const stats = (a, b) => {
    const f = P.frames.filter((x) => x[0] >= a && x[0] < b).map((x) => x[1]);
    if (!f.length) return null;
    const s = f.slice().sort((x, y) => x - y);
    return { fps: +(f.length / ((b - a) / 1000)).toFixed(1), p95: Math.round(s[Math.floor(s.length * 0.95)]), max: Math.round(s[s.length - 1]) };
  };
  const med = (a) => { const s = a.slice().sort((x, y) => x - y); return s.length ? +s[Math.floor(s.length / 2)].toFixed(1) : null; };
  await sleep(3000);
  const tz = (P.modes.find((m) => m[0] === 'zona') || [])[1];
  const lb = P.long.filter((x) => x[0] < tz);
  const out = { toZonaMs: tz, longBeforeZonaMs: lb.reduce((a, x) => a + x[1], 0), longMaxMs: Math.max(0, ...lb.map((x) => x[1])) };
  const cv = document.getElementById('valle-canvas'), r = cv.getBoundingClientRect();
  let a = performance.now();
  for (let i = 0; i < 150; i++) {
    const k = i / 150;
    const x = r.left + r.width * (0.1 + 0.55 * (0.5 + 0.5 * Math.sin(k * 14))), y = r.top + r.height * (0.25 + 0.5 * k);
    cv.dispatchEvent(new PointerEvent('pointermove', { clientX: x, clientY: y, bubbles: true }));
    await raf();
  }
  out.hover = stats(a, performance.now());
  const rows = () => [...document.querySelectorAll('#vp-predios .pn-row')];
  out.rankRowsInDom = rows().length;
  out.domNodes = document.querySelectorAll('*').length;
  const selSync = [], selFrame = [], backFrame = [];
  for (let i = 0; i < 3; i++) {
    const rw = rows()[i * 3];
    if (!rw) break;
    const s0 = performance.now(); rw.click(); const s1 = performance.now(); await raf(); const s2 = performance.now();
    selSync.push(s1 - s0); selFrame.push(s2 - s0);
    await sleep(1900);
    const bk = document.querySelector('#vp-predios .pn-back');
    if (bk) { const b0 = performance.now(); bk.click(); await raf(); await raf(); backFrame.push(performance.now() - b0); await sleep(1500); }
  }
  out.selectSyncMs = med(selSync); out.selectToFrameMs = med(selFrame); out.backToRankingMs = med(backFrame);
  const rs = [];
  for (const h of ['700px', '']) {
    const z0 = performance.now(); top.style.height = h; await raf(); await raf(); await raf();
    rs.push(performance.now() - z0); await sleep(500);
  }
  out.resizeMs = med(rs);
  out.heapMB = performance.memory ? Math.round(performance.memory.usedJSHeapSize / 1048576) : null;
  return out;
}

/* ---------- perfil de CPU (tiempo propio por función) ---------- */
function cpuSummary(profile) {
  const byId = new Map(profile.nodes.map((n) => [n.id, n]));
  const self = new Map();
  let total = 0;
  profile.samples.forEach((id, i) => {
    const dt = profile.timeDeltas[i] || 0;
    const n = byId.get(id);
    if (!n) return;
    const cf = n.callFrame;
    const file = (cf.url || '').split('/').pop().split('?')[0];
    const key = `${cf.functionName || '(anon)'}${file ? ' ' + file : ''}`;
    self.set(key, (self.get(key) || 0) + dt);
    total += dt;
  });
  const ms = (k) => Math.round((self.get(k) || 0) / 1000);
  const idle = ms('(idle)');
  const top = [...self.entries()].filter(([k]) => k !== '(idle)').sort((a, b) => b[1] - a[1]).slice(0, 10).map(([k, v]) => [k, Math.round(v / 1000)]);
  return {
    sampledMs: Math.round(total / 1000), busyMs: Math.round(total / 1000) - idle,
    depthAtPointMs: ms('depthAtPoint maplibre-gl.js'),
    clipTilesMs: ms('clipToChile map.js') + ms('clipDemToChile map.js'),
    top,
  };
}

/* ---------- escenarios ---------- */
/** Servidor local para los datos (multiplicados): cuerpos de decenas de MB no caben en route.fulfill. */
function startDataServer(body, counters) {
  return new Promise((resolve) => {
    const srv = http.createServer((req, res) => {
      const rel = decodeURIComponent(new URL(req.url, 'http://x').pathname.replace(/^\//, ''));
      const buf = body(rel);
      if (!buf) { res.writeHead(404); res.end('not found'); return; }
      counters.dataBytes += buf.length; counters.dataReqs++;
      res.writeHead(200, { 'content-type': 'application/json', 'content-length': buf.length });
      res.end(buf);
    });
    srv.listen(0, '127.0.0.1', () => resolve(srv));
  });
}

async function newPage(browser, mult, counters) {
  const ctx = await browser.newContext({ viewport: VIEWPORT, deviceScaleFactor: 1 });
  const page = await ctx.newPage();
  await page.addInitScript(initCollectors);
  const srv = await startDataServer(makeDataSource(mult), counters);
  const port = srv.address().port;
  await page.route('**/data/zonas/**', (route) => {
    const u = new URL(route.request().url());
    return route.continue({ url: `http://127.0.0.1:${port}${u.pathname}` });
  });
  const close = async () => { await ctx.close(); await new Promise((r) => srv.close(r)); };
  return { ctx, page, close };
}

async function runLanding(browser, base) {
  const counters = { dataBytes: 0, dataReqs: 0 };
  const { ctx, page, close } = await newPage(browser, 1, counters);
  const cdp = await ctx.newCDPSession(page);
  await cdp.send('Profiler.enable');
  await cdp.send('Profiler.setSamplingInterval', { interval: 500 });
  await cdp.send('Profiler.start');
  await page.goto(base + '/', { waitUntil: 'commit' });
  await page.waitForTimeout(LANDING_MS);
  const r = await page.evaluate(collectLanding, LANDING_MS - 1000);
  const { profile } = await cdp.send('Profiler.stop');
  r.cpu = cpuSummary(profile);
  r.zonaDataKB = Math.round(counters.dataBytes / 1024);
  await close();
  return r;
}

async function runZona(browser, base, mult) {
  const counters = { dataBytes: 0, dataReqs: 0 };
  const { page, close } = await newPage(browser, mult, counters);
  await page.goto(base + '/#z1', { waitUntil: 'commit' });
  await page.waitForFunction(() => document.getElementById('top')?.dataset.mode === 'zona', null, { timeout: ZONA_TIMEOUT_MS });
  const atZona = { kb: Math.round(counters.dataBytes / 1024), reqs: counters.dataReqs };
  const r = await page.evaluate(measureZona);
  r.predios = await page.evaluate(() => (document.getElementById('hz-count')?.textContent || '').trim());
  r.zonaDataKBToEnter = atZona.kb; r.zonaDataReqsToEnter = atZona.reqs;
  r.zonaDataKBTotal = Math.round(counters.dataBytes / 1024);
  await close();
  return r;
}

const pickBest = (runs, key) => runs.slice().sort((a, b) => key(a) - key(b))[Math.floor((runs.length - 1) / 2)];

async function main() {
  const args = parseArgs(process.argv);
  const only = args.only.split(',');
  const browser = await chromium.launch({
    channel: 'chrome', headless: !args.headed,
    args: ['--use-angle=metal', '--enable-gpu', '--ignore-gpu-blocklist', '--enable-precise-memory-info'],
  });
  const result = { label: args.label, date: new Date().toISOString(), viewport: VIEWPORT };
  try {
    if (only.includes('landing')) {
      const runs = [];
      for (let i = 0; i < +args.runs; i++) { process.stderr.write(`[measure] landing ${i + 1}/${args.runs}…\n`); runs.push(await runLanding(browser, args.base)); }
      result.landing = pickBest(runs, (r) => r.longTasks.totalMs);
      result.landingRuns = runs.map((r) => ({ longMs: r.longTasks.totalMs, introFps: r.introFps?.fps, totalKB: r.totalKB }));
    }
    if (only.includes('zona')) {
      result.zona = {};
      for (const m of args.mults.split(',').map(Number)) {
        process.stderr.write(`[measure] zona x${m}…\n`);
        try { result.zona[`x${m}`] = await runZona(browser, args.base, m); }
        catch (err) { result.zona[`x${m}`] = { error: String(err.message || err).split('\n')[0] }; process.stderr.write(`[measure] zona x${m} falló: ${err.message}\n`); }
      }
    }
  } finally {
    await browser.close();
  }
  const txt = JSON.stringify(result, null, 2);
  if (args.out) fs.writeFileSync(args.out, txt);
  process.stdout.write(txt + '\n');
}

main().catch((err) => { process.stderr.write(`[measure] ${err.stack || err}\n`); process.exit(1); });
