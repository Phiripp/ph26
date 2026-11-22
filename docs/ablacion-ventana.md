# ¿Cuánto aporta la condición de sequía del detector? (ablación de la ventana seca)

Generado por `scripts/models/ablacion_ventana.py` (no editar a mano). El detector de riego (M3) solo cuenta imágenes de diciembre a marzo tomadas tras 10 días o más sin lluvia. Ese supuesto se fijó al diseñar el modelo y no se había medido.

## Resultado

- H1, la condición de 10 días sin lluvia mejora el ranking dentro del verano: **Refutada**. Con todas las fechas de verano, 99,4 % del universo queda en la misma banda y el lift en alta pasa de 3,7 a 3,6 veces (7 y 7 de 19 positivos). Solo 13,5 % de las imágenes despejadas de verano tiene menos de 10 días sin lluvia.
- H2, tras una lluvia los huertos muestran menos señal: **Refutada**. Huertos con señal en 85,1 % de las imágenes secas y en 87,5 % de las imágenes con lluvia reciente (con lluvia menos seca: 2,5 puntos; IC 95 % 1,6 a 3,4).
- H3, fuera del verano el contraste se pierde: **Depende de la zona** (no refutada en Z1). Detección en huertos: 88 % en verano y 74 % en invierno. Falsa alarma en predios secos: 1,4 % y 0,7 %. Ese es el criterio escrito antes, con las dos zonas juntas. Por zona el resultado cambia: en Z1 la detección pasa de 77 % en verano a 41 % en invierno y 21 % en primavera (17 predios secos de referencia); en Z2 la detección pasa de 95 % en verano a 92 % en invierno y 76 % en primavera (5 predios secos de referencia). Es una muestra de 64 predios con una referencia sustituta: muestra el mecanismo, no el desempeño del modelo.
- Lo que no estaba en las hipótesis: el contraste sí se cae, pero en primavera y no con la lluvia. La detección baja a 59 % entre septiembre y noviembre, con el mínimo en sep (37 %), cuando el NDVI de los predios secos sube a 0,51 (en verano es 0,23). El cerro reverdece después de las lluvias de invierno y tarda en secarse. Meses con detección de 80 % o más: nov, dic, ene, feb, mar, abr, may, jun, jul.

## Antes de medir

Escrito antes de correr el script.

**Decisión que cambia.** Si la condición de sequía no aporta, se puede quitar del modelo y de la frase del pitch ("si lleva diez días sin llover…"), y el modelo deja de depender del dato de lluvia. Si el contraste entre regado y secano se cae fuera del verano, el método no se puede llevar tal cual a meses o regiones con lluvia (corrida nacional).

**Población.** A: los fiscalizados por extracción de la validación con vegetación detectable, y el universo de 7.911 predios para el azar. B: todas las imágenes despejadas de verano de esas dos series. C: 100 predios de muestra con el año completo.

| Hipótesis | Métrica | Qué la refuta | Predicción |
| --- | --- | --- | --- |
| H1. Dentro del verano, exigir 10 días sin lluvia mejora el ranking | Lift en alta del predio del punto, AUC entre fiscalizados y predios que cambian de banda, frente a "todas las fechas de verano" | Diferencia de 1 positivo o menos en alta, intervalo de la diferencia de AUC que incluye 0 y 95 % o más del universo en la misma banda | Refutada: casi todas las imágenes de verano ya cumplen la condición |
| H2. Tras una lluvia, los huertos muestran menos señal | Fracción de imágenes de huertos con señal, con menos de 10 días sin lluvia frente a 10 o más | Diferencia menor que 10 puntos | Refutada o débil: en verano llueve poco |
| H3. Fuera del verano el contraste se pierde | Detección en huertos y falsa alarma en predios secos, invierno frente a verano | Detección menos de 20 puntos más baja y falsa alarma menos de 10 puntos más alta | Confirmada: el cerro reverdece con la lluvia |

## A. Ablación contra los casos de la DGA

Misma evaluación que M6 (predio del punto de la DGA, positivos detectables, azar = proporción del universo de su zona en banda alta). Cada fila cambia solo qué fechas cuentan. Las columnas de la derecha comparan con la regla actual a iguales umbrales.

### Umbrales calibrados en M7 (2,5, 1,5 y 0,7)

| Fechas que cuentan | Fechas válidas por predio (mediana) | Predios sin fechas | Universo en alta | Positivos en alta | Lift en alta (IC 95 %) | En alta o media | AUC entre fiscalizados (IC 95 %) | Diferencia de AUC (IC 95 %) | Misma banda que la regla actual | Orden (Spearman) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| seca, 10 días o más (regla actual) | 16 | 0,0 % | 9,6 % | 7 de 19 | 3,7× (1,9–5,9) | 10 de 19 | 0,62 (0,46–0,77) | 0,00 (0,00 a 0,00) | 100,0 % | 1,000 |
| todas las fechas de verano | 18 | 0,0 % | 9,7 % | 7 de 19 | 3,6× (1,9–5,8) | 10 de 19 | 0,62 (0,46–0,78) | 0,01 (-0,01 a 0,03) | 99,4 % | 0,991 |
| solo con lluvia reciente | 3 | 7,5 % | 4,5 % | 1 de 19 | 1,1× (0,2–5,2) | 6 de 19 | 0,63 (0,49–0,76) | 0,01 (-0,10 a 0,12) | 90,8 % | 0,900 |
| seca, sin mínimo de días | 18 | 0,0 % | 9,7 % | 7 de 19 | 3,6× (1,9–5,8) | 10 de 19 | 0,62 (0,46–0,77) | 0,00 (-0,00 a 0,00) | 99,4 % | 0,991 |
| seca, 5 días o más | 18 | 0,0 % | 9,7 % | 7 de 19 | 3,6× (1,9–5,8) | 10 de 19 | 0,62 (0,46–0,77) | 0,00 (-0,00 a 0,00) | 99,6 % | 0,992 |
| seca, 20 días o más | 12 | 0,0 % | 10,0 % | 7 de 19 | 3,5× (1,8–5,6) | 10 de 19 | 0,62 (0,46–0,77) | -0,00 (-0,01 a 0,00) | 98,8 % | 0,996 |

### Umbrales iniciales, fijados antes de mirar (2, 2 y 0,5)

| Fechas que cuentan | Fechas válidas por predio (mediana) | Predios sin fechas | Universo en alta | Positivos en alta | Lift en alta (IC 95 %) | En alta o media | AUC entre fiscalizados (IC 95 %) | Diferencia de AUC (IC 95 %) | Misma banda que la regla actual | Orden (Spearman) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| seca, 10 días o más (regla actual) | 16 | 0,0 % | 11,5 % | 6 de 19 | 2,6× (1,3–4,4) | 9 de 19 | 0,56 (0,39–0,72) | 0,00 (0,00 a 0,00) | 100,0 % | 1,000 |
| todas las fechas de verano | 18 | 0,0 % | 11,5 % | 6 de 19 | 2,6× (1,3–4,4) | 9 de 19 | 0,57 (0,40–0,73) | 0,01 (-0,01 a 0,04) | 99,5 % | 0,991 |
| solo con lluvia reciente | 3 | 7,5 % | 5,8 % | 1 de 19 | 0,9× (0,2–4,0) | 8 de 19 | 0,61 (0,47–0,75) | 0,06 (-0,06 a 0,18) | 88,5 % | 0,889 |
| seca, sin mínimo de días | 18 | 0,0 % | 11,5 % | 6 de 19 | 2,6× (1,3–4,4) | 9 de 19 | 0,57 (0,40–0,73) | 0,01 (-0,01 a 0,04) | 99,5 % | 0,991 |
| seca, 5 días o más | 18 | 0,0 % | 11,4 % | 6 de 19 | 2,6× (1,3–4,5) | 9 de 19 | 0,56 (0,39–0,72) | 0,00 (0,00 a 0,00) | 99,5 % | 0,991 |
| seca, 20 días o más | 12 | 0,0 % | 11,6 % | 6 de 19 | 2,6× (1,3–4,4) | 9 de 19 | 0,55 (0,39–0,72) | -0,00 (-0,01 a 0,00) | 99,0 % | 0,994 |

La fila "solo con lluvia reciente" no es comparable: con 3 imágenes por predio el modelo marca confianza baja y baja la banda. Lo que pasa en las imágenes con lluvia se mide en B.

El AUC se calcula con 67 fiscalizados detectables. Con tan pocos positivos, un caso mueve el lift en varias décimas. Los umbrales calibrados se eligieron con estos mismos casos y con la regla actual, así que esa tabla favorece al control; la de umbrales iniciales no tiene ese sesgo.

## B. Por imagen, según los días sin lluvia (verano)

Por predio, con la regla actual (`puntaje.parquet`, 2025-26): el detector marca riego en 1008 de 1210 predios de huerto (83 %) y en 872 de 5923 predios sin frutales (15 %). Lo primero mide cuánto riego conocido encuentra; lo segundo no es una tasa de error, porque un predio sin frutales puede regar pradera o cultivos anuales.

Imágenes despejadas y con referencia de las dos series (167.266 imágenes). Señal: z de verdor ≥ 2,5 y z de humedad ≥ 1,5, sin exigir sequía. Huerto: 50 % o más de la superficie con frutales en el Catastro Frutícola (riego seguro). "Sin frutales" no es lo mismo que "sin riego": sirve de contraste, no de negativo.

| Días sin lluvia | Imágenes | Imágenes de huertos | Huertos con señal | Imágenes sin frutales | Sin frutales con señal | z de verdor en huertos (mediana) | z de humedad en huertos (mediana) | NDVI del secano (mediana) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 a 2 | 6086 | 1140 | 85,4 % | 4219 | 17,6 % | 5,1 | 5,7 | 0,22 |
| 3 a 5 | 7473 | 1210 | 90,9 % | 5502 | 22,0 % | 5,9 | 6,1 | 0,27 |
| 6 a 9 | 8960 | 1536 | 86,5 % | 6407 | 19,4 % | 5,1 | 5,7 | 0,21 |
| 10 a 19 | 29170 | 4832 | 80,9 % | 21243 | 16,8 % | 4,5 | 5,5 | 0,29 |
| 20 o más | 115577 | 18925 | 86,1 % | 83983 | 19,5 % | 5,1 | 5,6 | 0,27 |

Imágenes de huertos: 23757 con 10 días o más sin lluvia y 3886 con menos.

## C. Por mes del año (muestra con el año completo)

64 predios de la muestra con serie de todo el año (`serie_predio.parquet`; temporadas por zona: {'Z1': '2023 a 2026', 'Z2': '2020 a 2024'}). Huertos: {'Z1': 17, 'Z2': 25}. Predios secos de referencia: {'Z1': 17, 'Z2': 5} (sin frutales y con NDVI mediano de verano ≤ 0,30 en las otras temporadas; hacen falta 5 con dato en la fecha). Detección: imágenes de huertos con señal frente a los predios secos, con la fórmula de M2 y los umbrales de M3. Falsa alarma: imágenes de un predio seco con señal frente a los demás secos.

| Estación | Imágenes de huertos | Detección (IC 95 %) | Imágenes de predios secos | Falsa alarma (IC 95 %) | NDVI de huertos | NDVI de predios secos |
| --- | --- | --- | --- | --- | --- | --- |
| verano (dic a mar) | 2733 | 88 % (79 %–95 %) | 1249 | 1,4 % (0,2 %–3,2 %) | 0,56 | 0,23 |
| otoño (abr y may) | 992 | 89 % (81 %–96 %) | 475 | 0,8 % (0,0 %–2,6 %) | 0,61 | 0,24 |
| invierno (jun a ago) | 1205 | 74 % (64 %–83 %) | 539 | 0,7 % (0,0 %–1,7 %) | 0,68 | 0,30 |
| primavera (sep a nov) | 1382 | 59 % (48 %–68 %) | 562 | 2,1 % (0,3 %–5,1 %) | 0,63 | 0,33 |

| Mes | Lluvia media del mes (mm) | Imágenes de huertos | Detección | Imágenes de predios secos | Falsa alarma | NDVI de huertos | NDVI de predios secos |
| --- | --- | --- | --- | --- | --- | --- | --- |
| jul | 43 | 425 | 81 % | 176 | 0,6 % | 0,69 | 0,28 |
| ago | 34 | 443 | 57 % | 207 | 1,4 % | 0,67 | 0,43 |
| sep | 7 | 463 | 37 % | 212 | 1,4 % | 0,67 | 0,51 |
| oct | 6 | 439 | 56 % | 172 | 3,5 % | 0,60 | 0,34 |
| nov | 2 | 480 | 83 % | 178 | 1,7 % | 0,60 | 0,25 |
| dic | 1 | 845 | 88 % | 389 | 3,3 % | 0,58 | 0,24 |
| ene | 1 | 555 | 87 % | 238 | 1,3 % | 0,56 | 0,22 |
| feb | 0 | 696 | 88 % | 320 | 0,3 % | 0,54 | 0,22 |
| mar | 1 | 637 | 89 % | 302 | 0,0 % | 0,57 | 0,22 |
| abr | 3 | 675 | 88 % | 320 | 0,6 % | 0,60 | 0,23 |
| may | 10 | 317 | 91 % | 155 | 1,3 % | 0,64 | 0,26 |
| jun | 38 | 337 | 88 % | 156 | 0,0 % | 0,66 | 0,26 |

Por zona (los años son distintos en cada una, así que también separa por año):

| Zona | Estación | Predios de huerto | Imágenes de huertos | Detección | Predios secos | Falsa alarma |
| --- | --- | --- | --- | --- | --- | --- |
| Z1 | invierno (jun a ago) | 17 | 416 | 41 % | 17 | 0,8 % |
| Z1 | otoño (abr y may) | 17 | 385 | 77 % | 17 | 1,1 % |
| Z1 | primavera (sep a nov) | 17 | 438 | 21 % | 16 | 3,0 % |
| Z1 | verano (dic a mar) | 17 | 1049 | 77 % | 17 | 1,9 % |
| Z2 | invierno (jun a ago) | 25 | 789 | 92 % | 5 | 0,6 % |
| Z2 | otoño (abr y may) | 25 | 607 | 97 % | 5 | 0,0 % |
| Z2 | primavera (sep a nov) | 25 | 944 | 76 % | 5 | 0,5 % |
| Z2 | verano (dic a mar) | 25 | 1684 | 95 % | 5 | 0,0 % |

## Qué cambia

- **La regla de 10 días sin lluvia se mantiene, pero no es lo que hace confiable al detector.** En los veranos de Valparaíso casi todas las imágenes ya la cumplen, y quitarla deja el ranking prácticamente igual. No conviene presentarla como el corazón del método.
- **Lo que sí importa es la época del año**, y la causa es el verdor del cerro, no la lluvia de los últimos días. El contraste se pierde cuando el secano reverdece, y eso depende de la zona.
- **Hipótesis para la corrida nacional:** usar una imagen solo si el secano de referencia está seco ese día (un tope al NDVI de la referencia), en vez de contar días sin lluvia. Serviría igual en zonas con otro régimen de lluvias. No está probada: hay que bajar la serie del secano de CONAF para todo el año y repetir A con ella.
- **Posible ganancia:** si esa prueba confirma los meses de la tabla C, la ventana útil pasaría de 4 meses a más, con más imágenes por predio.

## Límites

- A y B solo ven el verano: las series procesadas van de diciembre a marzo. No dicen nada del resto del año.
- A tiene 19 positivos detectables. Sirve para ver si la regla cambia el resultado, no para afinarla.
- C usa una referencia sustituta (predios de la muestra, no el secano de CONAF) y pocos predios. Los predios secos se eligen por su verano de otras temporadas, así que en verano la falsa alarma es baja en parte por construcción; el dato que importa es cómo cambian la detección y la falsa alarma al salir del verano.
- Los huertos son los del Catastro Frutícola 2025: un huerto plantado después de la imagen baja la detección en todos los meses por igual.
- La prueba completa fuera del verano necesita la serie del secano de CONAF para todo el año (`serie_sentinel2.py --referencia` sin limitar a diciembre a marzo).
