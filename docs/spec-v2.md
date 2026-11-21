# Caudal — Spec técnico v2 (satélite + clima)

Nov 21, 2026 · @gabi · Zonas, fuentes verificadas y convenciones de datos: Nov 21, 2026 · @Tomas

Seguimiento de tareas de datos y modelos: [tareas-datos-modelos.md](tareas-datos-modelos.md).

## Resumen y alcance

Caudal v2 decide qué predios fiscalizar primero combinando imágenes satelitales y datos de estaciones meteorológicas. Su salida principal es una ruta de inspección, junto con el ranking y un expediente de evidencia.

- Qué cambia respecto a v1: se incorporan estaciones y humedad directa, y la salida principal pasa a ser una ruta de inspección. Se mantiene el modelo FAO-56 y el cruce con derechos de agua.
- Principio: el sistema prioriza, no acusa. Los m³ son un indicio para ordenar visitas, no una prueba.
- Dentro del alcance: dos zonas de la Región de Valparaíso (Z1 Petorca para la demo y Z2 Aconcagua bajo para validar; ver [Zonas de estudio](#zonas-de-estudio)), un ranking por zona, una ficha por predio, un expediente generado en vivo y una ruta de visita.
- Fuera del alcance: modelo entrenado de detección de tranques (se usan índices espectrales con umbral), presentar la denuncia de forma automática (la presenta una persona con Clave Única), m³ exactos, un segundo caso de uso y construir un sensor o dispositivo propio.

## Encaje con el track Physical World

El track exige contacto directo: la entrada debe ser una señal física (cámara, GPS, audio, sensor) o la salida debe ser una orden a algo físico. Caudal v2 cumple por la decisión física que entrega (la ruta de inspección) y por sus entradas reales (imágenes satelitales y datos de clima).

| Requisito del track | Cómo lo cumple Caudal v2 |
| --- | --- |
| Entrada física real | Imágenes satelitales (Sentinel-2) y datos de clima de estaciones reales (el track acepta datos reales grabados); el clima aporta lluvia y ET0 para la ventana seca |
| Decisión física que hoy se toma a ojo | Qué predios visitar y en qué orden, entregado como ruta de inspección; es la salida principal del sistema |
| Salida a algo físico | Opcional: plan de vuelo para un dron, solo si hay dron y operador |
| No calificar como Simulations | Ninguna señal es inventada; las imágenes satelitales y el clima son datos reales |
| No calificar como Hardware | No se arma ningún dispositivo; se usan datos satelitales y de estaciones que ya existen |

Riesgo abierto: no está confirmado que el jurado considere las imágenes satelitales como contacto directo. Por eso la ruta de inspección es la salida principal del sistema y conviene preguntarlo al mentor o a la organización. Fuente: descripción del track compartida por el equipo.

## Zonas de estudio

Las zonas se definen en esta sección y en ningún otro lugar. Toda extracción de datos usa estas zonas. Para cambiar una zona, se edita esta tabla y se avisa al equipo.

| Zona | Comunas | Bounding box WGS84 (lon mín, lat mín, lon máx, lat máx) | Uso | Predios CIREN | Derechos DGA | Fiscalizaciones por extracción de aguas (positivas) |
| --- | --- | --- | --- | --- | --- | --- |
| Z1 Petorca | Petorca, Cabildo, La Ligua, Papudo, Zapallar | -71.5421, -32.7328, -70.4104, -32.0200 | Demo principal: sequía y camiones aljibe | 9.331 | 6.104 | 345 (46) |
| Z2 Aconcagua bajo | Hijuelas, La Cruz, Quillota, Nogales, La Calera | -71.5008, -32.9905, -70.9708, -32.5897 | Validación con casos sancionados y segunda demo | 10.719 | 3.034 | 152 (33) |

- Universo elegible: predios con rol válido y 1 ha o más (columna `elegible` en `predio.parquet`). Son 7.911 predios (4.272 en Z1 y 3.639 en Z2). Todo el análisis satelital, el ranking y la ruta usan solo predios elegibles. Motivo: de las 428 fiscalizaciones por extracción no autorizada de aguas ubicadas a 50 m o menos de un predio de Z1 y Z2 (`data/processed/fiscalizacion.parquet`), las 67 positivas caen en predios de 9,6 ha en mediana (el predio típico de la capa mide 0,7 ha), y los predios de 1 ha o más cubren el 93 % de los positivos. Los de menos de 1 ha son el 57 % de la capa: parcelas residenciales y lotes de pozo, con 100 píxeles o menos.

  | Tamaño | Todos los predios | Positivos |
  | --- | --- | --- |
  | Menos de 1 ha | 57 % | 7 % |
  | 1 a 5 ha | 25 % | 25 % |
  | 5 a 20 ha | 12 % | 31 % |
  | 20 a 100 ha | 4 % | 22 % |
  | Más de 100 ha | 2 % | 13 % |

- El 73 % de los predios con infracción tiene derechos inscritos: la infracción típica es extraer más de lo autorizado o usar un pozo no inscrito, no regar sin ningún derecho. Por eso el índice (M5) mide el exceso del consumo estimado sobre los derechos propios y del entorno, y no usa "tiene o no tiene derechos" como señal. Entre los fiscalizados, la tasa de infracción es parecida con derechos (15 % de 325) y con derechos cerca de otro predio (17 % de 89); sin derechos cerca hay solo 6 fiscalizaciones (3 positivas): el estado de derechos solo no distingue al infractor.
- La pertenencia a una zona se decide por comuna, no por bounding box. Los bounding boxes se solapan entre las latitudes -32.73 y -32.59. El bounding box es la extensión de los predios CIREN de esas comunas y sirve solo para filtrar descargas.
- Los bounding boxes incluyen cordillera y cerros. Para Sentinel-2, se recorta con las geometrías de los predios, no con el bounding box.
- Periodo de análisis: desde enero de 2020 hasta la última escena limpia antes de la demo. Mientras más reciente el dato, más fuerte la demo. Periodos prioritarios:
  - Z1: de julio de 2023 a abril de 2024 (caso de la demo FD-0501-181, temporada seca 2023-24) y de diciembre de 2024 a la última escena (casos de 2025, temporada seca 2025-26 y escena reciente).
  - Z2: 2021–2022 (antecedente satelital) y de julio de 2023 a mayo de 2025 (casos FD-0504-257 y FO-0504-157).
- Ventanas para la demo: el ranking usa la temporada seca 2025-26 (diciembre de 2025 a marzo de 2026), que es la última completa. La ficha del predio muestra además la escena limpia más reciente. Esa escena se recalcula la noche antes de la demo (tarea D13).
- Octubre de 2026 fue lluvioso: según Open-Meteo, unos 100 mm en La Ligua y unos 160 mm en Hijuelas (última lluvia fuerte: 20-10 en La Ligua y 03-11 en Hijuelas). Las escenas de noviembre de 2026 muestran todo verde y separan mal riego de secano. Por eso el ranking no usa noviembre de 2026.
- Caso de la demo: expediente FD-0501-181, Cabildo (Z1), lat -32.41082, lon -71.02377; nació de una denuncia; inspección el 02-04-2024; resolución 992 del 31-07-2024 (acoge); multa de 710,6 UTM (unos $51 millones); con recurso de reconsideración presentado. El pozo cae dentro del predio `202-35` (17,2 ha), que tiene 16,1 ha de palto y chirimoyo (Catastro Frutícola 2025) y ningún derecho propio inscrito. Relato: un vecino tuvo que denunciar; la serie del verano 2023-24 muestra riego en ventana seca en un predio sin derechos, antes de la inspección. A 8.000–10.000 m³ por hectárea al año, son unos 130.000 a 160.000 m³ al año sin derecho (rango por confirmar con M4).
- Por qué no FO-0501-462 (el caso anterior): su predio no tiene frutales en el catastro y su derecho (63.072 m³ al año en 6,1 ha) alcanza casi justo para regarlo, así que el modelo probablemente no lo marca. Queda como caso de validación.
- Riesgo del caso de la demo: hay 910.000 m³ al año de derechos de pozos vecinos a 500 m o menos. Si M5 baja la confianza solo porque el entorno tiene derechos, este caso queda en confianza baja. Los derechos del entorno solo deben bajar la confianza si superan lo que necesitan los predios donde están inscritos.
- Antecedente satelital: expediente FO-0504-95, Hijuelas (Z2), lat -32.82257, lon -71.01774; inspección el 23-11-2021; multa de 1.983,9 UTM (unos $127 millones); la DGA dice que lo detectó con imágenes satelitales ([nota de la DGA](https://dga.mop.gob.cl/dga-valparaiso-multa-a-empresario-agricola-por-extraccion-no-autorizada-de-aguas-en-la-comuna-de-hijuelas/)).
- Otros casos de validación: FD-0504-257 (La Cruz, 2024: 8,2 ha de palto sin derechos propios, multa de 1.144 UTM), FO-0501-462 (La Ligua, 2025), FO-0504-157 (Hijuelas, 2025), FD-0501-191 y FD-0501-189 (Cabildo, 2025), FO-0501-376 y FO-0501-386 (Pullally, 2022) y FO-0501-380 (Cabildo, 2022). Todos están en [data/casos_validacion.geojson](../data/casos_validacion.geojson).
- Solo se usan casos resueltos. Los expedientes "En trámite" no se muestran como infractores en la demo.
- Los conteos vienen de las fuentes del 21-11-2026. Las fiscalizaciones son las de `data/processed/fiscalizacion.parquet` (D6): solo extracción no autorizada de aguas; la zona sale del predio a 50 m o menos del punto o, si no hay, de la comuna declarada.

## Flujo de datos

&#91;embedded content: flujo de datos · 3 entradas, 1 detector, 2 salidas\]

El satélite y las estaciones alimentan el detector; el índice los cruza con los derechos, y las salidas son una ruta que recorre un inspector y un expediente que presenta una persona.

## Satélite, estaciones y humedad directa

El núcleo usa Sentinel-2 y estaciones meteorológicas; el radar y el térmico quedan como extras. La humedad que se mide es un proxy relativo (anomalía frente a una referencia), no un valor absoluto de suelo a escala de predio.

| Fuente | Producto | Uso | Prioridad |
| --- | --- | --- | --- |
| Sentinel-2 L2A (STAC) | NDVI, NDWI y NDMI (SWIR, B8A y B11), máscara de nubes SCL, 10 a 20 m | Verdor, tranques y humedad por predio | MVP |
| Estaciones DMC, DGA e INIA Agromet | Lluvia diaria, temperatura, humedad relativa, viento y radiación cuando existan | Ventana seca y ET0 local | MVP, sujeto a cobertura en la zona |
| Open-Meteo | ET0 y lluvia histórica en grilla | Base y relleno donde no hay estación | MVP |
| Predios CIREN y derechos DGA | Polígonos y derechos registrados (ver [Fuentes de datos verificadas](#fuentes-de-datos-verificadas)) | Unidad de análisis y cruce | MVP |
| Sentinel-1 | Retrodispersión VV y VH, 10 m | Señal de humedad que atraviesa nubes | Opcional |
| Landsat 8 y 9 (térmico) | Temperatura superficial | Predio más frío que sus vecinos en día seco | Opcional |

Features por predio y fecha: `ndvi`, `ndwi`, `ndmi`, `nubosidad_pct`, `dias_sin_lluvia`, `et0_mm`, `z_verdor` y `z_humedad` (anomalía frente a la referencia).

- Ventana seca: periodo con N o más días sin lluvia efectiva según estaciones. N es un parámetro; se parte en 10 y se calibra.
- Referencia: polígonos de secano cercanos o la propia historia del predio en años secos. Sin referencia, no se calcula la anomalía y el predio queda con confianza baja.
- Estaciones: la cobertura en valles como Petorca o La Ligua suele ser rala. La grilla de Open-Meteo es la base y las estaciones la corrigen donde existan. Qué estaciones hay y si tienen API está por verificar en las primeras horas.
- Humedad directa: SMAP y SMOS son demasiado gruesos (9 a 36 km) y solo sirven de contexto regional.

## Fuentes de datos verificadas

Las fuentes de esta tabla se probaron el 21-11-2026 con una consulta o una descarga real. Todas son públicas y no piden login.

| Dato | Fuente y acceso | Formato | Llave | Notas |
| --- | --- | --- | --- | --- |
| Polígonos de predios | CIREN Propiedades Rurales 2022, ArcGIS REST: `https://esri.ciren.cl/server/rest/services/IDEMINAGRI/PROPIEDADES_RURALES/MapServer/4/query` | GeoJSON (`f=geojson`), hasta 10.000 por consulta | `rol` | No trae propietario ni superficie; la superficie se calcula en EPSG:32719. No se encontraron términos de uso: citar "CIREN 2022 vía IDE Minagri" y no redistribuir la capa completa |
| Derechos de agua | DGA, [derechos registrados](https://dga.mop.gob.cl/derechos-de-agua/derechos-registrados/): un `.xls` por región, actualización mensual | Excel, encabezados en la fila 7 | Coordenada de captación | Datums mixtos (PSAD56, SAD69, WGS84, vacío); 99 % en l/s; sin RUT; trae nombres de titulares |
| Fiscalizaciones | DGA, [planilla de seguimiento de fiscalización](https://dga.mop.gob.cl/tramites/denunciar/fiscalizacion/), actualización mensual | Excel, hoja "Planilla" | Código de expediente | Coordenadas UTM del acta de terreno (pozo o captación, no el predio); el campo "Comuna" a veces está mal; sin nombres |
| Especie plantada | CIREN Catastro Frutícola 2025, capa 59: `https://esri.ciren.cl/server/rest/services/IDEMINAGRI/CATASTRO_FRUTICOLA/MapServer/59` | GeoJSON, hasta 2.000 por consulta | `rol` | Especies 1 a 4; sin superficie ni tipo de riego; sirve para el Kc |
| Cauces | DGA, red de drenajes en el servidor de la SMA: `https://ideserver.sma.gob.cl/arcgis/rest/services/IDE/Recursos_hidricos_glaciares/MapServer/2` | Esri JSON (`f=json`; GeoJSON no funciona) | Geometría | Respaldo: Red_Hidrografica.zip de la BCN u OSM `waterway` |
| Canales de riego | CNR y CIREN: `https://esri.ciren.cl/server/rest/services/IDEMINAGRI/INFRAESTRUCTURA_RIEGO/MapServer/0` | GeoJSON | Geometría | Opcional, para el expediente |
| Zonas de prohibición y restricción | Servicios de la DGA en `https://rest-sit.mop.gob.cl/arcgis/rest/services/DGA/` (capa `Areas_de_Restriccion_y_Zonas_de_Prohibicion`) | Esri JSON | `COD_SHAC` | Todos los sectores de Z1 y Nogales-Hijuelas son zona de prohibición. Hoy no hay decreto de escasez vigente en Z1 (el último caducó el 13-08-2024) |
| Referencia de secano | CONAF, uso de la tierra 2001–2019, en IDE Minagri (servicio `USO_DE_LA_TIERRA_CUT_CONAF`, capa 5) | GeoJSON | Geometría | No separa riego de secano; se usan los polígonos de matorral y pradera |
| Red vial | OpenStreetMap con osmnx (`network_type="drive"`); respaldo offline: Geofabrik `chile-latest.osm.pbf` | GraphML | Nodo más cercano | El 49 % de los caminos no tiene superficie; usar 25 km/h en `track` |
| APR (opcional) | DOH, en el servidor IDE de la SMA | Puntos | — | Dato de enero de 2017; solo para el pitch |

No hay fuente pública para: propietario del predio, camiones aljibe por comuna en formato abierto y una capa que separe riego de secano.

## Convenciones de datos

Estas reglas permiten que cada persona extraiga datos por su cuenta y que todo se pueda unir después.

- CRS de trabajo: EPSG:32719 (UTM 19S) para calcular áreas y distancias. Los archivos se guardan en EPSG:4326.
- Datums de los derechos: cada fila se convierte según su columna "Datum": 1956 → EPSG:24879, 1969 → EPSG:29189 y 1984 → EPSG:32719. Si el datum viene vacío o es desconocido, se usa EPSG:24879 y la fila queda con `coord_estado = datum_supuesto`. Si el punto cae fuera de la región, se prueba el otro huso (`huso_corregido`); si sigue fuera, queda sin punto (`fuera_de_region`). Una coordenada "0" significa que no hay punto (`sin_coordenada`).
- Unidades de los derechos: se calcula el volumen anual con las columnas de cada mes y los días reales del mes, y `m3_mes` = `m3_anual` / 12 (1 l/s ≈ 2.628 m³ por mes). Los m³/año, m³/día, m³/h, m³/min, m³/s y l/min se convierten. Las "Acciones" y los "%" quedan sin cifra. `sumable` = consuntivo, no eventual y con cifra; solo los sumables cuentan como derecho del predio.
- Cruce de derechos con predios: el punto de captación dentro del predio, o en un radio de 500 m. Si falla, por nombre del titular dentro de la comuna. Cada cruce guarda `metodo_cruce` y `confianza_cruce`. Los derechos de 100 l/s o más (`gran_derecho`: 37 filas, el 37 % del volumen) son casi siempre canales o comunidades de aguas y no se asignan a un predio por coordenada sin revisión.
- Llaves: `predio_id` = `mslink` de CIREN, que es único en la capa. El `rol` no sirve como llave: se repite entre comunas y dentro de una misma comuna (un predio puede tener varios polígonos), y a veces no es un rol (`SR`, ríos, caminos). Se guarda como atributo para cruzar con el catastro frutícola, junto con `rol_valido`. Toda tabla lleva `zona` (`Z1` o `Z2`). Detalle de columnas en [data/README.md](../data/README.md).
- Carpetas: `scripts/extract/` para los scripts de descarga, uno por fuente; `data/raw/` para lo descargado; `data/processed/` para las salidas en GeoParquet o Parquet, una tabla por entidad del modelo de datos y con la columna `zona`.
- Git: `data/raw/` no se sube. Los nombres de titulares de derechos y otros datos personales tampoco se suben; el expediente los lee del archivo local. Lo que se sube son los scripts, que deben poder regenerar todo.
- Antes de extraer algo nuevo, se registra la tarea en [tareas-datos-modelos.md](tareas-datos-modelos.md) para no duplicar trabajo.

## Fusión y detector de riego

La señal que distingue riego de lluvia es humedad o verdor altos durante una ventana seca. El clima de las estaciones define esa ventana.

1. Por predio y ventana seca, se calcula la anomalía de verdor y de humedad frente a la referencia.
2. La señal satelital de riego es positiva cuando ambas anomalías superan su umbral dentro de la ventana (umbrales por calibrar con el caso sancionado).
3. Se estima el consumo con la ruta base de v1 y se compara con los derechos.

```latex
V_{\text{riego}} = \sum_{\text{mes}} \max\big(0,\; K_c(\text{NDVI}) \cdot ET_0 - P_{\text{ef}}\big) \cdot A
```

| Señal satelital y de clima | Resultado |
| --- | --- |
| Riego probable en ventana seca y consumo estimado sobre los derechos | Prioridad alta |
| Riego probable en ventana seca y consumo estimado dentro de los derechos | Prioridad baja |
| Sin señal de riego | Sin alerta |

Índice de sospecha = exceso de consumo sobre derechos, ponderado por una confianza que baja con nubosidad, con predios de pocos píxeles, con pocas escenas válidas y sin referencia, y sube cuando las rutas de estimación coinciden. Los pesos se fijan al calibrar. El ranking se muestra en bandas (alta, media, baja) junto con el rango de m³ estimado, nunca como una cifra única.

## Expediente y ruta de inspección

El expediente se arma sobre los campos que pide la Guía para la presentación de denuncias por infracciones al Código de Aguas (actualizada a julio de 2025). Caudal pre-llena lo que puede y deja el resto a la persona que denuncia.

| Campo de la guía de la DGA | Qué aporta Caudal | Quién lo completa |
| --- | --- | --- |
| Individualización del denunciante (nombre o razón social, RUN o RUT, comuna y región, correo o teléfono, copia de la cédula) | Nada | La persona, con Clave Única |
| Representante legal o apoderado, si corresponde | Nada | La persona |
| Ubicación y referencias (provincia, comuna, sector, cauce, croquis) | Mapa del predio con su polígono y coordenadas; cauce cercano si hay dato (por verificar) | Caudal pre-llena, la persona revisa |
| Descripción breve de hechos y fecha | Borrador: ventana seca detectada, señales observadas y fechas | Caudal redacta, la persona edita y firma |
| Adjuntos opcionales (fotografías, croquis, respaldos) | Series de NDVI y NDMI, imágenes antes y después, cálculo de m³ y derechos consultados | Caudal genera el anexo |

La guía dice que la DGA declara admisible una denuncia cuando la presenta un interesado que expone cómo se configura el perjuicio a la fuente o la afectación a sus derechos o a los de terceros. Por eso el expediente incluye un espacio para que el denunciante describa su propia afectación; Caudal no puede redactarlo por él. La presentación se hace por la Oficina Virtual (SNIA, con Clave Única) o de forma presencial con el formulario firmado. Caudal no presenta nada.

Ruta de inspección (la salida principal y la decisión física del sistema):

- Entrada: los N predios mejor rankeados, un punto de partida y la hora de inicio.
- Proceso: orden de visita que minimiza el recorrido, resuelto con OR-Tools.
- Salida: lista ordenada con mapa, descargable como GPX o enlace de navegación.
- Opcional, solo si hay dron y operador: plan de vuelo sobre los predios top. Sin hardware disponible, queda fuera.

## Arquitectura, stack y modelo de datos

Regla clave: todo lo satelital se precalcula; la demo en vivo solo consulta resultados, genera el expediente y la ruta.

- Datos: Python con `pystac-client`, `stackstac` o `rioxarray` y `geopandas`; resultados precalculados en Parquet o GeoJSON.
- Backend: FastAPI, que sirve los resultados precalculados.
- Ruta: OR-Tools.
- Frontend: mapa con MapLibre o Leaflet para ranking y ficha por predio.
- Expediente: generación de PDF a partir de plantilla.
- Despliegue: en producción desde temprano, porque la demo se presenta en producción.

Modelo de datos:

| Entidad | Campos clave |
| --- | --- |
| predio | predio\_id (`mslink` de CIREN), zona, comuna, rol, rol\_valido, geometría, área en hectáreas, elegible; la especie va en `predio_cultivo` (catastro frutícola, si existe) |
| serie\_predio | predio\_id, fecha, ndvi, ndwi, ndmi, nubosidad\_pct, escena\_id |
| clima | estación o celda, fecha, lluvia\_mm, et0\_mm |
| derecho | derecho\_id, expediente DGA, zona, naturaleza (superficial o subterránea), ejercicio, caudal\_ls, m3\_anual, m3\_mes, sumable, gran\_derecho, coord\_estado, punto de captación |
| derecho\_predio | derecho\_id, predio\_id, metodo\_cruce, confianza\_cruce, dist\_predio\_m |
| predio\_derecho | predio\_id, m3\_anual\_derecho, m3\_mes\_derecho, m3\_anual\_derecho\_entorno\_500m, estado\_derechos, confianza\_cruce (detalle en [data/README.md](../data/README.md)) |
| fiscalizacion | expediente, zona, zona\_origen, predio\_id, predio\_elegible, geometría (punto), fechas de inspección y resolución, tipo de infracción, extraccion, decisión, multa en UTM, etiqueta (positivo, negativo, en\_tramite u otro) |
| puntaje | predio\_id, fecha\_corte, m3\_estimado (rango), m3\_derecho, índice, banda, confianza |
| expediente | id, predio\_id, url\_pdf, fecha\_creación |

Endpoints mínimos:

- `GET /predios/ranking`
- `GET /predios/{id}`
- `POST /expediente/{id}`
- `GET /ruta`

## Plan y prioridades

Se trabaja por bloques en este orden; hay que ajustarlos a las horas reales que queden, que este spec no asume. Lo indispensable llega de punta a punta, aunque sea feo, antes de agregar nada opcional.

1. Zona y verificaciones: zonas definidas (Z1 y Z2) y fuentes de predios, derechos y fiscalizaciones verificadas. Falta confirmar escenas sin nubes y qué estaciones existen.
2. Pipeline base: series de NDVI y NDMI por predio, clima y ventana seca, con datos reales.
3. Detector, índice y ranking: m³ estimados contra derechos, bandas y confianza; validar con un caso sancionado.
4. Ruta de inspección: predios top en orden de visita con OR-Tools, y mapa de la ruta.
5. Expediente: PDF con los campos de la guía de la DGA y adjuntos.
6. Producción, demo congelada, guion y video de respaldo; después de congelar, solo arreglos menores.

| Componente | Indispensable | Opcional si sobra tiempo |
| --- | --- | --- |
| Datos satelitales | NDVI y NDMI mensuales por predio, 2 a 3 años | NDWI para tranques nuevos, Sentinel-1, térmico |
| Clima | Open-Meteo y estaciones donde existan | Calibración de ET0 con estaciones |
| Modelo hídrico y cruce | FAO-56 simplificado, Índice de sospecha en bandas | Calibración con caso sancionado, incertidumbre por predio |
| Expediente | PDF con campos de la guía y adjuntos | Borrador con la afectación del denunciante |
| Decisión física | Ruta de inspección | Plan de vuelo para dron |

## Métricas de impacto

La métrica responde dos preguntas: cuántos casos encuentra Caudal que la fiscalización no encontró, y cuánta agua y cuánto dinero representan. Un predio con señal alta que nunca fue fiscalizado es un candidato, no un caso. Por eso las cifras de candidatos se multiplican por una precisión medida y se muestran como rango.

Línea base (`data/processed/fiscalizacion.parquet`: planilla de fiscalización de la DGA, solo extracción no autorizada de aguas, sin áridos; zona por predio a 50 m o por comuna declarada; 2018 a abril de 2026):

| Dato | Valor |
| --- | --- |
| Fiscalizaciones por año | Desde 2019, entre 2 y 40 por zona (en 2018, 194 en Z1); hay 7.911 predios elegibles, así que cada año se revisa menos del 1 % |
| Tasa de acierto de la DGA (2022–2025) | 33 % (de 107 resueltas): una de cada tres fiscalizaciones constata infracción |
| Multas por extracción | 76 multas, 42.609,5 UTM en total (unos $3.087 millones) |
| Multa mediana | 575,7 UTM (unos $41,7 millones); Z1: 575,7 UTM y Z2: 535 UTM |
| Valor UTM usado | $72.440 (noviembre de 2026, mindicador.cl) |

Métricas:

1. **Adelanto de detección** (se puede probar con casos conocidos). Para cada caso positivo, se mide cuántos meses antes de la inspección de la DGA el predio entra en la banda alta. Agua evitable = suma del exceso mensual (m³ estimados menos m³ con derecho) entre la primera señal y la inspección. Ejemplo para el pitch: "Caudal marcaba el predio del caso FD-0501-181 X meses antes de que llegara la DGA; en ese tiempo se extrajeron entre A y B m³".
2. **Acierto frente a la DGA** (se puede probar, con muestra chica). De los predios fiscalizados que caen en la banda alta de Caudal, qué fracción tuvo infracción. Se compara con el 33 % de la DGA. Advertencia: los predios fiscalizados no son una muestra al azar, y en las zonas hay pocos casos.
3. **Candidatos no fiscalizados** (estimación). Predios en banda alta sin ninguna fiscalización registrada desde 2018 en un radio de 500 m. Casos esperados = candidatos × acierto de la métrica 2. Si la métrica 2 no tiene suficientes casos, se usa el 33 % de la DGA como piso conservador.
4. **Agua en juego** (estimación). Suma del exceso anual de los candidatos × acierto, en rango de m³. Se traduce a personas abastecidas en un año con la dotación por persona de los camiones aljibe (valor por verificar, tarea D14).
5. **Dinero** (estimación, dos cifras que no se suman):
   - Multas que no se cursaron = casos esperados × multa mediana de la zona × valor UTM.
   - Costo de reemplazar esa agua con camiones aljibe = m³ en juego × costo por m³ de camión aljibe (valor por verificar, tarea D14).

Reglas para mostrar las métricas:

- Siempre en rango (mínimo y máximo), con el supuesto de acierto a la vista.
- En el pitch se dice "predios con señal alta que nunca fueron fiscalizados", no "infractores" ni "casos encontrados".
- Los candidatos no se identifican en la demo pública: se muestran como conteo y en un mapa agregado, sin rol ni ubicación exacta.

## Demo, riesgos y preguntas abiertas

Guion de demo (3 minutos), con la ruta de inspección como cierre:

1. El problema en una frase y una imagen: un camión aljibe frente a un predio verde.
2. El mapa del valle con el ranking de predios sospechosos.
3. La serie satelital del predio del caso FD-0501-181 (16 ha de palto sin derechos propios) con la ventana seca marcada por las estaciones: el riego aparece antes de que llegue la DGA. Cierra con la escena más reciente del mismo predio.
4. Los m³ estimados frente a los derechos, en banda y con su confianza.
5. Botón "generar expediente" en vivo y, como cierre, la ruta de inspección de los predios top, que es la decisión central.
6. Cifra de impacto en una frase: adelanto de detección en el caso real, y candidatos no fiscalizados con su rango de m³ y de pesos (ver [Métricas de impacto](#métricas-de-impacto)).

| Riesgo | Mitigación |
| --- | --- |
| El jurado no considera el satélite como contacto directo | La ruta de inspección es la decisión física central; la entrada real son las imágenes satelitales y el clima; preguntar al mentor o a la organización |
| Falsos positivos que acusen a inocentes | Bandas y rangos, no cifras únicas; el sistema prioriza, no acusa |
| Derechos de la DGA no vinculables a predios | Cruce por coordenada de captación con radio de 500 m; luego por titular; si no, un subconjunto verificado a mano |
| El pozo está fuera del predio que riega | Radio de búsqueda y `confianza_cruce` baja; revisar a mano los predios top |
| Se cae un servicio de CIREN o de la DGA durante la demo | Descargar todo apenas se acuerdan las zonas y servir copias locales |
| Datos personales en el repo | Los nombres de titulares quedan fuera de git (ver [Convenciones de datos](#convenciones-de-datos)) |
| Pocas estaciones en la zona | Grilla de Open-Meteo como base y estaciones como corrección |
| Nubes o escenas faltantes | Composiciones mensuales; cambiar de zona temprano |
| Las lluvias de octubre de 2026 dejan todo verde y la escena reciente no muestra contraste | El ranking usa la temporada seca 2025-26; la escena reciente es solo contexto visual en la ficha |
| Falla en vivo | Demo en producción desde temprano y video de respaldo |

Preguntas abiertas:

- [ ] ¿Las imágenes satelitales cuentan como señal física para el track? Preguntar al mentor o a la organización.
- [x] Zona final del caso de demo: Z1 Petorca para la demo y Z2 Aconcagua bajo para validar (ver [Zonas de estudio](#zonas-de-estudio)).
- [ ] ¿Hay dron y operador disponibles, o el plan de vuelo queda fuera?
- [ ] Valor inicial de N días para la ventana seca y umbrales de anomalía.
- [ ] Qué estaciones existen en Z1 y Z2 y si tienen API.
- [x] Disponibilidad de polígonos de predios y de derechos descargables: sí, CIREN y DGA (ver [Fuentes de datos verificadas](#fuentes-de-datos-verificadas)).
- [ ] ¿Se puede usar y mostrar la capa de CIREN en una demo pública? No se encontraron términos de uso.
