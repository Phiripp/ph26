# Impacto de Caudal (M9)

Generado por `scripts/models/impacto.py` (no editar a mano). Todas las cifras van en rango; los supuestos están en el encabezado del script y en [spec-v2.md](spec-v2.md#métricas-de-impacto). Un candidato no es un caso: se multiplica por un acierto (M6 y DGA).

## En una frase

En la temporada 2025-26, Caudal marca **501 predios en banda alta sin ninguna fiscalización de la DGA a 500 m desde 2018** en Petorca y Aconcagua bajo. Son unos **39 a 153 casos** y **2,1 a 9,3 millones de m³ al año** sin derecho (escenario conservador a central), el agua de **34.398 a 255.762 personas** al año. El escenario alto (tabla) suma todos los extremos y no se usa como titular.

## Acierto

- DGA hoy: 33% de las fiscalizaciones por extracción con resultado terminan en infracción (107 expedientes de Z1 y Z2 inspeccionados entre 2022 y 2025).
- Caudal, entre los fiscalizados detectables cuyo predio pone en banda alta: 7 de 15 (47%; IC 95 % 25%–70%). Con tan pocos casos, el intervalo incluye el acierto de la DGA: entre predios que la DGA ya eligió, Caudal no los distingue bien (AUC 0,62, ver [validacion.md](validacion.md)).
- Lo que Caudal agrega es **dónde mirar**: en banda alta encuentra 3,7 veces más infractores que elegir predios al azar (M6), y la lista sale del satélite, sin esperar una denuncia.

## Candidatos nuevos (2025-26)

- Universo: 7.911 predios elegibles; 759 en banda alta, de los cuales 258 ya tienen alguna fiscalización de la DGA a 500 m o menos (desde 2018).
- Candidatos sin fiscalizar: 501 (Z1: 242, Z2: 259). 34 son predios de más de 100 ha y van aparte: suman 52,1 millones de m³/año de exceso mínimo, más que todos los demás juntos, y su consumo es el menos seguro.
- Capacidad: la DGA hizo en promedio 33 fiscalizaciones por extracción al año en Z1 y Z2 (2020–2025). A ese ritmo, revisar los 467 candidatos tomaría 14 años: hay que priorizar dentro de la banda (puntaje) y usar la ruta (M8: 10 a 12 predios por jornada).
- El 66% de los candidatos tiene un canal a 300 m o menos: puede regar con acciones de canal, que no aparecen en los derechos. El escenario conservador los excluye.

## Escenarios (predios de hasta 100 ha)

| Escenario | Candidatos | Acierto | Casos esperados | m³/año | Valor del agua (CLP/año) | Personas | Multas (CLP) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| conservador | 158 | 25% | 39 | 2,1 millones | 5,5 mil millones | 34.398 | 0,3 mil millones |
| central | 467 | 33% | 153 | 9,3 millones | 40,1 mil millones | 255.762 | 6,4 mil millones |
| alto | 467 | 70% | 326 | 43,6 millones | 609,8 mil millones | 2.386.679 | 22,3 mil millones |

Conservador: sin predios con canal cerca, exceso mínimo, acierto bajo (cota inferior de Caudal), 2.600 CLP/m³, 62 m³ por persona, multa p25. Central: exceso central, acierto de la DGA (33 %), 4.300 CLP/m³, 36,5 m³ por persona, multa mediana. Alto: exceso máximo, acierto alto, 14.000 CLP/m³, 18,25 m³ por persona, multa p75. Multa mediana 575,7 UTM (p25 115,6, p75 944,2; 76 multas) a 72.450 CLP/UTM.

## Adelanto en casos conocidos

Positivos detectables de la validación cuyo predio del punto estuvo en banda alta antes de la inspección: 8 de 19.

| Expediente | Zona | Inspección | Primera alerta | Años antes | Temporadas en alta | m³ sobre el derecho (central) | Multa (UTM) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| FD-0501-181 | Z1 | 2024-04-02 | 2019-20 | ≥ 4,3 | 5 | 549.404 | 710,6 |
| FD-0501-167 | Z1 | 2023-03-22 | 2019-20 | ≥ 3,3 | 4 | 432.356 | 270,7 |
| FO-0503-137 | Z2 | 2023-03-01 | 2019-20 | ≥ 3,2 | 3 | 19.121 | 123,7 |
| FO-0504-95 | Z2 | 2021-11-23 | 2019-20 | ≥ 2,0 | 2 | 137.673 | 1.983,9 |
| FO-0504-96 | Z2 | 2021-11-17 | 2019-20 | ≥ 2,0 | 2 | 1.179.105 | 50,0 |
| FD-0504-227 | Z2 | 2021-07-15 | 2019-20 | ≥ 1,6 | 1 | 33.261 | 1.331,5 |
| FD-0501-143 | Z1 | 2021-02-18 | 2019-20 | ≥ 1,2 | 2 | 17.511 | 847,0 |
| FO-0501-345 | Z1 | 2021-09-15 | 2020-21 | 0,8 | 1 | 296.066 | 330,0 |

- Mediana: Caudal los habría marcado **al menos 2,0 años antes** de la inspección (cota inferior: la serie parte en 2019-20; 7 ya estaban en alta en 2019-20).
- Agua extraída sobre el derecho entre la primera alerta y la inspección: 2,4 a 2,7 millones de m³ (mínimo a central) en 8 predios; a 4.300 CLP/m³, 11.457,3 millones de CLP; el agua de 73.000 personas durante un año.

## Limitaciones

- El acierto se mide entre predios que la DGA ya eligió y con pocos casos (intervalo ancho).
- El consumo es neto de M4 dividido por la eficiencia; el rango de consumo es ancho (máximo ≈ 2,9 veces el mínimo).
- El agua de canal (acciones) no está en los derechos: el escenario conservador excluye a los predios con canal cerca.
- El 44 % de los positivos no es detectable por verdor: estas cifras no los cuentan.
- Las cifras son agregadas: no se identifican predios ni roles.
