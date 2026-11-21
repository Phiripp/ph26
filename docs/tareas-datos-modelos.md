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
| D1 | Series mensuales de NDVI, NDWI y NDMI por predio, con máscara de nubes SCL; de enero de 2020 a octubre de 2026 (prioridad: 2021–2022 en Z2 y 2024–2026 en Z1) | Sentinel-2 L2A (STAC) | Z1, Z2 | Gabriela | D3 (geometrías) | `serie_predio.parquet` | ⬜ |
| D2 | Lluvia diaria y ET0 en grilla; estaciones DMC, DGA e INIA donde existan | Open-Meteo y estaciones | Z1, Z2 | Gabriela | — | `clima.parquet` | ⬜ |
| D3 | Descargar los predios de las comunas de cada zona y calcular el área en EPSG:32719. Entregar primero una muestra de 50 predios por zona para desbloquear D1 | CIREN Propiedades Rurales | Z1, Z2 | Tomás | — | `scripts/extract/predios_ciren.py` → `predio.parquet` (local) y `predio_muestra.geojson` (en git) | ✅ |
| D4 | Descargar el Excel de derechos de Valparaíso; convertir datums; normalizar a m³ por mes; marcar los eventuales y las "Acciones" | DGA derechos registrados | Z1, Z2 | Por asignar | — | `derecho.parquet` (sin nombres de titulares; los nombres quedan en `data/raw/`) | ⬜ |
| D5 | Cruzar derechos con predios: punto de captación en el predio o a menos de 500 m; si falla, por titular en la comuna. Guardar `metodo_cruce` y `confianza_cruce` | D3 + D4 | Z1, Z2 | Por asignar | D3, D4 | `derecho.parquet` con `predio_id` | ⬜ |
| D6 | Filtrar la planilla de fiscalizaciones por extracción no autorizada en cada zona. Positivo: multa o "Constata infracción" / "Acoge". Negativo débil: "No acoge" / "Cierra expediente" | DGA planilla de fiscalización | Z1, Z2 | Por asignar | — | `fiscalizacion.parquet` | ⬜ |
| D7 | Especie plantada por predio | CIREN Catastro Frutícola 2025 | Z1, Z2 | Por asignar | D3 | columna `especie` en `predio.parquet` | ⬜ |
| D8 | Cauces y canales de riego | DGA red de drenajes (SMA) y CIREN infraestructura de riego | Z1, Z2 | Por asignar | — | `cauce.parquet` | ⬜ |
| D9 | Red vial guardada para uso offline, con 25 km/h en `track` | OSM con osmnx | Z1, Z2 | Por asignar | — | `red_vial_z1.graphml`, `red_vial_z2.graphml` | ⬜ |
| D10 | Zonas de prohibición y restricción de los acuíferos | DGA (rest-sit.mop.gob.cl) | Z1, Z2 | Por asignar | — | `restriccion.parquet` | ⬜ |
| D11 | Polígonos de referencia de secano (matorral y pradera) | CONAF uso de la tierra 2001–2019 | Z1, Z2 | Gabriela | — | `referencia_secano.parquet` | ⬜ |
| D12 | Opcional: ubicación de APR y cifras de camiones aljibe para el pitch | DOH (SMA), prensa y estudios | Z1 | Por asignar | — | `apr.parquet` y notas para el pitch | ⬜ |

## Tareas de modelos

Cada tarea entrega código en el repo y un archivo de resultados en `data/processed/`.

| ID | Tarea | Zonas | Responsable | Depende de | Entrega | Estado |
| --- | --- | --- | --- | --- | --- | --- |
| M1 | Ventanas secas: periodos con N o más días sin lluvia efectiva (N inicial = 10) | Z1, Z2 | Por asignar | D2 | `ventana_seca.parquet` | ⬜ |
| M2 | Anomalías `z_verdor` y `z_humedad` por predio frente a la referencia de secano o a la historia del predio | Z1, Z2 | Por asignar | D1, D11 | columnas en `serie_predio.parquet` | ⬜ |
| M3 | Detector de riego: ambas anomalías sobre su umbral dentro de una ventana seca | Z1, Z2 | Por asignar | M1, M2 | `senal_riego.parquet` | ⬜ |
| M4 | Consumo estimado con FAO-56: Kc(NDVI), con ajuste por especie si existe; resultado en rango de m³ | Z1, Z2 | Por asignar | D1, D2, D7 | `consumo.parquet` | ⬜ |
| M5 | Índice de sospecha, confianza y bandas (alta, media, baja) | Z1, Z2 | Por asignar | M3, M4, D5 | `puntaje.parquet` | ⬜ |
| M6 | Validación: posición en el ranking de los positivos de D6; métrica precisión en los k primeros. Caso principal: FO-0504-95 (Hijuelas) | Z2 primero, después Z1 | Por asignar | M5, D6 | `validacion.md` con la métrica y el mapa | ⬜ |
| M7 | Calibrar N, los umbrales de anomalía y los pesos de la confianza con el resultado de M6 | Z2 | Por asignar | M6 | valores fijados en el spec | ⬜ |
| M8 | Ruta de inspección con OR-Tools: un vehículo, cada predio como parada opcional con premio según su puntaje, jornada de 8 h; exportar GPX | Z1, Z2 | Por asignar | M5, D9 | `ruta.py` y GPX de ejemplo | ⬜ |

## Camino crítico

D3 → D1 → M2 → M3 → M5 → M6 es la cadena más larga. Por eso D3 entrega primero una muestra de 50 predios por zona, para que D1 parta sin esperar la descarga completa.

D4 → D5 corre en paralelo y debe estar listo antes de M5.

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
