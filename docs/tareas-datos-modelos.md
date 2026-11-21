# Caudal — Seguimiento de tareas de datos y modelos

Nov 21, 2026 · @Tomas

Este documento dice quién extrae qué dato y quién construye qué modelo, para no duplicar trabajo. Las zonas, las fuentes y las convenciones de datos están en [spec-v2.md](spec-v2.md); este documento no las repite.

## Cómo usar este documento

- Antes de empezar una tarea, pon tu nombre en "Responsable" y cambia el estado a 🟡. Haz commit y push de inmediato, para que el resto lo vea.
- Al terminar, cambia el estado a ✅ y escribe en "Entrega" la ruta del archivo que generaste.
- Si una tarea está bloqueada, cambia el estado a ⛔ y escribe el motivo en [Bloqueos](#bloqueos).
- Una tarea nueva lleva el siguiente número libre (D13, M9, etc.). No reuses números.
- Si necesitas otra zona u otro periodo, edita primero [Zonas de estudio](spec-v2.md#zonas-de-estudio) en el spec.

Estados: ⬜ pendiente · 🟡 en curso · ✅ listo · ⛔ bloqueado

## Estado por zona

Vista rápida de qué datos están listos en cada zona. Se actualiza al cerrar una tarea D.

| Dato | Tarea | Z1 Petorca | Z2 Aconcagua bajo |
| --- | --- | --- | --- |
| Series Sentinel-2 por predio | D1 | ⬜ | ⬜ |
| Clima (lluvia y ET0) | D2 | ✅ | ✅ |
| Predios | D3 | ✅ | ✅ |
| Derechos normalizados | D4 | ✅ | ✅ |
| Cruce derechos–predios | D5 | ✅ | ✅ |
| Fiscalizaciones (validación) | D6 | ✅ | ✅ |
| Especie por predio | D7 | ✅ | ✅ |
| Cauces y canales | D8 | ✅ | ✅ |
| Red vial | D9 | ✅ | ✅ |
| Zonas de prohibición | D10 | ✅ | ✅ |
| Referencia de secano | D11 | ✅ | ✅ |

## Tareas de datos

Cada tarea entrega un script en `scripts/extract/` y un archivo en `data/processed/` con la columna `zona`.

| ID | Tarea | Fuente | Zonas | Responsable | Depende de | Entrega | Estado |
| --- | --- | --- | --- | --- | --- | --- | --- |
| D1 | Series mensuales de NDVI, NDWI y NDMI por predio, con máscara de nubes SCL; desde enero de 2020 hasta la última escena limpia (periodos prioritarios en `data/zonas.json`: Z1 de julio de 2023 a abril de 2024 y desde diciembre de 2024; Z2 en 2021–2022 y de julio de 2023 a mayo de 2025). Solo predios `elegible` (7.911). Modos de `serie_sentinel2.py`: `--elegibles` (ranking), `--validacion` (vecindarios de D18), `--referencia` (secano de D11), `--predios archivo`; `--temporadas 2019-20:2025-26` toma diciembre a marzo de cada temporada | Sentinel-2 L2A (STAC) | Z1, Z2 | Gabriela | D3 (geometrías) | `serie_predio.parquet` | ⬜ |
| D2 | Lluvia diaria y ET0 en grilla; estaciones DMC, DGA e INIA donde existan | Open-Meteo y estaciones | Z1, Z2 | Gabriela | — | `clima.parquet`, `predio_clima.parquet` y `estacion_clima.parquet` (plan: [d2-clima.md](plans/d2-clima.md)) | ✅ |
| D3 | Descargar los predios de las comunas de cada zona y calcular el área en EPSG:32719. Entregar primero una muestra de 50 predios por zona para desbloquear D1 | CIREN Propiedades Rurales | Z1, Z2 | Tomás | — | `scripts/extract/predios_ciren.py` → `predio.parquet` (local) y `predio_muestra.geojson` (en git) | ✅ |
| D4 | Descargar el Excel de derechos de Valparaíso; convertir datums; normalizar a m³ por mes; marcar los eventuales y las "Acciones" | DGA derechos registrados | Z1, Z2 | Tomás | — | `scripts/extract/derechos_dga.py` → `derecho.parquet` (en git, sin nombres); Excel y titulares en `data/raw/dga/` (local) | ✅ |
| D5 | Cruzar derechos con predios: punto de captación en el predio o a menos de 500 m; si falla, por titular en la comuna. Guardar `metodo_cruce` y `confianza_cruce`. No asignar por coordenada los `gran_derecho` (100 l/s o más: canales y comunidades de aguas) | D3 + D4 | Z1, Z2 | Tomás | D3, D4 | `scripts/extract/cruce_derechos_predios.py` → `derecho_predio.parquet` y `predio_derecho.parquet` (en git; columnas en `data/README.md`) | ✅ |
| D6 | Filtrar la planilla de fiscalizaciones por extracción no autorizada en cada zona. Positivo: multa o "Constata infracción" / "Acoge". Negativo débil: "No acoge" / "Cierra expediente" | DGA planilla de fiscalización | Z1, Z2 | Tomás | — | `scripts/extract/fiscalizaciones_dga.py` → `fiscalizacion.parquet` (en git; 835 expedientes de Z1 y Z2, 497 de extracción de aguas) | ✅ |
| D7 | Especie plantada y superficie frutal por predio elegible, cruzando cuarteles por superficie (no por rol) | CIREN Catastro Frutícola 2025 | Z1, Z2 | Tomás | D3 | `scripts/extract/cultivos_ciren.py` → `predio_cultivo.parquet` (en git) | ✅ |
| D8 | Cauces y canales de riego | DGA red de drenajes (SMA) y CIREN infraestructura de riego | Z1, Z2 | Tomás | — | `canales_ciren.py` → `raw/ciren_riego/canales.parquet`; `cauces_dga.py` → `cauce.parquet` y `predio_cauce.parquet` (cauce, río y canal más cercanos por predio elegible; lo usa M12) | ✅ |
| D9 | Rutas con OSRM para los N predios top (no la red completa): matriz `/table` y trazado `/route`, verificados con los 10 positivos limpios. La red completa con osmnx queda descartada (Overpass corta la conexión; Z1 es muy grande) | OSRM público (OpenStreetMap) | Z1, Z2 | Tomás | — | decisión y prueba en el spec (Fuentes de datos verificadas); las llamadas las hace M8 | ✅ |
| D10 | Zonas de prohibición y restricción de los acuíferos | DGA (rest-sit.mop.gob.cl) | Z1, Z2 | Gabriela | — | `scripts/extract/restriccion_dga.py` → `restriccion.parquet` y `predio_restriccion.parquet` (en git; 98,9 % de los elegibles cae en zona de prohibición) | ✅ |
| D11 | Polígonos de referencia de secano (matorral y pradera) | CONAF uso de la tierra 2001–2019 | Z1, Z2 | Gabriela | — | `scripts/extract/referencia_secano_conaf.py` → `referencia_secano.parquet` (en git; solo polígonos estables 2001–2019, sin estepa andina) | ✅ |
| D12 | Opcional: ubicación de APR y cifras de camiones aljibe para el pitch | DOH (SMA), prensa y estudios | Z1 | Por asignar | — | `apr.parquet` y notas para el pitch | ⬜ |
| D13 | Recalcular con la escena limpia más reciente la noche antes de la demo: índices de la ficha e imagen del predio de la demo en vivo (por elegir, D19). Debe correr con un solo comando | Sentinel-2 L2A (STAC) | Z1 | Gabriela | D1 | comando en `scripts/extract/` y escena en `data/processed/` | ⬜ |
| D14 | Buscar con fuente: costo por m³ del agua de camión aljibe (Subdere, SENAPRED, órdenes de compra, estudio EURE 2022) y dotación en litros por persona al día | Mercado Público, Subdere, prensa | Z1 | Tomás | — | valores con fuente en [Métricas de impacto](spec-v2.md#métricas-de-impacto): 4.300 CLP/m³ (2.600–14.000) y 36,5 m³ por persona al año | ✅ |
| D15 | **Urgente.** Corregir la lectura Sentinel-2 de D1: `serie_sentinel2.py` resta el offset de −0,1 que declara Earth Search, pero los DN ya vienen corregidos. Verificado en `serie_predio_temporada_2025-26.parquet`: en las 57 escenas con menos de 1 % de nubes, la mediana de píxeles descartados por predio es del 88 % (la vegetación queda con rojo ≤ 0 y se descarta), y el predio de control `88-31` da NDVI 0,28 en vez de ≈ 0,1. Quitar la resta del offset (la lectura por tile ya está hecha); solo diciembre a marzo; percentil 90 o fracción de píxeles verdes en predios de más de 100 ha. Control: el predio `88-31` (FO-0501-462, suelo desnudo) debe dar NDVI ≈ 0,1 | Sentinel-2 L2A (STAC) | Z1, Z2 | Gabriela | — | ajuste del script de D1 y nota en `docs/pruebas-acceso-datos.md` |✅ |
| D16 | Cruce de derechos versión 2: no asignar pozos compartidos, sumar por rol, filtrar por fecha de otorgamiento por temporada, tope anual con "Volumen", excluir duplicados VPC y caudales negativos, distancia a canal | D3 + D4 + canales CIREN | Z1, Z2 | Tomás | D3, D4 | `predio_derecho.parquet` por predio y temporada (columnas en `data/README.md`) | ✅ |
| D17 | Clima: `clima.parquet` repite filas por `punto_id` y fecha (estaciones compartidas entre zonas): unir también por `zona` o deduplicar. La estación Zapallar Catapilco (asignada a 2.285 predios de Z1) registró 5 mm en 2020 contra 440 mm en Quintero sin marcarse como faltante: marcar como faltante y rellenar con Open-Meteo | DMC y Open-Meteo | Z1, Z2 | Gabriela | D2 | `clima.parquet` corregido; `scripts/extract/d2_clima_unir.py` marca como faltante el año de una estación con total anual bajo el 10 % de la mediana de las otras (Zapallar 2020: 2 mm contra 247 mm). Los duplicados por `punto_id` y fecha son estaciones compartidas entre zonas: no hay duplicados por `zona`, así que quien lea `clima.parquet` debe unir también por `zona` | ✅ |
| D18 | Set de validación limpio: marcar positivos ambiguos (otro predio a 30 m o menos del punto: el 49 %), predios con ambas etiquetas, positivos con recurso de reconsideración y positivos no detectables por verdor (suelo desnudo, p. ej. FO-0501-462). Evaluar por vecindario (predio y vecinos a 30 m) | `fiscalizacion.parquet` + D15 | Z1, Z2 | Tomás | D6, D15 | columnas `vecindario`, `ambiguo`, `predio_grande`, `etiquetas_mixtas`, `con_recurso` y `set_validacion` en `fiscalizacion.parquet` (✅): 10 positivos y 24 negativos limpios. Falta `detectable`, que necesita D15 | 🟡 |
| D19 | Elegir el caso de la demo en vivo: reconocer un predio con datos hasta el último mes, armar la denuncia y enviarla; se decide después de tener toda la data de base (D15 y ranking de M5). El caso base con multa efectuada ya está fijado: FO-0504-95 (NDVI 0,88–0,91 en 2019–20 y 0,67–0,71 en 2022–24: el verde baja después de la fiscalización). FD-0501-181 queda como validación (NDVI estable 0,45–0,58 en 2019–2024, sin "inicio de riego"; el pozo está a 12 m del predio vecino `202-90`, que tiene un derecho a 51 m) | D15 | Z1, Z2 | Tomás | D15 | caso y relato fijados en el spec | ⬜ |
| D20 | Opcional: probar si el Monitoreo de Extracciones Efectivas (MEE) de la DGA se puede descargar (verdad de terreno directa) y ESA WorldCover 10 m como referencia de secano (más rápido que CONAF 2001–2019) | DGA MEE, ESA WorldCover | Z1, Z2 | Por asignar | — | nota con el resultado | ⬜ |

## Tareas de modelos

Cada tarea entrega código en el repo y un archivo de resultados en `data/processed/`.

| ID | Tarea | Zonas | Responsable | Depende de | Entrega | Estado |
| --- | --- | --- | --- | --- | --- | --- |
| M1 | Ventanas secas: periodos con N o más días sin lluvia efectiva (N inicial = 10) | Z1, Z2 | Gabriela | D2 | `scripts/models/ventana_seca.py` → `ventana_seca.parquet` y `dias_sin_lluvia.parquet` | ✅ |
| M2 | Anomalías `z_verdor` y `z_humedad` por predio frente a la referencia de secano o a la historia del predio | Z1, Z2 | Tomás | D1, D11 | columnas en `serie_predio.parquet` |🟡 |
| M3 | Detector de riego: ambas anomalías sobre su umbral dentro de una ventana seca | Z1, Z2 | Tomás | M1, M2 | `senal_riego.parquet` |🟡 |
| M4 | Consumo estimado con FAO-56: Kc(NDVI), con ajuste por especie si existe; resultado en rango de m³. El Kc sale del NDVI; la especie (`predio_cultivo.parquet`) solo ajusta: el 44 % de los positivos no tiene frutales en el catastro | Z1, Z2 | Tomás | D1, D2, D7 | 🟡 |
| M5 | Índice de sospecha, confianza y bandas (alta, media, baja). Mide el exceso del consumo sobre los derechos propios y del entorno (`predio_derecho.parquet`), no "tiene o no tiene derechos": el 73 % de los positivos tiene derechos. Los derechos del entorno solo bajan la confianza si superan lo que necesitan los predios donde están inscritos (si no, el caso de la demo queda en confianza baja). Usar `m3_anual_derecho_rol` de la temporada (no el del polígono). Los derechos solos no distinguen infractores (AUC 0,49–0,54 entre fiscalizados): la sospecha sale de la señal satelital y los derechos dimensionan el exceso. `canal_300m` no baja la confianza (68 % de los elegibles) | Z1, Z2 | Tomás | M3, M4, D5 | `puntaje.parquet` | ⬜ |
| M6 | Validación: posición en el ranking de los positivos de D6; métrica precisión en los k primeros. Casos clave: FO-0504-95 (caso base con multa efectuada y antecedente satelital, Hijuelas 2021) y FD-0501-181 (validación, Cabildo 2024). Usar el set limpio de D18, evaluar por vecindario y reportar recall con intervalo de confianza: hay 34 positivos en predios elegibles desde 2020 y unos 10 limpios | Z1 y Z2 | Tomás | M5, D6 | `validacion.md` con la métrica y el mapa | ⬜ |
| M7 | Calibrar N, los umbrales de anomalía y los pesos de la confianza con el resultado de M6 | Z2 | Tomás | M6 | valores fijados en el spec | ⬜ |
| M8 | Ruta de inspección con OR-Tools: un vehículo, cada predio como parada opcional con premio según su puntaje, jornada de 8 h; exportar GPX. Matriz de tiempos y trazado con OSRM (`/table` y `/route`) para los predios top; precalcular y guardar la ruta por zona, sin llamadas en vivo en la demo | Z1, Z2 | Tomás | M5, D9 | `ruta.py` y GPX de ejemplo |🟡 |
| M9 | Métricas de impacto: adelanto de detección en casos conocidos, acierto frente al 33 % de la DGA, candidatos no fiscalizados, m³ en juego y pesos (multas y costo de camión aljibe), todo en rango | Z1, Z2 | Tomás | M5, M6, D5, D6, D14 | `impacto.md` con las cifras y supuestos | ⬜ |
| M10 | Puntos de interés por predio: zonas con anomalía de humedad y verdor en ventana seca, posibles tranques por NDWI y punto del cauce más cercano; máximo 8 por predio, cada uno con tipo, razón, fecha de la imagen y confianza (ver [spec-flujos-poligono.md](spec-flujos-poligono.md), A1) | Z1, Z2 | Gabriela | D1, D8, M2, M3 | `poi.parquet` | ⬜ |
| M11 | Recorrido dentro del predio: acceso por red vial, orden de visita de los POI con OR-Tools, ficha de verificación por parada y GPX. Es el detalle de una parada de M8 (A2) | Z1, Z2 | Gabriela | M10, D9, M8 | `recorrido.py` y GPX de ejemplo | ⬜ |
| M12 | Contexto del predio al elegirlo: provincia, comuna y sector, cauce cercano y distancia, derechos y puntaje; expuesto en `GET /predios/{id}/contexto` (paso 0) | Z1, Z2 | Gabriela | D4, D5, D8, M5 | `contexto.py` y endpoint | ⬜ |
| M13 | Expediente PDF con los campos de la guía de la DGA (jul 2025): secciones pre-llenadas, vacías y generadas, sección de afectación del denunciante y anexo técnico (B1 a B4) | Z1, Z2 | Gabriela | M12, M5, M10 | plantilla y `expediente.py`; PDF de ejemplo | ⬜ |
| M14 | Opcional, solo si hay dron y operador: plan de vuelo con barrido del polígono y pasadas sobre tranques y bocatomas (A3) | Z1 | Gabriela | M10 | `plan_vuelo.py` y archivo de misión de ejemplo | ⬜ |
| M15 | Opcional: retorno de campo, con fotos y notas por POI que alimentan el expediente en versión post-visita (A4) | Z1 | Gabriela | M11, M13 | `POST /predios/{id}/retorno` | ⬜ |

## Camino crítico

D3 → D1 → M2 → M3 → M5 → M6 es la cadena más larga. Por eso D3 entrega primero una muestra de 50 predios por zona, para que D1 parta sin esperar la descarga completa.

D4 → D5 corre en paralelo y debe estar listo antes de M5.

Los flujos por polígono salen de M5: M10 → M11 (recorrido) y M12 → M13 (expediente) corren en paralelo. M14 y M15 solo si sobra tiempo.

## Prioridad actual

Orden de trabajo al 21-11-2026, con la serie Sentinel-2 corregida (D15). Se actualiza cuando cambia lo que bloquea.

| Orden | Tarea | Responsable | Estado | Por qué ahora |
| --- | --- | --- | --- | --- |
| 1a | D1 corrida de validación: 159 predios, diciembre a marzo de 2019-20 a 2025-26 (`--validacion`) | Tomás | 🟡 corriendo | Desbloquea D18 `detectable`, D19 y M6 |
| 1b | D1 corrida de ranking: 7.911 elegibles, 2025-26 (`--elegibles`) | Tomás | ⬜ | Universo del ranking de la demo; es la corrida más larga |
| 1c | D1 corrida de referencia de secano, mismas temporadas (`--referencia`) | Tomás | ⬜ | M2 necesita la referencia para las anomalías |
| 2 | M2 a M4: anomalías, detector de riego, consumo FAO-56 | Tomás | ⬜ | Camino crítico; el código puede partir con la serie de la muestra |
| 3 | D18 `detectable`, D19 caso de la demo, primera versión de M6 | Tomás | ⬜ | Cuando termine 1a |
| 4 | M5 ranking, M8 ruta, M9 impacto | Tomás | ⬜ | Cuando estén 1b, 1c y 2 |
| ✅ | D3 a D10, D15, D16, D17 | Tomás, Gabriela | ✅ | Datos base, cruce versión 2, cauces, rutas OSRM y fix de Sentinel-2 |
| — | D12, D14, D20 | Por asignar | ⬜ | No bloquean el camino crítico |

## Assessment de datos (21-11-2026)

Revisión independiente de los datos frente a lo que necesitan M2 a M9 y la demo. Detalle de cada gap en su tarea.

| Gap | Impacto | Tarea | Estado |
| --- | --- | --- | --- |
| La serie Sentinel-2 resta el offset dos veces (verificado: 88 % de píxeles descartados en escenas despejadas) | Alto: bloquea M2 a M6 | D15, D1 | ✅ corregido; faltan las corridas de validación, ranking y referencia |
| El agua de canal no aparece en los derechos: 43 % (Z1) y 61 % (Z2) de los predios con frutales no tiene derecho propio, casi todos junto a un canal | Alto: infla candidatos (M9) | D16 (`dist_canal_m`), M5, M9 | 🟡 dato listo; falta la regla en M5 y M9 |
| Derechos inflados en el predio que contiene el punto (pozos compartidos, sin agregar por rol, sin tope de Volumen, derechos posteriores a los hechos) | Alto: M5 y M6 | D16 | ✅ |
| Los derechos solos no distinguen infractores (AUC ≈ 0,5 entre fiscalizados) | Alto: el índice depende del satélite | M5 | ⬜ |
| Caso de la demo frágil | Alto: demo | D19 | ⬜ |
| Validación chica y ambigua | Alto: M6, M7, M9 | D18 | 🟡 set listo; falta `detectable` (D15) |
| Duplicados VPC y caudales negativos | Medio-bajo | D16 | ✅ |
| Clima con filas repetidas y una estación con lluvia faltante | Bajo a medio | D17 | ✅ |
| Predios de más de 100 ha (86 % de la superficie elegible) diluyen la señal | Medio | D15 | ⬜ |

## Bloqueos

| Tarea | Motivo | Desde | Quién lo resuelve |
| --- | --- | --- | --- |
| — | — | — | — |

## Decisiones

| Fecha | Decisión | Quién |
| --- | --- | --- |
| 21-11-2026 | Zonas Z1 Petorca (demo) y Z2 Aconcagua bajo (validación), definidas en el spec v2 | Equipo |
| 21-11-2026 | Gabriela extrae satélite (D1), clima (D2) y referencia de secano (D11) en ambas zonas | Equipo |
| 21-11-2026 | Los nombres de titulares y los datos descargados no se suben a git | Equipo |
| 21-11-2026 | `predio_id` = `mslink` de CIREN, no el rol (el rol se repite y a veces no es un rol) | Tomás |
| 21-11-2026 | Fiscalizaciones: solo "extracción no autorizada de aguas" (sin áridos). Corrige la línea base: acierto de la DGA 33 % y multa mediana 575,7 UTM | Tomás |
| 21-11-2026 | Universo elegible: rol válido y 1 ha o más (7.911 predios); cubre el 93 % de los positivos por extracción de aguas | Tomás |
| 21-11-2026 | Tomás toma las corridas de ranking y referencia de D1 y los modelos M2 a M9 | Tomás |
| 21-11-2026 | D9: rutas con OSRM solo para los predios top, precalculadas. No se baja la red vial completa (Overpass corta la conexión y no hace falta para el MVP) | Tomás |
| 21-11-2026 | Assessment de datos: tareas D15 a D20. Cruce de derechos versión 2 (por rol y por temporada, sin pozos compartidos). `canal_300m` queda como dato, no baja la confianza | Tomás |
| 21-11-2026 | D5 entrega `predio_derecho.parquet` con `m3_anual_derecho_entorno_500m`: M5 baja la confianza (no sube la sospecha) si el predio tiene poco derecho propio y mucho en el entorno (lotes de pozo) | Tomás |
| 21-11-2026 | Métrica de impacto: candidatos no fiscalizados × acierto medido, en rango de m³ y pesos; un candidato no es un caso | Tomás |
| 21-11-2026 | Caso de la demo: FD-0501-181 (Cabildo, 2024; 16,1 ha de palto sin derechos propios) en lugar de FO-0501-462, cuyo derecho alcanza para su superficie y que no tiene frutales | Tomás |
| 21-11-2026 | Datos lo más recientes posible. Caso de la demo inicial: FO-0501-462 (La Ligua, 2025), reemplazado por FD-0501-181. El ranking usa la temporada seca 2025-26 y la ficha muestra la escena más reciente (octubre de 2026 fue lluvioso) | Tomás |
| 21-11-2026 | Caso base para mostrar una multa efectuada: FO-0504-95 (Hijuelas, predio `61-6`, inspección el 23-11-2021, multa de 1.983,9 UTM; la DGA dice que lo detectó con satélite). La demo en vivo será otra: reconocer un caso con datos hasta el último mes, armar la denuncia y enviarla. Ese caso se elige cuando esté toda la data de base. FD-0501-181 pasa a caso de validación | Gabriela |
