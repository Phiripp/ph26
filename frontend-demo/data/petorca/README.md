# Datos demo — Valle de Petorca (Caudal v2)

> **El sistema prioriza, no acusa.** Los predios se identifican solo por ID (P-001…). Nada aquí nombra dueños.

Generado por `scripts/build_petorca_data.py` (re-ejecutable; cachea llamadas externas en `scripts/.cache/petorca/`).

## Qué es real y qué es ilustrativo

| Archivo | Real | Ilustrativo |
|---|---|---|
| `predios.geojson` | Geometría: polígonos OpenStreetMap (`landuse=orchard/farmland`) vía Overpass, `fuente_geom:"OSM"`. Área calculada de la geometría. | `m3_derecho` (**calibrado para la demo**), y por lo tanto `indice` y `banda` (`illustrative_scores: true`). Cultivo marcado `cultivo_fuente:"supuesto"` cuando OSM no lo dice. |
| `clima.json` | Open-Meteo archive (reanálisis ERA5), diario 2022-2024. | — (pendiente contrastar con estaciones DMC / DGA / INIA). |
| `series.json` | NDVI/NDMI Sentinel-2 L2A reales (Earth Search, tesela 19HCE), 1 escena/mes, 40 m. | Referencia de secano es una aproximación por píxeles (no un predio de secano verificado). |
| `ruta.json` / `ruta.gpx` | Orden óptimo (OR-Tools) sobre matriz OSRM; geometría por camino (OSRM). | La selección de predios depende del índice ilustrativo. |

## Método

1. **Ventana seca**: ≥ 10 días seguidos con lluvia < 1.0 mm (lluvia efectiva). Meses con racha seca ≥ 20 días se usan para medir verdor anómalo.
2. **Índices**: NDVI = (B08−B04)/(B08+B04); NDMI = (B8A−B11)/(B8A+B11), mediana por predio de píxeles válidos (máscara SCL: se descartan nubes 3/8/9/10). Resolución de lectura 40 m (overviews COG) para mantener liviana la descarga. Reflectancia = DN·0,0001 − 0,1 (sin el −0,1 en escenas que Earth Search ya re-armonizó, `earthsearch:boa_offset_applied`).
3. **Referencia de secano**: mediana mensual de píxeles de vegetación/suelo a >120 m de los predios OSM con 0,05 < NDVI < 0,5 (cerros y matorral). `z_verdor = (NDVI_predio − NDVI_ref) / (1,4826·MAD_ref)`; ídem `z_humedad` con NDMI.
4. **Consumo estimado (FAO-56 simplificado)**, año 2024:
   `V = Σ_mes max(0, Kc(NDVI)·ET0 − Pef) · A`, con `Kc = clamp(1.25·NDVI + 0.1, 0.15, 1.15)`, `Pef = 0.8·P`, ET0 y P mensuales de `clima.json`, A en ha (1 mm·ha = 10 m³). Kc lineal simple; para palto NDVI≈0,65 → Kc≈0,91 (rango FAO 0,75–0,95 para palto/cítricos con cobertura).
5. **Rango, no número**: `m3_estimado_min/max = V·(1 ∓ r)`, r = 20 % (confianza alta), 27 % (media), 35 % (baja).
6. **Confianza**: baja con cada motivo (`pocos píxeles` < 15 px de 40 m, `pocas escenas válidas` < 9 meses, `nubosidad alta` > 20 % media, `sin referencia de secano cercana`, `cultivo no verificado`). 0 motivos = alta, 1 = media, ≥2 = baja. Peso w = 1 / 0,85 / 0,65.
7. **Índice de sospecha**: `exceso = (V − m3_derecho)/m3_derecho`; `indice = min(1, max(0, exceso)/0,5) · w`. Bandas: alta ≥ 0,60; media ≥ 0,30; baja ≥ 0,10; sin_alerta < 0,10.
8. **m3_derecho (ILUSTRATIVO)**: no tenemos el catastro de derechos (CPA/DGA) cruzado con predios. Para la demo se calibra a partir del ranking de verdor en ventana seca (`0,6·z_verdor + 0,4·z_humedad`, ponderado por confianza y área) para mostrar ~5 alta / ~8 media / resto baja–sin alerta. **No representa derechos reales.**
9. **Ruta**: plaza de Petorca 08:30, alta + top media (N=8), 20 min por parada, ida y vuelta. Distancias OSRM (servidor demo público) + TSP OR-Tools; fallback haversine + 2-opt y tramos rectos.

## Resultado de esta corrida

- Predios: 34 (34 OSM, 0 ilustrativos). Bandas: alta 5, media 8, baja 11, sin_alerta 10.
- Ventanas secas 2022-2024: 28.
- Ruta: 68.6 km, 346 min totales (OR-Tools / OSRM).
