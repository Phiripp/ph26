# Validación de las alertas en Valparaíso fuera de Z1 y Z2

Generado por `scripts/models/validacion_region.py --region R05 --excluir-z1z2` (no editar a mano, salvo la recomendación). Misma metodología que [validacion.md](validacion.md); las diferencias están en [Método](#método-y-límites).

## Resumen

- **Banda alta, predio del punto.** De los 40 positivos detectables por verdor fuera de Z1 y Z2, el predio del punto de la DGA cae en banda alta en 3 (8%; IC 95 % de Wilson 3%–20%), contra 17% al azar (14%–19%): **0.5 veces** (IC 95 % 0.2–1.2; 0.0–1.0 contando el error del azar). En alta o media: 4 (10%) contra 21%, 0.5 veces (0.2–1.1).
- **Todos los positivos.** Contando los 10 que el verdor no puede ver, el recall en alta es 3 de 50 (6%) y el lift 0.4 veces (0.1–1.1).
- **Aconcagua interior.** 3 de 10 positivos detectables en alta (30%; 11%–60%), contra 46% al azar (41%–52%): 0.6 veces (IC 95 % 0.2–1.3).
- **Resto.** 0 de 30 positivos detectables en alta (0%; 0%–11%), contra 7% al azar (4%–10%): 0.0 veces (IC 95 % 0.0–1.7).
- **Por vecindario.** Con la mejor banda de los predios a 30 m: 3 de 40 en alta, contra 24% al azar: 0.3 veces (0.1–0.8).
- **Por qué.** El predio del punto tiene señal de riego en 8 de 50 positivos y en 18 de 147 negativos, y derechos propios ubicados en 24 y 69. Detalle por subzona y comparación con los controles en [Señal de riego y derechos propios](#señal-de-riego-y-derechos-propios).
- **Azar de la región.** Ponderando las subzonas por sus predios elegibles, el 20% de los predios de control queda en alta en su temporada (falta el contraste con el universo de la corrida nacional: `--universo`).
- **Sesgo de canal, canal a 300 m o menos.** De los fiscalizados en alta con el indicio, 3 de 12 son positivos; sin el indicio, 0 de 0 (Fisher exacto: no aplica, un grupo está vacío). Descontando esas alertas, el lift en alta queda en 0.0 veces (IC 95 % 0.0–1.6), con 0 de 40 positivos.
- **Sesgo de canal, área de riego superficial de CIREN en la mitad del predio o más.** De los fiscalizados en alta con el indicio, 2 de 10 son positivos; sin el indicio, 1 de 2 (Fisher exacto: p = 0.45). Descontando esas alertas, el lift en alta queda en 0.4 veces (IC 95 % 0.1–2.1), con 1 de 40 positivos.
- **Entre fiscalizados.** AUC 0.49 (IC 95 % 0.41–0.58) entre 40 positivos y 93 negativos detectables.

## Recomendación

<!-- recomendacion:inicio -->
**Mantener el rótulo "exploratorio" en todo Valparaíso fuera de Z1 y Z2.** Ni en el Aconcagua interior ni en el resto hay evidencia de que la banda alta encuentre más infractores que el azar.

**¿La banda alta encuentra más infractores que el azar?** No. Lift 0.5 veces (IC 95 % 0.2–1.2): 3 de 40 positivos detectables en alta, contra 17 % al azar. El intervalo incluye el azar por poco y excluye el 2.6 de Z1 y Z2: con ese lift habrían caído en alta unos 18 de los 40. Contando los positivos que el verdor no ve da 0.4 (0.1–1.1) y por vecindario 0.3 (0.1–0.8). Entre fiscalizados el AUC es 0.49 (0.41–0.58).

**¿El Aconcagua interior se comporta distinto?** En la cantidad de alertas sí; en el acierto no.

- **Aconcagua interior.** El 46 % de los predios de control queda en alta (7 % en el resto), así que la banda no prioriza: aunque acertara todos los positivos el lift no pasaría de 2.2. Acierta 3 de 10 positivos detectables (0.6 veces; 0.2–1.3) y pone en alta a los negativos en una proporción parecida (9 de 26). Con 10 positivos no se puede descartar un lift de 1.3, pero sí el de Z1 y Z2.
- **Resto.** Ningún predio del punto queda en alta: 0 de 39 positivos y 0 de 121 negativos. El límite superior del lift es 1.7 entre los detectables. La causa se ve en [Señal de riego y derechos propios](#señal-de-riego-y-derechos-propios): solo 3 de los 39 positivos tienen señal de riego y más de la mitad tiene derechos propios ubicados (22 de 39, contra 12 % de los controles). Las infracciones que la DGA constata ahí no son las que Caudal busca. Fuera de Z1 y Z2 tiene señal de riego el 28 % de los positivos detectables (vecindario); en Z1 y Z2 era el 74 %.

**¿El canal explica las alertas?** Describe bien las alertas, pero los casos no alcanzan para probar que sean falsas.

- En el Aconcagua interior, el 93 % de los controles en alta tiene un canal a 300 m o menos y el 85 % está dentro de un área de riego superficial de CIREN.
- Los 12 fiscalizados en alta tienen `canal_300m`: 3 son positivos (25 %; 9 %–53 %), la misma proporción que entre todos los fiscalizados (25 %). No hay grupo sin canal para comparar. Con el área de riego de CIREN: 2 de 10 positivos dentro y 1 de 2 fuera (Fisher p = 0.45).
- Descontar las alertas dentro de un área de riego superficial baja el azar del interior de 46 % a 7 % y deja 1 de 10 positivos en alta: 1.4 veces (0.3–5.8). No decide nada.
- El catastro de organizaciones de usuarios de la DGA no sirve para esto: son listados por comuna, sin canal, acciones ni ubicación. La capa de áreas de riego de CIREN (`scripts/extract/areas_riego_ciren.py`) es el mejor sustituto público que encontré.

**Qué cambiaría la decisión.**

1. Más positivos con riego por canal: repetir esta validación en la Región Metropolitana y en O'Higgins (`--region`), donde hay más fiscalizaciones en valles con canales.
2. Si se decide tocar el ranking (aquí no se tocó), probar que las alertas dentro de un área de riego superficial bajen de alta a "riego por canal probable" y volver a medir. Hoy esa regla quitaría cerca del 85 % de las alertas altas del interior.
3. Repetir con el clima de ERA5-Land y con `--universo` apuntando al puntaje 2025-26 del bucket. No espero que cambie la conclusión: el 20 % de controles en alta que sale aquí es parecido al 23 % de la corrida nacional, y el 46 % del interior cae en su rango de 40 % a 60 % (cifras de la tarea: sin el bucket no las pude verificar).

**Límites de esta medición.** El clima es de Open-Meteo y no de ERA5-Land. El azar sale de 600 predios de control y no del ranking de toda la región. Las tablas base se reconstruyeron desde las fuentes públicas porque no hubo acceso al bucket. La DGA fiscaliza por denuncia: los fiscalizados no son una muestra al azar de los infractores.
<!-- recomendacion:fin -->

## Casos

Expedientes de extracción no autorizada con etiqueta positivo o negativo, predio elegible a 50 m o menos, inspección desde julio de 2020 y predio fuera de Z1 y Z2: **197** (50 positivos y 147 negativos). Con puntaje en su temporada previa: 197 (50 positivos). Detectables por verdor (NDVI previo de 0,30 o más en el vecindario): 40 de 50 positivos y 93 de 147 negativos.

| Temporada previa | positivo | negativo | Total |
| --- | --- | --- | --- |
| 2019-20 | 6 | 15 | 21 |
| 2020-21 | 7 | 30 | 37 |
| 2021-22 | 9 | 47 | 56 |
| 2022-23 | 8 | 25 | 33 |
| 2023-24 | 10 | 20 | 30 |
| 2024-25 | 10 | 10 | 20 |
| **Total** | 50 | 147 | 197 |

| Subzona | positivo | negativo | Total |
| --- | --- | --- | --- |
| Aconcagua interior | 11 | 26 | 37 |
| Resto | 39 | 121 | 160 |
| **Total** | 50 | 147 | 197 |

## Azar: predios de control

No existe el ranking histórico de toda la región, así que el azar se estima con una muestra aleatoria de 600 predios elegibles fuera de Z1 y Z2 (300 por subzona, semilla 0). Cada control se evalúa en una temporada sorteada entre las temporadas previas de los casos de su subzona y pasa por la misma corrida de M1 a M5 que los casos. Todos tienen puntaje.

| Subzona | Predios elegibles | Controles | En alta (IC 95 %) | En alta o media (IC 95 %) | Con señal de riego |
| --- | --- | --- | --- | --- | --- |
| Aconcagua interior | 6.959 | 300 | 139 de 300 (46%; 41%–52%) | 184 de 300 (61%; 56%–67%) | 63% |
| Resto | 13.549 | 300 | 20 de 300 (7%; 4%–10%) | 24 de 300 (8%; 5%–12%) | 9% |
| **Región fuera de Z1 y Z2** (ponderado por predios elegibles) | 20.508 | 600 | 20% | 26% | — |

Controles en alta por temporada (la última columna pondera las subzonas por sus predios elegibles):

| Temporada | Aconcagua interior | Resto | Región fuera de Z1 y Z2 |
| --- | --- | --- | --- |
| 2019-20 | 3 de 14 (21%; 8%–48%) | 3 de 30 (10%; 3%–26%) | 14% |
| 2020-21 | 16 de 30 (53%; 36%–70%) | 1 de 60 (2%; 0%–9%) | 19% |
| 2021-22 | 35 de 80 (44%; 33%–55%) | 6 de 81 (7%; 3%–15%) | 20% |
| 2022-23 | 36 de 74 (49%; 38%–60%) | 7 de 55 (13%; 6%–24%) | 25% |
| 2023-24 | 35 de 76 (46%; 35%–57%) | 1 de 38 (3%; 0%–13%) | 17% |
| 2024-25 | 14 de 26 (54%; 35%–71%) | 2 de 36 (6%; 2%–18%) | 22% |

## Recall frente al azar: predio del punto (principal)

Banda del predio que contiene el punto de la inspección, en la temporada previa. Azar: proporción de los controles de su subzona en esa banda.

### Positivos detectables (40)

| Nivel | Positivos encontrados | Recall (IC 95 %) | Azar (IC 95 %) | Lift (IC 95 % de Wilson) | Lift (IC 95 % con el error del azar) |
| --- | --- | --- | --- | --- | --- |
| alta | 3 de 40 | 8% (3%–20%) | 17% (14%–19%) | 0.5× (0.2–1.2) | 0.5× (0.0–1.0) |
| alta o media | 4 de 40 | 10% (4%–23%) | 21% (19%–24%) | 0.5× (0.2–1.1) | 0.5× (0.1–0.9) |
| cualquier alerta | 4 de 40 | 10% (4%–23%) | 22% (19%–25%) | 0.5× (0.2–1.1) | 0.5× (0.1–0.9) |

### Todos los positivos, detectables o no (50)

| Nivel | Positivos encontrados | Recall (IC 95 %) | Azar (IC 95 %) | Lift (IC 95 % de Wilson) | Lift (IC 95 % con el error del azar) |
| --- | --- | --- | --- | --- | --- |
| alta | 3 de 50 | 6% (2%–16%) | 15% (13%–18%) | 0.4× (0.1–1.1) | 0.4× (0.0–0.9) |
| alta o media | 4 de 50 | 8% (3%–19%) | 20% (17%–23%) | 0.4× (0.2–1.0) | 0.4× (0.1–0.9) |
| cualquier alerta | 4 de 50 | 8% (3%–19%) | 20% (17%–23%) | 0.4× (0.2–0.9) | 0.4× (0.1–0.8) |

### Positivos detectables del set limpio (11)

| Nivel | Positivos encontrados | Recall (IC 95 %) | Azar (IC 95 %) | Lift (IC 95 % de Wilson) | Lift (IC 95 % con el error del azar) |
| --- | --- | --- | --- | --- | --- |
| alta | 1 de 11 | 9% (2%–38%) | 17% (15%–20%) | 0.5× (0.1–2.2) | 0.5× (0.0–1.7) |
| alta o media | 2 de 11 | 18% (5%–48%) | 23% (20%–25%) | 0.8× (0.2–2.1) | 0.8× (0.0–2.0) |
| cualquier alerta | 2 de 11 | 18% (5%–48%) | 23% (20%–26%) | 0.8× (0.2–2.1) | 0.8× (0.0–1.9) |

### Positivos detectables de Aconcagua interior (10)

| Nivel | Positivos encontrados | Recall (IC 95 %) | Azar (IC 95 %) | Lift (IC 95 % de Wilson) | Lift (IC 95 % con el error del azar) |
| --- | --- | --- | --- | --- | --- |
| alta | 3 de 10 | 30% (11%–60%) | 46% (41%–52%) | 0.6× (0.2–1.3) | 0.6× (0.0–1.3) |
| alta o media | 4 de 10 | 40% (17%–69%) | 61% (56%–67%) | 0.7× (0.3–1.1) | 0.7× (0.2–1.2) |
| cualquier alerta | 4 de 10 | 40% (17%–69%) | 62% (56%–67%) | 0.6× (0.3–1.1) | 0.6× (0.2–1.1) |

### Positivos detectables de Resto (30)

| Nivel | Positivos encontrados | Recall (IC 95 %) | Azar (IC 95 %) | Lift (IC 95 % de Wilson) | Lift (IC 95 % con el error del azar) |
| --- | --- | --- | --- | --- | --- |
| alta | 0 de 30 | 0% (0%–11%) | 7% (4%–10%) | 0.0× (0.0–1.7) | 0.0× (—) |
| alta o media | 0 de 30 | 0% (0%–11%) | 8% (5%–11%) | 0.0× (0.0–1.4) | 0.0× (—) |
| cualquier alerta | 0 de 30 | 0% (0%–11%) | 8% (5%–12%) | 0.0× (0.0–1.4) | 0.0× (—) |

## Recall frente al azar: vecindario (sensibilidad)

Mejor banda entre los predios a 30 m o menos del punto. Azar: probabilidad de que al menos uno de los n predios del vecindario caiga en la banda, 1 − (1 − p)^n, con p de los controles de su subzona.

### Positivos detectables (40)

| Nivel | Positivos encontrados | Recall (IC 95 %) | Azar (IC 95 %) | Lift (IC 95 % de Wilson) | Lift (IC 95 % con el error del azar) |
| --- | --- | --- | --- | --- | --- |
| alta | 3 de 40 | 8% (3%–20%) | 24% (21%–27%) | 0.3× (0.1–0.8) | 0.3× (0.0–0.7) |
| alta o media | 7 de 40 | 18% (9%–32%) | 29% (25%–32%) | 0.6× (0.3–1.1) | 0.6× (0.2–1.1) |
| cualquier alerta | 7 de 40 | 18% (9%–32%) | 29% (25%–33%) | 0.6× (0.3–1.1) | 0.6× (0.2–1.1) |

### Todos los positivos (50)

| Nivel | Positivos encontrados | Recall (IC 95 %) | Azar (IC 95 %) | Lift (IC 95 % de Wilson) | Lift (IC 95 % con el error del azar) |
| --- | --- | --- | --- | --- | --- |
| alta | 3 de 50 | 6% (2%–16%) | 22% (19%–25%) | 0.3× (0.1–0.7) | 0.3× (0.0–0.6) |
| alta o media | 7 de 50 | 14% (7%–26%) | 26% (23%–30%) | 0.5× (0.3–1.0) | 0.5× (0.2–0.9) |
| cualquier alerta | 7 de 50 | 14% (7%–26%) | 27% (23%–30%) | 0.5× (0.3–1.0) | 0.5× (0.2–0.9) |

### Positivos detectables de Aconcagua interior (10)

| Nivel | Positivos encontrados | Recall (IC 95 %) | Azar (IC 95 %) | Lift (IC 95 % de Wilson) | Lift (IC 95 % con el error del azar) |
| --- | --- | --- | --- | --- | --- |
| alta | 3 de 10 | 30% (11%–60%) | 65% (59%–70%) | 0.5× (0.2–0.9) | 0.5× (0.1–0.9) |
| alta o media | 6 de 10 | 60% (31%–83%) | 78% (73%–82%) | 0.8× (0.4–1.1) | 0.8× (0.4–1.2) |
| cualquier alerta | 6 de 10 | 60% (31%–83%) | 78% (74%–82%) | 0.8× (0.4–1.1) | 0.8× (0.4–1.2) |

### Positivos detectables de Resto (30)

| Nivel | Positivos encontrados | Recall (IC 95 %) | Azar (IC 95 %) | Lift (IC 95 % de Wilson) | Lift (IC 95 % con el error del azar) |
| --- | --- | --- | --- | --- | --- |
| alta | 0 de 30 | 0% (0%–11%) | 10% (6%–15%) | 0.0× (0.0–1.1) | 0.0× (—) |
| alta o media | 1 de 30 | 3% (1%–17%) | 12% (8%–17%) | 0.3× (0.0–1.4) | 0.3× (0.0–1.0) |
| cualquier alerta | 1 de 30 | 3% (1%–17%) | 13% (8%–18%) | 0.3× (0.0–1.3) | 0.3× (0.0–1.0) |

## Señal de riego y derechos propios

La banda alta pide dos cosas: señal de riego (M3) y que el consumo no se explique con derechos. Predio del punto de cada expediente (detectable o no) y predios de control.

| Grupo | Predios | Con señal de riego | Con derechos propios ubicados | En alta |
| --- | --- | --- | --- | --- |
| Aconcagua interior, positivos | 11 | 5 de 11 (45%; 21%–72%) | 2 de 11 (18%; 5%–48%) | 3 de 11 (27%; 10%–57%) |
| Aconcagua interior, negativos | 26 | 12 de 26 (46%; 29%–65%) | 6 de 26 (23%; 11%–42%) | 9 de 26 (35%; 19%–54%) |
| Aconcagua interior, controles | 300 | 189 de 300 (63%; 57%–68%) | 10 de 300 (3%; 2%–6%) | 139 de 300 (46%; 41%–52%) |
| Resto, positivos | 39 | 3 de 39 (8%; 3%–20%) | 22 de 39 (56%; 41%–71%) | 0 de 39 (0%; 0%–9%) |
| Resto, negativos | 121 | 6 de 121 (5%; 2%–10%) | 63 de 121 (52%; 43%–61%) | 0 de 121 (0%; 0%–3%) |
| Resto, controles | 300 | 27 de 300 (9%; 6%–13%) | 37 de 300 (12%; 9%–17%) | 20 de 300 (7%; 4%–10%) |

## Con y sin el motivo de canal

Qué pasa con la banda alta si se descuentan las alertas con indicio de riego por canal: esas alertas pasan a sin_alerta en los casos y en los controles por igual. Predio del punto, positivos detectables.

| Variante | Subzona | Positivos en alta | Recall (IC 95 %) | Azar (IC 95 %) | Lift (IC 95 % de Wilson) | Lift (IC 95 % con el error del azar) |
| --- | --- | --- | --- | --- | --- | --- |
| Sin descuento | Todas | 3 de 40 | 8% (3%–20%) | 17% (14%–19%) | 0.5× (0.2–1.2) | 0.5× (0.0–1.0) |
| Sin descuento | Aconcagua interior | 3 de 10 | 30% (11%–60%) | 46% (41%–52%) | 0.6× (0.2–1.3) | 0.6× (0.0–1.3) |
| Sin descuento | Resto | 0 de 30 | 0% (0%–11%) | 7% (4%–10%) | 0.0× (0.0–1.7) | 0.0× (—) |
| Canal a 300 m o menos (`canal_300m`) | Todas | 0 de 40 | 0% (0%–9%) | 5% (3%–8%) | 0.0× (0.0–1.6) | 0.0× (—) |
| Canal a 300 m o menos (`canal_300m`) | Aconcagua interior | 0 de 10 | 0% (0%–28%) | 3% (1%–6%) | 0.0× (0.0–8.3) | 0.0× (—) |
| Canal a 300 m o menos (`canal_300m`) | Resto | 0 de 30 | 0% (0%–11%) | 6% (3%–9%) | 0.0× (0.0–1.9) | 0.0× (—) |
| Área de riego superficial de CIREN en la mitad del predio o más | Todas | 1 de 40 | 2% (0%–13%) | 6% (4%–8%) | 0.4× (0.1–2.1) | 0.4× (0.0–1.5) |
| Área de riego superficial de CIREN en la mitad del predio o más | Aconcagua interior | 1 de 10 | 10% (2%–40%) | 7% (4%–10%) | 1.4× (0.3–5.8) | 1.4× (0.0–5.0) |
| Área de riego superficial de CIREN en la mitad del predio o más | Resto | 0 de 30 | 0% (0%–11%) | 6% (3%–9%) | 0.0× (0.0–1.9) | 0.0× (—) |

## Prueba del sesgo de canal

Si el canal explica las alertas, los fiscalizados en alerta alta con indicio de canal deberían resultar negativos más seguido que los demás. Predio del punto en banda alta en la temporada previa (detectables o no).

| Fiscalizados en alta | Expedientes | Negativos | Positivos | Positivos del grupo (IC 95 %) |
| --- | --- | --- | --- | --- |
| Con canal a 300 m o menos (`canal_300m`) | 12 | 9 | 3 | 3 de 12 (25%; 9%–53%) |
| Sin canal a 300 m o menos | 0 | 0 | 0 | — |
| *Fisher exacto, dos colas* | | | | no aplica, un grupo está vacío |
| Con área de riego superficial de CIREN en la mitad del predio o más | 10 | 8 | 2 | 2 de 10 (20%; 6%–51%) |
| Sin área de riego superficial de CIREN en la mitad del predio o más | 2 | 1 | 1 | 1 de 2 (50%; 9%–91%) |
| *Fisher exacto, dos colas* | | | | p = 0.45 |
| Todos los fiscalizados en alta | 12 | 9 | 3 | 3 de 12 (25%; 9%–53%) |

Referencia: entre todos los fiscalizados con puntaje, 50 de 197 (25%; 20%–32%) son positivos.

Los mismos indicios entre los controles (para saber cuánto pesa el canal en las alertas al azar):

| Subzona | Controles en alta | Con `canal_300m` | Con área de riego superficial |
| --- | --- | --- | --- |
| Aconcagua interior | 139 | 129 de 139 (93%; 87%–96%) | 118 de 139 (85%; 78%–90%) |
| Resto | 20 | 2 de 20 (10%; 3%–30%) | 2 de 20 (10%; 3%–30%) |

Controles (todas las bandas) con área de riego superficial: Aconcagua interior 70%; Resto 5%.

## Entre fiscalizados (límite)

| Comparación | Positivos | Negativos | AUC (IC 95 %) |
| --- | --- | --- | --- |
| Detectables, todos los negativos | 40 | 93 | 0.49 (0.41–0.58) |
| Detectables, solo "No acoge" | 40 | 50 | 0.49 (0.38–0.58) |
| Todos (detectables o no) | 50 | 147 | 0.52 (0.46–0.59) |
| Detectables de Aconcagua interior | 10 | 14 | 0.42 (0.16–0.68) |
| Detectables de Resto | 30 | 79 | 0.43 (0.38–0.48) |

Acierto entre fiscalizados detectables: 30% en general y 27% entre los que Caudal pone en alta o media (7 de 26). Tienen señal de riego el 28% de los positivos detectables y el 28% de los negativos.

Bandas de los fiscalizados detectables (mejor banda del vecindario):

| Subzona y etiqueta | alta | media | baja | sin_alerta | Total |
| --- | --- | --- | --- | --- | --- |
| Aconcagua interior, negativo | 10 | 1 | 0 | 3 | 14 |
| Aconcagua interior, positivo | 3 | 3 | 0 | 4 | 10 |
| Resto, negativo | 4 | 4 | 0 | 71 | 79 |
| Resto, positivo | 0 | 1 | 0 | 29 | 30 |
| **Total** | 17 | 9 | 0 | 107 | 133 |

## Por comuna

Predio del punto. Los controles por comuna son pocos: la columna sirve para ver el orden de magnitud, no para comparar comunas entre sí.

| Comuna | Subzona | Positivos | Positivos en alta | Negativos | Negativos en alta | Controles | Controles en alta |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Calle Larga | Aconcagua interior | 0 | 0 | 1 | 0 | 23 | 52% |
| Catemu | Aconcagua interior | 2 | 0 | 7 | 1 | 35 | 49% |
| Llaillay | Aconcagua interior | 2 | 0 | 3 | 2 | 21 | 48% |
| Los Andes | Aconcagua interior | 0 | 0 | 2 | 1 | 20 | 10% |
| Panquehue | Aconcagua interior | 6 | 2 | 7 | 3 | 21 | 43% |
| Rinconada | Aconcagua interior | 0 | 0 | 1 | 1 | 12 | 58% |
| San Esteban | Aconcagua interior | 0 | 0 | 2 | 0 | 37 | 51% |
| San Felipe | Aconcagua interior | 0 | 0 | 3 | 1 | 47 | 36% |
| Santa Maria | Aconcagua interior | 1 | 1 | 0 | 0 | 27 | 56% |
| Algarrobo | Resto | 6 | 0 | 2 | 0 | 20 | 5% |
| Cartagena | Resto | 1 | 0 | 0 | 0 | 17 | 0% |
| Casablanca | Resto | 5 | 0 | 12 | 0 | 31 | 10% |
| Concon | Resto | 0 | 0 | 1 | 0 | 3 | 0% |
| Curacavi | Resto | 0 | 0 | 1 | 0 | 0 | — |
| El Quisco | Resto | 1 | 0 | 3 | 0 | 3 | 0% |
| El Tabo | Resto | 1 | 0 | 8 | 0 | 15 | 0% |
| Limache | Resto | 2 | 0 | 21 | 0 | 29 | 3% |
| Olmue | Resto | 0 | 0 | 10 | 0 | 12 | 8% |
| Puchuncavi | Resto | 4 | 0 | 5 | 0 | 24 | 8% |
| Quilpue | Resto | 0 | 0 | 8 | 0 | 30 | 7% |
| Quintero | Resto | 0 | 0 | 16 | 0 | 10 | 10% |
| San Antonio | Resto | 4 | 0 | 16 | 0 | 28 | 14% |
| Santo Domingo | Resto | 8 | 0 | 14 | 0 | 15 | 7% |
| Valparaiso | Resto | 2 | 0 | 3 | 0 | 39 | 3% |
| Villa Alemana | Resto | 2 | 0 | 1 | 0 | 10 | 0% |
| Vina Del Mar | Resto | 3 | 0 | 0 | 0 | 14 | 21% |

## Método y límites

- **Casos y vecindario:** las reglas del set de validación de `scripts/extract/fiscalizaciones_dga.py` (D18), sobre la planilla de fiscalización de la DGA y la capa de predios de CIREN de la región. Cada expediente se evalúa en su temporada previa: la última de diciembre a marzo que empezó antes de la inspección.
- **Serie Sentinel-2:** `scripts/extract/serie_sentinel2.py --parte` (celdas de 512, escenas con menos de 40 % de nubes), solo para los predios de los casos, los controles y todo el secano de referencia a 10 km. Cada predio se lee solo en su temporada.
- **Clima:** Open-Meteo, reanálisis `era5_seamless`, sin corrección de estaciones, con M1 en `--umbral-mm 2`. La corrida nacional usa ERA5-Land ARCO con el mismo umbral; aquí no había clave de CDS. Pendiente: repetir el paso de clima con `d2_clima_era5land.py` y comprobar que las bandas no cambian.
- **M1 a M5:** los scripts y umbrales de la corrida nacional (M7), con los derechos otorgados antes del 1 de diciembre de cada temporada. No se calibró nada con estos casos: el lift no tiene el sesgo de elección del de Z1 y Z2.
- **Azar:** en `validacion.md` es la proporción del universo 2025-26 en cada banda. Aquí es una muestra de control por subzona y temporada. Por eso el lift lleva dos intervalos: el de Wilson sobre el recall (comparable con `validacion.md`) y uno por remuestreo conjunto de positivos y controles, que cuenta el error de la muestra de control. Con 0 positivos en la banda el remuestreo no varía (—): ahí solo vale el de Wilson. Los controles no se filtran por verdor, igual que el universo en `validacion.md`.
- **Derechos ajenos:** M5 cuenta con consumo 0 a los predios vecinos sin estimación de M4. En esta corrida solo tienen M4 los casos y los controles, así que el descuento por derechos ajenos es mayor que en una corrida de todo el universo, para casos y controles por igual.
- **NDVI de secano de M4:** es la mediana mensual del secano leído (el que está a 10 km de algún predio evaluado), no de todo el secano de la región.
- **Secano de regiones vecinas:** la corrida nacional usa también el secano de la región vecina a menos de 10 km del borde; aquí solo se usó el de la región.
- **Subzonas:** Aconcagua interior son las provincias de San Felipe de Aconcagua y Los Andes; el resto es la costa, Casablanca, San Antonio y Marga Marga.
- **Área de riego superficial:** capa `AREAS DE RIEGO` del estudio FNDR de infraestructura de riego de CIREN (`scripts/extract/areas_riego_ciren.py`). Un predio cuenta como regado por canal si la mitad o más de su superficie cae en un área de riego `SUPERFICIAL` o `MIXTO`. El umbral se fijó antes de mirar los resultados.
- **Etiquetas:** un negativo es débil (la DGA no constató infracción ese día) y la DGA fiscaliza por denuncia, no al azar.
- **Muestra chica:** los intervalos son anchos. Sirven para decir si hay señal, no para afinar umbrales.

## Cómo reproducir

```bash
# Tablas base de la región: del bucket (base/<tabla>/region=R05.parquet) o desde las fuentes, con los extractores:
export CAUDAL_DATA=$PWD/data/raw/r05 CAUDAL_ZONAS=$PWD/data/raw/r05/regiones_R05.json   # regiones.json con solo R05
for s in predios_ciren canales_ciren derechos_dga cruce_derechos_predios fiscalizaciones_dga referencia_secano_conaf \
         cultivos_ciren areas_riego_ciren; do uv run scripts/extract/$s.py; done
unset CAUDAL_DATA CAUDAL_ZONAS
uv run scripts/models/validacion_region.py --region R05 --excluir-z1z2
```
