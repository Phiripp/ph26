# Caudal — Spec técnico v2 (satélite + clima)

Nov 21, 2026 · @gabi

## Resumen y alcance

Caudal v2 decide qué predios fiscalizar primero combinando imágenes satelitales y datos de estaciones meteorológicas. Su salida principal es una ruta de inspección, junto con el ranking y un expediente de evidencia.

- Qué cambia respecto a v1: se incorporan estaciones y humedad directa, y la salida principal pasa a ser una ruta de inspección. Se mantiene el modelo FAO-56 y el cruce con derechos de agua.
- Principio: el sistema prioriza, no acusa. Los m³ son un indicio para ordenar visitas, no una prueba.
- Dentro del alcance: un valle, un ranking, una ficha por predio, un expediente generado en vivo y una ruta de visita.
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
| Predios y derechos DGA | Polígonos y derechos registrados | Unidad de análisis y cruce | MVP |
| Sentinel-1 | Retrodispersión VV y VH, 10 m | Señal de humedad que atraviesa nubes | Opcional |
| Landsat 8 y 9 (térmico) | Temperatura superficial | Predio más frío que sus vecinos en día seco | Opcional |

Features por predio y fecha: `ndvi`, `ndwi`, `ndmi`, `nubosidad_pct`, `dias_sin_lluvia`, `et0_mm`, `z_verdor` y `z_humedad` (anomalía frente a la referencia).

- Ventana seca: periodo con N o más días sin lluvia efectiva según estaciones. N es un parámetro; se parte en 10 y se calibra.
- Referencia: polígonos de secano cercanos o la propia historia del predio en años secos. Sin referencia, no se calcula la anomalía y el predio queda con confianza baja.
- Estaciones: la cobertura en valles como Petorca o La Ligua suele ser rala. La grilla de Open-Meteo es la base y las estaciones la corrigen donde existan. Qué estaciones hay y si tienen API está por verificar en las primeras horas.
- Humedad directa: SMAP y SMOS son demasiado gruesos (9 a 36 km) y solo sirven de contexto regional.

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
| predio | id, geometría, área en hectáreas |
| serie\_predio | predio\_id, fecha, ndvi, ndwi, ndmi, nubosidad\_pct, escena\_id |
| clima | estación o celda, fecha, lluvia\_mm, et0\_mm |
| derecho | id, predio\_id, caudal autorizado (unidad según el registro DGA; normalizar a m³ por mes) |
| puntaje | predio\_id, fecha\_corte, m3\_estimado (rango), m3\_derecho, índice, banda, confianza |
| expediente | id, predio\_id, url\_pdf, fecha\_creación |

Endpoints mínimos:

- `GET /predios/ranking`
- `GET /predios/{id}`
- `POST /expediente/{id}`
- `GET /ruta`

## Plan y prioridades

Se trabaja por bloques en este orden; hay que ajustarlos a las horas reales que queden, que este spec no asume. Lo indispensable llega de punta a punta, aunque sea feo, antes de agregar nada opcional.

1. Zona y verificaciones: elegir el valle, confirmar escenas sin nubes, derechos descargables, polígonos de predios y qué estaciones existen.
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

## Demo, riesgos y preguntas abiertas

Guion de demo (3 minutos), con la ruta de inspección como cierre:

1. El problema en una frase y una imagen: un camión aljibe frente a un predio verde.
2. El mapa del valle con el ranking de predios sospechosos.
3. La serie satelital del mismo predio con la ventana seca marcada por las estaciones.
4. Los m³ estimados frente a los derechos, en banda y con su confianza.
5. Botón "generar expediente" en vivo y, como cierre, la ruta de inspección de los predios top, que es la decisión central.

| Riesgo | Mitigación |
| --- | --- |
| El jurado no considera el satélite como contacto directo | La ruta de inspección es la decisión física central; la entrada real son las imágenes satelitales y el clima; preguntar al mentor o a la organización |
| Falsos positivos que acusen a inocentes | Bandas y rangos, no cifras únicas; el sistema prioriza, no acusa |
| Derechos de la DGA no vinculables a predios | Cruzar por titular o usar un subconjunto verificado a mano |
| Pocas estaciones en la zona | Grilla de Open-Meteo como base y estaciones como corrección |
| Nubes o escenas faltantes | Composiciones mensuales; cambiar de zona temprano |
| Falla en vivo | Demo en producción desde temprano y video de respaldo |

Preguntas abiertas:

- [ ] ¿Las imágenes satelitales cuentan como señal física para el track? Preguntar al mentor o a la organización.
- [ ] Zona final del caso de demo.
- [ ] ¿Hay dron y operador disponibles, o el plan de vuelo queda fuera?
- [ ] Valor inicial de N días para la ventana seca y umbrales de anomalía.
- [ ] Qué estaciones existen en la zona y si tienen API.
- [ ] Disponibilidad de polígonos de predios y de derechos descargables.
