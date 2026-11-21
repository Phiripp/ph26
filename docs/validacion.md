# Validación del índice de sospecha (M6)

Generado por `scripts/models/validacion.py` (no editar a mano). Datos: `fiscalizacion.parquet` (D6, D18), `puntaje_validacion.parquet` y `puntaje.parquet` (M5). Mapa: [validacion_casos.geojson](../data/processed/validacion_casos.geojson).

## Resumen

- **Prioriza mejor que el azar en la banda alta.** De los 19 positivos detectables por verdor, el predio del punto de la DGA cae en banda alta en 6 (32%), contra 12% al azar: **2.6 veces** (IC 95 % 1.3–4.4). En alta o media: 9 (47%) contra 27% (1.8 veces).
- **Por vecindario el lift es menor.** Con la mejor banda de los predios a 30 m, 11 de 19 positivos quedan en alta o media, pero el azar también sube (varios predios): 1.4 veces, con intervalo que incluye 1.
- **No distingue infractores entre fiscalizados.** AUC 0.56 (IC 95 % 0.39–0.72) entre 19 positivos y 48 negativos detectables. La DGA ya fiscaliza predios regados: tienen señal de riego el 79% de los positivos y el 69% de los negativos.
- **El verdor no ve todo.** 14 de 33 positivos no son detectables por verdor (NDVI previo bajo 0,30 en el vecindario: suelo desnudo o sequía). Contándolos, el lift baja y su intervalo incluye 1.
- **Muestra chica.** Los intervalos son anchos: sirven para decir si hay señal, no para afinar umbrales.

## Recall frente al azar: predio del punto (principal)

Banda del predio que contiene el punto de la inspección, en la temporada previa. Azar: proporción del universo de su zona en esa banda (2025-26).

### Positivos detectables (19)

| Nivel | Positivos encontrados | Recall (IC 95 %) | Azar esperado | Lift (IC 95 %) |
| --- | --- | --- | --- | --- |
| alta | 6 de 19 | 32% (15%–54%) | 12% | 2.6× (1.3–4.4) |
| alta o media | 9 de 19 | 47% (27%–68%) | 27% | 1.8× (1.0–2.6) |
| cualquier alerta | 10 de 19 | 53% (32%–73%) | 29% | 1.8× (1.1–2.5) |

### Positivos detectables del set limpio (6)

Sin otro predio a 30 m, sin etiquetas mixtas ni recurso (D18).

| Nivel | Positivos encontrados | Recall (IC 95 %) | Azar esperado | Lift (IC 95 %) |
| --- | --- | --- | --- | --- |
| alta | 2 de 6 | 33% (10%–70%) | 14% | 2.4× (0.7–5.1) |
| alta o media | 2 de 6 | 33% (10%–70%) | 29% | 1.2× (0.3–2.4) |
| cualquier alerta | 2 de 6 | 33% (10%–70%) | 32% | 1.1× (0.3–2.2) |

### Todos los positivos, detectables o no (33)

| Nivel | Positivos encontrados | Recall (IC 95 %) | Azar esperado | Lift (IC 95 %) |
| --- | --- | --- | --- | --- |
| alta | 7 de 33 | 21% (11%–38%) | 12% | 1.8× (0.9–3.2) |
| alta o media | 11 de 33 | 33% (20%–50%) | 26% | 1.3× (0.8–2.0) |
| cualquier alerta | 12 de 33 | 36% (22%–53%) | 28% | 1.3× (0.8–1.9) |

### Positivos detectables de Z1 (8)

| Nivel | Positivos encontrados | Recall (IC 95 %) | Azar esperado | Lift (IC 95 %) |
| --- | --- | --- | --- | --- |
| alta | 3 de 8 | 38% (14%–69%) | 9% | 4.2× (1.5–7.8) |
| alta o media | 4 de 8 | 50% (22%–78%) | 22% | 2.3× (1.0–3.6) |
| cualquier alerta | 4 de 8 | 50% (22%–78%) | 24% | 2.1× (0.9–3.3) |

### Positivos detectables de Z2 (11)

| Nivel | Positivos encontrados | Recall (IC 95 %) | Azar esperado | Lift (IC 95 %) |
| --- | --- | --- | --- | --- |
| alta | 3 de 11 | 27% (10%–57%) | 15% | 1.9× (0.7–3.9) |
| alta o media | 5 de 11 | 45% (21%–72%) | 30% | 1.5× (0.7–2.4) |
| cualquier alerta | 6 de 11 | 55% (28%–79%) | 33% | 1.6× (0.8–2.4) |

## Recall frente al azar: vecindario (sensibilidad)

Mejor banda entre los predios a 30 m o menos del punto. Azar: probabilidad de que al menos uno de los n predios del vecindario caiga en la banda, 1 − (1 − p)^n.

### Positivos detectables (19)

| Nivel | Positivos encontrados | Recall (IC 95 %) | Azar esperado | Lift (IC 95 %) |
| --- | --- | --- | --- | --- |
| alta | 6 de 19 | 32% (15%–54%) | 20% | 1.6× (0.8–2.7) |
| alta o media | 11 de 19 | 58% (36%–77%) | 41% | 1.4× (0.9–1.9) |
| cualquier alerta | 12 de 19 | 63% (41%–81%) | 44% | 1.4× (0.9–1.8) |

### Todos los positivos (33)

| Nivel | Positivos encontrados | Recall (IC 95 %) | Azar esperado | Lift (IC 95 %) |
| --- | --- | --- | --- | --- |
| alta | 7 de 33 | 21% (11%–38%) | 19% | 1.1× (0.6–2.0) |
| alta o media | 13 de 33 | 39% (25%–56%) | 39% | 1.0× (0.6–1.4) |
| cualquier alerta | 14 de 33 | 42% (27%–59%) | 42% | 1.0× (0.6–1.4) |

## Entre fiscalizados (límite)

| Comparación | Positivos | Negativos | AUC (IC 95 %) |
| --- | --- | --- | --- |
| Detectables, todos los negativos | 19 | 48 | 0.56 (0.40–0.72) |
| Detectables, solo "No acoge" | 19 | 21 | 0.59 (0.40–0.76) |
| Todos (detectables o no) | 33 | 74 | 0.53 (0.42–0.64) |

Acierto entre fiscalizados detectables: 28% en general y 31% entre los que Caudal pone en alta o media (11 de 36).

## Bandas de los fiscalizados detectables

| Etiqueta | alta | media | baja | sin_alerta |
| --- | --- | --- | --- | --- |
| negativo | 10 | 15 | 1 | 22 |
| positivo | 6 | 5 | 1 | 7 |

## Casos clave

| Expediente | Zona | Etiqueta | Temporada previa | Detectable | Banda | Puntaje | Derechos propios |
| --- | --- | --- | --- | --- | --- | --- | --- |
| FO-0504-95 | Z2 | positivo | 2020-21 | sí | alta | 91 | no |
| FD-0501-181 | Z1 | positivo | 2023-24 | sí | alta | 92 | no |
| FO-0504-157 | Z2 | positivo | 2024-25 | sí | sin_alerta | 0 | sí |
| FD-0504-257 | Z2 | positivo | 2023-24 | sí | sin_alerta | 0 | no |

## Por qué el AUC es bajo y qué se probó

- Sesgo de selección: la DGA fiscaliza por denuncia u oficio predios que ya riegan; entre ellos el verdor satura.
- Negativos débiles: más de la mitad son "Cierra expediente" (archivo), no "No acoge".
- La infracción no siempre es de volumen: de los positivos detectables con derechos, la mayoría consume según M4 menos de la mitad de lo inscrito; su falta es de punto de captación, caudal instantáneo o traslado.
- Rango de consumo ancho (máximo ≈ 2,9 veces el mínimo): solo se detectan excesos grandes.
- Prueba de variantes de M5 (exceso anual o mensual × orden por volumen o por hectárea): mensual + hectárea dio el mayor AUC (0,558 contra 0,532) con el mismo recall. Ver `data/README.md`, sección M5.

## Limitaciones

- El universo de la línea base es 2025-26; los expedientes son de 2019-20 a 2024-25.
- La ubicación del expediente es el punto declarado por la DGA; el vecindario de 30 m absorbe parte del error.
- El 44 % de los positivos no es detectable por verdor: Caudal no los ve con esta señal.
- Una cifra anterior (2,8 veces en alta, 2,3 en alta o media) comparaba la mejor banda del vecindario con la proporción de un solo predio: estaba inflada. Las cifras de este documento la reemplazan.
