// Caudal · panel de ruta de inspección (la decisión física del sistema).
import { BAND_SHORT, fmtNum, fmtMin, esc } from './petorca-data.js';

export function renderRuta(el, data, { onPlay, onStop, onGPX } = {}) {
  if (!el) return null;
  const r = data.ruta;
  const paradas = (r.paradas || []).slice().sort((a, b) => a.orden - b.orden);
  const ini = r.inicio || {};
  const reg = r.regreso || {};
  const banda = s => s.banda || data.byId.get(s.predio_id)?.properties.banda || 'baja';

  // Google Maps directions: start → stops in optimized order → back to start (driving).
  const ll = p => `${(+p.lat).toFixed(6)},${(+p.lon).toFixed(6)}`;
  const gmapsUrl = (ini.lat != null && paradas.length)
    ? 'https://www.google.com/maps/dir/?api=1&travelmode=driving'
      + `&origin=${encodeURIComponent(ll(ini))}`
      + `&destination=${encodeURIComponent(ll(reg.lat != null ? reg : ini))}`
      + `&waypoints=${encodeURIComponent(paradas.map(ll).join('|'))}`
    : null;

  el.innerHTML = `
    <header class="pn-fh">
      <h3 class="pn-title">${paradas.length} paradas · ${fmtNum(+r.distancia_km, 1)} km</h3>
      <p class="pn-sub">${esc(ini.hora || '')}–${esc(reg.llegada || '')} · ida y vuelta desde ${esc(ini.nombre || 'el inicio')}</p>
    </header>
    <div class="pn-prog" aria-hidden="true"><i></i></div>
    <ol class="pn-stops">
      <li class="pn-stop pn-stop-base"><span class="pn-ord">⌂</span><span class="pn-st-main"><b>${esc(ini.nombre || 'Inicio')}</b><small>Salida ${esc(ini.hora || '')}</small></span></li>
      ${paradas.map(s => `<li><button type="button" class="pn-stop" data-orden="${s.orden}" data-id="${esc(s.predio_id)}" aria-label="Parada ${s.orden}: predio ${esc(s.predio_id)}">
        <span class="pn-ord">${s.orden}</span>
        <span class="pn-st-main"><b>${esc(s.predio_id)}</b> <span class="pn-pill pn-${banda(s)}">${esc(BAND_SHORT[banda(s)] || '')}</span></span>
        <span class="pn-st-time"><b>${esc(s.llegada)}</b></span>
      </button></li>`).join('')}
      <li class="pn-stop pn-stop-base"><span class="pn-ord">⌂</span><span class="pn-st-main"><b>${esc(reg.nombre || 'Regreso')}</b><small>${fmtNum(+(reg.distancia_km_acum ?? r.distancia_km), 1)} km</small></span><span class="pn-st-time"><b>${esc(reg.llegada || '')}</b></span></li>
    </ol>
    <div class="pn-actions">
      <button type="button" class="btn primary" data-act="play">▶ Recorrer ruta</button>
      ${gmapsUrl ? `<a class="btn" data-act="gmaps" href="${esc(gmapsUrl)}" target="_blank" rel="noopener">Abrir en Google Maps ↗</a>` : ''}
    </div>
    <p class="pn-note"><a data-act="gpx" href="${esc(data.gpxUrl || data.base + 'ruta.gpx')}" download="caudal-ruta-petorca.gpx">Descargar GPX</a> para otras apps de navegación.</p>
    <p class="pn-note">Orden óptimo (OR-Tools) sobre caminos reales. Es la decisión física del sistema.</p>`;

  const playBtn = el.querySelector('[data-act="play"]');
  const bar = el.querySelector('.pn-prog i');
  const stops = [...el.querySelectorAll('button.pn-stop')];

  const api = {
    setActiveStop(orden) {
      for (const b of stops) {
        const o = +b.dataset.orden;
        b.classList.toggle('is-done', orden != null && o < orden);
        b.classList.toggle('is-active', o === orden);
      }
      el.querySelector(`button.pn-stop[data-orden="${orden}"]`)?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    },
    setProgress(t) {
      if (bar) bar.style.transform = `scaleX(${Math.max(0, Math.min(1, t || 0))})`;
    },
  };

  el.onclick = async e => {
    const t = e.target.closest('[data-act], button.pn-stop');
    if (!t) return;
    if (t.matches('button.pn-stop')) { api.setActiveStop(+t.dataset.orden); onStop?.(t.dataset.id, +t.dataset.orden); return; }
    const act = t.dataset.act;
    if (act === 'gpx') { onGPX?.(); return; }
    if (act === 'play' && !playBtn.disabled) {
      playBtn.disabled = true;
      playBtn.textContent = 'Recorriendo…';
      api.setActiveStop(null); api.setProgress(0);
      try { await onPlay?.(); } catch (err) { console.error('[Caudal] ruta:', err); }
      finally {
        playBtn.disabled = false;
        playBtn.textContent = '↻ Recorrer de nuevo';
      }
    }
  };
  return api;
}
