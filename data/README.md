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
   - **FD-0501-181** (`papel = demo_principal`, Cabildo, predio `202-35`, 17,2 ha con 16,1 ha de palto y chirimoyo, sin derechos propios; inspección el 02-04-2024): la serie del verano 2023-24 debería mostrar riego en ventana seca antes de la inspección. Es el caso que se muestra en la demo.
   - **FO-0504-95** (`papel = antecedente_satelital`, Hijuelas, predio `61-6`, inspección el 23-11-2021): la DGA dice que lo detectó con satélite; su serie de 2021 debería mostrar riego en ventana seca.
5. Periodos: el análisis cubre desde enero de 2020 hasta la última escena limpia. Los periodos prioritarios de cada zona están en `zonas.json`. Para la demo, el ranking usa la temporada seca 2025-26 (diciembre de 2025 a marzo de 2026), y la ficha muestra además la escena limpia más reciente.
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
| `processed/predio_derecho.parquet` | Sí | Resumen por predio con rol válido (18.244): m³ con derecho, derechos del entorno y `estado_derechos`. Lo leen M5 y M12 | `scripts/extract/cruce_derechos_predios.py` |
| `processed/fiscalizacion.parquet` | Sí | 835 expedientes de fiscalización de la DGA en Z1 y Z2 (497 de extracción de aguas), con etiqueta y predio. Sin nombres | `scripts/extract/fiscalizaciones_dga.py` |
| `raw/dga/planilla_fiscalizacion.xlsx` | No | Planilla de seguimiento de fiscalización de la DGA (se regenera) | `scripts/extract/fiscalizaciones_dga.py` |
| `processed/predio_cultivo.parquet` | Sí | Especie frutal y superficie plantada por predio elegible (Catastro Frutícola CIREN 2025), sin geometría | `scripts/extract/cultivos_ciren.py` |
| `raw/ciren_fruticola/cuarteles.parquet` | No | 5.696 cuarteles plantados de las comunas de Z1 y Z2 (caché) | `scripts/extract/cultivos_ciren.py` |
| `raw/dga/Derechos_Concedidos_V_Region.xls` | No | Excel de derechos de la DGA, Región de Valparaíso (trae nombres de titulares) | `scripts/extract/derechos_dga.py` |
| `raw/dga/derecho_titulares.parquet` | No | `derecho_id` y nombre del titular, para el cruce por titular (D5) y el expediente | `scripts/extract/derechos_dga.py` |

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
| `sumable` | Consuntivo, no eventual y con cifra. Solo estos cuentan como derecho de un predio |
| `gran_derecho` | 100 l/s o más: casi siempre un canal o una comunidad de aguas, no un predio |
| `utm_norte`, `utm_este`, `huso_origen`, `datum_origen` | Coordenada original |
| `coord_estado` | `ok` (7.663), `sin_coordenada` (1.314), `datum_supuesto` (111), `huso_corregido` (37), `fuera_de_region` (13) |
| `geometry` | Punto de captación en EPSG:4326; vacío si no hay coordenada válida |

## Cruce de derechos con predios (D5)

Para regenerar: `uv run scripts/extract/cruce_derechos_predios.py` (necesita `predio.parquet`, `derecho.parquet` y, para el cruce por titular, `raw/dga/derecho_titulares.parquet`).

`metodo_cruce` de cada derecho, en orden de prioridad:

| Método | Derechos | Confianza |
| --- | --- | --- |
| `punto_en_predio`: el punto de captación cae dentro del predio | 6.061 | alta |
| `cercania`: predio válido más cercano a 500 m o menos | 1.656 | media hasta 100 m, baja después |
| `titular`: el mismo titular tiene otros derechos ubicados en un solo predio de la comuna | 181 | baja |
| `gran_derecho_sin_asignar`: 100 l/s o más | 45 | — |
| `sin_predio_a_500m` / `sin_coordenada` | 49 / 1.146 | — |

La confianza baja un nivel si la coordenada tiene un supuesto o si el derecho es superficial (la bocatoma no está en el predio que riega). En total queda asignado el 86 % de los derechos y el 47 % del volumen sumable; el resto son grandes derechos y derechos sin coordenada.

Columnas de `predio_derecho`:

| Columna | Descripción |
| --- | --- |
| `predio_id`, `zona`, `comuna`, `area_ha` | Del predio; para la geometría, unir con `predio.parquet` por `predio_id` |
| `n_derechos`, `n_derechos_sumables` | Derechos asignados al predio |
| `m3_anual_derecho`, `m3_mes_derecho`, `m3_anual_derecho_subterraneo` | Volumen con derecho; solo sumables |
| `m3_anual_derecho_entorno_500m` | Derechos sumables con punto a 500 m o menos del predio, propios o de vecinos (sin grandes derechos) |
| `estado_derechos` | `con_derechos` (2.864), `sin_derechos_cerca` (3.042: ningún punto de derecho a 500 m) o `derechos_cerca_de_otro_predio` (12.338) |
| `confianza_cruce` | La peor de sus derechos. "Sin derechos" nunca es alta (el 14 % de los derechos no tiene coordenada); `derechos_cerca_de_otro_predio` es baja |

Tres cosas para M5 y M6:

- **Lotes de pozo:** un pozo puede estar inscrito en un lote chico y regar el predio vecino. Hay predios de 0,1 ha con más de 1 millón de m³ al año. Si `m3_anual_derecho` es bajo pero `m3_anual_derecho_entorno_500m` es alto, el predio no es sospechoso con confianza alta: puede regar con el pozo del vecino.
- **No todos los positivos tienen exceso sobre derechos:** FO-0504-157 tiene 1,0 millones de m³ al año en 29,8 ha y fue multado igual (probablemente por un pozo no inscrito). El índice consumo-contra-derechos detecta mejor los casos sin derechos, como FO-0504-95 (`sin_derechos_cerca`). La validación no debe esperar que todos los positivos queden arriba.
- **FO-0501-462 dejó de ser el caso de la demo:** tiene un derecho de 2 l/s (63.072 m³ al año) en 6,1 ha (unos 10.300 m³ por hectárea, cerca de lo que consume un frutal) y su predio no tiene frutales en el catastro. El caso de la demo ahora es FD-0501-181: 16,1 ha de palto sin derechos propios.

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

- Derechos: hay 7.295 derechos sumables, menores de 100 l/s y con punto, para cruzar con predios (D5); el 92 % son subterráneos.
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
