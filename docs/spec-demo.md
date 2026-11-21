# Caudal — Spec de frontend y backend para la demo

Nov 21, 2026 · @Tomas

Este documento dice qué debe mostrar la plataforma para sostener el guion de [pitch-demo.md](pitch-demo.md), qué datos necesita cada pantalla y qué falta decidir. No repite el spec del producto ([spec-v2.md](spec-v2.md)) ni el de los flujos por polígono ([spec-flujos-poligono.md](spec-flujos-poligono.md)).

La presentación es el domingo 22 en la mañana. Solo es obligatorio lo marcado P0.

**Qué decide este documento y qué no.** Define el contenido de cada pantalla y el contrato de datos (qué campos, con qué significado). **No decide dónde ni cómo se guardan los datos**: eso lo deciden Nico y Felipe (ver [Decisiones de almacenamiento](#decisiones-de-almacenamiento-nico-y-felipe)).

## Qué debe poder mostrar la demo

Cinco pantallas, en este orden, todas en producción y con datos reales:

| Paso | Pantalla | Dato que la alimenta | Estado hoy |
| --- | --- | --- | --- |
| 1 | Zona Z2 con los predios por banda | `puntaje.parquet` (M5) | El frontend muestra 50 predios por zona con una banda provisional propia |
| 2 | Caso FO-0504-95: serie, banda por temporada y antes/después | `puntaje_validacion.parquet`, `anomalias_predio_validacion.parquet` | Existe la ficha del caso; falta la banda por temporada y el adelanto |
| 3 | Candidato `5301984`: por qué está en alerta | `puntaje.parquet`, `anomalias_predio_elegibles_2025-26.parquet`, `poi.parquet` | La ficha existe con datos provisionales y sin explicación |
| 4 | Expediente PDF generado en vivo | `scripts/models/expediente.py` (M13) | El frontend baja un `.txt` armado en el navegador; el PDF solo se genera por línea de comandos |
| 5 | Ruta del día y panel de impacto | `ruta_z2.json` (M8), `impacto.json` (M9) | La ruta del frontend es provisional; el panel de impacto no existe |

## Principios

- **Nada simulado ni escrito a mano.** Cada cifra en pantalla sale de un archivo de `data/processed/` que genera un script del repo. El jurado tendrá un agente leyendo el repo: un número pegado en el código del frontend se nota.
- **Transparente, sin abrumar.** Cada alerta dice por qué existe, con su fuente y con lo que no sabemos. Como máximo 4 razones y 2 límites por predio; el detalle queda a un clic.
- **Honesto sobre lo que es en vivo.** Las series satelitales se precalculan; la interfaz muestra la fecha de cálculo. El expediente se genera de verdad.
- **La demo no depende de terceros.** No se llama en vivo a OSRM, CIREN ni la DGA.
- **Caudal prioriza, no acusa.** Sin nombres de dueños. En modo demo tampoco se muestra el rol. Siempre rangos de m³. Solo los casos con multa se llaman "sancionados".

## Por qué este predio está en alerta (P0)

Es la pieza central de la ficha. Responde tres preguntas, en este orden, y nada más.

**1. Qué vimos** (hasta 4 razones). Cada una es una frase con su número, su fuente y un enlace a la referencia:

| Razón | Ejemplo para el predio `5301984` | Campos de origen | Fuente que se muestra |
| --- | --- | --- | --- |
| Riego sin lluvia | "Más verde y más húmedo que el cerro vecino en 20 de 20 imágenes tomadas tras 10 días o más sin lluvia" | `frac_senal`, `n_fechas_validas`, `ndvi_mediana` y la mediana del secano (`ref_ndvi_mediana`) | Imágenes Sentinel-2 (Copernicus), con la lista de fechas y escenas; lluvia de DMC y Open-Meteo |
| Consumo | "Consume entre 105.000 y 280.000 m³ al año" | `m3_consumo_bruto_min`, `m3_consumo_bruto_max` | Método FAO-56 (FAO, 1998); enlace a la sección del método |
| Derechos | "Derechos de agua inscritos en el predio: 0 m³. De vecinos a 500 m: 0 m³" | `m3_derecho_asignado`, `m3_derecho_ajeno_disponible_500m` | Registro de derechos concedidos de la DGA, con la fecha de descarga |
| Contexto | "Canal más cercano: 1,2 km. Sin fiscalización de la DGA a 500 m desde 2018" | `dist_canal_m`, fiscalizaciones a 500 m | Canales CNR/CIREN 2020; planilla de fiscalización de la DGA |

Los valores del ejemplo son los reales del predio `5301984` en la temporada 2025-26 (`puntaje.parquet` y `senal_riego_elegibles_2025-26.parquet`).

**2. Qué tan seguros estamos.** La confianza (alta, media o baja) con su motivo en una frase. Sale de `confianza` y `motivos`:

| `motivos` | Texto en pantalla |
| --- | --- |
| `sin_derechos_propios_ubicados` | "No encontramos derechos ubicados en el predio; podría tener derechos sin coordenada en el registro" |
| `derechos_ajenos_cubren_exceso` | "Hay derechos de vecinos a 500 m que podrían cubrir el consumo" |
| `canal_300m` | "Hay un canal a menos de 300 m: puede regar con acciones de canal, que no están en el registro" |
| `predio_grande` | "Predio de más de 100 ha: la señal se diluye" |
| `pocos_pixeles` | "Predio chico: pocas mediciones por imagen" |
| `cruce_derechos_media`, `cruce_derechos_baja` | "La ubicación del derecho en el registro es incierta" |

**3. Qué no sabemos** (hasta 2 límites). Fijo para todo predio: "Caudal ve que se riega, no de dónde sale el agua. La infracción la constata un inspector".

Reglas:

- Nada de índices con nombre técnico en la primera vista (NDVI, z, percentiles). Van en "ver método", que enlaza a `data/README.md` y a [validacion.md](validacion.md).
- Las frases se generan a partir de los datos, con una sola función que usan la ficha y el expediente (`scripts/models/explicacion.py`, tarea T1). Así el PDF y la pantalla dicen lo mismo.
- El caso sancionado usa el mismo bloque, calculado con los datos previos a la inspección.

Contrato de la explicación (lo que entrega la función por predio y temporada):

```json
{
  "predio_id": 5301984, "temporada": "2025-26", "banda": "alta", "confianza": "media",
  "razones": [
    {"id": "riego_sin_lluvia", "texto": "…", "valor": {"fechas_con_senal": 20, "fechas_validas": 20},
     "fuente": "Sentinel-2 (Copernicus) · DMC · Open-Meteo", "referencia": "…", "dato_al": "2026-03-28"}
  ],
  "confianza_motivos": ["…"],
  "limites": ["…"],
  "escenas": [{"fecha": "2026-01-12", "escena_id": "S2B_19HBD_20260112_0_L2A"}],
  "calculado": "2026-11-21T14:02:00-03:00", "version_modelo": "<commit>"
}
```

## Contrato de datos

Lo que cada pantalla necesita, sin importar cómo se guarde o se transporte. Los nombres de la derecha son las columnas de `data/processed/` (documentadas en `data/README.md`).

| Recurso | Para qué pantalla | Campos | Origen |
| --- | --- | --- | --- |
| Resumen de zona | Portada y zona | Total de predios, conteo por banda | `puntaje.parquet` |
| Ranking de zona | Zona | `predio_id`, `rank_zona`, `banda`, `puntaje`, `confianza`, comuna, `area_ha`, especie; filtros por canal y por fiscalización | `puntaje.parquet`, `predio_cultivo.parquet` |
| Geometría de predios | Mapa | Polígono por `predio_id` | `predio.parquet` (no está en git: capa de CIREN) |
| Ficha del predio | Ficha | La explicación de arriba, más rangos de consumo y exceso | `puntaje.parquet`, `explicacion.py` |
| Serie del predio | Gráfico de la ficha | Por fecha: `ndvi`, `ndmi`, mediana del secano, si está en ventana seca, si hay señal, `escena_id` | `anomalias_predio_*.parquet` |
| Puntos a revisar | Ficha y ruta | Hasta 8 por predio: tipo, coordenada, razón, confianza | `poi.parquet` |
| Historial del caso | Ficha del caso | Por temporada: banda, puntaje, exceso; fecha de inspección, multa, primera alerta y años de adelanto | `puntaje_validacion.parquet`, `fiscalizacion.parquet`, `impacto.py` |
| Imágenes del predio | Ficha y caso | Recortes satelitales por fecha, con escena y fecha | Hoy: `frontend-demo/assets/casos/` y las figuras de `expediente.py` |
| Ruta | Pestaña Ruta | Paradas con horas, km, punto de acceso, enlace de navegación; GPX | `ruta_z1.json`, `ruta_z2.json` |
| Impacto | Panel de impacto | Candidatos, lift, escenarios, capacidad, equivalencias con su fuente | `impacto.json` |
| Expediente | Botón de la ficha | PDF e identificador | `expediente.py` |

## Decisiones de almacenamiento (Nico y Felipe)

Estas decisiones son de ustedes. Abajo van los hechos que las condicionan y las opciones que veo, sin elegir.

Hechos:

- **Tamaños.** 7.911 predios elegibles (20.050 polígonos en total). El puntaje pesa 0,7 MB en Parquet. Las series de la temporada tienen 158.000 filas (predio × fecha); con 7 temporadas serían cerca de 1,1 millones. Los POI son unas 32.000 filas.
- **Frecuencia.** Sentinel-2 pasa cada 5 días. Cada pasada agrega una fila por predio a las series y puede cambiar la banda. Hoy la cadena completa (serie, M2 a M5) se corre a mano; las series se calculan en GCP en minutos.
- **Imágenes.** Hoy hay recortes solo para 3 casos (`assets/casos/`) y los que genera el expediente al vuelo desde Earth Search. No hay un almacén de recortes por predio y fecha.
- **Restricciones.** La capa de predios de CIREN no puede ir a un repo público. Los nombres de titulares no salen de `data/raw/`.
- **Plazo.** Lo que se elija tiene que estar desplegado esta noche.

| Decisión | Opciones | Qué considerar |
| --- | --- | --- |
| Datos tabulares de predios (puntajes, series, POI) | (a) Parquet dentro de la imagen del backend, leído con pandas o DuckDB. (b) Postgres con PostGIS en Cloud SQL. (c) BigQuery. (d) Archivos JSON generados al desplegar | (a) y (d) no tienen servicio que mantener, pero actualizar datos exige redesplegar. (b) permite consultas espaciales y cargas incrementales cada 5 días; hay que crear la instancia y cargarla hoy. (c) sirve para análisis, pero responde lento para una ficha |
| Geometrías | Con los datos tabulares, o como teselas vectoriales (PMTiles) en un bucket | 20.050 polígonos pesan decenas de MB como GeoJSON; el frontend ya se probó con 5.000 |
| Imágenes prebuscadas por predio y fecha | (a) Bucket de GCS con un recorte por predio y fecha, llenado por un job en cada pasada. (b) Solo para los predios en alerta. (c) Pedirlas a Earth Search cuando se abre la ficha | (a) es lo que escala como producto; son hasta 7.911 recortes por pasada. (b) reduce a unos 1.600. (c) no guarda nada, pero depende de un tercero en vivo |
| Expedientes PDF | Bucket de GCS, o disco temporal del contenedor más los pregenerados en la imagen | El disco temporal se pierde al reiniciar; el bucket da enlaces estables |
| Transporte al frontend | API para todo, o API solo para lo que es en vivo y archivos para el resto | Lo que elijan, el frontend no debe tener datos pegados en el código |

Requisitos que debe cumplir cualquier opción:

- La fuente de verdad son las salidas de `data/processed/`. La carga a donde sea se hace con un script del repo, repetible.
- Cada respuesta lleva la fecha del dato (`dato_al`) y la fecha de cálculo.
- Con el servicio caído, la demo tiene un camino de respaldo (al menos el PDF del candidato y la ruta).
- Sin arranque en frío durante la final.

## Frontend

Base: `frontend-demo/` (three.js y MapLibre). No se cambia la estructura de modos ni la precarga.

### F1. Datos reales de M5 (P0)

- La página deja de usar los puntajes provisionales de `build_zonas_scores.py` y usa los de M5.
- Se quita todo texto "provisional" de bandas, índice y consumo.
- La portada muestra 7.911 predios analizados y el conteo por banda de cada zona.
- El ranking se ordena por `rank_zona`.

### F2. Ficha del predio (P0)

Bloques, de arriba hacia abajo:

1. Encabezado: "Predio candidato", comuna, hectáreas y especie. Sin rol en modo demo.
2. Banda y bloque **Por qué está en alerta** (sección anterior): razones, confianza, límites.
3. Serie de la temporada con la línea del cerro seco de referencia y las ventanas sin lluvia sombreadas. Leyenda: "predio" y "cerro seco vecino". Al pasar por un punto: fecha e identificador de la escena.
4. Agua: barra con el rango de consumo y una marca en el derecho inscrito.
5. Puntos a revisar: lista y marcadores en el mapa.
6. Botón **Generar expediente**.
7. Pie: "Calculado el {fecha} · datos al {fecha} · ver método".

### F3. Expediente en vivo (P0)

- El botón pide el expediente al backend.
- Mientras espera, muestra los pasos reales que informa el backend. Sin barras de progreso falsas.
- Al terminar, abre el PDF en un visor dentro del panel y ofrece descargarlo.
- Si el backend no responde en 20 segundos o falla, abre el PDF de respaldo y muestra "generado el {fecha}".
- Se elimina la descarga del `.txt` de `js/expediente.js`.

### F4. Ficha del caso sancionado (P0)

- Línea de tiempo por temporada con la banda de Caudal y una línea vertical en la fecha de inspección.
- Frase destacada con datos del historial: "Caudal: alerta alta desde {primera alerta} · Inspección DGA: {fecha} · al menos {años} años antes".
- Multa en UTM y en pesos; imágenes antes y después.
- El mismo bloque **Por qué está en alerta**, con los datos previos a la inspección.

### F5. Ruta (P0)

- Usa la ruta de M8: paradas con hora de llegada, minutos y km desde la anterior.
- Botones: abrir en Google Maps y bajar GPX.
- Encabezado con los totales de la ruta (predios, horas, km, punto de salida), leídos del dato.
- Al tocar una parada se abre la ficha del predio.

### F6. Panel de impacto (P0)

Pantalla nueva, con enlace directo `#impacto`. Queda en pantalla 45 segundos del pitch: pocas cifras, grandes, en el orden en que se dicen. Todas se leen de `impacto.json`; ninguna va escrita en el código.

| Orden | Cifra en pantalla | Campo de `impacto.json` |
| --- | --- | --- |
| 1 | 2,6× más infractores que al azar | `lift_alta_sin_calibrar.valor`, con `ic_bajo` e `ic_alto` en letra chica. No usar `lift_alta` (3,7): se midió con los mismos casos que calibraron los umbrales |
| 2 | 1 predio = el agua de 3.000 personas al año = 220 millones de latas | Exceso mínimo del predio abierto ÷ `equivalencias.m3_persona_ano.valor` y ÷ `equivalencias.lata_monster_ml.valor` |
| 3 | 501 predios en alerta alta sin fiscalizar | `candidatos` |
| 4 | Entre 5 y 20 Torres Costanera de agua al año | `torres_costanera_ano.conservador` y `.central` |
| 5 | 14 años para revisarlos uno por uno | `capacidad.anos` |

Las cifras 2 y 4 llevan un dibujo simple (personas, latas, torres). Cada equivalencia muestra su fuente al pasar el cursor (`equivalencias.*.fuente` y `.nota`); la de la torre dice que es una estimación.

### F7. Modo demo (P1)

- Enlaces directos al caso, al candidato, a la ruta y al impacto.
- Teclas 1 a 5 para saltar entre los pasos del guion.
- `?demo=1` oculta el rol en todas las fichas.
- Los identificadores del caso y del candidato de la demo van en un archivo de configuración (`data/demo.json`), no en el código.

### F8. Filtros del ranking (P2)

Dos filtros: "sin canal a 300 m" y "nunca fiscalizado". Corresponden al escenario conservador de M9.

## Backend

Lo único que tiene que ocurrir en un servidor, se decida lo que se decida arriba, es el expediente. El resto de los recursos del contrato se sirve como definan Nico y Felipe.

### Expediente (P0)

Servicio `caudal-api` (FastAPI). Importa las funciones de `scripts/models/expediente.py`; no las reescribe.

| Método y ruta | Qué hace |
| --- | --- |
| `GET /api/health` | Estado del servicio, versión de los datos (commit y fecha) y número de predios |
| `POST /api/expediente` | Genera el expediente de un predio, o lo devuelve si ya existe con los mismos insumos |
| `GET /api/expediente/{id}/expediente.pdf` | Entrega el PDF |

Entrada de `POST /api/expediente`:

```json
{"predio_id": 5301984, "temporada": "2025-26"}
```

Salida (200):

```json
{
  "id": "CAU-5301984-202611220915",
  "predio_id": 5301984,
  "temporada": "2025-26",
  "banda": "alta",
  "confianza": "media",
  "reutilizado": true,
  "segundos": 0.4,
  "con_imagenes": true,
  "url_pdf": "/api/expediente/CAU-5301984-202611220915/expediente.pdf",
  "creado": "2026-11-22T09:15:03-03:00"
}
```

Reglas:

- Dos solicitudes con los mismos insumos devuelven el mismo expediente. La clave es el `hash_insumos` que ya calcula `expediente.py`. La respuesta lo dice (`reutilizado`), y la interfaz muestra la fecha de creación: no se presenta como recién generado algo que no lo es.
- Si Earth Search o Esri no responden en 15 segundos, se genera sin imágenes (`con_imagenes: false`) en vez de fallar.
- Tope de 60 segundos por solicitud. Una generación a la vez por predio.
- Errores: 404 si el predio no tiene puntaje; 422 si la temporada no tiene datos; 503 con detalle si la generación falla.
- El PDF usa el mismo texto de `explicacion.py` y mantiene las reglas de lenguaje del flujo B: "indicios", rangos, sin nombres.

Para la demo, el expediente del candidato se genera una vez antes de presentar. En el escenario se dice lo que es: "el expediente se arma en el servidor"; si el jurado pide otro predio, se genera delante de ellos.

### Otros recursos (según la decisión de almacenamiento)

Si se sirven por API, estas son las rutas sugeridas, con los campos del contrato de datos:

| Método y ruta | Prioridad |
| --- | --- |
| `GET /api/zonas/{zona}/resumen` | P0 |
| `GET /api/zonas/{zona}/ranking?banda=&sin_canal=&sin_fiscalizar=&limite=` | P0 |
| `GET /api/predios/{id}` (ficha con explicación) | P0 |
| `GET /api/predios/{id}/serie?temporada=` | P0 |
| `GET /api/casos/{expediente}` | P0 |
| `GET /api/zonas/{zona}/ruta` | P0 |
| `GET /api/impacto` | P0 |
| `POST /api/ruta` (otra jornada u otro filtro; solo con matrices de OSRM guardadas) | P2 |

## Despliegue en Cloud Run

| Parámetro | `caudal-web` | `caudal-api` |
| --- | --- | --- |
| Origen | `frontend-demo/` (Dockerfile con nginx, ya existe) | Dockerfile con Python 3.12 y las bibliotecas de WeasyPrint (pango, cairo, gdk-pixbuf) |
| Región | `southamerica-west1` | `southamerica-west1` |
| CPU y memoria | 1 vCPU, 512 MiB | 2 vCPU, 2 GiB |
| Concurrencia | 80 | 4 |
| Tiempo máximo | 60 s | 120 s |
| Instancias | mínimo 1, máximo 3 | mínimo 1, máximo 2 |
| Acceso | Público | Público, CORS solo desde la URL de `caudal-web` |

Cosas a saber:

- **Cuota:** Cloud Run tiene 20 vCPU y 40 GiB por región. Los trabajos de Gabi corren en `us-west1`, así que no compiten con estos servicios.
- **Cloud Build:** falló con `PERMISSION_DENIED` al desplegar el trabajo de POI. Si falla aquí, construir la imagen en local con Docker y subirla a Artifact Registry.
- **Capa de CIREN:** `predio.parquet` no está en git. El despliegue del backend debe copiarla al contexto de construcción (como hace `scripts/cloud/poi/desplegar.sh`) o leerla de un bucket privado.
- **Arranque en frío:** con una instancia mínima no hay. Volver a 0 después de la final.
- **Service worker:** las llamadas a `/api/` no se guardan en caché. Al cambiar los datos hay que subir la versión del caché en `sw.js`.
- **URL para el jurado:** la de `caudal-web` va en `platanus-hack-project.jsonc`.

## El repo frente al agente del jurado

El jurado hará preguntas técnicas a un agente que lee el repo. Lo que debe encontrar:

| Pregunta probable | Dónde está la respuesta | Pendiente |
| --- | --- | --- |
| ¿Hay datos escritos a mano? | Cada cifra sale de `data/processed/` y de un script | Quitar los puntajes provisionales del frontend (`build_zonas_scores.py`, `scores*.json`), el `.txt` de `expediente.js` y cualquier identificador de predio en el código (pasan a `data/demo.json`) |
| ¿De dónde sale cada número del pitch? | Tabla de respaldo en [pitch-demo.md](pitch-demo.md); `impacto.json` lleva sus fuentes y sus supuestos | — |
| ¿Qué es en vivo y qué es precalculado? | Sección nueva en el README raíz | Escribirla (T10) |
| ¿Cómo se reproduce? | Comando de cada script en `data/README.md` | Agregar el orden completo de la cadena en el README raíz |
| ¿Está validado? | [validacion.md](validacion.md), con intervalos y límites | — |
| ¿Los umbrales salieron de la nada? | [calibracion.md](calibracion.md) y `calibracion_grilla.csv` | — |
| ¿Qué supuestos tiene? | Encabezado de cada script y `impacto.json` (`supuestos`, `equivalencias`) | — |

Ya corregido: la cifra de validación del pitch (2,6) y las equivalencias (personas, latas, torre) estaban escritas como texto; ahora se calculan y quedan en `impacto.json` con su fuente.

## Tareas

| ID | Tarea | Prioridad | Responsable sugerido | Depende de | Listo cuando |
| --- | --- | --- | --- | --- | --- |
| T0 | Decidir almacenamiento y transporte (tabla de decisiones) | P0 | Nico y Felipe | — | Queda escrito en este documento qué se eligió |
| T1 | `explicacion.py`: razones, confianza y límites por predio, con fuentes | P0 | Tomás | — | Devuelve el contrato de la explicación para `5301984` y para el caso FO-0504-95 |
| T2 | Cargar o exportar los datos de M5 según T0, con un script repetible | P0 | Felipe, con apoyo de Tomás | T0, T1 | La zona Z2 muestra las bandas de M5 |
| T3 | F1 y F2: página con datos de M5 y ficha con "Por qué está en alerta" | P0 | Nico | T1, T2 | El predio `5301984` muestra sus razones con fuente |
| T4 | F4: línea de tiempo y adelanto en la ficha del caso | P0 | Nico | T2 | FO-0504-95 muestra su primera alerta y los años de adelanto |
| T5 | F5 y F6: ruta de M8 y panel de impacto leídos del dato | P0 | Felipe | T2 | `#impacto` muestra las 5 cifras sin números en el código |
| T6 | `caudal-api`: `health` y `expediente` | P0 | Gabi | — | `POST /api/expediente` devuelve un PDF en local |
| T7 | Desplegar `caudal-api` y generar el expediente del candidato | P0 | Gabi | T6 | El endpoint responde en producción |
| T8 | F3: botón que llama al backend, visor de PDF y respaldo | P0 | Nico | T6 | El clic abre el PDF en producción; con el backend apagado abre el respaldo |
| T9 | Desplegar `caudal-web` y llenar `platanus-hack-project.jsonc` | P0 | Nico | T3 a T8 | El recorrido completo funciona en la URL pública |
| T10 | Limpieza para el agente del jurado: quitar lo provisional, `data/demo.json`, README raíz con "en vivo y precalculado" | P0 | Tomás | T3 | La tabla de la sección anterior no tiene pendientes |
| T11 | Video de respaldo y 5 ensayos con cronómetro | P0 | Todos | T9 | Video guardado en dos computadores |
| T12 | F7: modo demo (enlaces, teclas, `?demo=1`) | P1 | Nico | T3 | Las teclas 1 a 5 recorren el guion |
| T13 | Imágenes prebuscadas por predio y fecha, según T0 | P1 | Felipe o Gabi | T0 | La ficha del candidato muestra recortes con fecha y escena |
| T14 | Filtros del ranking y ruta del escenario conservador | P2 | Tomás | T2 | — |

Orden sugerido para hoy: T0, T1 y T6 parten ya y en paralelo.

## Criterios de aceptación de la demo

- [ ] El recorrido del guion se completa en producción en menos de 1:40, sin recargar.
- [ ] Ninguna pantalla dice "provisional" ni muestra una cifra que no esté en `data/processed/`.
- [ ] La ficha del candidato muestra como máximo 4 razones y 2 límites, cada razón con su fuente.
- [ ] El texto de la ficha y el del PDF coinciden.
- [ ] El expediente del candidato se abre en menos de 3 segundos y es un PDF con las 7 secciones de la guía de la DGA.
- [ ] Con el backend apagado, el botón abre el PDF de respaldo.
- [ ] En modo demo no aparece ningún rol ni nombre.
- [ ] Buscar en `frontend-demo/js/` los números del pitch (501, 2,6, 5301984) no da resultados.

## Fuera de alcance

- Usuarios, sesiones y permisos.
- Envío de la denuncia a la DGA (requiere Clave Única; el expediente queda listo para que la persona lo presente).
- Recalcular series satelitales en vivo.
- Plan de vuelo de dron (M14) y retorno de campo (M15).
