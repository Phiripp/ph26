# Caudal — Spec acotado: agua potable primero

Nov 21, 2026 · @Gabi

Este documento define una prioridad nueva para la demo del domingo: marcar los candidatos que riegan cerca de un pozo de agua potable del mismo acuífero. No cambia el puntaje, las bandas, la validación ni la ruta. Tiempo disponible: unas 5 horas antes de la demo, así que solo es obligatorio lo marcado P0.

## Por qué

**Mensaje:** Caudal ayuda a proteger el agua potable de las comunidades rurales en las cuencas semiáridas con sequía. Para eso manda la fiscalización primero a quienes riegan sin derechos cerca de sus pozos.

Cada parte del mensaje tiene su fuente:

| Afirmación | Fuente |
| --- | --- |
| En Ligua y Petorca, el agotamiento del acuífero se debe sobre todo a causas humanas (expansión del palto, riego, sobreotorgamiento de derechos) y no al clima | Duran-Llacer et al. (2020), *Water* 12(9), 2446, [doi:10.3390/w12092446](https://doi.org/10.3390/w12092446). Artículo revisado por pares, de la U. de Concepción |
| Esa baja de las napas cortó el agua para necesidades básicas en las cuencas de Petorca y Ligua | Alvarez-Garreton et al. (2024), *HESS Opinions*, [HESS 28, 1605](https://hess.copernicus.org/articles/28/1605/2024/) (sección 4, cita a Duran-Llacer et al. 2020 y a Muñoz et al. 2020). Autores del CR2 |
| La usurpación de agua en Petorca afecta a la fuente de los APR (caso de Hierro Viejo). Los dirigentes de APR dicen que la cuenca "seguiría siendo usurpada". En 2018 la DGA encontró 27 presuntas irregularidades en 53 pozos | INDH, [Actualización del Informe de la Misión de Observación a Petorca](https://www.lemondediplomatique.cl/IMG/pdf/informe_mision_de_observacion_INDH_DICIEMBRE_2018.pdf), diciembre de 2018, pp. 9, 12 y 13. Hay que bajar la versión oficial de la [biblioteca del INDH](https://bibliotecadigital.indh.cl/) |
| La ley obliga a que el consumo humano prevalezca: "Siempre prevalecerá el uso para el consumo humano, el uso doméstico de subsistencia y el saneamiento, tanto en el otorgamiento como en la limitación al ejercicio de los derechos de aprovechamiento" | Código de Aguas, art. 5 bis, introducido por la [Ley 21.435 (BCN)](https://www.bcn.cl/leychile/navegar?idNorma=1174443) |

**Qué no podemos decir:**

- **"Las zonas más áridas de Chile":** Petorca y Aconcagua son semiáridas. Las más áridas son las del norte, donde Caudal no corre hoy. Hay que decir "cuencas en sequía" o "semiáridas".
- **"Ayudamos a acceder a agua potable de forma óptima":** Caudal no entrega agua ni optimiza su distribución.
- **Que fiscalizar devuelve el agua a los pozos:** no encontramos un estudio que mida cuánta agua recupera un APR después de una fiscalización. Lo que sí está respaldado es la cadena: la extracción agota el acuífero, eso corta el agua potable y la ley prioriza el consumo humano. Caudal actúa en el primer eslabón.
- **Que todos son pozos de APR:** el uso "Bebida/Uso Doméstico/Saneamiento" incluye APR, sanitarias y algunos usos domésticos privados.

Todo sale de datos que ya tenemos: los derechos de uso "Bebida/Uso Doméstico/Saneamiento" de `derecho.parquet` y los sectores de acuífero (SHAC) de `restriccion.parquet`.

## Definición

Un predio está **cerca de agua potable** si cumple dos condiciones:

- **Distancia:** su polígono está a 1.000 m o menos del punto de captación de un pozo de agua potable. La distancia se mide desde el borde del predio, no desde su centro.
- **Mismo acuífero:** el pozo y el predio están en el mismo sector de acuífero (`cod_shac`).

Pozo de agua potable: un derecho de `derecho.parquet` que cumple todo esto:

- `uso` = "Bebida/Uso Domestico/Saneamiento".
- `naturaleza` = "subterranea".
- Tiene coordenada.
- `m3_anual` > 0.

Son 141 pozos: 76 en Z1 y 65 en Z2.

Notas:

- 1.000 m es un parámetro (`RADIO_M`) y no un radio de influencia medido. No tenemos un modelo hidrogeológico. Se dice así en la ficha y en el pitch.
- Los derechos sin uso declarado (3.823, `uso` nulo) quedan fuera. Puede haber pozos de APR entre ellos, así que la cifra es una cota inferior.
- No se muestran titulares. `derecho_titulares.parquet` no está en git.

## Cifras de la exploración

Las cifras se calcularon el 21-11 sobre la temporada 2025-26 de `puntaje.parquet`. El universo es el mismo de [impacto.md](impacto.md): **467 candidatos**, es decir, predios en banda alta, sin fiscalización a 500 m desde 2018 y de hasta 100 ha. El script de la tarea AP1 las regenera, y el pitch usa las que salgan de ese script.

| Radio | Candidatos cerca | Z1 / Z2 | Sin canal a 300 m | Exceso central sin multiplicar por el acierto (m³/año) | Pozos de agua potable afectados |
| --- | --- | --- | --- | --- | --- |
| 500 m | 25 | 7 / 18 | 4 | 1,2 millones | 10 |
| **1.000 m** | **72** | **23 / 49** | **11** | **3,9 millones** | **26** |
| 2.000 m | 201 | 60 / 141 | 36 | 11,0 millones | 52 |

- Con 1.000 m, 72 de los 467 candidatos (15 %) están cerca de 26 pozos de agua potable.
- 3,9 millones de m³ al año alcanzan para unas 107.000 personas, a 100 litros al día. Con el acierto de la DGA (33 %), los casos esperados son unos 24 y el agua, unos 1,3 millones de m³ al año.
- 61 de los 72 tienen un canal a 300 m o menos. Pueden regar con acciones de canal, que no salen en el registro de derechos. Esa advertencia va en la ficha.
- Predios de la demo:

| Predio | Rol en la demo | Distancia al pozo más cercano del mismo SHAC | ¿Queda marcado? |
| --- | --- | --- | --- |
| `5301984` | Candidato en vivo | 1,4 km | No. La ficha igual muestra la distancia |
| `5301325` | Parada 5 de la ruta Z2 | 853 m | Sí |

No ajustar el radio para que el candidato de la demo quede marcado.

## Corrida nacional

La etapa `base` de la corrida nacional ya bajó los derechos y los sectores de acuífero de las 14 regiones (`gs://ph-26-caudal-chile/base/derecho/` y `base/predio_restriccion/`). Con la misma definición hay **8.554 pozos de agua potable** en el país. El 21-11 a las 23:26 se contaron estos:

| Región | Pozos | Región | Pozos |
| --- | --- | --- | --- |
| Arica y Parinacota | 58 | O'Higgins | 446 |
| Tarapacá | 30 | Maule | 418 |
| Atacama | 38 | Ñuble | 691 |
| Coquimbo | 264 | Biobío | 784 |
| Valparaíso | 330 | Araucanía | 944 |
| Metropolitana | 530 | Los Ríos | 508 |
| Los Lagos | 3.401 | Aysén | 112 |

- **AP1 ya funciona para todo el país:** se escribe como función, `marcar(predios, derechos, predio_restriccion)`, para que la etapa `region` de `prediccion.py` la pueda llamar después. Para la demo corre solo sobre Z1 y Z2.
- **Los candidatos de otras regiones necesitan el ranking:** hoy solo Valparaíso tiene plan satelital. Antes de la demo no habrá candidatos cerca de agua potable en el norte ni en el resto del país.
- **No decir "las zonas más áridas de Chile":** el ranking del norte desértico no existe todavía.
- **Las cifras de Valparaíso completo van a ser otras:** cuando termine la etapa `region` de R05 (28.419 predios con acuífero asignado, contra los 7.911 de Z1 y Z2), las cifras cambian. El pitch se queda con Z1 y Z2, que son las cifras validadas.

## Qué no cambia

- El puntaje, las bandas, `rank_zona` y la validación (2,6 veces, AUC). Es una etiqueta y un filtro, no un componente del índice.
- La ruta de Z1 y Z2. Se calcula con OSRM y no se regenera hoy.
- Los expedientes PDF ya generados. Su huella solo mira los insumos de M2 a M5, así que se reutilizan con el texto anterior. Uno nuevo sí trae la frase, porque usa `explicacion.py`.

## Tareas

| # | Tarea | Prioridad | Quién | Depende de | Hecho cuando |
| --- | --- | --- | --- | --- | --- |
| AP1 | `scripts/models/agua_potable.py`: escribe `data/processed/predio_agua_potable.parquet` y `data/processed/pozo_agua_potable.geojson` (ver el contrato) | P0 | — | — | Da 72 candidatos cerca con 1.000 m |
| AP1b | `scripts/extract/apr_mop.py`: baja la [capa APR del MOP](https://rest-sit.mop.gob.cl/arcgis/rest/services/DOH/APR/MapServer/0) con `scripts/comun/arcgis.py`, deduplica por `ID_IDE` (la paginación devuelve cada sistema dos veces) y escribe `data/processed/apr.parquet`. `agua_potable.py` le asigna a cada pozo de agua potable los APR a `RADIO_APR_M` (2.000 m) o menos | P0 | — | — | 90 APR y 93.489 beneficiarios en las comunas de Z1 y Z2; 22 APR y unos 23.800 beneficiarios cerca de los 26 pozos con candidatos |
| AP2 | `impacto.py`: bloque `agua_potable` en `impacto.json` y sección "Agua potable" en `impacto.md`, con el mismo universo de candidatos (`candidatos()`) | P0 | — | AP1 | `impacto.md` muestra los candidatos cerca, por zona, sin canal cerca, en m³ y en personas |
| AP3 | `explicacion.py`: en `_contexto`, agregar la frase y el campo `dist_agua_potable_m`. No se agrega una razón nueva: se mantienen las 4 | P0 | — | AP1 | `/api/predios/5301325` dice "Pozo de agua potable del mismo acuífero a 853 m" |
| AP4 | `build_m5_web.py`: campos `agua_potable` y `dist_agua_potable_m` en `scores.lite.json`, y copia de `pozo_agua_potable.geojson` a `data/zonas/` | P0 | — | AP1 | Los archivos exportados traen los campos |
| AP5 | Frontend: capa de pozos de agua potable (mismo patrón que los puntos de fiscalización en `map.js`), etiqueta "Cerca de agua potable" en la lista y en la ficha, y la cifra en el panel de impacto | P0 | — | AP2, AP4 | En Z2 se ven los pozos y la parada 5 lleva la etiqueta |
| AP6 | Regenerar el respaldo (`api/respaldo.py --predios demo`), desplegar `caudal-api` y `caudal-web`, y correr `probar.sh` | P0 | — | AP3 a AP5 | El recorrido completo funciona en producción y con la API apagada |
| AP7 | Pitch: agregar la frase y cortar la de las latas de Monster | P0 | — | AP2 | El guion sigue bajo 430 palabras y la cifra calza con `impacto.md` |
| AP8 | Filtro "solo cerca de agua potable" en la lista de la zona, y `?agua_potable=1` en `/api/zonas/{zona}/ranking` | P1 | — | AP4 | Z2 muestra solo los 49 |

Orden sugerido: AP1, AP1b y AP7 en paralelo (el guion se escribe con la cifra de la exploración y se ajusta después). Luego AP2, AP3 y AP4 a la vez, después AP5, y AP6 al final. Hay que congelar el código 1 hora antes de la demo para AP6 y para ensayar.

## Contrato de datos

**`predio_agua_potable.parquet`:** una fila por predio elegible (7.911).

| Campo | Tipo | Significado |
| --- | --- | --- |
| `predio_id` | int | Igual que en `puntaje.parquet` |
| `zona` | str | Z1 o Z2 |
| `cod_shac` | str | Sector de acuífero del predio (de `predio_restriccion.parquet`) |
| `apr_derecho_id` | str | Pozo de agua potable más cercano del mismo SHAC, o nulo si no hay |
| `dist_agua_potable_m` | float | Distancia del borde del predio a ese pozo, en metros (EPSG:32719) |
| `apr_m3_anual` | float | Volumen anual del derecho de ese pozo |
| `agua_potable` | bool | `dist_agua_potable_m` ≤ `RADIO_M` |
| `radio_m` | int | Radio usado (1.000) |

**`pozo_agua_potable.geojson`:** son puntos con `derecho_id`, `zona`, `comuna`, `caudal_ls`, `m3_anual`, `cod_shac` y `n_candidatos_cerca` (candidatos de los 467 a `RADIO_M` o menos). No lleva titular.

**`apr.parquet`:** una fila por sistema de agua potable rural (SSR, ex APR).

| Campo | Origen en la capa del MOP | Nota |
| --- | --- | --- |
| `apr_id` | `ID_IDE` | Clave única |
| `nombre` | `NOMBRE_SSR` | Nombre del sistema. Se puede mostrar |
| `region`, `comuna` | `REGION`, `COMUNA` | — |
| `beneficiarios` | `BENEF_EST` | Estimación de la SSR |
| `arranques` | `CANT_ARR` | Conexiones |
| `captaciones` | `CANT_CAPT` | Número de captaciones (no trae su ubicación) |
| `telemetria` | `TELEMETRIA` | Sí, No o sin información |
| `actualizado` | `FECHA_ACTUALIZACION` | 30-06-2026 en las comunas de Z1 y Z2 |
| `geometry` | `LATITUD`, `LONGITUD` | Punto de referencia de la localidad, no la captación |

No se guarda `RUT`. Se descartan `CAMION_ALJ` y `DAA`, que en Z1 y Z2 vienen vacíos ("sin información").

En `pozo_agua_potable.geojson` se agregan `apr_cercanos` (lista de `nombre`) y `beneficiarios_cercanos` (suma de los APR a `RADIO_APR_M` o menos).

**`impacto.json` → `agua_potable`:**

- Con los mismos nombres de los escenarios:
  - `radio_m`
  - `candidatos_cerca`
  - `por_zona`
  - `sin_canal`
  - `m3_exceso_central`
  - `m3_exceso_min`
  - `personas`
  - `pozos_afectados`
  - `apr_cercanos`
  - `beneficiarios_cercanos`: cada APR se cuenta una sola vez, aunque esté cerca de varios pozos
- `casos_esperados`: los candidatos cerca multiplicados por el acierto de la DGA.

## Textos

- **Ficha, dentro de "Contexto":**
  - Si hay pozo del mismo acuífero: "Pozo de agua potable del mismo acuífero a 853 m."
  - Si no hay: "Sin pozos de agua potable registrados en su acuífero."
- **Límite**, en la ficha cuando `agua_potable` es verdadero: "La cercanía no prueba que el predio afecte ese pozo: es una prioridad, no un hallazgo."
- **Etiqueta** en la lista y en la ficha: "Cerca de agua potable". Va con un ícono de gota y un color que no se confunda con las bandas.
- **Panel de impacto:** "72 candidatos riegan a menos de 1 km de un pozo de agua potable de su mismo acuífero". Debajo: "Cerca de esos pozos hay 22 sistemas de agua potable rural, con unos 23.800 beneficiarios".
- **Ficha, si hay APR cerca del pozo:** "APR cercanos al pozo: `<nombre>` (`<N>` beneficiarios)". Va el nombre del sistema y nunca un RUT.

## Pitch

Esta frase va en el bloque de 2:00, después de "Revisarlos uno por uno tomaría 14 años", y reemplaza la frase de las latas de Monster. La frase tiene 19 palabras y la de las latas tenía 8, así que el guion pasa de unas 410 a unas 421 palabras. "Del mismo acuífero" no se dice en voz alta: queda en la ficha y en la respuesta al jurado.

> "Y 72 de ellos riegan a menos de un kilómetro de un pozo de agua potable. Caudal los pone primero."

Opcional en la ruta (1:35), si sobra tiempo: "Y la quinta parada está a 850 metros del pozo que abastece de agua potable".

Respuesta lista para el jurado. Pregunta: "¿Cómo saben que afecta al pozo?". Respuesta: "No lo sabemos. Usamos el mismo acuífero y un kilómetro como criterio para priorizar. Medir el efecto requiere niveles de pozos, que la DGA tiene y nosotros no".

## Datos buscados para un plan de acceso

Para decir cuánta agua le falta a cada comunidad hacen falta datos que no siempre son públicos. Esto es lo que se encontró el 21-11:

| Dato | Fuente | ¿Se puede bajar? | Uso |
| --- | --- | --- | --- |
| Sistemas APR: ubicación, beneficiarios, arranques | [Capa APR del MOP (DOH/SSR)](https://rest-sit.mop.gob.cl/arcgis/rest/services/DOH/APR/MapServer/0), 2.500 sistemas en el país | ✅ Sí, sin registro | AP1b |
| Si el APR recibe camión aljibe o tiene derechos | Misma capa (`CAMION_ALJ`, `DAA`) | ⚠️ Vacíos en Z1 y Z2 | No se usan |
| Hogares abastecidos por camión aljibe | Censo 2017 del INE, pregunta P05, [capa por unidad vecinal](https://sig.ine.cl/server/rest/services/Open_Data/Censos/MapServer/5) | ❌ El servidor SIG del INE no respondió; falta probar microdatos o REDATAM | Después de la demo |
| Niveles de pozos | [Red hidrométrica de la DGA](https://rest-sit.mop.gob.cl/arcgis/rest/services/DGA/Red_Hidrometrica/MapServer/0): 68 pozos de nivel en las comunas de Z1 y Z2, entre ellos "Agua Potable Hierro Viejo" (BNA 05110005) | ⚠️ Solo la lista. Las series están en el portal BNA, que respondió 403 | Después de la demo, con descarga manual |
| Decretos de escasez | [Capa de la DGA](https://rest-sit.mop.gob.cl/arcgis/rest/services/DGA/Decretos_Escasez_Hidrica/MapServer/0) y [página de decretos](https://dga.mop.gob.cl/derechos-de-agua/proteccion-de-las-fuentes/decretos-de-escasez-2/) | ✅ El historial; ⚠️ el campo `VIGENTE` está desactualizado | Dato de contexto: Petorca, La Ligua, Aconcagua y Quillota tuvieron decreto cada año entre 2008 y 2022, salvo 2009 |
| Extracción real por pozo (MEE) | Monitoreo de extracciones de la DGA | ❌ Token y captcha (prueba D20, [pruebas-acceso-datos.md](pruebas-acceso-datos.md)) | No |

Sin datos de demanda ni de déficit por APR, Caudal no propone un plan de acceso. Propone prioridades de fiscalización y dice a qué comunidades afectan.

## Riesgos

| Riesgo | Mitigación |
| --- | --- |
| Romper la demo a 5 horas | No se toca el puntaje, la ruta ni el expediente. Si AP5 no llega, se muestra solo la cifra en el panel de impacto (AP2 y AP4) |
| La cifra del guion no calza con el dato | AP7 usa la cifra que sale de AP2, y se revisa en el último ensayo |
| Que se lea como acusación | La palabra es "prioridad" y la ficha trae el límite. No se muestran titulares de los pozos |
| Pozos de APR sin uso declarado | Es una cota inferior, y la cifra se presenta así |
| Leer los beneficiarios como "personas afectadas" | Se dice "cerca" y "del mismo acuífero". El punto del APR es la localidad y los 2.000 m son un criterio de asociación, no una conexión medida |

## Criterios de aceptación

- `uv run scripts/models/agua_potable.py` da 72 candidatos cerca con 1.000 m. Si cambia, se actualizan esta tabla y el guion.
- `impacto.md` tiene la sección "Agua potable", generada por el script y sin cifras escritas a mano.
- `apr.parquet` no trae `RUT`, y cada APR aparece una sola vez.
- En producción, en Z2 se ven los pozos de agua potable y la parada 5 de la ruta lleva la etiqueta y la distancia.
- Con `caudal-api` apagado, el respaldo muestra lo mismo.
