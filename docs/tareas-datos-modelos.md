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
| Clima (lluvia y ET0) | D2 | ⬜ | ⬜ |
| Predios | D3 | ✅ | ✅ |
| Derechos normalizados | D4 | ⬜ | ⬜ |
| Cruce derechos–predios | D5 | ⬜ | ⬜ |
| Fiscalizaciones (validación) | D6 | ⬜ | ⬜ |
| Especie por predio | D7 | ⬜ | ⬜ |
| Cauces y canales | D8 | ⬜ | ⬜ |
| Red vial | D9 | ⬜ | ⬜ |
| Zonas de prohibición | D10 | ⬜ | ⬜ |
| Referencia de secano | D11 | ⬜ | ⬜ |

## Tareas de datos

Cada tarea entrega un script en `scripts/extract/` y un archivo en `data/processed/` con la columna `zona`.

| ID | Tarea | Fuente | Zonas | Responsable | Depende de | Entrega | Estado |
| --- | --- | --- | --- | --- | --- | --- | --- |
| D1 | Series mensuales de NDVI, NDWI y NDMI por predio, con máscara de nubes SCL; desde enero de 2020 hasta la última escena limpia (periodos prioritarios en `data/zonas.json`: Z1 desde diciembre de 2024; Z2 en 2021–2022 y de diciembre de 2024 a mayo de 2025) | Sentinel-2 L2A (STAC) | Z1, Z2 | Gabriela | D3 (geometrías) | `serie_predio.parquet` | ⬜ |
| D2 | Lluvia diaria y ET0 en grilla; estaciones DMC, DGA e INIA donde existan | Open-Meteo y estaciones | Z1, Z2 | Gabriela | — | `clima.parquet` | ⬜ |
| D3 | Descargar los predios de las comunas de cada zona y calcular el área en EPSG:32719. Entregar primero una muestra de 50 predios por zona para desbloquear D1 | CIREN Propiedades Rurales | Z1, Z2 | Tomás | — | `scripts/extract/predios_ciren.py` → `predio.parquet` (local) y `predio_muestra.geojson` (en git) | ✅ |
| D4 | Descargar el Excel de derechos de Valparaíso; convertir datums; normalizar a m³ por mes; marcar los eventuales y las "Acciones" | DGA derechos registrados | Z1, Z2 | Tomás | — | `derecho.parquet` (sin nombres de titulares; los nombres quedan en `data/raw/`) | ⬜ |
| D5 | Cruzar derechos con predios: punto de captación en el predio o a menos de 500 m; si falla, por titular en la comuna. Guardar `metodo_cruce` y `confianza_cruce` | D3 + D4 | Z1, Z2 | Tomás | D3, D4 | `derecho.parquet` con `predio_id` | ⬜ |
| D6 | Filtrar la planilla de fiscalizaciones por extracción no autorizada en cada zona. Positivo: multa o "Constata infracción" / "Acoge". Negativo débil: "No acoge" / "Cierra expediente" | DGA planilla de fiscalización | Z1, Z2 | Tomás | — | `fiscalizacion.parquet` | ⬜ |
| D7 | Especie plantada por predio | CIREN Catastro Frutícola 2025 | Z1, Z2 | Tomás | D3 | columna `especie` en `predio.parquet` | ⬜ |
| D8 | Cauces y canales de riego | DGA red de drenajes (SMA) y CIREN infraestructura de riego | Z1, Z2 | Por asignar | — | `cauce.parquet` | ⬜ |
| D9 | Red vial guardada para uso offline, con 25 km/h en `track` | OSM con osmnx | Z1, Z2 | Por asignar | — | `red_vial_z1.graphml`, `red_vial_z2.graphml` | ⬜ |
| D10 | Zonas de prohibición y restricción de los acuíferos | DGA (rest-sit.mop.gob.cl) | Z1, Z2 | Por asignar | — | `restriccion.parquet` | ⬜ |
| D11 | Polígonos de referencia de secano (matorral y pradera) | CONAF uso de la tierra 2001–2019 | Z1, Z2 | Gabriela | — | `referencia_secano.parquet` | ⬜ |
| D12 | Opcional: ubicación de APR y cifras de camiones aljibe para el pitch | DOH (SMA), prensa y estudios | Z1 | Por asignar | — | `apr.parquet` y notas para el pitch | ⬜ |
| D13 | Recalcular con la escena limpia más reciente la noche antes de la demo: índices de la ficha e imagen del predio de la demo (FO-0501-462). Debe correr con un solo comando | Sentinel-2 L2A (STAC) | Z1 | Gabriela | D1 | comando en `scripts/extract/` y escena en `data/processed/` | ⬜ |
| D14 | Buscar con fuente: costo por m³ del agua de camión aljibe (Subdere, SENAPRED, órdenes de compra, estudio EURE 2022) y dotación en litros por persona al día | Mercado Público, Subdere, prensa | Z1 | Por asignar | — | valores con fuente en [Métricas de impacto](spec-v2.md#métricas-de-impacto) | ⬜ |

## Tareas de modelos

Cada tarea entrega código en el repo y un archivo de resultados en `data/processed/`.

| ID | Tarea | Zonas | Responsable | Depende de | Entrega | Estado |
| --- | --- | --- | --- | --- | --- | --- |
| M1 | Ventanas secas: periodos con N o más días sin lluvia efectiva (N inicial = 10) | Z1, Z2 | Por asignar | D2 | `ventana_seca.parquet` | ⬜ |
| M2 | Anomalías `z_verdor` y `z_humedad` por predio frente a la referencia de secano o a la historia del predio | Z1, Z2 | Por asignar | D1, D11 | columnas en `serie_predio.parquet` | ⬜ |
| M3 | Detector de riego: ambas anomalías sobre su umbral dentro de una ventana seca | Z1, Z2 | Por asignar | M1, M2 | `senal_riego.parquet` | ⬜ |
| M4 | Consumo estimado con FAO-56: Kc(NDVI), con ajuste por especie si existe; resultado en rango de m³ | Z1, Z2 | Por asignar | D1, D2, D7 | `consumo.parquet` | ⬜ |
| M5 | Índice de sospecha, confianza y bandas (alta, media, baja) | Z1, Z2 | Por asignar | M3, M4, D5 | `puntaje.parquet` | ⬜ |
| M6 | Validación: posición en el ranking de los positivos de D6; métrica precisión en los k primeros. Casos clave: FO-0501-462 (demo, La Ligua 2025) y FO-0504-95 (antecedente satelital, Hijuelas 2021) | Z1 y Z2 | Por asignar | M5, D6 | `validacion.md` con la métrica y el mapa | ⬜ |
| M7 | Calibrar N, los umbrales de anomalía y los pesos de la confianza con el resultado de M6 | Z2 | Por asignar | M6 | valores fijados en el spec | ⬜ |
| M8 | Ruta de inspección con OR-Tools: un vehículo, cada predio como parada opcional con premio según su puntaje, jornada de 8 h; exportar GPX | Z1, Z2 | Por asignar | M5, D9 | `ruta.py` y GPX de ejemplo | ⬜ |
| M9 | Métricas de impacto: adelanto de detección en casos conocidos, acierto frente al 27 % de la DGA, candidatos no fiscalizados, m³ en juego y pesos (multas y costo de camión aljibe), todo en rango | Z1, Z2 | Por asignar | M5, M6, D5, D6, D14 | `impacto.md` con las cifras y supuestos | ⬜ |

## Camino crítico

D3 → D1 → M2 → M3 → M5 → M6 es la cadena más larga. Por eso D3 entrega primero una muestra de 50 predios por zona, para que D1 parta sin esperar la descarga completa.

D4 → D5 corre en paralelo y debe estar listo antes de M5.

## Prioridad actual

Orden de trabajo al 21-11-2026. Se actualiza cuando cambia lo que bloquea.

| Orden | Tarea | Responsable | Por qué ahora | Qué ya hay |
| --- | --- | --- | --- | --- |
| 1 | D1, D2, D11 | Gabriela | Es el inicio del camino crítico | Zonas, muestra de predios y casos en `data/` |
| 2 | D4 Derechos normalizados | Tomás | Es la tarea de datos más difícil (datums, unidades) y M5 no puede partir sin ella | Excel de Valparaíso descargado y columnas revisadas |
| 3 | D5 Cruce derechos–predios | Tomás | Sin el cruce no hay "consumo sobre derechos", que es el núcleo del índice | Predios listos (D3) |
| 4 | D6 Fiscalizaciones | Tomás | Desbloquea la validación (M6) y la métrica de impacto (M9); reemplaza `data/casos_validacion.geojson` | Planilla descargada y filtros probados |
| 5 | D7 Especie por predio | Tomás | Mejora el Kc de M4; es rápida porque la llave es el rol | Capa de CIREN probada |
| — | D8, D9, D10, D12, D14 | Por asignar | No bloquean el camino crítico; sirven para el expediente, la ruta y el pitch | Fuentes verificadas en el spec |

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
| 21-11-2026 | Métrica de impacto: candidatos no fiscalizados × acierto medido, en rango de m³ y pesos; un candidato no es un caso | Tomás |
| 21-11-2026 | Datos lo más recientes posible. Caso de la demo: FO-0501-462 (La Ligua, 2025). El ranking usa la temporada seca 2025-26 y la ficha muestra la escena más reciente (octubre de 2026 fue lluvioso) | Tomás |
