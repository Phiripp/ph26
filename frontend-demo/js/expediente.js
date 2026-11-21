// Caudal · borrador de expediente siguiendo la "Guía para la presentación de denuncias" DGA.
// Caudal prepara; una PERSONA presenta con Clave Única. Caudal no presenta nada.
import { fmtNum, fmtMil, fmtCoord, fmtDate, excesoRange, dryWindowStats, esc } from './petorca-data.js';

function croquis(feature, W = 150, H = 110) {
  const g = feature.geometry;
  const rings = g.type === 'Polygon' ? [g.coordinates[0]] : g.type === 'MultiPolygon' ? g.coordinates.map(p => p[0]) : [];
  const pts = rings.flat();
  if (!pts.length) return '';
  const lat0 = pts.reduce((a, c) => a + c[1], 0) / pts.length, k = Math.cos(lat0 * Math.PI / 180);
  const xs = pts.map(c => c[0] * k), ys = pts.map(c => c[1]);
  const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
  const pad = 12, s = Math.min((W - 2 * pad) / (x1 - x0 || 1), (H - 2 * pad) / (y1 - y0 || 1));
  const ox = (W - (x1 - x0) * s) / 2, oy = (H - (y1 - y0) * s) / 2;
  const d = rings.map(r => r.map((c, i) => (i ? 'L' : 'M') + (ox + (c[0] * k - x0) * s).toFixed(1) + ' ' + (oy + (y1 - c[1]) * s).toFixed(1)).join('') + 'Z').join('');
  const [cx, cy] = feature.properties.centroid;
  const px = ox + (cx * k - x0) * s, py = oy + (y1 - cy) * s;
  return `<svg class="pn-croquis" viewBox="0 0 ${W} ${H}" role="img" aria-label="Croquis del polígono del predio"><path class="pn-cq-poly" d="${d}"/><circle class="pn-cq-c" cx="${px.toFixed(1)}" cy="${py.toFixed(1)}" r="2.5"/><text class="pn-cq-n" x="${W - 8}" y="16" text-anchor="end">N ↑</text></svg>`;
}

function hechos(p, data) {
  const st = dryWindowStats(data, p.id, 2024);
  const ex = excesoRange(p);
  const parts = [];
  if (st) {
    parts.push(`Entre el ${fmtDate(st.win.inicio)} y el ${fmtDate(st.win.fin)} (${st.win.dias} días) no se registró lluvia efectiva (< 1 mm/día) en el valle de Petorca, según reanálisis Open-Meteo ERA5.`);
    if (st.ndvi != null) parts.push(`En ese período, el predio ${p.id} (${p.cultivo}, ${fmtNum(p.area_ha, 2)} ha) mantuvo un NDVI medio de ${fmtNum(st.ndvi, 2)} y un NDMI de ${fmtNum(st.ndmi, 2)} (Sentinel-2 L2A), frente a ${fmtNum(st.refNdvi, 2)} y ${fmtNum(st.refNdmi, 2)} de la vegetación de secano de referencia. ${st.ndmi > st.refNdmi ? 'Vegetación verde y húmeda sin lluvia sugiere riego.' : 'Vegetación más verde que el secano sin lluvia sugiere riego.'}`);
  }
  parts.push(`Con el método FAO-56 simplificado (Kc a partir de NDVI, ET0 y lluvia mensuales), el consumo estimado del predio para 2024 se sitúa entre ${fmtMil(p.m3_estimado_min)} y ${fmtMil(p.m3_estimado_max)} mil m³, frente a un derecho registrado de ${fmtMil(p.m3_derecho)} mil m³/año${ex.hi > 0 ? ` (posible exceso de ${fmtMil(ex.lo)} a ${fmtMil(ex.hi)} mil m³)` : ''}. Confianza de la estimación: ${p.confianza}${(p.confianza_motivos || []).length ? ` (${p.confianza_motivos.join('; ')})` : ''}.`);
  parts.push('Estos antecedentes son un indicio para priorizar la fiscalización en terreno; no constituyen prueba ni identifican a personas.');
  return parts.join('\n\n');
}

const ADJUNTOS = p => [
  `Serie mensual NDVI/NDMI 2022–2024 del predio ${p.id} y de la referencia de secano (Sentinel-2 L2A, Element84 Earth Search)`,
  'Imágenes satelitales antes/después de la ventana seca (color natural e infrarrojo)',
  'Cálculo de consumo FAO-56 simplificado (método descrito en data/petorca/README.md)',
  'Registro de derechos de aprovechamiento consultados (CPA/DGA) — ilustrativo en esta demo',
  'Ventanas secas detectadas (Open-Meteo ERA5, ≥ 10 días con lluvia < 1 mm)',
];

export function renderExpediente(el, feature, data, { onBack } = {}) {
  if (!el || !feature) return;
  const p = feature.properties;
  const [lon, lat] = p.centroid;
  const draft = hechos(p, data);
  const fields = [['nombre', 'Nombre completo'], ['rut', 'RUT'], ['domicilio', 'Domicilio'], ['correo', 'Correo electrónico'], ['telefono', 'Teléfono']];

  el.innerHTML = `
    <button type="button" class="pn-back" data-act="back">← Ficha ${esc(p.id)}</button>
    <header class="pn-fh">
      <p class="pn-kicker">Borrador de expediente · formato guía DGA</p>
      <h3 class="pn-title">Expediente ${esc(p.id)}</h3>
      <p class="pn-sub">Caudal ordena los antecedentes. La presentación la hace una persona.</p>
    </header>
    <ol class="pn-exp">
      <li class="pn-sec"><h4>1 · Denunciante</h4>
        <p class="pn-hint">Lo completa la persona con Clave Única. Caudal no guarda ni sugiere estos datos.</p>
        <div class="pn-fields">${fields.map(([k, l]) => `<label><span>${l}</span><input type="text" name="${k}" autocomplete="off" placeholder="—"></label>`).join('')}</div>
      </li>
      <li class="pn-sec"><h4>2 · Ubicación</h4>
        <div class="pn-ubic">
          <dl class="pn-dl">
            <div><dt>Predio</dt><dd>${esc(p.id)}</dd></div>
            <div><dt>Comuna</dt><dd>Petorca</dd></div>
            <div><dt>Región</dt><dd>Valparaíso</dd></div>
            <div><dt>Coordenadas</dt><dd>${fmtCoord(lon, lat)}</dd></div>
            <div><dt>Área</dt><dd>${fmtNum(p.area_ha, 2)} ha</dd></div>
          </dl>
          ${croquis(feature)}
        </div>
      </li>
      <li class="pn-sec"><h4>3 · Descripción de los hechos <em class="pn-tag">borrador automático</em></h4>
        <textarea class="pn-ta" name="hechos" rows="12">${esc(draft)}</textarea>
      </li>
      <li class="pn-sec"><h4>4 · Afectación del denunciante</h4>
        <p class="pn-hint">Caudal no puede escribir esto. Describe cómo te afecta: pozo o APR con menos agua, cultivo propio sin riego, fechas y lugares concretos.</p>
        <textarea class="pn-ta" name="afectacion" rows="4" placeholder="Escríbelo con tus palabras…"></textarea>
      </li>
      <li class="pn-sec"><h4>5 · Adjuntos</h4>
        <ul class="pn-adj">${ADJUNTOS(p).map(a => `<li>${esc(a)}</li>`).join('')}</ul>
      </li>
    </ol>
    <div class="pn-actions">
      <button type="button" class="btn primary" data-act="copy">Copiar texto</button>
      <button type="button" class="btn" data-act="txt">Descargar borrador (.txt)</button>
      <span class="pn-status" role="status" aria-live="polite"></span>
    </div>
    <p class="pn-legal">Se presenta en la Oficina Virtual DGA (SNIA) con Clave Única. Caudal no presenta nada.</p>`;

  const val = n => el.querySelector(`[name="${n}"]`)?.value.trim() || '';
  const text = () => {
    const L = [];
    L.push(`BORRADOR DE EXPEDIENTE — Predio ${p.id} — Valle de Petorca`);
    L.push('Preparado con Caudal. Se presenta en la Oficina Virtual DGA (SNIA) con Clave Única. Caudal no presenta nada.', '');
    L.push('1. DENUNCIANTE');
    for (const [k, l] of fields) L.push(`${l}: ${val(k) || '[completar]'}`);
    L.push('', '2. UBICACIÓN', `Predio: ${p.id}`, 'Comuna: Petorca', 'Región: Valparaíso', `Coordenadas (centroide): ${fmtCoord(lon, lat)} (${lat}, ${lon})`, `Área: ${fmtNum(p.area_ha, 2)} ha`);
    L.push('', '3. DESCRIPCIÓN DE LOS HECHOS', val('hechos') || draft);
    L.push('', '4. AFECTACIÓN DEL DENUNCIANTE', val('afectacion') || '[completar por la persona que presenta]');
    L.push('', '5. ADJUNTOS', ...ADJUNTOS(p).map(a => `- ${a}`));
    return L.join('\n');
  };
  const status = msg => { const s = el.querySelector('.pn-status'); if (s) { s.textContent = msg; clearTimeout(s._t); s._t = setTimeout(() => (s.textContent = ''), 2600); } };
  async function copy() {
    const t = text();
    try { await navigator.clipboard.writeText(t); status('Texto copiado'); return; } catch { /* fallback */ }
    const ta = document.createElement('textarea');
    ta.value = t; ta.setAttribute('readonly', ''); ta.style.cssText = 'position:fixed;left:-9999px;top:0';
    document.body.appendChild(ta); ta.select();
    let ok = false; try { ok = document.execCommand('copy'); } catch { ok = false; }
    ta.remove();
    status(ok ? 'Texto copiado' : 'No se pudo copiar: usa Descargar');
  }
  function download() {
    const url = URL.createObjectURL(new Blob([text()], { type: 'text/plain;charset=utf-8' }));
    const a = Object.assign(document.createElement('a'), { href: url, download: `caudal-expediente-${p.id}.txt` });
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    status('Borrador descargado');
  }
  el.onclick = e => {
    const a = e.target.closest('[data-act]')?.dataset.act;
    if (a === 'back') onBack?.();
    else if (a === 'copy') copy();
    else if (a === 'txt') download();
  };
  el.scrollTop = 0;
  return { getText: text };
}
