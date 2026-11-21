# Datos por zona — series, puntajes y rutas (Caudal v2)

> **El sistema prioriza, no acusa.** Predios por ID CIREN y rol; sin nombres. Las bandas son **provisionales**
> hasta el modelo M5 del equipo. Los 10 casos son expedientes **resueltos** por la DGA (sancionados).

Generado por `scripts/build_zonas_scores.py` (series, scores, ruta) y `scripts/build_zonas_data.py` (predios,
clima, casos, fiscalizaciones). Ambos son re-ejecutables; las llamadas externas se cachean en `scripts/.cache/zonas/`.

## Qué es real y qué es provisional

| Archivo | Real | Provisional |
|---|---|---|
| `{z}/predios.geojson` | Polígonos CIREN 2022, rol, derechos DGA del rol (temporada 2025-26), especie (Catastro Frutícola 2025) | — |
| `{z}/clima.json` | Lluvia Open-Meteo corregida con estaciones DMC, ET0, ventanas secas N=10 (equipo) | — |
| `{z}/series.json` | NDVI/NDMI Sentinel-2 L2A (Earth Search), 1 escena por mes y tesela, mediana por predio | Referencia de secano = píxeles CONAF (matorral/pradera estable) en la ventana |
| `{z}/scores.json` | Consumo FAO-56 con NDVI real, ET0/lluvia reales, derechos reales del rol | Umbrales, Kc(NDVI), pesos de confianza, bandas (`provisional: true`) |
| `{z}/ruta.json`, `ruta.gpx` | Orden óptimo (OR-Tools) y geometría por camino (OSRM) | La selección depende de las bandas provisionales |

## Método

1. **Escenas**: Sentinel-2 L2A, Element84 Earth Search (COG en AWS). Por tesela MGRS y mes, se prueban hasta
   3 escenas en orden de nubosidad de la tesela y se elige la con más píxeles despejados (SCL 4/5/6/7/11)
   sobre los predios. Lectura a 20 m (overview 2x de B04/B08, nativo B8A/B11/SCL), en una ventana alrededor de
   los predios + 3.0 km. Meses: 2020-07 a 2026-11. Teselas: Z1 19HBE + 19HCE, Z2 19HBD + 19HCD.
2. **Offset BOA (corregido)**: desde la baseline 04.00 los DN traen +1000. Earth Search ya los re-armonizó en
   parte de las escenas, pero `earthsearch:boa_offset_applied` no es confiable (p. ej. `S2C_19HBE_20241108_1`
   dice `False` y ya está armonizada). Se decide **con los datos**: si el percentil 1 de B04 sobre vegetación/suelo
   (SCL 4/5) es > 800 DN, se resta 1000; si no, no. Reflectancia = (DN − offset)/10000. Se resta **una sola vez**
   (el bug D15 del `serie_predio` del equipo la restaba dos veces). Validación en la tabla de abajo.
3. **Índices**: NDVI = (B08−B04)/(B08+B04); NDMI = (B8A−B11)/(B8A+B11); mediana por predio de píxeles válidos SCL
   (nubes 3/8/9/10 descartadas; `nubosidad_pct` = % del predio con nube). Se exige ≥ 30 % del predio válido.
4. **Referencia de secano**: polígonos CONAF del equipo (`referencia_secano.parquet`, matorral y pradera estable,
   sin huertos) dentro de la ventana, a > 60 m de los predios. Mediana y MAD mensual por tesela.
   `z = (índice_predio − mediana_ref) / max(0,02; 1,4826·MAD)`.
5. **Área regada en seca**: píxeles del predio con NDVI > max(0.3; ref + 3.0·MAD) en los meses secos.
   `area_riego_ha = área × mediana(frac_verde)`. Evita que un cerro de 900 ha "consuma" como huerto.
6. **Ventana seca**: mes seco = ≥ 20 días dentro de una ventana seca (N=10 días sin lluvia efectiva) de la celda
   de clima del predio (`dias_sin_lluvia.parquet` del equipo). Se miran dic–mar de cada temporada.
7. **Riego probable en ventana seca**: `area_riego_ha ≥ 0.5` y anomalía de humedad del área verde
   (`z_humedad_verde`, NDMI) ≥ 1.0 en los meses secos (verdor y humedad sobre la referencia a la vez).
8. **Consumo (FAO-56 simplificado)**, temporada jul–jun:
   `V = Σ_mes max(0, Kc(NDVI_verde)·ET0 − 0.8·P) · area_riego`, `Kc = clamp(1.25·NDVI + 0.1, 0.15, 1.15)`,
   ET0 y P (lluvia corregida) mensuales de la celda del predio. 1 mm·ha = 10 m³. Meses sin escena: interpolación.
9. **Rango, no número**: `m3_estimado_min/max = V·(1 ∓ r)`, r = 20 / 27 / 35 % según confianza alta / media / baja.
10. **Confianza**: baja un nivel por motivo (`pocos píxeles` < 25 px, `pocas escenas válidas`, `nubosidad alta`
    > 20 %, `sin referencia de secano cercana` < 20 ha CONAF a 3 km, `predio muy grande` > 150 ha,
    `geometría aproximada`, `cruce de derechos con confianza baja` solo si el rol tiene derechos, y en Z2
    `posible agua de canal no registrada en el rol` si el rol no tiene derechos y hay canal a ≤ 300 m: en el
    Aconcagua el canal sí trae agua por acciones de comunidades que no se inscriben por rol). Los derechos del
    entorno **no** bajan la confianza (riesgo del caso FD-0501-181 en el spec). Peso w = 1 / 0,85 / 0,65.
11. **Índice y banda** (`m3_derecho_rol` real de la temporada, `predio_derecho.parquet`):
    sin riego en ventana seca → `sin_alerta`; con riego, `exceso = V − derecho`,
    `indice = w · max(0, exceso)/V · min(1, √(exceso/50000))`; alta ≥ 0,60, media ≥ 0,30, si no `baja`
    (riego dentro de los derechos = prioridad baja, como dice el spec). `alta` exige confianza media o alta (si no,
    queda en `media`). `sin_dato` si no hay escenas en la seca.
12. **Histórico**: lo mismo para cada temporada 2020-21…2025-26 con los derechos vigentes a esa temporada
    (`scores.json → predios[id].historico`). `scores.json → casos` resume, para cada caso, las temporadas cuya ventana
    seca empezó antes de la inspección y en cuáles el predio ya estaba en banda alta.
13. **Ruta**: sale de la plaza de la comuna principal (Z1 Cabildo, Z2 Hijuelas) a las 08:30, visita alta + media
    (máx. 8) por índice, 20 min por parada, ida y vuelta. Matriz OSRM (servidor demo público) + TSP OR-Tools.

## Resultado de esta corrida (2026-11-21)

- **Z1 Petorca**: 50 predios (predios.geojson (DATA-TAB)); teselas 19HBE, 19HCE; 77/77 meses con escena; bandas 2025-26: alta 7, media 14, baja 11, sin_alerta 18, sin_dato 0; ruta 115.1 km, 333 min, 8 paradas (OR-Tools/OSRM)
  - Caso FD-0501-181 (predio 5344224, inspección 2024-04-02): banda en la temporada previa 2023-24 = alta; temporadas en alta antes de la inspección: 2020-21, 2021-22, 2022-23, 2023-24
  - Caso FO-0501-462 (predio 5304670, inspección 2025-05-07): banda en la temporada previa 2024-25 = sin_alerta; temporadas en alta antes de la inspección: ninguna
  - Caso FO-0501-376 (predio 5306951, inspección 2022-12-27): banda en la temporada previa 2022-23 = baja; temporadas en alta antes de la inspección: ninguna
  - Caso FO-0501-386 (predio 5306903, inspección 2022-12-27): banda en la temporada previa 2022-23 = baja; temporadas en alta antes de la inspección: ninguna
  - Caso FD-0501-191 (predio 5343901, inspección 2025-03-31): banda en la temporada previa 2024-25 = media; temporadas en alta antes de la inspección: ninguna
  - Caso FO-0501-380 (predio 5344279, inspección 2022-08-04): banda en la temporada previa 2021-22 = alta; temporadas en alta antes de la inspección: 2020-21, 2021-22
  - Caso FD-0501-189 (predio 5344930, inspección 2025-02-25): banda en la temporada previa 2024-25 = baja; temporadas en alta antes de la inspección: ninguna
- **Z2 Aconcagua bajo**: 50 predios (predios.geojson (DATA-TAB)); teselas 19HBD, 19HCD; 77/77 meses con escena; bandas 2025-26: alta 17, media 13, baja 12, sin_alerta 8, sin_dato 0; ruta 59.1 km, 244 min, 8 paradas (OR-Tools/OSRM)
  - Caso FD-0504-257 (predio 5331880, inspección 2024-07-09): banda en la temporada previa 2023-24 = media; temporadas en alta antes de la inspección: 2020-21, 2021-22, 2022-23
  - Caso FO-0504-95 (predio 5301413, inspección 2021-11-23): banda en la temporada previa 2020-21 = alta; temporadas en alta antes de la inspección: 2020-21
  - Caso FO-0504-157 (predio 5300004, inspección 2025-05-14): banda en la temporada previa 2024-25 = baja; temporadas en alta antes de la inspección: ninguna

## Validación del offset (escenas con flag y percentil 1 de B04)

| Escena | Baseline | boa_offset_applied | p1 B04 (DN) | Offset restado |
|---|---|---|---|---|
| S2A_19HBE_20200722_1_L2A | 05.00 | True | 167.0 | 0 |
| S2B_19HBE_20220118_0_L2A | 03.01 | False | 385.0 | 0 |
| S2A_19HBE_20220503_0_L2A | 04.00 | False | 14.0 | 0 |
| S2B_19HCE_20220128_0_L2A | 04.00 | False | 1646.0 | 1000 |
| S2A_19HBD_20200722_1_L2A | 05.00 | True | 113.0 | 0 |
| S2B_19HBD_20220118_0_L2A | 03.01 | False | 310.0 | 0 |
| S2B_19HBD_20220329_0_L2A | 04.00 | False | 242.0 | 0 |
| S2B_19HCD_20220128_0_L2A | 04.00 | False | 1280.0 | 1000 |
