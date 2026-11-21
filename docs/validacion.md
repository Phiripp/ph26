# Validación del índice de sospecha (M6)

Generado por `scripts/models/validacion.py` (no editar a mano). Datos: `fiscalizacion.parquet` (D6, D18), `puntaje_validacion.parquet` y `puntaje.parquet` (M5). Mapa: [validacion_casos.geojson](../data/processed/validacion_casos.geojson).

## Resumen

- **Prioriza mejor que el azar en la banda alta.** De los 19 positivos detectables por verdor, el predio del punto de la DGA cae en banda alta en 7 (37%), contra 10% al azar: **3.7 veces** (IC 95 % 1.9–5.9). En alta o media: 10 (53%) contra 21% (2.5 veces).
- **Por vecindario el lift es menor.** Con la mejor banda de los predios a 30 m, 12 de 19 positivos quedan en alta o media, pero el azar también sube (varios predios): 1.9 veces (IC 95 % 1.2–2.4).
- **No distingue infractores entre fiscalizados.** AUC 0.62 (IC 95 % 0.46–0.77) entre 19 positivos y 48 negativos detectables. La DGA ya fiscaliza predios regados: tienen señal de riego el 74% de los positivos y el 60% de los negativos.
- **El verdor no ve todo.** 14 de 33 positivos no son detectables por verdor (NDVI previo bajo 0,30 en el vecindario: suelo desnudo o sequía). Contándolos, el lift en alta baja a 2.2 veces (IC 95 % 1.1–3.9).
- **Umbrales calibrados con este mismo set (M7).** Los umbrales de M3 se eligieron en [calibracion.md](calibracion.md) con estos positivos, así que el lift es optimista. Con los umbrales iniciales (fijados antes de mirar) era 2.6 veces (IC 95 % 1.3–4.4): esa es la cifra sin sesgo de elección.
- **Muestra chica.** Los intervalos son anchos: sirven para decir si hay señal, no para afinar umbrales.

## Recall frente al azar: predio del punto (principal)

Banda del predio que contiene el punto de la inspección, en la temporada previa. Azar: proporción del universo de su zona en esa banda (2025-26).

### Positivos detectables (19)

| Nivel | Positivos encontrados | Recall (IC 95 %) | Azar esperado | Lift (IC 95 %) |
| --- | --- | --- | --- | --- |
| alta | 7 de 19 | 37% (19%–59%) | 10% | 3.7× (1.9–5.9) |
| alta o media | 10 de 19 | 53% (32%–73%) | 21% | 2.5× (1.5–3.5) |
| cualquier alerta | 11 de 19 | 58% (36%–77%) | 23% | 2.5× (1.6–3.3) |

### Positivos detectables del set limpio (6)

Sin otro predio a 30 m, sin etiquetas mixtas ni recurso (D18).

| Nivel | Positivos encontrados | Recall (IC 95 %) | Azar esperado | Lift (IC 95 %) |
| --- | --- | --- | --- | --- |
| alta | 2 de 6 | 33% (10%–70%) | 11% | 3.0× (0.9–6.3) |
| alta o media | 2 de 6 | 33% (10%–70%) | 22% | 1.5× (0.4–3.2) |
| cualquier alerta | 2 de 6 | 33% (10%–70%) | 24% | 1.4× (0.4–2.9) |

### Todos los positivos, detectables o no (33)

| Nivel | Positivos encontrados | Recall (IC 95 %) | Azar esperado | Lift (IC 95 %) |
| --- | --- | --- | --- | --- |
| alta | 7 de 33 | 21% (11%–38%) | 10% | 2.2× (1.1–3.9) |
| alta o media | 10 de 33 | 30% (17%–47%) | 21% | 1.5× (0.8–2.3) |
| cualquier alerta | 11 de 33 | 33% (20%–50%) | 23% | 1.5× (0.9–2.2) |

### Positivos detectables de Z1 (8)

| Nivel | Positivos encontrados | Recall (IC 95 %) | Azar esperado | Lift (IC 95 %) |
| --- | --- | --- | --- | --- |
| alta | 4 de 8 | 50% (22%–78%) | 8% | 6.4× (2.8–10.0) |
| alta o media | 5 de 8 | 62% (31%–86%) | 18% | 3.4× (1.7–4.7) |
| cualquier alerta | 5 de 8 | 62% (31%–86%) | 20% | 3.1× (1.5–4.2) |

### Positivos detectables de Z2 (11)

| Nivel | Positivos encontrados | Recall (IC 95 %) | Azar esperado | Lift (IC 95 %) |
| --- | --- | --- | --- | --- |
| alta | 3 de 11 | 27% (10%–57%) | 12% | 2.3× (0.8–4.8) |
| alta o media | 5 de 11 | 45% (21%–72%) | 23% | 2.0× (0.9–3.2) |
| cualquier alerta | 6 de 11 | 55% (28%–79%) | 25% | 2.2× (1.1–3.1) |

## Recall frente al azar: vecindario (sensibilidad)

Mejor banda entre los predios a 30 m o menos del punto. Azar: probabilidad de que al menos uno de los n predios del vecindario caiga en la banda, 1 − (1 − p)^n.

### Positivos detectables (19)

| Nivel | Positivos encontrados | Recall (IC 95 %) | Azar esperado | Lift (IC 95 %) |
| --- | --- | --- | --- | --- |
| alta | 7 de 19 | 37% (19%–59%) | 17% | 2.2× (1.1–3.4) |
| alta o media | 12 de 19 | 63% (41%–81%) | 33% | 1.9× (1.2–2.4) |
| cualquier alerta | 13 de 19 | 68% (46%–85%) | 36% | 1.9× (1.3–2.3) |

### Todos los positivos (33)

| Nivel | Positivos encontrados | Recall (IC 95 %) | Azar esperado | Lift (IC 95 %) |
| --- | --- | --- | --- | --- |
| alta | 7 de 33 | 21% (11%–38%) | 16% | 1.3× (0.7–2.4) |
| alta o media | 12 de 33 | 36% (22%–53%) | 32% | 1.1× (0.7–1.7) |
| cualquier alerta | 13 de 33 | 39% (25%–56%) | 35% | 1.1× (0.7–1.6) |

## Entre fiscalizados (límite)

| Comparación | Positivos | Negativos | AUC (IC 95 %) |
| --- | --- | --- | --- |
| Detectables, todos los negativos | 19 | 48 | 0.62 (0.46–0.77) |
| Detectables, solo "No acoge" | 19 | 21 | 0.65 (0.48–0.82) |
| Todos (detectables o no) | 33 | 74 | 0.57 (0.46–0.68) |

Acierto entre fiscalizados detectables: 28% en general y 36% entre los que Caudal pone en alta o media (12 de 33).

## Bandas de los fiscalizados detectables

| Etiqueta | alta | media | baja | sin_alerta |
| --- | --- | --- | --- | --- |
| negativo | 8 | 13 | 1 | 26 |
| positivo | 7 | 5 | 1 | 6 |

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
