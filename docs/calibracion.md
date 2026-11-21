# Calibración del detector de riego (M7)

Generado por `scripts/models/calibracion.py` (no editar a mano). Grilla completa en [calibracion_grilla.csv](../data/processed/calibracion_grilla.csv).

## Regla

Para cada combinación de parámetros de M3 se corren M3 y M5 sobre la validación y el universo 2025-26, y se evalúa como M6: predio del punto de la DGA, positivos detectables, azar = proporción del universo de su zona. La métrica es la cota inferior de Wilson del lift en banda alta, suavizada con las combinaciones vecinas de la grilla. Se cambian los valores actuales solo si la ganadora los supera en esa métrica.

## Resultado

| Combinación | Verdor | Humedad | Frac. mín. | Días secos | Universo en alta | Recall alta | Lift alta | Cota inf. lift | Suavizada | Recall alta+media | Lift alta+media | AUC | Recall alta (detectable relativo) | Lift alta (relativo) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| actual | 2 | 2 | 0.5 | 10 | 11.5% | 32% | 2.6× | 1.26 | 1.31 | 47% | 1.8× | 0.56 | 37% (19) | 3.2× |
| **elegida** | 2.5 | 1.5 | 0.7 | 10 | 9.6% | 37% | 3.7× | 1.90 | 1.77 | 53% | 2.5× | 0.62 | 37% (19) | 3.8× |

**Decisión:** se cambian los valores de M3: umbral de verdor 2.5, umbral de humedad 1.5, fracción mínima 0.7, días secos 10.

## Las 10 mejores (suavizadas)

| Combinación | Verdor | Humedad | Frac. mín. | Días secos | Universo en alta | Recall alta | Lift alta | Cota inf. lift | Suavizada | Recall alta+media | Lift alta+media | AUC | Recall alta (detectable relativo) | Lift alta (relativo) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| #1 | 2.5 | 1.5 | 0.7 | 10 | 9.6% | 37% | 3.7× | 1.90 | 1.77 | 53% | 2.5× | 0.62 | 37% (19) | 3.8× |
| #2 | 2.5 | 1.5 | 0.7 | 7 | 9.6% | 37% | 3.7× | 1.91 | 1.75 | 53% | 2.5× | 0.62 | 37% (19) | 3.8× |
| #3 | 2.5 | 1.5 | 0.7 | 14 | 9.7% | 37% | 3.6× | 1.89 | 1.74 | 53% | 2.5× | 0.62 | 37% (19) | 3.8× |
| #4 | 2.5 | 2.5 | 0.7 | 10 | 8.1% | 32% | 3.6× | 1.76 | 1.66 | 47% | 2.5× | 0.57 | 32% (19) | 3.9× |
| #5 | 2.5 | 2.5 | 0.7 | 7 | 8.1% | 32% | 3.6× | 1.77 | 1.65 | 47% | 2.5× | 0.57 | 32% (19) | 3.9× |
| #6 | 2.5 | 1.5 | 0.5 | 10 | 10.7% | 37% | 3.3× | 1.70 | 1.64 | 53% | 2.2× | 0.62 | 37% (19) | 3.4× |
| #7 | 2.5 | 1.5 | 0.5 | 7 | 10.7% | 37% | 3.3× | 1.70 | 1.63 | 53% | 2.2× | 0.62 | 37% (19) | 3.4× |
| #8 | 2.5 | 2.5 | 0.7 | 14 | 8.2% | 32% | 3.6× | 1.74 | 1.63 | 47% | 2.5× | 0.57 | 32% (19) | 3.8× |
| #9 | 2.5 | 2 | 0.7 | 7 | 9.0% | 32% | 3.3× | 1.62 | 1.62 | 47% | 2.4× | 0.58 | 32% (19) | 3.5× |
| #10 | 2.5 | 1.5 | 0.5 | 14 | 10.8% | 37% | 3.2× | 1.68 | 1.62 | 53% | 2.2× | 0.62 | 37% (19) | 3.4× |

## Estabilidad

- Lift medio en alta según la fracción mínima: {0.3: 2.6, 0.5: 2.8, 0.7: 3.12}.
- Rango del lift en alta en la grilla: 2.2× a 3.7×; AUC entre fiscalizados: 0.53 a 0.62.
- Detectable relativo (NDVI previo ≥ secano local + 0,10) en lugar de ≥ 0,30: cambia el set de positivos evaluados, sobre todo en Z2 (secano más verde). Se reporta en las últimas columnas.

## Limitaciones

- 19 positivos detectables: diferencias de uno o dos casos mueven el lift en más de 0,5×. La regla suavizada evita elegir un pico, pero la calibración es gruesa.
- No se calibra la escala mínima de M2 ni el radio de referencia (rehacer M2 por combinación es caro); quedan en 0,05 y 10 km.
