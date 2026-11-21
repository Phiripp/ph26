// intro-title.js — animated landing title shown on the LEFT of the stage, over the map.
//
// PLACEHOLDER: the project name, kicker and tagline below are temporary copy.
// Change them in TITLE_CONFIG (or pass `config` to showTitle) — nothing else needs touching.
//
// Behaviour:
//   - Builds a non-interactive block (pointer-events: none) inside header.stage.
//   - Animation (CSS, css/intro.css): kicker fades in, letters rise from a baseline
//     as cyan outlines and fill with "water" from the bottom, a light band sweeps
//     across the word once, a thin cyan line draws under it, then the tagline types in.
//     Everything plays ONCE (~3 s) and then stays still (no loops after the intro).
//   - prefers-reduced-motion: static end state (CSS drops every animation).
//   - Hides itself (fade/slide out ~400 ms, then removed from the DOM) on the first
//     USER interaction with the map: user-initiated movestart/zoomstart/rotatestart/
//     pitchstart (event has originalEvent), wheel / pointerdown / touchstart on the map
//     container (covers marker clicks), arrow/+/- keys, a hash change, or the stage
//     leaving landing mode (data-mode !== "landing"). Programmatic camera moves
//     (flyTo/easeTo without originalEvent) do NOT hide it.

/** PLACEHOLDER copy — edit here. */
export const TITLE_CONFIG = {
  name: 'CAUDAL',                                   // PLACEHOLDER project name
  kicker: 'Platanus Hack 26 · Physical World',      // PLACEHOLDER kicker
  tagline: 'Agua vista desde el espacio',           // PLACEHOLDER tagline
  sub: '',                                          // optional mono line under the tagline ('' = none)
};

const HIDE_MS = 400;
const NAV_KEYS = new Set(['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', '+', '-', '=', '_', 'PageUp', 'PageDown']);

const reducedMotion = () => {
  try { return matchMedia('(prefers-reduced-motion: reduce)').matches; } catch { return false; }
};

function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
}

const LOGO_URL = 'assets/logo.svg';

function buildDom(cfg) {
  const root = el('div', 'intro-title');
  root.setAttribute('data-intro-title', '');

  const wrap = el('div', 'wrap it-wrap');
  const block = el('div', 'it-block');

  // logo (decorative here: the name right below is the accessible text)
  const logo = el('img', 'it-logo');
  logo.src = LOGO_URL;
  logo.alt = '';
  logo.decoding = 'async';
  logo.addEventListener('error', () => logo.remove(), { once: true });
  block.append(logo);

  // kicker
  if (cfg.kicker) {
    const k = el('p', 'it-kicker');
    const dot = el('span', 'it-dot'); dot.setAttribute('aria-hidden', 'true');
    const rule = el('span', 'it-rule'); rule.setAttribute('aria-hidden', 'true');
    k.append(dot, el('span', '', cfg.kicker), rule);
    block.append(k);
  }

  // name: h1 only if the page has none (the landing currently has no h1)
  const nameTag = document.querySelector('h1') ? 'p' : 'h1';
  const name = el(nameTag, 'it-name');
  name.setAttribute('aria-label', cfg.name);
  name.dataset.text = cfg.name; // feeds the ::after shine layer
  [...cfg.name].forEach((ch, i) => {
    const slot = el('span', 'it-slot');
    slot.setAttribute('aria-hidden', 'true');
    const c = el('span', 'it-ch', ch === ' ' ? ' ' : ch);
    c.style.setProperty('--i', String(i));
    slot.append(c);
    name.append(slot);
  });
  block.append(name);

  const line = el('span', 'it-line'); line.setAttribute('aria-hidden', 'true');
  block.append(line);

  // tagline, one span per character for the type-in (text exposed via aria-label)
  if (cfg.tagline) {
    const t = el('p', 'it-tagline');
    t.setAttribute('aria-label', cfg.tagline);
    let idx = 0;
    // keep words unbreakable so the reveal never re-wraps mid-word
    cfg.tagline.split(/(\s+)/).forEach((part) => {
      if (!part) return;
      if (/^\s+$/.test(part)) { t.append(document.createTextNode(' ')); idx++; return; }
      const w = el('span', 'it-w'); w.style.whiteSpace = 'nowrap'; w.setAttribute('aria-hidden', 'true');
      for (const ch of part) {
        const c = el('span', 'it-c', ch);
        c.style.setProperty('--c', String(idx++));
        w.append(c);
      }
      t.append(w);
    });
    block.append(t);
  }

  block.append(el('p', 'it-sub', cfg.sub || ''));

  wrap.append(block);
  root.append(wrap);
  return { root, block, name };
}

/**
 * Show the animated title.
 * @param {object} opts
 * @param {HTMLElement} opts.stage   header.stage (title is appended here)
 * @param {object|null} opts.map     maplibre Map instance (optional; falls back to #map element)
 * @param {object} [opts.config]     overrides for TITLE_CONFIG
 * @param {number} [opts.delay=0]    ms before the animation starts
 * @param {boolean} [opts.autoHide=true] wire "hide on first user interaction"
 * @param {(reason:string)=>void} [opts.onHide]
 * @returns {{ el: HTMLElement, hide: (reason?: string) => Promise<void>, hidden: Promise<void> }}
 */
export function showTitle({ stage, map = null, config = {}, delay = 0, autoHide = true, onHide } = {}) {
  stage = stage || document.getElementById('top') || document.body;
  const cfg = { ...TITLE_CONFIG, ...config };

  // only one title at a time
  stage.querySelectorAll('[data-intro-title]').forEach((n) => n.remove());

  const { root, block, name } = buildDom(cfg);
  root.style.setProperty('--it-d', `${Math.max(0, delay | 0)}ms`);
  stage.append(root);

  let resolveHidden;
  const hidden = new Promise((r) => { resolveHidden = r; });
  let state = 'shown';
  const cleanups = [];
  const on = (target, type, fn, opts) => {
    if (!target) return;
    target.addEventListener(type, fn, opts);
    cleanups.push(() => target.removeEventListener(type, fn, opts));
  };

  // ---- keep the word on the left of Chile (wide screens) -------------------
  const fit = () => {
    if (state !== 'shown') return;
    root.style.removeProperty('--it-size');
    const sw = stage.clientWidth;
    if (sw < 700) return; // narrow layout puts the title on top (CSS)
    const sr = stage.getBoundingClientRect();
    const right = name.getBoundingClientRect().right - sr.left;
    const limit = sw * 0.42; // Chile sits around the horizontal centre of the home view
    if (right > limit) {
      const cur = parseFloat(getComputedStyle(name).fontSize) || 100;
      const left = block.getBoundingClientRect().left - sr.left;
      const k = Math.max(0.45, (limit - left) / Math.max(1, right - left));
      root.style.setProperty('--it-size', `${Math.floor(cur * k)}px`);
    }
  };
  fit();
  try { document.fonts?.ready.then(fit); } catch { /* ignore */ }
  let fitRaf = 0;
  on(window, 'resize', () => { cancelAnimationFrame(fitRaf); fitRaf = requestAnimationFrame(fit); });

  // ---- hide -----------------------------------------------------------------
  function hide(reason = 'manual') {
    if (state !== 'shown') return hidden;
    state = 'leaving';
    cleanups.splice(0).forEach((fn) => { try { fn(); } catch { /* ignore */ } });
    const finish = () => {
      if (state === 'gone') return;
      state = 'gone';
      root.remove();
      try { onHide?.(reason); } catch (e) { console.error(e); }
      resolveHidden();
    };
    if (reducedMotion()) { finish(); return hidden; }
    root.classList.add('is-leaving');
    root.addEventListener('transitionend', (e) => { if (e.target === root) finish(); });
    setTimeout(finish, HIDE_MS + 120); // safety net
    return hidden;
  }

  // ---- auto-hide on first user interaction ----------------------------------
  if (autoHide) {
    const byUser = (e) => { if (e && e.originalEvent) hide(`map:${e.type}`); };
    if (map && typeof map.on === 'function') {
      const types = ['movestart', 'zoomstart', 'rotatestart', 'pitchstart', 'dragstart'];
      types.forEach((t) => map.on(t, byUser));
      cleanups.push(() => types.forEach((t) => { try { map.off(t, byUser); } catch { /* ignore */ } }));
    }
    let container = null;
    try { container = map?.getContainer?.() || null; } catch { /* ignore */ }
    container = container || stage.querySelector('#map');
    const direct = (e) => hide(`dom:${e.type}`);
    on(container, 'wheel', direct, { passive: true });
    on(container, 'pointerdown', direct, { passive: true });
    on(container, 'touchstart', direct, { passive: true });
    on(container, 'click', direct, true); // marker clicks (capture), in case pointerdown is swallowed

    on(window, 'keydown', (e) => {
      if (e.defaultPrevented || e.metaKey || e.ctrlKey || e.altKey) return;
      if (!NAV_KEYS.has(e.key)) return;
      const t = e.target;
      if (t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName))) return;
      hide(`key:${e.key}`);
    });
    on(window, 'hashchange', () => hide('hash'));

    // stage leaves landing mode (valle / lagoon / transitions)
    try {
      const mo = new MutationObserver(() => {
        const m = stage.getAttribute('data-mode');
        if (m && m !== 'landing') hide('mode');
      });
      mo.observe(stage, { attributes: true, attributeFilter: ['data-mode'] });
      cleanups.push(() => mo.disconnect());
    } catch { /* ignore */ }
  }

  return { el: root, hide, hidden };
}

export default showTitle;
