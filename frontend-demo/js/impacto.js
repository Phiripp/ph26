// Caudal · panel de impacto (spec-demo F6). Pantalla completa sobre el mapa atenuado, enlace directo #impacto.
//
// Cinco cifras, grandes y en el orden del guion (docs/pitch-demo.md, 2:00):
//   1 · 2,6× más infractores que al azar (fijo, umbrales iniciales; IC 95 % 1,3–4,4, docs/validacion.md)
//   2 · 1 predio = el agua de N personas al año = M latas (exceso mínimo del candidato del pitch)
//   3 · 501 predios en alerta alta sin fiscalizar
//   4 · Entre 5 y 20 Torres Costanera de agua al año (escenarios conservador y central ÷ 450.000 m³)
//   5 · 14 años para revisarlos uno por uno (candidatos de hasta 100 ha ÷ 33 fiscalizaciones al año)
//
// Todo sale de data/zonas/impacto.json (copia de data/processed/impacto.json, M9) y de su bloque "pitch"
// (build_m5_web.py). Si el bloque "pitch" falta, las cifras que se pueden sacar del bloque base se calculan
// aquí con las mismas reglas; la que necesita el predio (cifra 2) queda en "—" y el panel reintenta.
// Nada se anima solo: el panel aparece con un fundido corto (ninguno con reduced-motion).

const URL_IMPACTO = 'data/zonas/impacto.json';
const RETRY_MS = 15000;

// Supuestos fijos del pitch (docs/spec-demo.md F6, docs/pitch-demo.md "Fuentes de cada cifra").
// Solo se usan si el bloque "pitch" del JSON no trae su propio valor.
const LIFT = { valor: 2.6, ic: [1.3, 4.4] };     // validacion.md: umbrales iniciales, antes de calibrar
const M3_PERSONA_ANO = 36.5;                       // 100 l/día (Corte Suprema, 2021)
const M3_LATA = 0.000473;                          // lata de 473 ml
const M3_TORRE = 450000;                           // Torre Costanera: estimación propia (107.125 m² × ~4,2 m por piso)
const FISC_ANO = 33;                               // fiscalizaciones por extracción al año, Z1+Z2 2020–2025 (impacto.md)

const nf = (d = 0) => new Intl.NumberFormat('es-CL', { minimumFractionDigits: d, maximumFractionDigits: d });
const fmt = (v, d = 0) => (Number.isFinite(v) ? nf(d).format(v) : '—');
const num = v => (v == null || v === '' ? NaN : Number(v));
const first = (...vs) => { for (const v of vs) { const n = num(v); if (Number.isFinite(n)) return n; } return NaN; };
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

/** Redondeo para decir en voz alta: 2 cifras significativas ("casi 3.000", "220 millones"). */
function spoken(v) {
  if (!Number.isFinite(v) || v <= 0) return { txt: '—', pre: '' };
  const mag = 10 ** Math.max(0, Math.floor(Math.log10(v)) - 1);
  let r = Math.round(v / mag) * mag;
  // 2.867 → "casi 2.900"; con una cifra (3.000) si queda a menos del 5 %
  const one = 10 ** Math.floor(Math.log10(v));
  const r1 = Math.round(v / one) * one;
  if (Math.abs(r1 - v) / v < 0.05) r = r1;
  const pre = r > v * 1.001 ? 'casi ' : r < v * 0.999 ? 'más de ' : '';
  return { r, pre };
}
function millones(v) {
  if (!Number.isFinite(v)) return '—';
  if (v >= 1e6) return fmt(v / 1e6, v >= 1e8 ? 0 : 1) + ' millones';
  return fmt(v);
}

/**
 * Normaliza el JSON a las cifras del panel. Acepta el bloque "pitch" con nombres flexibles (lo escribe T1)
 * y cae al bloque base de M9 cuando falta algo que se pueda calcular desde ahí.
 */
export function cifras(j) {
  const p = j?.pitch || {};
  const esc_ = j?.escenarios || {};

  // 1 · lift
  const L = p.lift || {};
  const lift = first(L.valor, L.value, L.lift, typeof p.lift === 'number' ? p.lift : null, LIFT.valor);
  const ic = Array.isArray(L.ic95) ? L.ic95 : Array.isArray(L.ic) ? L.ic : [first(L.ic_bajo, L.ic_min, L.lo, LIFT.ic[0]), first(L.ic_alto, L.ic_max, L.hi, LIFT.ic[1])];

  // 2 · un predio
  const P = p.predio || p.candidato || p.equivalencia || {};
  const m3p = first(P.m3_exceso_min, P.m3, P.m3_ano, p.predio_m3_exceso_min);
  const mPers = first(P.m3_persona_ano, P.m3_persona, j?.supuestos?.m3_persona_ano?.central, M3_PERSONA_ANO);
  const mLata = first(P.m3_lata, P.lata_m3, M3_LATA);
  const personas = first(P.personas, P.personas_ano, m3p / mPers);
  const latas = first(P.latas, m3p / mLata);
  const predioId = P.predio_id ?? P.id ?? p.predio_id ?? '';

  // 3 · candidatos sin fiscalizar
  const C = p.candidatos && typeof p.candidatos === 'object' ? p.candidatos : {};
  const candidatos = first(C.n, C.valor, C.total, typeof p.candidatos === 'number' ? p.candidatos : null, j?.candidatos);
  const porZona = C.por_zona || j?.candidatos_por_zona || {};

  // 4 · torres
  const T = p.torres || p.torre || {};
  const m3Torre = first(T.m3_torre, T.m3, M3_TORRE);
  const m3Lo = first(T.m3_ano_conservador, T.m3_min, esc_.conservador?.m3_ano);
  const m3Hi = first(T.m3_ano_central, T.m3_max, esc_.central?.m3_ano);
  const torresLo = first(m3Lo / m3Torre, T.valor_min);
  const torresHi = first(m3Hi / m3Torre, T.valor_max);
  // cifra dicha: mínimo al entero más cercano, máximo hacia abajo (4,7 a 20,7 → "entre 5 y 20", pitch-demo.md)
  const torresMin = first(T.min, Math.round(torresLo));
  const torresMax = first(T.max, Math.floor(torresHi));

  // 5 · años
  const A = p.anos || p.años || p.capacidad || {};
  const candHa = first(A.candidatos_hasta_100ha, A.candidatos, esc_.central?.candidatos);
  const fiscAno = first(A.fiscalizaciones_ano, FISC_ANO);
  const anosValor = first(A.anos_valor, candHa / fiscAno);
  const anos = first(A.anos, Math.round(anosValor));

  return {
    temporada: j?.temporada || '',
    lift, ic,
    m3p, mPers, mLata, personas, latas, predioId,
    candidatos, porZona,
    m3Torre, m3Lo, m3Hi, torresLo, torresHi, torresMin, torresMax, pie: typeof p.pie === 'string' ? p.pie : '',
    candHa, fiscAno, anos, anosValor,
    completo: !!j?.pitch && Number.isFinite(m3p),
  };
}

/* ---------- dibujos (SVG estático, decorativo) ---------- */

function svgPersonas(n = 12) {
  const cols = 6, w = 22, h = 34;
  let g = '';
  for (let i = 0; i < n; i++) {
    const x = (i % cols) * w + 11, y = Math.floor(i / cols) * h + 4;
    g += `<g transform="translate(${x} ${y})"><circle cx="0" cy="5" r="4.6"/><path d="M-8 28v-9a8 8 0 0 1 16 0v9z"/></g>`;
  }
  return `<svg class="im-ico im-pers" viewBox="0 0 ${cols * w} ${Math.ceil(n / cols) * h}" aria-hidden="true">${g}</svg>`;
}

function svgLatas(n = 5) {
  const w = 22;
  let g = '';
  for (let i = 0; i < n; i++) {
    const x = i * w + 2;
    g += `<g transform="translate(${x} 2)"><rect x="1" y="3" width="16" height="36" rx="3"/><rect x="3" y="0" width="12" height="4" rx="1.5" class="im-lid"/><rect x="1" y="14" width="16" height="11" class="im-band"/></g>`;
  }
  return `<svg class="im-ico im-latas" viewBox="0 0 ${n * w + 2} 42" aria-hidden="true">${g}</svg>`;
}

/** 20 torres (máximo del rango): las del escenario conservador llenas, el resto hasta el central en línea. */
function svgTorres(lo, hi) {
  const nLo = Math.max(0, Math.round(lo)), nHi = Math.max(nLo, Math.round(hi));
  const n = Number.isFinite(nHi) && nHi > 0 ? Math.min(nHi, 30) : 20;
  const w = 15, H = 92;
  // silueta simple: prisma que se angosta arriba, con la corona abierta de la Gran Torre Santiago
  const tower = 'M1 92V20L3 6h6l2 14v72z';
  const crown = 'M3 6L4 0M9 6L8 0';
  let g = '';
  for (let i = 0; i < n; i++) {
    const solid = i < nLo;
    g += `<g transform="translate(${i * w + 2} 2)" class="${solid ? 'im-t-lo' : 'im-t-hi'}"><path d="${tower}"/><path d="${crown}" class="im-crown"/></g>`;
  }
  return `<svg class="im-ico im-torres" viewBox="0 0 ${n * w + 2} ${H + 4}" aria-hidden="true">${g}</svg>`;
}

/* ---------- panel ---------- */

let root = null, lastFocus = null, retry = 0, openState = false;

function build() {
  if (root) return root;
  root = document.createElement('section');
  root.id = 'impacto-panel';
  root.className = 'impacto';
  root.setAttribute('role', 'dialog');
  root.setAttribute('aria-modal', 'true');
  root.setAttribute('aria-labelledby', 'im-title');
  root.tabIndex = -1;
  root.hidden = true;
  root.innerHTML = `
    <div class="im-inner">
      <header class="im-head">
        <p class="im-kicker" id="im-title">Impacto · <span id="im-temp">temporada 2025-26</span> · Petorca y Aconcagua bajo</p>
        <button class="btn im-close" id="im-close" type="button" aria-label="Cerrar el panel de impacto">Cerrar <span aria-hidden="true">×</span></button>
      </header>
      <ol class="im-list" id="im-list"><li class="im-loading">Cargando cifras…</li></ol>
      <footer class="im-foot" id="im-foot"></footer>
    </div>`;
  document.body.appendChild(root);
  root.querySelector('#im-close').addEventListener('click', () => closeImpacto());
  // fuera del contenido = cerrar
  root.addEventListener('click', e => { if (e.target === root) closeImpacto(); });
  // Escape antes que el handler de main.js (que miraría el modo del escenario)
  window.addEventListener('keydown', e => {
    if (!openState || e.key !== 'Escape') return;
    e.preventDefault(); e.stopPropagation();
    closeImpacto();
  }, true);
  root.addEventListener('keydown', e => {
    if (e.key !== 'Tab') return;
    const f = [...root.querySelectorAll('button, a[href]')].filter(el => !el.hidden && el.offsetParent !== null);
    if (!f.length) return;
    const a = f[0], z = f[f.length - 1];
    if (e.shiftKey && document.activeElement === a) { e.preventDefault(); z.focus(); }
    else if (!e.shiftKey && document.activeElement === z) { e.preventDefault(); a.focus(); }
  });
  // atrás del navegador / otro enlace: el panel se cierra si el hash ya no es #impacto
  const sync = () => { if (openState && location.hash !== '#impacto') closeImpacto({ keepHash: true }); };
  window.addEventListener('hashchange', sync);
  window.addEventListener('popstate', sync);
  return root;
}

function render(c) {
  const list = root.querySelector('#im-list');
  const pers = spoken(c.personas), lat = spoken(c.latas);
  const persTxt = Number.isFinite(c.personas) ? `${pers.pre}${fmt(pers.r)}` : '—';
  const latTxt = Number.isFinite(c.latas) ? `${lat.pre}${millones(lat.r)}` : '—';
  const tLo = c.torresMin, tHi = c.torresMax;
  const zonas = Object.entries(c.porZona || {}).map(([z, n]) => `${esc(z)} ${fmt(num(n))}`).join(' · ');

  list.innerHTML = `
    <li class="im-row">
      <span class="im-n" aria-hidden="true">1</span>
      <p class="im-big">${fmt(c.lift, 1)}<small>×</small></p>
      <div class="im-txt"><b>más infractores que al azar</b><span>donde Caudal marca alerta alta · IC 95 %: ${fmt(c.ic[0], 1)}–${fmt(c.ic[1], 1)}</span></div>
    </li>
    <li class="im-row im-row-draw">
      <span class="im-n" aria-hidden="true">2</span>
      <p class="im-big">1<small>predio</small></p>
      <div class="im-eq">
        <div class="im-eq-i">${svgPersonas()}<p><b>= el agua de ${persTxt} personas</b><span>al año</span></p></div>
        <div class="im-eq-i">${svgLatas()}<p><b>= ${latTxt} de latas</b><span>de Monster, de 473 ml</span></p></div>
      </div>
    </li>
    <li class="im-row">
      <span class="im-n" aria-hidden="true">3</span>
      <p class="im-big">${fmt(c.candidatos)}</p>
      <div class="im-txt"><b>predios en alerta alta sin fiscalizar</b><span>ninguna fiscalización DGA a 500 m desde 2018${zonas ? ' · ' + zonas : ''}</span></div>
    </li>
    <li class="im-row im-row-draw">
      <span class="im-n" aria-hidden="true">4</span>
      <p class="im-big">${Number.isFinite(tLo) ? fmt(tLo) : '—'}<small>a</small>${Number.isFinite(tHi) ? fmt(tHi) : '—'}</p>
      <div class="im-eq im-eq-t">
        ${svgTorres(tLo, tHi)}
        <p><b>Torres Costanera de agua, todos los años</b><span><i class="im-k im-k-lo"></i>escenario conservador <i class="im-k im-k-hi"></i>hasta el central</span></p>
      </div>
    </li>
    <li class="im-row">
      <span class="im-n" aria-hidden="true">5</span>
      <p class="im-big">${fmt(c.anos)}<small>años</small></p>
      <div class="im-txt"><b>para revisarlos uno por uno</b><span>al ritmo actual de la DGA en las dos zonas</span></div>
    </li>`;

  const foot = root.querySelector('#im-foot');
  foot.innerHTML = `
    <p>
      <span>1 · Lift con los umbrales iniciales, fijados antes de mirar los casos (19 positivos DGA, validacion.md).</span>
      <span>2 · Predio ${esc(c.predioId || '—')}: exceso mínimo ${fmt(c.m3p)} m³/año ÷ ${fmt(c.mPers, 1)} m³ por persona (100 l/día) = ${fmt(c.personas)} personas; ÷ 473 ml = ${fmt(c.latas / 1e6, 1)} millones de latas.</span>
      <span>3 · Banda alta, temporada ${esc(c.temporada || '2025-26')}, M9 (impacto.json).</span>
      <span>4 · ${c.pie ? esc(c.pie) : `${fmt(c.m3Lo / 1e6, 1)} a ${fmt(c.m3Hi / 1e6, 1)} millones de m³ al año · torre estimada en ${fmt(c.m3Torre)} m³`} (escenarios conservador y central, hasta 100 ha; ${fmt(c.torresLo, 1)} a ${fmt(c.torresHi, 1)} torres).</span>
      <span>5 · ${fmt(c.candHa)} candidatos de hasta 100 ha ÷ ${fmt(c.fiscAno, Number.isInteger(c.fiscAno) ? 0 : 1)} fiscalizaciones por extracción al año (DGA, Z1 y Z2, 2020–2025) = ${fmt(c.anosValor, 1)} años.</span>
    </p>
    <p class="im-principle">Cifras agregadas, en rango: no identifican dueños ni roles. Un candidato no es un caso. Caudal prioriza, no acusa.</p>`;
  if (c.temporada) root.querySelector('#im-temp').textContent = 'temporada ' + c.temporada;
}

async function load() {
  clearTimeout(retry);
  const list = root.querySelector('#im-list');
  try {
    const r = await fetch(URL_IMPACTO, { cache: 'no-cache' });
    if (!r.ok) throw new Error('impacto ' + r.status);
    const j = await r.json();
    const c = cifras(j);
    render(c);
    root.dataset.ready = c.completo ? 'done' : 'partial';
    // falta el bloque "pitch" (lo escribe build_m5_web.py): reintentar mientras el panel esté abierto
    if (!c.completo && openState) retry = setTimeout(load, RETRY_MS);
  } catch (err) {
    console.warn('[Caudal] impacto:', err?.message || err);
    if (!list.querySelector('.im-row')) list.innerHTML = '<li class="im-loading im-error">No se pudieron cargar las cifras de impacto. Reintentando…</li>';
    root.dataset.ready = 'error';
    if (openState) retry = setTimeout(load, RETRY_MS);
  }
}

export function isOpen() { return openState; }

export function openImpacto() {
  build();
  if (!openState) {
    lastFocus = document.activeElement;
    openState = true;
    root.hidden = false;
    document.documentElement.classList.add('impacto-open');
    // el mapa queda detrás, atenuado: volver al tope de la página
    window.scrollTo({ top: 0, behavior: 'auto' });
    requestAnimationFrame(() => root.classList.add('on'));
    root.focus({ preventScroll: true });
  }
  // entrada propia en el historial: atrás (o Cerrar) vuelve a donde estaba, con su hash (#z2, #caso-…)
  if (location.hash !== '#impacto') history.pushState({ caudalImpacto: 1 }, '', '#impacto');
  load();
}

export function closeImpacto({ keepHash = false } = {}) {
  if (!root || !openState) return;
  openState = false;
  clearTimeout(retry);
  root.classList.remove('on');
  root.hidden = true;
  document.documentElement.classList.remove('impacto-open');
  if (!keepHash && location.hash === '#impacto') {
    if (history.state?.caudalImpacto) history.back();
    else history.replaceState(null, '', location.pathname + location.search);   // abrió en frío con #impacto
  }
  if (lastFocus && typeof lastFocus.focus === 'function' && document.contains(lastFocus)) lastFocus.focus({ preventScroll: true });
  lastFocus = null;
}
