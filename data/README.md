# data/

Datos de entrada de Caudal. Las zonas, las fuentes y las convenciones están en [docs/spec-v2.md](../docs/spec-v2.md). Quién hace qué está en [docs/tareas-datos-modelos.md](../docs/tareas-datos-modelos.md).

## Para empezar (Gabi: D1, D2 y D11)

1. Lee las zonas en [`zonas.json`](zonas.json): comunas, bounding box y periodo de cada zona.
2. Para tener predios ya, usa [`processed/predio_muestra.geojson`](processed/predio_muestra.geojson). Son 100 predios (50 por zona) alrededor de los casos de validación, y ya están en git.
3. Para tener todos los predios (20.050), corre:

   ```bash
   uv run scripts/extract/predios_ciren.py
   ```

   Tarda menos de un minuto y genera `processed/predio.parquet`. No va a git (ver [Licencia](#licencia-y-datos-personales)).
4. Para revisar las series, los casos de validación están en [`casos_validacion.geojson`](casos_validacion.geojson). Empieza por estos dos:
   - **FO-0504-95** (`papel = antecedente_satelital`, Hijuelas, predio `61-6`, inspección el 23-11-2021): es el **caso base** para mostrar una multa efectuada. La DGA dice que lo detectó con satélite; su serie de 2021 debería mostrar riego en ventana seca. Sus imágenes ya están en `processed/imagenes/FO-0504-95/`.
   - **FD-0501-181** (`papel = demo_principal` en el archivo, Cabildo, predio `202-35`, 17,2 ha con 16,1 ha de palto y chirimoyo, sin derechos propios; inspección el 02-04-2024): pasa a caso de validación. Su serie es frágil (NDVI estable, sin inicio de riego visible según D19).
   - La **demo en vivo** será otro caso: un predio con datos hasta el último mes para armar la denuncia y enviarla. Se elige después de tener toda la data de base (D19); todavía no está en este directorio.
5. Periodos: el análisis cubre desde enero de 2020 hasta la última escena limpia. Los periodos prioritarios de cada zona están en `zonas.json`. Para la demo en vivo, el ranking usa la temporada seca 2025-26 (diciembre de 2025 a marzo de 2026), y la ficha muestra además la escena limpia más reciente.
6. Cuidado con octubre de 2026: según Open-Meteo llovieron unos 100 mm en La Ligua y unos 160 mm en Hijuelas (última lluvia fuerte: 20-10 en La Ligua y 03-11 en Hijuelas). Las escenas de noviembre de 2026 muestran todo verde y separan mal riego de secano.

## Archivos

| Archivo | En git | Qué es | Lo genera |
| --- | --- | --- | --- |
| `zonas.json` | Sí | Copia de las zonas del spec, para leer desde código, con los periodos prioritarios de cada zona | A mano; si cambia, se edita también el spec |
| `casos_validacion.geojson` | Sí | 10 casos resueltos por extracción no autorizada (7 en Z1, 3 en Z2; 2 de 2024 y 4 de 2025), con la columna `papel` | A mano desde la planilla DGA. Es la lista curada de casos clave; la tabla completa es `fiscalizacion.parquet` |
| `processed/predio_muestra.geojson` | Sí | 100 predios cerca de los casos, con `caso_cercano` y `dist_caso_m` | `scripts/extract/predios_ciren.py` |
| `processed/predio.parquet` | No | Todos los predios de Z1 (9.331) y Z2 (10.719), GeoParquet | `scripts/extract/predios_ciren.py` |
| `raw/ciren/<COMUNA>.geojson` | No | Respuesta cruda de CIREN, una por comuna (caché) | `scripts/extract/predios_ciren.py` |
| `processed/derecho.parquet` | Sí | 9.138 derechos de agua de Z1 y Z2, normalizados, sin nombres; punto de captación en EPSG:4326 | `scripts/extract/derechos_dga.py` |
| `processed/derecho_predio.parquet` | Sí | A qué predio se asigna cada derecho: `predio_id`, `metodo_cruce`, `confianza_cruce`, `dist_predio_m` | `scripts/extract/cruce_derechos_predios.py` |
| `processed/predio_derecho.parquet` | Sí | Un registro por predio con rol válido y temporada seca (18.244 × 7): m³ con derecho del polígono y del rol, derechos del entorno, distancia a canal y `estado_derechos`. Lo leen M5 y M12 | `scripts/extract/cruce_derechos_predios.py` |
| `processed/fiscalizacion.parquet` | Sí | 835 expedientes de fiscalización de la DGA en Z1 y Z2 (497 de extracción de aguas), con etiqueta y predio. Sin nombres | `scripts/extract/fiscalizaciones_dga.py` |
| `raw/dga/planilla_fiscalizacion.xlsx` | No | Planilla de seguimiento de fiscalización de la DGA (se regenera) | `scripts/extract/fiscalizaciones_dga.py` |
| `processed/predio_cultivo.parquet` | Sí | Especie frutal y superficie plantada por predio elegible (Catastro Frutícola CIREN 2025), sin geometría | `scripts/extract/cultivos_ciren.py` |
| `raw/ciren_fruticola/cuarteles.parquet` | No | 5.696 cuarteles plantados de las comunas de Z1 y Z2 (caché) | `scripts/extract/cultivos_ciren.py` |
| `raw/dga/Derechos_Concedidos_V_Region.xls` | No | Excel de derechos de la DGA, Región de Valparaíso (trae nombres de titulares) | `scripts/extract/derechos_dga.py` |
| `raw/dga/derecho_titulares.parquet` | No | `derecho_id` y nombre del titular, para el cruce por titular (D5) y el expediente | `scripts/extract/derechos_dga.py` |
| `processed/clima.parquet` | Sí | Lluvia y ET0 diarias, 2020 a nov-2026: estaciones DMC (`fuente=dmc`) y celdas de Open-Meteo (`fuente=openmeteo`, con `lluvia_corr_mm` corregida con estaciones). Detalle en [docs/plans/d2-clima.md](../docs/plans/d2-clima.md) | `scripts/extract/d2_clima_*.py` (4 pasos, en orden) |
| `processed/predio_clima.parquet` | Sí | Celda de Open-Meteo y estación DMC más cercana de cada predio (`celda_id`, `estacion_id`, `distancia_estacion_km`) | `scripts/extract/d2_clima_openmeteo.py` |
| `processed/estacion_clima.parquet` | Sí | Estaciones DMC candidatas por zona, con rango de fechas y `descartada` | `scripts/extract/d2_clima_dmc.py` |
| `processed/clima_validacion.csv` | Sí | Contraste de la lluvia corregida contra la estación de referencia, por celda | `scripts/extract/d2_clima_unir.py` |
| `processed/referencia_secano.parquet` | Sí | 3.642 polígonos de matorral y pradera anual estables 2001–2019 (CONAF), sin los huertos del Catastro Frutícola 2025 (más 20 m), geometría simplificada a 10 m: `ref_id`, `zona`, `comuna`, `clase`, `area_ha`, `recortado_fruta`. Referencia de secano para M2 | `scripts/extract/referencia_secano_conaf.py` |
| `raw/conaf/<COMUNA>.geojson` | No | Respuesta cruda de CONAF (pradera y matorral 2019), una por comuna (caché) | `scripts/extract/referencia_secano_conaf.py` |
| `raw/ciren_riego/canales.parquet` | No | 532 tramos de canales de riego CNR/CIREN 2020 (capa 1 de infraestructura de riego) | `scripts/extract/canales_ciren.py` |

## Columnas de `predio`

| Columna | Tipo | Descripción |
| --- | --- | --- |
| `predio_id` | int | `mslink` de CIREN; único en la capa. Es la llave para `serie_predio` y el resto de las tablas |
| `zona` | str | `Z1` o `Z2` |
| `comuna` | str | Nombre de la comuna en mayúsculas, sin tildes |
| `rol` | str | Rol SII. Se repite dentro de una comuna (un predio puede tener varios polígonos) |
| `elegible` | bool | `rol_valido` y 1 ha o más: 7.911 predios. Es el universo del análisis satelital, el ranking y la ruta (ver [Zonas de estudio](../docs/spec-v2.md#zonas-de-estudio)) |
| `rol_valido` | bool | `True` si el rol tiene formato `manzana-predio` (p. ej. `87-3`). `False` en ríos, caminos, vialidad (`VP-*`, `RV-*`), sin rol (`SR`) y bienes comunes (`BC`): unos 1.800 polígonos que no son predios agrícolas |
| `area_ha` | float | Área en hectáreas, calculada en EPSG:32719 |
| `geometry` | Polygon | EPSG:4326 |

La muestra tiene además `caso_cercano` (expediente del caso más cercano) y `dist_caso_m` (distancia en metros). Solo incluye predios `elegible`.

## Columnas de `derecho`

Para regenerar: `uv run scripts/extract/derechos_dga.py` (usa el Excel local; `--refrescar` baja el del mes desde la DGA).

| Columna | Descripción |
| --- | --- |
| `derecho_id` | `expediente/solicitud`; si se repite, con sufijo de secuencia (`ND-0501-3458/1-2`) |
| `expediente`, `zona`, `comuna`, `fecha_resolucion` | Del Excel; la zona sale de la comuna |
| `naturaleza` | `subterranea` o `superficial` |
| `fuente` | Sector del acuífero o cauce (p. ej. `Sector 7 - Rio La Ligua Cabildo`) |
| `consuntivo`, `eventual`, `provisional` | Tipo y ejercicio del derecho |
| `unidad_origen`, `caudal_origen` | Como vienen en el Excel |
| `caudal_ls`, `m3_anual`, `m3_mes` | Normalizados; `m3_mes` = `m3_anual` / 12. Vacíos si la unidad es "Acciones" o "%" |
| `m3_anual_continuo`, `volumen_origen`, `volumen_aplicado` | `m3_anual` usa la columna "Volumen" del Excel (tope anual autorizado) cuando está entre el 5 % y el 105 % del volumen continuo: 3.910 derechos, la mayoría con un tope del 20 % o del 100 %. Si no, `m3_anual` = `m3_anual_continuo` |
| `caudal_negativo` | 31 filas con caudal negativo (cesiones o errores de carga; una de −41.666 l/s). No se suman |
| `duplicado_de` | 56 derechos no VPC que repiten un VPC (mismo titular, comuna y caudal, a 600 m o menos): `derecho_id` del VPC. No se suman |
| `pozo_compartido` | 1.444 derechos en un punto (celda de 20 m) con 3 o más titulares distintos: pozos comunitarios. No se asignan a un predio |
| `sumable` | Consuntivo, no eventual, con cifra positiva y no duplicado. Solo estos cuentan como derecho |
| `gran_derecho` | 100 l/s o más: casi siempre un canal o una comunidad de aguas, no un predio |
| `utm_norte`, `utm_este`, `huso_origen`, `datum_origen` | Coordenada original |
| `coord_estado` | `ok` (7.663), `sin_coordenada` (1.314), `datum_supuesto` (111), `huso_corregido` (37), `fuera_de_region` (13) |
| `geometry` | Punto de captación en EPSG:4326; vacío si no hay coordenada válida |

## Cruce de derechos con predios (D5, versión 2)

Para regenerar: `uv run scripts/extract/canales_ciren.py` (una vez) y `uv run scripts/extract/cruce_derechos_predios.py` (necesita `predio.parquet`, `derecho.parquet` y, para el cruce por titular, `raw/dga/derecho_titulares.parquet`).

La versión 2 corrige los gaps del assessment de datos del 21-11-2026: derechos inflados por pozos compartidos, derechos en otro polígono del mismo rol, derechos otorgados después de los hechos y agua de canal.

`metodo_cruce` de cada derecho (`derecho_predio.parquet`):

| Método | Derechos | Confianza |
| --- | --- | --- |
| `punto_en_predio`: el punto de captación cae dentro del predio | 4.897 | alta |
| `cercania`: predio válido más cercano a 500 m o menos | 1.326 | media hasta 100 m, baja después |
| `titular`: el mismo titular tiene otros derechos ubicados en un solo predio de la comuna | 180 | baja |
| `pozo_compartido_sin_asignar`: 3 o más titulares en el mismo punto | 1.444 | — |
| `gran_derecho_sin_asignar`: 100 l/s o más | 45 | — |
| `duplicado_vpc` | 56 | — |
| `sin_predio_a_500m` / `sin_coordenada` | 47 / 1.143 | — |

La confianza baja un nivel si la coordenada tiene un supuesto o si el derecho es superficial. Queda asignado el 38 % del volumen sumable; el resto son grandes derechos, pozos compartidos y derechos sin coordenada.

Columnas de `predio_derecho` (un registro por predio y temporada):

| Columna | Descripción |
| --- | --- |
| `predio_id`, `temporada`, `corte` | Temporada seca `2019-20` a `2025-26`. Solo cuentan los derechos otorgados antes de `corte` (1 de diciembre) |
| `zona`, `comuna`, `rol_id`, `area_ha`, `area_rol_ha`, `n_poligonos_rol`, `elegible` | `rol_id` = comuna:rol. Un rol puede tener varios polígonos |
| `n_derechos_predio`, `m3_anual_derecho_predio` | Derechos asignados a este polígono |
| `n_derechos_rol`, `m3_anual_derecho_rol`, `m3_anual_derecho_rol_subterraneo`, `m3_ha_derecho_rol` | Derechos de todo el rol. **Usar estos para comparar con el consumo**: el pozo puede estar en otro polígono del mismo rol |
| `m3_anual_derecho_entorno_500m` | Derechos sumables con punto a 500 m o menos (incluye pozos compartidos, no grandes derechos) |
| `pozo_compartido_500m` | Hay un pozo compartido a 500 m o menos |
| `dist_canal_m`, `canal_300m` | Distancia al canal de riego más cercano (hasta 5 km) |
| `estado_derechos` | `con_derechos` (el rol tiene derechos), `derechos_cerca_de_otro_rol` o `sin_derechos_cerca` |
| `confianza_cruce` | La peor de los derechos del rol. Sin derechos: media; con derechos cerca de otro rol: baja |

Temporada 2025-26, predios elegibles: 2.512 `con_derechos`, 4.455 `derechos_cerca_de_otro_rol` y 944 `sin_derechos_cerca`. La mediana de derechos de los predios con derechos es de 7.058 m³/ha al año (antes del arreglo, 16.364).

Lo que hay que saber para M5 y M6:

- **Los derechos solos no distinguen infractores.** Entre los 143 predios elegibles fiscalizados desde 2020 (38 positivos), con la temporada de la inspección, el AUC es de 0,53 para el déficit (8.000 m³/ha frutal menos derechos), 0,54 para m³/ha con derecho y 0,49 para los derechos del entorno. La señal que distingue tiene que venir del satélite (riego en ventana seca); los derechos sirven para dimensionar el exceso y para el expediente. Los fiscalizados no son una muestra al azar: la DGA ya los había elegido por sospechosos.
- **El canal no sirve para bajar la confianza:** el 68 % de los predios elegibles tiene un canal a 300 m o menos, y los 5 casos clave tienen `dist_canal_m = 0`. Se deja como dato. En Z1 los ríos La Ligua y Petorca pasan buena parte del año secos, así que el canal aporta poca agua; en Z2 el Aconcagua sí la trae.
- **Casos clave** (temporada de la inspección): FD-0501-181 y FD-0504-257 no tienen derechos en el rol y sí derechos a 500 m (505.000 y 1,47 millones de m³): `derechos_cerca_de_otro_rol`. FO-0504-95: `sin_derechos_cerca`. FD-0501-191 ahora tiene 273.000 m³ en su rol (antes aparecía sin derechos). FO-0501-462: 12.614 m³ en el rol, porque el volumen autorizado es el 20 % del caudal.

## Fiscalizaciones (D6)

Para regenerar: `uv run scripts/extract/fiscalizaciones_dga.py` (baja la planilla si no está; `--refrescar` baja la del mes).

| Columna | Descripción |
| --- | --- |
| `expediente` | Código FD (denuncia) u FO (oficio). FO-0504-45 aparece dos veces en la planilla |
| `zona`, `zona_origen` | Zona del predio a 50 m o menos del punto (`predio`) o, si no hay, de la comuna declarada (`comuna`) |
| `predio_id`, `dist_predio_m`, `predio_elegible` | Predio con rol válido más cercano a 50 m o menos |
| `tipo_infraccion`, `extraccion` | `extraccion` = "extracción no autorizada de aguas" (no incluye áridos) |
| `fecha_inspeccion`, `fecha_resolucion`, `resolucion`, `decision`, `multa_utm`, `estado_tramitacion`, `recurso` | De la planilla |
| `etiqueta` | `positivo` (constata, acoge o aplica multa), `negativo` (no acoge, cierra, rechaza, archiva), `en_tramite` (no resuelto) u `otro` (acumula, apercibe) |
| `geometry` | Punto del acta en EPSG:4326, suponiendo datum WGS84 |

Extracción de aguas por etiqueta: Z1 46 positivos, 290 negativos, 6 en trámite; Z2 33 positivos, 110 negativos, 9 en trámite. Con predio elegible a 50 m o menos: 62 positivos y 318 negativos. Los negativos son débiles: la DGA no encontró infracción el día de la visita. Los `en_tramite` no se muestran como infractores.

## Especie por predio (D7)

Para regenerar: `uv run scripts/extract/cultivos_ciren.py` (necesita `predio.parquet`; `--refrescar` vuelve a bajar los cuarteles).

Los polígonos del Catastro Frutícola son cuarteles plantados (mediana 1,45 ha), no predios. El cruce es por superficie: para cada predio elegible se suma la superficie plantada de cada especie que cae dentro (se ignoran solapes de menos de 0,05 ha). Un cuartel con varias especies se reparte en partes iguales.

| Columna | Descripción |
| --- | --- |
| `predio_id`, `zona`, `comuna`, `area_ha` | Del predio elegible |
| `con_frutales` | Al menos un cuartel dentro: 1.999 de 7.911 predios (25 %) |
| `area_fruticola_ha`, `frac_fruticola` | Superficie plantada y fracción del predio (tope 1) |
| `especie_principal`, `especies` | Especie con más superficie; todas, separadas por `;`, de mayor a menor. Palto en el 68 % de los predios con frutales |
| `n_cuarteles` | Cuarteles que caen dentro |
| `rol_coincide` | Algún cuartel trae el mismo rol y comuna que el predio (67 % de los predios con frutales) |

Para M4: el 44 % de los predios con infracción (positivos de D6) no tiene frutales en el catastro (pueden ser hortalizas, praderas o cultivos anuales). El Kc tiene que salir del NDVI; la especie solo ajusta cuando existe.

## Lo que hay que saber

- Derechos, prueba con casos: el pozo de FO-0504-95 (multado por "2 pozos sin derechos") no tiene ningún derecho a menos de 500 m; el más cercano está a 1.280 m. El de FO-0501-462 tiene 11 derechos a menos de 500 m, así que ahí la infracción sería extraer más de lo autorizado.

- Filtra `elegible = True` antes de calcular series: deja fuera cauces, caminos y polígonos sin rol, y también parcelas y lotes de pozo de menos de 1 ha.
- Hay polígonos muy grandes (hasta unas 1.000 ha) que son cerros o fundos enteros. Su NDVI promedio diluye la señal de riego.
- El punto del caso es el pozo o la captación, no el centro del predio. El punto cae dentro de un predio elegible en FD-0501-181 (`202-35`, 17,2 ha), FD-0504-257 (`133-9`, 9,4 ha), FO-0501-462 (`88-31`, 6,1 ha), FO-0504-95 (`61-6`, 5,7 ha), FO-0504-157 (`46-25`, 29,8 ha) y FO-0501-376 (`101-12`, 993 ha: demasiado grande para una señal clara). En los otros 4 casos cae fuera, a entre 5 y 24 m del predio más cercano.
- Solo se usan casos resueltos. Hay expedientes "En trámite" en las zonas; no se muestran como infractores en la demo.
- Las coordenadas de los casos suponen datum WGS84; la planilla de la DGA no lo indica.

## Licencia y datos personales

- Predios: CIREN 2022, vía IDE Minagri. No se encontraron términos de uso. Se cita la fuente y no se sube la capa completa; solo la muestra.
- Casos: planilla pública de la DGA. No trae nombres.
- Los nombres de titulares de derechos de agua (tarea D4) no se suben a git.
