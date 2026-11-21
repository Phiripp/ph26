// Caudal · borrador de expediente siguiendo la "Guía para la presentación de denuncias" DGA.
// Caudal prepara; una PERSONA presenta con Clave Única. Caudal no presenta nada.
import { fmtNum, fmtMil, fmtCoord, fmtDate, fmtComuna, excesoRange, dryWindowStats, esc } from './zona-data.js';
import { temporadaOf, seasonRange } from './ficha.js';

function croquis(feature, W = 150, H = 110) {
  const g = feature.geometry;
  const rings = g?.type === 'Polygon' ? [g.coordinates[0]] : g?.type === 'MultiPolygon' ? g.coordinates.map(p => p[0]) : [];
  const pts = rings.flat();
  if (!pts.length) return '';
  const lat0 = pts.reduce((a, c) => a + c[1], 0) / pts.length, k = Math.cos(lat0 * Math.PI / 180);
  const xs = pts.map(c => c[0] * k), ys = pts.map(c => c[1]);
  const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
  const pad = 12, s = Math.min((W - 2 * pad) / (x1 - x0 || 1), (H - 2 * pad) / (y1 - y0 || 1));
  const ox = (W - (x1 - x0) * s) / 2, oy = (H - (y1 - y0) * s) / 2;
  const d = rings.map(r => r.map((c, i) => (i ? 'L' : 'M') + (ox + (c[0] * k - x0) * s).toFixed(1) + ' ' + (oy + (y1 - c[1]) * s).toFixed(1)).join('') + 'Z').join('');
  const [cx, cy] = feature.properties.centroid || [];
  const dot = cx != null ? `<circle class="pn-cq-c" cx="${(ox + (cx * k - x0) * s).toFixed(1)}" cy="${(oy + (y1 - cy) * s).toFixed(1)}" r="2.5"/>` : '';
  return `<svg class="pn-croquis" viewBox="0 0 ${W} ${H}" role="img" aria-label="Croquis del polígono del predio"><path class="pn-cq-poly" d="${d}"/>${dot}<text class="pn-cq-n" x="${W - 8}" y="16" text-anchor="end">N ↑</text></svg>`;
}

const climaFuente = data => data.clima?.fuente || 'DMC + Open-Meteo corregido';
const zonaNombre = data => data.zona?.nombre || '';

function hechos(p, data) {
  const temporada = temporadaOf(data);
  const st = dryWindowStats(data, p.id, seasonRange(temporada));
  const ex = excesoRange(p);
  const der = p.m3_derecho_rol ?? p.m3_derecho;
  const name = p.rol ? `rol ${p.rol}` : `predio ${p.id}`;
  const parts = [];
  if (st) {
    parts.push(`Entre el ${fmtDate(st.win.inicio)} y el ${fmtDate(st.win.fin)}${st.win.dias ? ` (${st.win.dias} días)` : ''} no se registró lluvia efectiva en la zona ${zonaNombre(data)} (comuna de ${fmtComuna(p.comuna)}), según ${climaFuente(data)}.`);
    if (st.ndvi != null) parts.push(`En ese período, el ${name} (${p.cultivo && p.cultivo !== 'sin catastro' ? p.cultivo + ', ' : ''}${fmtNum(p.area_ha, 2)} ha) mantuvo un NDVI medio de ${fmtNum(st.ndvi, 2)}${st.ndmi != null ? ` y un NDMI de ${fmtNum(st.ndmi, 2)}` : ''} (Sentinel-2 L2A), frente a ${fmtNum(st.refNdvi, 2)}${st.refNdmi != null ? ` y ${fmtNum(st.refNdmi, 2)}` : ''} de la vegetación de secano de referencia (CONAF). ${st.ndvi > st.refNdvi ? 'Vegetación más verde que el secano sin lluvia sugiere riego.' : ''}`.trim());
  }
  const derTxt = der == null ? 'sin cruce disponible con el registro de derechos'
    : +der === 0 ? `sin derechos de aprovechamiento asociados al rol en el registro DGA${p.estado_derechos ? ` (${p.estado_derechos})` : ''}`
      : `frente a un derecho asociado al rol de ${fmtMil(der)} mil m³/año (registro DGA)`;
  if (p.m3_estimado_min != null) {
    parts.push(`Con el método FAO-56 simplificado (Kc a partir de NDVI, ET0 y lluvia), el consumo estimado del predio para la temporada ${temporada} se sitúa entre ${fmtMil(p.m3_estimado_min)} y ${fmtMil(p.m3_estimado_max)} mil m³, ${derTxt}${ex.hi > 0 ? ` (posible exceso de ${fmtMil(ex.lo)} a ${fmtMil(ex.hi)} mil m³)` : ''}. Estimación provisional; confianza ${p.confianza || 'no evaluada'}${(p.confianza_motivos || []).length ? ` (${p.confianza_motivos.join('; ')})` : ''}.`);
  }
  parts.push('Estos antecedentes son un indicio para priorizar la fiscalización en terreno; no constituyen prueba ni identifican a personas.');
  return parts.join('\n\n');
}

const ADJUNTOS = (p, data) => [
  `Serie mensual NDVI/NDMI del predio (${p.rol ? 'rol ' + p.rol : p.id}) y de la referencia de secano CONAF (Sentinel-2 L2A, Element84 Earth Search)`,
  'Imágenes satelitales antes/después de la ventana seca (color natural y NDVI)',
  `Cálculo de consumo FAO-56 simplificado, temporada ${temporadaOf(data)} (provisional)`,
  'Derechos de aprovechamiento asociados al rol (registro DGA / CPA)',
  `Ventanas secas detectadas (${climaFuente(data)}, ≥ 10 días sin lluvia efectiva)`,
];

export function renderExpediente(el, feature, data, { onBack } = {}) {
  if (!el || !feature) return;
  const p = feature.properties;
  const [lon, lat] = p.centroid || [NaN, NaN];
  const draft = hechos(p, data);
  const label = p.rol ? `Rol ${p.rol}` : `Predio ${p.id}`;
  const comuna = fmtComuna(p.comuna);
  const fields = [['nombre', 'Nombre completo'], ['rut', 'RUT'], ['domicilio', 'Domicilio'], ['correo', 'Correo electrónico'], ['telefono', 'Teléfono']];

  el.innerHTML = `
    <button type="button" class="pn-back" data-act="back">← Ficha ${esc(label)}</button>
    <header class="pn-fh">
      <p class="pn-kicker">Borrador de expediente · formato guía DGA</p>
      <h3 class="pn-title">Expediente ${esc(label)}</h3>
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
            <div><dt>Rol</dt><dd>${esc(p.rol || '—')}</dd></div>
            <div><dt>Predio</dt><dd>${esc(p.id)}</dd></div>
            <div><dt>Comuna</dt><dd>${esc(comuna)}</dd></div>
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
        <ul class="pn-adj">${ADJUNTOS(p, data).map(a => `<li>${esc(a)}</li>`).join('')}</ul>
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
    L.push(`BORRADOR DE EXPEDIENTE — ${label} — ${comuna}${zonaNombre(data) ? ` (zona ${zonaNombre(data)})` : ''}`);
    L.push('Preparado con Caudal. Se presenta en la Oficina Virtual DGA (SNIA) con Clave Única. Caudal no presenta nada.', '');
    L.push('1. DENUNCIANTE');
    for (const [k, l] of fields) L.push(`${l}: ${val(k) || '[completar]'}`);
    L.push('', '2. UBICACIÓN', `Rol: ${p.rol || '—'}`, `Predio (CIREN): ${p.id}`, `Comuna: ${comuna}`, 'Región: Valparaíso', `Coordenadas (centroide): ${fmtCoord(lon, lat)} (${lat}, ${lon})`, `Área: ${fmtNum(p.area_ha, 2)} ha`);
    L.push('', '3. DESCRIPCIÓN DE LOS HECHOS', val('hechos') || draft);
    L.push('', '4. AFECTACIÓN DEL DENUNCIANTE', val('afectacion') || '[completar por la persona que presenta]');
    L.push('', '5. ADJUNTOS', ...ADJUNTOS(p, data).map(a => `- ${a}`));
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
    const a = Object.assign(document.createElement('a'), { href: url, download: `caudal-expediente-${String(p.rol || p.id).replace(/[^\w-]+/g, '_')}.txt` });
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
