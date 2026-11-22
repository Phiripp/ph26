# Pruebas de acceso a datos (2026-11-21)

Caja: lon -71.35 a -70.85, lat -32.60 a -32.10 (Petorca / La Ligua). Periodo: 2025-11-21 a 2026-11-21. Scripts en `scripts/pruebas_datos/`.

| Fuente | Resultado | Registro | Cobertura en la zona | Nota |
| --- | --- | --- | --- | --- |
| Sentinel-2 L2A, Earth Search | **Pasa** | No | 191 escenas con nubes < 30 %; 13 meses con mínimo 4 por mes (nov-25: 4, jul-26: 8) | Búsqueda STAC ~14 s. Assets: `red`, `nir`, `swir16`, `scl`. |
| Recorte ~11 ha, NDVI y NDMI | **Pasa con ajuste** | No | Punto de prueba -70.93, -32.25; escena S2C_19HCE_20260402 | Lectura COG sin firma (`AWS_NO_SIGN_REQUEST`), ~1 min por 4 bandas. **Corregido (D15):** la reflectancia es `x*0.0001`, sin restar 0,1. Los COG de Earth Search ya traen el offset aplicado en todos los baselines, aunque `raster:bands` declare `offset: -0.1` y aunque `earthsearch:boa_offset_applied` diga `False`. Prueba: DN roja del mar frente a La Ligua (19HBE, dic-25 a mar-26) 50–170 y frente a Quintero (19HBD, 2021–2025, baselines 03.01 a 05.12) 49–290; con el offset en el archivo estaría sobre 1000. La franja común 19HBD/19HCD coincide en ±20 DN en 10 pasadas, con banderas iguales o distintas. La nota original (`x*0.0001 - 0.1`) descartaba ~88 % de los píxeles de vegetación. SWIR (20 m) se remuestrea a 10 m. |
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
- Para el frontend: cargar Esri como capa de tiles raster en el mapa (con su atribución), directo desde Esri, y dibujar encima el polígono del predio y las capas de NDVI/NDMI derivadas de Sentinel-2 (los PNG de `data/processed/imagenes/` se retiraron por baja calidad; hay que generarlas de nuevo).
- Si hace falta análisis en alta resolución: imágenes comerciales (Planet, Maxar) o una ortofoto pública de CIREN. No se encontró un servicio de CIREN accesible.

## Monitoreo de extracciones de la DGA y WorldCover como secano (D20, probado el 2026-11-21)

Zonas: Z1 Petorca y Z2 Aconcagua bajo. Scripts: `scripts/pruebas_datos/04_mee_dga.py` y `05_worldcover_secano.py`. Todo se verificó corriendo los scripts, salvo lo marcado como inferido.

| Fuente | Resultado | Registro | Cobertura en las zonas | Nota |
| --- | --- | --- | --- | --- |
| DGA MEE, series por obra | **Solo sitio** | Token de la aplicación y reCAPTCHA | No se pudo contar ninguna obra de Z1 o Z2 | Sin descarga masiva ni consulta por obra sin esas barreras |
| DGA MEE, cobertura y plazos (ArcGIS Online) | **Pasa** | No | Z1: 6 territorios subterráneos y 10 superficiales tocan el bbox; Z2: 10 y 7 | Dice quién debe informar, no cuánto extrae. 0,2 a 0,3 s por consulta |
| ESA WorldCover 2021 v200, AWS | **Pasa** | No | Un solo tile (`S33W072`) cubre Z1 y Z2 | Lectura por ventana: Z1 18,1 s, Z2 2,4 s |
| ESA WorldCover, Planetary Computer | **Pasa con ajuste** | No | El mismo tile | El asset sin firmar da 409; hay que firmarlo con `/api/sas/v1/sign` (anónimo) |

### Monitoreo de Extracciones Efectivas (MEE)

El MEE es el sistema donde los titulares informan lo que extraen por obra de captación. Sería verdad de terreno directa, pero hoy no se puede bajar de forma automática.

- **Por qué no se llega a las series.** Todos los servicios de `snia.mop.gob.cl/extracciones/data/...` responden 403 sin un token que la página pide con una clave embebida en su JavaScript. No se usó: es una credencial de la aplicación. Además, la búsqueda pública y la descarga de reportes envían un reCAPTCHA (inferido del JavaScript).
- **API de transmisión** (`apimee.mop.gob.cl`, con OpenAPI público): es para que los titulares envíen mediciones. Leer exige el comprobante de un envío o el RUT y la clave del informante.
- **Sin datos abiertos.** `datos.gob.cl` no tiene conjuntos del MEE, y los servidores ArcGIS del MOP y de la SMA no tienen capas con mediciones.
- **Descarga a mano** (inferido, no probado): una persona podría bajar en el navegador un CSV por región, naturaleza y mes.
- **Llave.** El MEE identifica la obra con un código `OB-RRPP-N` y trae UTM. El cruce con `derecho.parquet` sería por expediente (mismo formato `ND-0501-123`) o por coordenada. En la única capa pública con obras (Limarí, mayo de 2024) solo 56 de 217 traen un expediente legible, así que mandaría la coordenada.

Lo que sí se midió:

- **Plazos vencidos.** Los plazos de aguas subterráneas ya vencieron en las dos provincias: Petorca (resolución 1065 de 2019, último plazo 01-07-2025) y Quillota (resolución 2178 de 2019, último plazo 02-01-2026). Hoy todo derecho subterráneo de Z1 y Z2 debería informar.
- **Universo que debería informar** (derechos subterráneos sumables de `derecho.parquet`, no obras registradas): 4.848 en Z1 y 2.751 en Z2. En Z1, 427 derechos del estándar mayor concentran el 53 % del caudal; en Z2, 515 concentran el 71 %.
- **Cumplimiento en Limarí.** De 217 obras, 35 tenían transmisiones completas. De 3.359 derechos subterráneos revisados, 76 estaban en el software.
- **Ojo con esa capa:** las columnas de enero a diciembre repiten el caudal autorizado, no lo medido. Tiene RUT, nombres y correos; el script solo pide estadísticas y campos sin datos personales.

**Para Caudal:** no adoptar ahora. No hay vía automática y, si Limarí es representativo, pocos pozos transmiten. Sí sirve la capa de cobertura: permite decir en el expediente que el predio está en un territorio con la obligación de informar vencida. Las series quedan para después, por descarga manual o por solicitud de transparencia.

Repetir: `uv run scripts/pruebas_datos/04_mee_dga.py` (19 a 41 s).

### ESA WorldCover como referencia de secano

Pregunta: ¿pueden las clases matorral (20), pradera (30) y suelo desnudo o ralo (60) de WorldCover reemplazar o complementar la referencia de CONAF (`referencia_secano.parquet`, 3.642 polígonos)?

- **Acceso.** Sin registro, desde AWS: `esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/ESA_WorldCover_10m_2021_v200_S33W072_Map.tif`. El tile completo pesa 110 MB (51 s con curl). La corrida entera tarda 87 s con descarga y 8 s desde caché. No se midió cuánto tarda la extracción de CONAF, así que no se puede decir cuál es más rápida.
- **Acuerdo con CONAF.** WorldCover clasifica como matorral o pradera el 77,3 % de la superficie de la referencia en Z1 y el 86,4 % en Z2. Sumando suelo desnudo o ralo, 98,2 % y 92,7 %. Árboles: 1,3 % y 6,3 %. Cultivo: 0,4 % y 0,6 %.
- **Polígonos dudosos de la referencia actual:** 70 con mayoría de árboles (43 en Z1, 27 en Z2) y 68 con 10 % o más de cultivo (50 y 18).
- **Qué agrega.** Más superficie: WorldCover marca 715.345 ha de esas clases en Z1 y 137.732 ha en Z2, y la referencia de CONAF cubre el 14 % y el 13 %. Parte del extra es cordillera alta, que CONAF excluye a propósito. Además es una sola fuente para todo Chile (inferido).
- **Qué pierde.** Es una foto de 2021; CONAF exige el mismo uso entre 2001 y 2019. Y no separa riego de secano: WorldCover clasifica como matorral, pradera o ralo el 26,9 % de la superficie de los huertos del Catastro Frutícola 2025 en Z1 y el 21,8 % en Z2 (una parte son huertos plantados después de 2021).
- **Sin medir:** la vegetación de ribera. Habría que quitarla con un margen a `cauce.parquet`.

**Para Caudal:** no reemplazar CONAF, porque usar las tres clases directo metería riego en la referencia. Sí sirve como filtro barato sobre CONAF: marcar los 70 polígonos con mayoría de árboles y los 68 con cultivo. Para la corrida nacional sirve de respaldo donde falta CONAF, siempre recortando huertos y cauces.

Repetir: `uv run scripts/pruebas_datos/05_worldcover_secano.py [--refrescar] [--tile-completo]`. Los recortes quedan en `data/raw/worldcover/` (fuera de git).
