# Pruebas de acceso a datos (2026-11-21)

Caja: lon -71.35 a -70.85, lat -32.60 a -32.10 (Petorca / La Ligua). Periodo: 2025-11-21 a 2026-11-21. Scripts en `scripts/pruebas_datos/`.

| Fuente | Resultado | Registro | Cobertura en la zona | Nota |
| --- | --- | --- | --- | --- |
| Sentinel-2 L2A, Earth Search | **Pasa** | No | 191 escenas con nubes < 30 %; 13 meses con mínimo 4 por mes (nov-25: 4, jul-26: 8) | Búsqueda STAC ~14 s. Assets: `red`, `nir`, `swir16`, `scl`. |
| Recorte ~11 ha, NDVI y NDMI | **Pasa con ajuste** | No | Punto de prueba -70.93, -32.25; escena S2C_19HCE_20260402 | Lectura COG sin firma (`AWS_NO_SIGN_REQUEST`), ~1 min por 4 bandas. Con baseline ≥ 04.00 hay que aplicar `x*0.0001 - 0.1`; sin recortar la reflectancia a [0,1] NDVI salió en -16..11. Con recorte: NDVI -0.02..1.0, NDMI -0.66..0.41, 0 vacíos. SWIR (20 m) se remuestrea a 10 m. |
| Planetary Computer / Copernicus | No se probó | - | - | Earth Search respondió. |
| DMC, catálogo de estaciones | **Pasa** | No | 150 estaciones EMA; en la caja solo Chincolco Liceo Agrícola (320049); cercanas: Zapallar Catapilco, El Tártaro (Putaendo), Llay Llay, Panquehue | `GET climatologia.meteochile.gob.cl/application/servicios/getEstacionesRedEma`. Latitud y longitud vienen como texto; la codificación de acentos sale rota. |
| DMC, datos recientes | **Pasa con apikey** | **Sí: usuario y token (probado)** | - | `.../servicios/getDatosRecientesEma/{codigo}` responde "tiene que indicar el usuario y un token válido". La URL `productos/datosRecientesEma/{codigo}` del catálogo da 404. |
| DMC, cooperativas (La Ligua Esval, Trapiche Longotoma, etc.) | No verificado | Probablemente sí | - | No hay servicio de catálogo de cooperativas abierto (probé `getEstacionesRedCooperativas`, 404). |
| INIA Agromet | **Bloqueado** | Por confirmar | - | `www.agromet.cl` (endpoint de agrometR, `ext/aux/getGraphData.php`) tiene la cadena de certificados incompleta y curl lo rechaza; no se desactivó la verificación. `agromet.inia.cl` es una página de redirección a `agrometeorologia.cl`, donde las rutas de API probadas dan 404. Escribir a info@agromet.cl. |
| DGA | **Solo sitio** | No | - | Hay formulario JSP en `snia.mop.gob.cl` (dgasat); sin API documentada. Falta bajar a mano un CSV de lluvia. |
| Open-Meteo histórico | **Pasa** | No | Punto -70.93, -32.25 | 366 días sin huecos (lluvia y ET0), 1,4 s. Lluvia acumulada 762 mm en el periodo (ver nota). |
| Contraste estación vs. Open-Meteo | **No se pudo** | - | - | Sin datos de estación (DMC exige token, INIA bloqueado). |

Nota: 762 mm anuales es alto para Petorca (secano, zona semiárida); sin estación de contraste no se puede juzgar el sesgo de la grilla. Hay que contrastar antes de confiar en la lluvia de Open-Meteo.

## DMC con apikey (probado el 2026-11-21)

- La apikey funciona: `getDatosRecientesEma/320049?usuario=...&token=...` entrega 710 registros de las últimas 12 horas de Chincolco.
- Servicios útiles (docs en `climatologia.meteochile.gob.cl/application/documentacion/getDocumento/{n}`, n = 1 a 25): `getAguaCaidaDiaria/{codigo}` y `getAguaCaidaMensualAnual/{codigo}` (ojo, ruta `serviciosb`, no `servicios`), `getEmaResumenDiario` (hoy y ayer) y `getDatosRecientesEma` (12 horas).
- La lluvia diaria histórica llega hasta el **2025-12-31** (30 años por estación, 2018-2025 en Chincolco, 2013-2025 en Llay Llay). Enero a noviembre de 2026 no está en línea; para 2026 solo hay las últimas 12 horas o el resumen diario, o sea que hay que acumular una serie propia llamando a diario.
- **Contraste 2025 contra Open-Meteo** (mm de lluvia en el año; meses de ene a dic):
  - Chincolco (320049): estación 125,7 mm frente a Open-Meteo 305,5 mm.
  - Llay Llay (320045, la más cercana con registro completo): estación 196,4 mm frente a Open-Meteo 382,5 mm (el registro tiene días faltantes en marzo y diciembre).
  - Open-Meteo sobreestima cerca de 2 veces en ambas, y los meses no calzan (agosto: 29 mm contra 102 mm en Chincolco). La grilla sirve para ET0 y como tendencia, pero **no** para decidir la ventana seca de un día concreto.
- Implicación: Open-Meteo deja de ser fuente base de lluvia. Usar estaciones para lluvia (con tope de cobertura 2025) y Open-Meteo solo para ET0 y respaldo.

## Caja alternativa: Laguna de Aculeo (lon -71.06 a -70.76, lat -33.98 a -33.68)

| Fuente | Resultado | Detalle |
| --- | --- | --- |
| Sentinel-2 L2A | **Pasa a medias** | 95 escenas con nubes < 30 % repartidas en 2 tiles (19HCC: 52, 19HBC: 43), así que cada punto ve menos. Meses con menos de 2 escenas: ago-26 (1); nov-25 y nov-26 en el límite. Para esta caja conviene subir el umbral de nubes o usar SCL por píxel. |
| Open-Meteo | **Pasa** | 365 días sin huecos; 816 mm de lluvia (jul 314, oct 176, ago 147) y ET0 de 1.304 mm. Verano casi sin lluvia, como se espera. |
| DMC (catálogo) | Sin estación en la caja | Más cercanas: El Milagro Buin (330160, 16 km), El Paico (330113, 16 km), Talagante (19 km), Río Clarillo (40 km). Los datos siguen pidiendo token. |

## Decisiones

- Imágenes: Sentinel-2 L2A por Earth Search.
- Clima base: Open-Meteo (única fuente completa y sin registro).
- Estaciones: pedir token DMC (registro en climatologia.meteochile.gob.cl) para Chincolco y bajar un CSV de DGA a mano para el contraste. INIA queda pendiente de respuesta.

## Pendiente

- [ ] Token DMC y contraste mensual Chincolco vs. Open-Meteo.
- [ ] CSV de lluvia DGA de una estación de la zona.
- [ ] Correo a info@agromet.cl.
- [ ] Confirmar zona final del valle en un mapa.

## Imágenes de mayor calidad (2026-11-21)

Decisión: **Sentinel-2 para el análisis y Esri World Imagery solo como fondo visual.**

- Esri World Imagery (`services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer`): sin clave, 0,31 m por píxel sobre el predio 88-31 (fuente Vivid de Vantor, captura del 2025-09-08, exactitud ~5 m). Cada zona tiene su propia fecha de captura; se consulta en `MapServer/4/query`.
- Solo color real: sin infrarrojo, así que no sirve para NDVI ni NDMI. Es un mosaico con color corregido, sin reflectancia comparable entre fechas.
- Licencia (según los resultados de búsqueda; falta leer el texto completo): Esri no permite usarla como entrada directa de extracción automática; lo exportado y lo derivado queda para uso no comercial dentro de ArcGIS. Por eso **no se guardan recortes de Esri en el repo ni se procesan con código**.
- Para el frontend: cargar Esri como capa de tiles raster en el mapa (con su atribución), directo desde Esri, y dibujar encima el polígono del predio y las capas de NDVI/NDMI derivadas de Sentinel-2 (`data/processed/imagenes/`).
- Si hace falta análisis en alta resolución: imágenes comerciales (Planet, Maxar) o una ortofoto pública de CIREN. No se encontró un servicio de CIREN accesible.
