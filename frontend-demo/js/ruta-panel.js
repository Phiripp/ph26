// Caudal · panel de ruta de inspección (la decisión física del sistema).
// Lee la ruta de M8 (data/zonas/{z}/ruta.json = data/processed/ruta_z*.json, formato sin cambios):
//   {inicio:{nombre, lon, lat, acceso_lon, acceso_lat}, hora_inicio, hora_termino, total_min, total_km,
//    n_candidatos, n_visitados, min_por_visita, jornada_h, fuente,
//    paradas:[{orden, predio_id, lon, lat, acceso_lon, acceso_lat, llegada, salida, min_desde_anterior, km_desde_anterior}],
//    fuera:[{predio_id, motivo, ...}]}
// Tolera el formato anterior (distancia_km, duracion_min, inicio.hora, regreso) por si la zona aún no se regeneró.
import { BAND_SHORT, fmtNum, esc } from './zona-data.js';

// Google Maps (api=1) acepta hasta 9 puntos intermedios por enlace: más paradas se parten en tramos
const GMAPS_MAX_WAYPOINTS = 9;

const num = v => (v == null || v === '' || Number.isNaN(+v) ? null : +v);

/** "sale de la Plaza de Armas de Quillota" / "sale de Hijuelas" */
function saleDe(nombre) {
  const n = String(nombre || '').trim();
  if (!n) return 'sale del punto de inicio';
  return /^(plaza|municipalidad|oficina|sede)/i.test(n) ? `sale de la ${n}` : `sale de ${n}`;
}

/** total minutes → "8 horas" / "7,5 horas" / "45 min" */
function fmtHoras(min) {
  if (min == null) return null;
  if (min < 60) return `${Math.round(min)} min`;
  const h = Math.round(min / 30) / 2; // nearest half hour
  return `${fmtNum(h, h % 1 ? 1 : 0)} ${h === 1 ? 'hora' : 'horas'}`;
}

export function renderRuta(el, data, { onPlay, onStop, onGPX } = {}) {
  if (!el) return null;
  const r = data.ruta;
  if (!r || !(r.paradas || []).length) {
    el.innerHTML = `<p class="pn-note">Sin ruta de inspección para esta zona todavía.</p>`;
    return { setActiveStop() {}, setProgress() {} };
  }
  const paradas = (r.paradas || []).slice().sort((a, b) => a.orden - b.orden);
  const ini = r.inicio || {};
  const reg = r.regreso || {};
  const props = s => data.byId?.get(String(s.predio_id))?.properties || {};
  const banda = s => props(s).banda || s.banda || null; // unknown predio (zone data not regenerated): no pill
  const caso = s => props(s).caso || s.caso || null;

  const kmTotal = num(r.total_km ?? r.distancia_km ?? reg.distancia_km_acum);
  const minTotal = num(r.total_min ?? r.duracion_min);
  const horaIni = r.hora_inicio || ini.hora || '';
  const horaFin = r.hora_termino || reg.llegada || '';

  // on-road access point when the route provides it (that is where the car stops)
  const ll = p => {
    const lat = num(p.acceso_lat) ?? num(p.lat), lon = num(p.acceso_lon) ?? num(p.lon);
    return lat == null || lon == null ? null : `${lat.toFixed(6)},${lon.toFixed(6)}`;
  };
  // start → stops in the optimised order → back to start, split in legs of ≤ 9 waypoints
  const gmapsLegs = [];
  {
    const back = reg.lat != null ? reg : ini;
    const pts = [ll(ini), ...paradas.map(ll), ll(back)];
    if (pts.every(Boolean) && pts.length > 2) {
      for (let a = 0; a < pts.length - 1; a += GMAPS_MAX_WAYPOINTS + 1) {
        const b = Math.min(a + GMAPS_MAX_WAYPOINTS + 1, pts.length - 1);
        const mid = pts.slice(a + 1, b);
        gmapsLegs.push('https://www.google.com/maps/dir/?api=1&travelmode=driving'
          + `&origin=${encodeURIComponent(pts[a])}&destination=${encodeURIComponent(pts[b])}`
          + (mid.length ? `&waypoints=${encodeURIComponent(mid.join('|'))}` : ''));
      }
    }
  }
  const gmapsBtns = gmapsLegs.length === 1
    ? `<a class="btn" data-act="gmaps" href="${esc(gmapsLegs[0])}" target="_blank" rel="noopener">Abrir en Google Maps ↗</a>`
    : gmapsLegs.map((u, i) => `<a class="btn" data-act="gmaps" href="${esc(u)}" target="_blank" rel="noopener" title="Google Maps admite ${GMAPS_MAX_WAYPOINTS} paradas por enlace">Google Maps ${i + 1}/${gmapsLegs.length} ↗</a>`).join('');

  // spec F5 header: "12 predios · 8 horas · 91 km · sale de la Plaza de …" (title + the "sale de" part below)
  const head = [
    `${paradas.length} predios`,
    fmtHoras(minTotal),
    kmTotal != null ? `${fmtNum(kmTotal, 0)} km` : null,
  ].filter(Boolean).map(s => s.replace(/ /g, ' ')).join(' · '); // keep "143 km" together when it wraps
  const sub = [saleDe(ini.nombre), horaIni ? `${horaIni}${horaFin ? '–' + horaFin : ''}` : null, 'ida y vuelta'].filter(Boolean).join(' · ');

  const tramo = s => {
    const m = num(s.min_desde_anterior), k = num(s.km_desde_anterior);
    if (m == null && k == null) return '';
    return [m != null ? `${fmtNum(m, 0)} min` : null, k != null ? `${fmtNum(k, 1)} km` : null].filter(Boolean).join(' · ');
  };

  const nCand = num(r.n_candidatos);
  const visita = num(r.min_por_visita);
  const jornada = num(r.jornada_h);
  const nota = nCand != null && nCand > paradas.length
    ? `De ${fmtNum(nCand)} predios en prioridad alta y media, ${paradas.length} caben en una jornada${jornada ? ` de ${fmtNum(jornada)} h` : ''}${visita ? ` con ${fmtNum(visita)} min por predio` : ''}. Orden óptimo sobre caminos reales.`
    : 'Orden óptimo sobre caminos reales, priorizando predios en prioridad alta y media.';

  el.innerHTML = `
    <header class="pn-fh">
      <h3 class="pn-title">${esc(head)}</h3>
      <p class="pn-sub">${esc(sub.charAt(0).toUpperCase() + sub.slice(1))}</p>
    </header>
    <div class="pn-prog" aria-hidden="true"><i></i></div>
    <ol class="pn-stops">
      <li class="pn-stop pn-stop-base"><span class="pn-ord">⌂</span><span class="pn-st-main"><b>${esc(ini.nombre || 'Inicio')}</b><small>Salida</small></span><span class="pn-st-time"><b>${esc(horaIni)}</b></span></li>
      ${paradas.map(s => {
        const b = banda(s), tr = tramo(s);
        return `<li><button type="button" class="pn-stop" data-orden="${esc(s.orden)}" data-id="${esc(s.predio_id)}" aria-label="Parada ${esc(s.orden)}: predio ${esc(s.predio_id)}, llegada ${esc(s.llegada || '')}">
        <span class="pn-ord">${esc(s.orden)}</span>
        <span class="pn-st-main"><b>${esc(s.predio_id)}</b>${b && BAND_SHORT[b] ? ` <span class="pn-pill pn-${esc(b)}">${esc(BAND_SHORT[b])}</span>` : ''}${caso(s) ? '<span class="pn-caso">Caso</span>' : ''}${tr ? `<small>${esc(tr)} desde la anterior</small>` : ''}</span>
        <span class="pn-st-time"><b>${esc(s.llegada || '')}</b></span>
      </button></li>`;
      }).join('')}
      <li class="pn-stop pn-stop-base"><span class="pn-ord">⌂</span><span class="pn-st-main"><b>${esc(reg.nombre || ini.nombre || 'Regreso')}</b><small>Regreso${kmTotal != null ? ` · ${fmtNum(kmTotal, 1)} km en total` : ''}</small></span><span class="pn-st-time"><b>${esc(horaFin)}</b></span></li>
    </ol>
    <div class="pn-actions">
      <button type="button" class="btn primary" data-act="play">▶ Recorrer ruta</button>
      ${gmapsBtns}
    </div>
    <p class="pn-note"><a data-act="gpx" href="${esc(data.gpxUrl || data.base + 'ruta.gpx')}" download="caudal-ruta-${esc(data.id || 'zona')}.gpx">Descargar GPX</a> para otras apps de navegación.</p>
    <p class="pn-note">${esc(nota)}</p>`;

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
