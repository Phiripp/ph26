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
   - **FO-0504-95** (`papel = antecedente_satelital`, Hijuelas, predio `61-6`, inspección el 23-11-2021): es el **caso base** para mostrar una multa efectuada. La DGA dice que lo detectó con satélite; su serie de 2021 debería mostrar riego en ventana seca.
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
| `processed/cauce.parquet` | Sí | 2.855 tramos de cauces de la DGA en Z1 y Z2 (río, estero, quebrada, etc.), con nombre, tipo y subsubcuenca | `scripts/extract/cauces_dga.py` |
| `processed/consumo_predio.parquet`, `processed/consumo_predio_temporada.parquet` | Sí | Consumo de riego FAO-56 en rango de m³ por predio y mes, y por temporada (M4) | `scripts/models/consumo_fao56.py` |
| `processed/puntaje.parquet` | Sí | Índice de sospecha (M5) de los 7.911 elegibles en 2025-26: banda, puntaje 0–100, confianza y motivos, consumo bruto, derecho asignado, exceso en rango y derechos ajenos disponibles a 500 m. Lo leen M8, M9, M12 y M13 | `scripts/models/indice_sospecha.py` |
| `processed/puntaje_validacion.parquet` | Sí | Lo mismo para los 159 predios de los vecindarios de validación, temporadas 2019-20 a 2025-26 (M6) | `scripts/models/indice_sospecha.py --senal ..._validacion --consumo ..._validacion_temporada` |
| `processed/impacto.json` | Sí | Cifras de impacto (M9) para el frontend: candidatos, acierto, escenarios conservador, central y alto (casos, m³, CLP, personas, multas) y adelanto. Detalle en [docs/impacto.md](../docs/impacto.md) | `scripts/models/impacto.py` |
| `processed/calibracion_grilla.csv` | Sí | Grilla de calibración de M3 (81 combinaciones) con recall, lift y AUC de cada una (M7). Detalle en [docs/calibracion.md](../docs/calibracion.md) | `scripts/models/calibracion.py` |
| `processed/validacion_casos.geojson` | Sí | 107 expedientes de extracción de aguas evaluados en M6: etiqueta, temporada previa, `detectable`, banda y puntaje (del vecindario), con color por etiqueta. GitHub lo muestra como mapa | `scripts/models/validacion.py` (también escribe `docs/validacion.md`) |
| `processed/ruta_z1.*`, `processed/ruta_z2.*` | Sí | Rutas de inspección con los 40 predios de mayor puntaje de M5 por zona (M8) | `scripts/models/ruta_inspeccion.py --puntajes data/processed/puntaje.parquet` |
| `processed/ruta_ejemplo_z1.*`, `processed/ruta_ejemplo_z2.*` | Sí | Rutas de inspección de ejemplo (JSON, GeoJSON, GPX) con los casos de validación (M8) | `scripts/models/ruta_inspeccion.py --demo` |
| `processed/anomalias_predio.parquet`, `processed/senal_riego.parquet` | Sí | Anomalías de verdor y humedad por predio y fecha (M2) y señal de riego por predio y temporada (M3) | `scripts/models/anomalias.py`, `scripts/models/detector_riego.py` |
| `processed/serie_predio_elegibles_2025-26.parquet` | Sí | Serie Sentinel-2 corregida (D15) de los 7.911 predios elegibles, diciembre de 2025 a marzo de 2026: 158.053 filas, 97 escenas. Universo del ranking. En predios que cruzan el borde entre tiles (19HBE/19HCE, 19HBD/19HCD), cada fecha usa el tile con más píxeles válidos y puede cubrir solo parte del predio | `scripts/extract/serie_sentinel2.py --elegibles --temporadas 2025-26:2025-26 --nubes-max 40` |
| `processed/serie_predio_validacion.parquet` | Sí | Serie Sentinel-2 corregida de los 159 predios de los vecindarios de validación (D18), diciembre a marzo de 2019-20 a 2025-26: 19.397 filas, 663 escenas | `scripts/extract/serie_sentinel2.py --validacion --temporadas 2019-20:2025-26 --nubes-max 40` |
| `processed/serie_referencia.parquet` | Sí | Serie Sentinel-2 corregida de los 3.642 polígonos de secano (D11), diciembre a marzo de 2019-20 a 2025-26; `predio_id` lleva el `ref_id`. NDVI mediano del secano: Z1 0,13–0,20 y Z2 0,23–0,35 según la temporada (Z2 es bastante más verde) | `scripts/extract/serie_sentinel2.py --referencia --temporadas 2019-20:2025-26 --nubes-max 40` |
| `processed/predio_cauce.parquet` | Sí | Cauce, río o estero y canal más cercanos a cada predio elegible, con distancias. Para el campo "cauce cercano" del expediente (M12, M13) | `scripts/extract/cauces_dga.py` |
| `processed/restriccion.parquet` | Sí | 57 sectores hidrogeológicos (SHAC) de la DGA que tocan Z1 o Z2, con `tipo_limite` (`prohibicion`, `restriccion`, `abierto`), resolución y fechas. Polígonos en EPSG:4326 | `scripts/extract/restriccion_dga.py` |
| `processed/predio_restriccion.parquet` | Sí | Por predio elegible, el SHAC donde cae la mayor parte de su superficie: `cod_shac`, `sector`, `tipo_limite`, `resolucion_dga`, `fecha_resolucion`, `frac_en_shac`, `en_prohibicion` (SHAC dominante es de prohibición) y `toca_prohibicion` (intersecta algún SHAC de prohibición). Un predio sin SHAC queda vacío (1 de 7.911). Para el contexto y el expediente (M12, M13); no entra al ranking | `scripts/extract/restriccion_dga.py` |
| `processed/poi.parquet` | Sí | Puntos de interés dentro y junto al predio (máx. 8 por predio): `zona_riego`, `posible_tranque`, `captacion`, `pozo_derecho`, `bocatoma`, `cauce` y `canal`, cada uno con coordenada, razón, fecha de la imagen, confianza, elevación, pendiente y la señal de M3 (`senal_riego_m3`, `frac_senal_m3`). Cubre los 7.911 elegibles (temporada seca 2025-26): 32.289 POI en 7.793 predios; los demás no tienen señal ni infraestructura cerca. Se regenera en Cloud Run con `scripts/cloud/poi/` (unos 45 min) | `scripts/extract/poi_predio.py` |
| `processed/expedientes/` | Sí (ejemplo) | Expedientes PDF de M13: una carpeta por expediente (`CAU-<predio_id>-<fecha>/` con `expediente.pdf`, `expediente.html` y figuras) y `registro.csv` (id, predio, temporada, confianza, versión, hash de insumos). En git va el ejemplo del caso base FO-0504-95 (`HIJUELAS:61-6`) | `scripts/models/expediente.py` |

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
| `m3_max_dic`, `m3_max_ene`, `m3_max_feb`, `m3_max_mar` | Máximo extraíble en ese mes: caudal mensual autorizado × días (columna del mes del Excel si las 12 están completas; si no, caudal promedio). No aplica el tope anual "Volumen". Lo usa el exceso mensual de M5 |
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
| `vecindario`, `n_predios_30m`, `ambiguo` | Predios con rol válido a 30 m o menos del punto (lista de `predio_id`); `ambiguo` si son 2 o más. El punto es el pozo y puede regar al vecino |
| `predio_grande` | El predio mide más de 100 ha (la señal se diluye) |
| `etiquetas_mixtas` | El predio tiene expedientes de extracción positivos y negativos |
| `con_recurso` | El infractor presentó recurso de reconsideración |
| `set_validacion` | `limpio`, `vecindario` o `fuera` (ver abajo) |
| `temporada_previa`, `ndvi_previo`, `detectable` | Última temporada seca (diciembre a marzo) antes de la inspección, el mayor NDVI mediano del vecindario en esas fechas y si supera 0,30 (secano 0,16–0,30; suelo desnudo 0,10–0,15). Vacío sin serie de validación |

Extracción de aguas por etiqueta: Z1 46 positivos, 290 negativos, 6 en trámite; Z2 33 positivos, 110 negativos, 9 en trámite. Con predio elegible a 50 m o menos: 62 positivos y 318 negativos. Los negativos son débiles: la DGA no encontró infracción el día de la visita. Los `en_tramite` no se muestran como infractores.

Set de validación (D18). Base: extracción de aguas, positivo o negativo, predio elegible e inspección desde julio de 2020 (hay al menos una temporada seca previa en el periodo de análisis).

| `set_validacion` | Regla | Positivos | Negativos |
| --- | --- | --- | --- |
| `limpio` | Base, no ambiguo, predio de 100 ha o menos; un negativo además sin etiquetas mixtas | 10 (Z1: 4, Z2: 6) | 24 |
| `vecindario` | Base, pero ambiguo, predio grande o negativo con etiquetas mixtas: evaluar con el mejor puntaje del vecindario | 24 | 51 |
| `fuera` | El resto | — | — |

Para M6: con 10 positivos limpios, el recall tiene un intervalo de confianza muy ancho (con 7 de 10 detectados, el intervalo de Wilson al 95 % va de 40 % a 89 %). Hay que reportarlo así.

`detectable` (con `serie_predio_validacion.parquet`): de los positivos, 6 de 10 limpios y 13 de 24 de vecindario son detectables. Los no detectables se concentran en Z1 en el verano 2021-22 (megasequía): predios ya secos multados por extracción, que ningún índice de verdor puede marcar. M6 se mide sobre los positivos detectables y reporta aparte cuántos no lo son. Entre los negativos, el 64 % es detectable (48 de 75): el verdor solo no separa positivos de negativos entre los fiscalizados. FD-0501-181 y FO-0501-462 quedan en `vecindario`.

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

## Cauces y canales (D8)

Para regenerar: `uv run scripts/extract/canales_ciren.py` y luego `uv run scripts/extract/cauces_dga.py` (necesita `predio.parquet`).

Columnas de `predio_cauce` (un registro por predio elegible):

| Columna | Descripción |
| --- | --- |
| `cauce_nombre`, `cauce_tipo`, `cod_subsubcuenca`, `dist_cauce_m` | Cauce con nombre más cercano (río, estero, quebrada o embalse; no línea de costa). Mediana 308 m |
| `rio_nombre`, `rio_tipo`, `dist_rio_m` | Río o estero más cercano: la fuente que suele nombrar una denuncia. Mediana 533 m |
| `canal_nombre`, `canal_organizacion`, `canal_fuente`, `dist_canal_m` | Canal de riego CNR/CIREN más cercano, su organización de usuarios y su fuente. Mediana 92 m |

Ejemplo para el expediente de FO-0504-95: río más cercano, Rio Aconcagua, a 1.166 m; canal La Sombra (Comunidad de Aguas del Canal La Sombra, Río Aconcagua 2.ª sección) atraviesa el predio.

## Consumo estimado FAO-56 (M4)

Para regenerar: `uv run scripts/models/consumo_fao56.py` (muestra) o con `--serie data/processed/serie_predio_validacion.parquet --salida ...`; `--serie-referencia` usa la serie de secano (D11) en vez del NDVI de secano fijo de 0,30.

- `consumo_predio.parquet`: por predio y mes de diciembre a marzo: estado del mes (observado, interpolado o faltante), escenas, NDVI, Kc mínimo, central y máximo, ET0, lluvia efectiva y m³ mínimo, central y máximo.
- `consumo_predio_temporada.parquet`: por predio y temporada: m³ y m³/ha de la temporada y anual extrapolado, con columnas de calidad y `supuestos`.
- Kc desde el NDVI con tres relaciones publicadas (Campos et al. 2010; Allen y Pereira 2009); la especie solo pone tope al Kc. Suelo desnudo da 0 (control `88-31`).
- Es **consumo neto** (evapotranspiración que la lluvia no cubre). Para compararlo con derechos (extracción), M5 divide por la eficiencia de aplicación (~0,85 en microaspersión).
- Palto adulto de FO-0504-95: 7.871 m³/ha al año central (5.816–11.334), dentro de lo publicado para Quillota (7.000–9.000, Gardiazabal et al. 2003).
- Predios de más de 100 ha: el central cuenta el matorral del cerro como consumo; usar el mínimo.

## Ruta de inspección (M8)

Para regenerar: `uv run scripts/models/ruta_inspeccion.py --zona Z1 --puntajes data/processed/puntaje.parquet` (o `--demo`, que usa los positivos limpios y los casos de validación con puntaje 1). Desde el backend: `from scripts.models.ruta_inspeccion import ruta`.

- Prize-collecting TSP con OR-Tools sobre la matriz de tiempos de OSRM: sale y vuelve a la plaza de La Ligua (Z1) o de Quillota (Z2), jornada de 8 h, 30 min por visita, 40 predios de mayor puntaje como máximo.
- Con M5 (`ruta_z1`, `ruta_z2`): Z1 visita 10 de 40 predios (08:30 a 16:25, 143 km); Z2, 12 de 40 (08:30 a 16:29, 91 km).
- Salidas `ruta_ejemplo_z1` y `ruta_ejemplo_z2`: `.json` (orden, horas, km, punto de acceso al camino, enlace a Google Maps, predios fuera y motivo), `.geojson` y `.gpx` (válido contra el esquema GPX 1.1).
- Ejemplo Z1: 7 de 8 predios entre 08:30 y 15:20, 141 km. Ejemplo Z2: 6 de 6 entre 08:30 y 13:31, 110 km.
- Caché de OSRM en `data/raw/osrm/` (no va a git). La demo sirve rutas precalculadas: el servidor público a veces tarda minutos.
- Limitaciones: el perfil auto de OSRM no usa caminos de tierra; el último tramo hasta el predio (58–397 m, hasta 1,4 km en predios grandes) no se suma al tiempo. Los tiempos son optimistas.

## Índice de sospecha (M5)

Para regenerar: `uv run scripts/models/indice_sospecha.py` (elegibles 2025-26 → `puntaje.parquet`). Para la validación: `--senal data/processed/senal_riego_validacion.parquet --consumo data/processed/consumo_predio_validacion_temporada.parquet --salida data/processed/puntaje_validacion.parquet`. Necesita `predio.parquet` (local).

- La sospecha sale de la señal satelital (M3); los derechos dimensionan el exceso. Exceso anual = consumo bruto (M4 / eficiencia 0,90, 0,85 o 0,75) − derecho asignado (`m3_anual_derecho_rol` de la temporada × `area_ha` / `area_rol_ha`), en mínimo, central y máximo. En predios de más de 100 ha el central es el mínimo.
- Exceso mensual (por defecto): el exceso es el mayor entre el anual y la suma, de diciembre a marzo, del consumo bruto del mes sobre el máximo extraíble ese mes (`m3_max_*` de `derecho`, columnas `m3_exceso_mensual_*`). Capta el peak de verano: en enero se consume cerca del 15 % del año y el tope "Volumen" no limita un mes.
- `banda`: `alta` (señal y exceso mínimo > 0), `media` (exceso central > 0), `baja` (exceso máximo > 0), `sin_alerta`. Con confianza baja la banda baja un nivel.
- `confianza`: la peor entre la de M3, la del cruce de derechos, `media` sin derechos propios ubicados, `baja` si los derechos ajenos disponibles a 500 m cubren el exceso central, y `media` si M4 no tiene la temporada completa. `motivos` dice por qué. `canal_300m` es solo un motivo: lo tiene el 81 % de los predios positivos y el 76 % de los que tienen señal, así que no discrimina.
- `m3_derecho_ajeno_disponible_500m`: derechos de riego de otros roles a 500 m o menos, por la fracción que su rol no usa según M4, repartidos en partes iguales entre los predios elegibles a 500 m del punto. Un pozo compartido sin asignar cuenta entero antes de repartirse.
- `aplicabilidad` (corrida nacional): `calibrado` en Z1 y Z2; en `data/regiones.json`, cada región trae la suya. En `sur_humedo` no hay banda alta (una alerta alta baja a media, motivo `aplicabilidad_sur_humedo`).
- `puntaje`: base de la banda (75, 50, 25 o 0) + 25 × `frac_senal` × peso de la confianza (1; 0,7; 0,4) × percentil del exceso central **por hectárea** en la zona (intensidad, no tamaño: los positivos tienden a ser predios más chicos). `rank_zona` ordena por banda y puntaje.
- `fiscalizado_dga`: el predio está en el vecindario de una fiscalización por extracción de aguas (cualquier resultado; no dice si hubo infracción).
- 2025-26 (con los umbrales de M7): alta 759 (9,6 %), media 856 (10,8 %), baja 169, sin alerta 6.127. Casos: FD-0501-181 puesto 41 de Z1 y FO-0504-95 puesto 69 de Z2, ambos en banda alta. FO-0504-157 queda sin alerta, porque sus derechos superan su consumo.
- Validación (M6, [docs/validacion.md](../docs/validacion.md)): con los umbrales calibrados (M7), el predio del punto de la DGA cae en banda alta en 7 de 19 positivos detectables (37 %), contra 10 % al azar: 3,7 veces (IC 95 % 1,9–5,9), optimista porque los umbrales se eligieron con ese set. Con los umbrales iniciales era 2,6 veces (1,3–4,4). Entre fiscalizados el AUC es 0,62 (0,46–0,77). Una lectura anterior de 2,8 y 2,3 veces estaba inflada (comparaba la mejor banda del vecindario con un solo predio).
- Prueba de variantes (21-11-2026): anual o mensual × orden por volumen, por intensidad o por intensidad descontando derechos ajenos. Mensual + intensidad dio el mayor AUC (0,558 contra 0,532 del índice original; mejor en el 88 % de los remuestreos, no significativo) con el mismo recall; es la que queda. Con solo los negativos "No acoge" (21) el AUC es 0,59. Se reproduce con `--exceso anual|mensual --orden volumen|intensidad|intensidad_ajenos`.
- Limitación para M9: 64 predios de más de 100 ha suman 77 de los 122 millones de m³/año de exceso mínimo de las bandas alta y media. M9 debe reportarlos aparte.

## Calibración (M7) e impacto (M9)

- M7 ([docs/calibracion.md](../docs/calibracion.md)): grilla de 81 combinaciones de M3 (`uv run scripts/models/calibracion.py`, unos 3 min). Regla fijada antes de correr: cota inferior de Wilson del lift en banda alta, suavizada con las combinaciones vecinas. Quedan z_verdor ≥ 2,5, z_humedad ≥ 1,5, frac_min 0,7 y 10 días secos. El verdor alto y la fracción alta mandan; los días secos casi no cambian nada. 2,5 es el borde de la grilla.
- M9 ([docs/impacto.md](../docs/impacto.md), `impacto.json` para el frontend): candidatos en banda alta sin fiscalización a 500 m desde 2018, casos esperados con acierto bajo (Wilson de Caudal), central (33 % de la DGA) y alto, m³, CLP, personas y multas; adelanto en casos conocidos. Regenerar con `uv run scripts/models/impacto.py` después de M5.

## Anomalías y detector de riego (M2, M3)

Para regenerar (con la referencia real, cuando exista `serie_referencia.parquet`):

```
uv run scripts/models/anomalias.py --serie data/processed/serie_predio_elegibles_2025-26.parquet --referencia data/processed/serie_referencia.parquet
uv run scripts/models/detector_riego.py [--umbral-verdor 2 --umbral-humedad 2 --dias-min 10]
```

- `anomalias_predio.parquet` (M2): por predio y fecha, `z_verdor` y `z_humedad` frente a los 30 polígonos de secano más cercanos (10 km o menos) con dato válido ese día. Escala robusta: max(1,4826 × MAD; 0,05). Con menos de 8 referencias, z queda vacío (`sin_referencia`).
- `senal_riego.parquet` (M3): por predio y temporada, `frac_senal` (fechas con z_verdor ≥ 2,5 y z_humedad ≥ 1,5 dentro de una ventana seca de M1 y con 10 o más días sin lluvia; calibrado en M7, antes 2 y 2), `senal_riego` (frac_senal ≥ 0,7; antes 0,5), medianas de z, `confianza` y `motivos_confianza`.
- Se exigen las dos anomalías: el suelo desnudo puede tener NDMI más alto que el matorral seco (falso positivo si solo se mira la humedad).
- Lo generado hoy usa la **muestra y una referencia provisional** (los predios oscuros de la misma muestra; columna `referencia = provisional`): sirve para ver el formato, no para calibrar. Con la referencia CONAF real de diciembre de 2019, el secano da NDVI 0,16 con MAD ≈ 0,02, así que el piso de escala 0,05 manda: z ≥ 2 equivale a 0,10 de NDVI y de NDMI sobre el secano. Esa escala y los umbrales se calibran en M7.
- El detector marca riego, no ilegalidad: con z ≥ 2, el 42 % de los predios de los vecindarios de validación tendría señal en diciembre de 2019. M5 cruza la señal con el consumo (M4) y los derechos.

## Series Sentinel-2 en GCP (D1)

`serie_sentinel2.py` se puede correr en una VM de Compute Engine del proyecto `ph-26-caudal`. Es mucho más rápido que en un notebook: la referencia de secano de 2025-26 (3.642 polígonos, 112 escenas) tardó 52 s, contra ~90 s por escena en local. La VM está cerca del bucket de Earth Search (AWS us-west-2), y en local manda la red.

```
scripts/gcp/bootstrap.sh       # una vez: APIs, bucket, permiso de la VM y revisión de cuota
scripts/gcp/job-serie-sentinel2-deploy.sh <corrida> -- <argumentos de serie_sentinel2.py>
# p. ej.: scripts/gcp/job-serie-sentinel2-deploy.sh elegibles-2025-26 -- --elegibles --temporadas 2025-26:2025-26 --nubes-max 40
gcloud storage cat gs://ph-26-caudal-sentinel2/runs/<corrida>/DONE    # 0 = completa
gcloud storage cp gs://ph-26-caudal-sentinel2/runs/<corrida>/serie_<corrida>.parquet data/processed/
gcloud compute instances delete job-s2-<corrida> --zone us-west1-b --project ph-26-caudal --quiet
```

- La VM (`e2-highmem-8`, 16 hilos) baja las entradas, corre el script, sube la serie, el log y el caché a `gs://ph-26-caudal-sentinel2/` y se apaga sola. Configuración en `scripts/gcp/config.sh`.
- Usa `--nubes-max 40` como las series de esta tabla: sin él, el script toma 70 y agrega escenas muy nubladas.
- Cuota global del proyecto: 12 vCPU, así que corre una VM a la vez y bórrala al terminar.
- Memoria: con `--referencia` o `--elegibles`, cada hilo lee ventanas de casi un tile. Una `e2-highcpu-8` (8 GB) con 24 hilos murió por memoria (`DONE` = 137).
- `--elegibles` y `--validacion` necesitan tu `predio.parquet` local con la columna `elegible`; el deploy lo revisa antes de crear la VM.
- Verificación: la referencia 2025-26 calculada en GCP coincide exactamente con `serie_referencia.parquet` (NDVI, NDMI y píxeles válidos iguales en las 80.518 filas comunes). Las 15 escenas de más que trajo GCP tenían 42 % a 70 % de nubes y quedaban fuera con `--nubes-max 40`.

## Expediente PDF (M13)

Borrador de antecedentes para una denuncia, con las 7 secciones de la *Guía para la presentación de denuncias por infracciones al Código de Aguas* (DGA, julio de 2025) y un anexo técnico. Sigue el flujo B de [spec-flujos-poligono.md](../docs/spec-flujos-poligono.md).

```
uv run scripts/models/expediente.py --rol HIJUELAS:61-6                 # caso base FO-0504-95, ~15–25 s con imágenes
uv run scripts/models/expediente.py --predio-id 5344181 --sin-imagenes   # ~3 s, sin leer Sentinel-2
uv run scripts/models/expediente.py --rol CABILDO:390-80 --temporada 2025-26
```

- Secciones: 1 denunciante y 2 representante vacíos; 3 ubicación pre-llenada (provincia, comuna, cauce y canal más cercanos de `predio_cauce`, coordenadas y croquis con POI de M10 sobre la foto de Esri World Imagery Wayback, con su fecha de captura y atribución; `--fondo sentinel2` o `ninguno` para cambiarla); 4 hechos en borrador, redactado con M3, M4, D5, D7 y D6; 5 afectación vacía con preguntas guía (requisito de admisibilidad); 6 adjuntos; 7 declaración y firma vacía; cómo presentarla (Oficina Virtual o presencial, plazo de 5 días hábiles).
- Anexo técnico: A1 POI, A2 series NDVI y NDMI frente al secano con ventanas secas y señal, A3 imágenes de la primera y la última temporada, A4 consumo en rango y derechos por temporada, A5 calidad y limitaciones, A6 archivos usados con su commit.
- Busca el predio en las salidas de M2 a M4 en este orden: `_elegibles_2025-26`, `_validacion` y la muestra. Sirve para cualquier predio que esté en alguna de ellas.
- Lenguaje: "indicios" y "eventual infracción"; los m³ van en rango y redondeados a 2 cifras. Si el predio no tiene señal de riego, el borrador no pide fiscalizar. Con confianza baja, la primera página lo advierte. Si hay un canal a 300 m o menos, el texto lo menciona como posible fuente.
- Índice de sospecha (M5): el resumen muestra banda, puntaje, puesto en la zona (solo con `puntaje.parquet`, los elegibles 2025-26; en otras temporadas usa `puntaje_validacion.parquet` sin puesto) y la confianza de M5 junto a la de M3. Los hechos agregan el agua sin derecho que la respalde (exceso de M5, con pérdidas de riego). La alerta de la primera página sale si M3 o M5 tienen confianza baja.
- Pendiente: endpoint `POST /expediente/{id}`, versión post-visita (fotos del retorno de campo, M15) y campo "sector" (no está en las fuentes).

## Corrida nacional (todo Chile)

Extensión de M1 a M5 a las 14 regiones con capa de predios CIREN ([docs/spec-chile.md](../docs/spec-chile.md); el código y los comandos de cada etapa están en [scripts/cloud/chile/README.md](../scripts/cloud/chile/README.md)). Lo que cambia para el trabajo local:

- `scripts/comun/rutas.py` define `DATA` desde `CAUDAL_DATA` y las zonas desde `CAUDAL_ZONAS`. Sin variables, todo queda como antes (`data/` y `data/zonas.json`), así que los comandos de arriba no cambian.
- [`regiones.json`](regiones.json): mismo esquema que `zonas.json`, con `zona` = código de región (`R05`) y las capas de cada fuente. Lo genera `uv run scripts/cloud/chile/regiones.py` (consulta CIREN); va a git.
- Los extractores aceptan una zona de `regiones.json` (con `CAUDAL_ZONAS=data/regiones.json` y una sola región): `predios_ciren.py` baja la capa regional completa paginando por `objectid`; `referencia_secano_conaf.py` consulta la región entera (campo de uso según la capa, `ref_id` = región × 10⁸ + `objectid`); `cultivos_ciren.py`, `derechos_dga.py` y `fiscalizaciones_dga.py` usan la capa, el Excel y el bbox de la región. Cada uno corre en una carpeta de trabajo propia (`CAUDAL_DATA=/tmp/trabajo/R05`).
- Clima: `uv run scripts/extract/d2_clima_era5land.py` (ERA5-Land ARCO de ECMWF; necesita `CDS_API_KEY`) escribe `clima.parquet` y `predio_clima.parquet` con `fuente = era5land`, sin corrección de estaciones (`correccion = ninguna`: M1 va con `--umbral-mm 2`). `--probar` verifica la ET0 de FAO-56 sin red y `--contrastar` la compara con la de Open-Meteo. M1 y M4 aceptan las dos fuentes.
- Satélite: `serie_sentinel2.py --parte K` lee `plan/partes/K.jsonl`; ver el docstring del script. Con `data/processed/serie_predio_elegibles_2025-26.parquet` de Z1, el modo coincide en 3.037 de 3.037 predios de una escena (diferencia máxima 2·10⁻⁸).
- Exportación web: `frontend-demo/scripts/build_m5_web.py --region R05 --salida <carpeta>`.

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
