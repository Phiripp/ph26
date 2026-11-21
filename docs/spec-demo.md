# Caudal — Spec de frontend y backend para la demo

Nov 21, 2026 · @Tomas

Este documento dice qué hay que construir en el frontend y en el backend para mostrar el guion de [pitch-demo.md](pitch-demo.md), y cómo se despliega en Cloud Run. No repite el spec del producto ([spec-v2.md](spec-v2.md)) ni el de los flujos por polígono ([spec-flujos-poligono.md](spec-flujos-poligono.md)).

La presentación es el domingo 22 en la mañana. Solo es obligatorio lo marcado P0.

## Qué debe poder mostrar la demo

Cinco pantallas, en este orden, todas en producción y con datos reales:

| Paso | Pantalla | Dato que la alimenta | Estado hoy |
| --- | --- | --- | --- |
| 1 | Zona Z2 con los predios por banda | `puntaje.parquet` (M5) | El frontend muestra 50 predios por zona con una banda provisional propia |
| 2 | Caso FO-0504-95: serie, banda por temporada y antes/después | `puntaje_validacion.parquet`, `anomalias_predio_validacion.parquet` | Existe la ficha del caso; falta la banda por temporada y el adelanto |
| 3 | Candidato `5301984`: ficha con consumo, derechos y avisos | `puntaje.parquet`, `poi.parquet` | La ficha existe con datos provisionales |
| 4 | Expediente PDF generado en vivo | `scripts/models/expediente.py` (M13) | El frontend baja un `.txt` armado en el navegador; el PDF solo se genera por línea de comandos |
| 5 | Ruta del día y panel de impacto | `ruta_z2.json` (M8), `impacto.json` (M9) | La ruta del frontend es provisional; el panel de impacto no existe |

## Principios

- **Nada simulado.** Cada cifra en pantalla sale de un archivo de `data/processed/`. Si algo es precalculado, la interfaz lo dice ("calculado el 21-11-2026").
- **Estático primero.** Todo lo que se puede precalcular se sirve como archivo estático. El backend solo hace lo que debe ocurrir en vivo: generar el expediente.
- **La demo no depende de terceros.** No se llama en vivo a OSRM, CIREN ni la DGA. El expediente tiene un camino sin red.
- **Caudal prioriza, no acusa.** Sin nombres de dueños. En modo demo tampoco se muestra el rol. Siempre rangos de m³. Solo los casos con multa se llaman "sancionados".

## Arquitectura

```
Navegador ──► caudal-web (Cloud Run, nginx, estático)
   │             └─ data/zonas/*.json   ◄── build_m5_web.py ◄── data/processed/ (M3 a M9)
   │
   └────────► caudal-api (Cloud Run, FastAPI)
                 ├─ POST /api/expediente  ──► expediente.py ──► PDF
                 └─ GET  /api/predios/{id}
```

- Dos servicios en el proyecto `ph-26-caudal`, región `southamerica-west1`.
- El frontend llama al backend con CORS. La URL del backend va en `frontend-demo/js/config.js` (`API_BASE`).
- El backend lee Parquet incluido en su imagen. No hay base de datos.

## Datos: exportación de M5 al frontend (P0)

Un script nuevo, `frontend-demo/scripts/build_m5_web.py`, reemplaza los puntajes provisionales de `build_zonas_scores.py`. Lee `data/processed/` y escribe los mismos archivos que el frontend ya carga, para cambiar lo menos posible en el código de la página.

Qué predios se exportan, por zona:

- Todos los de banda alta y media (Z1: 788; Z2: 827).
- Los predios de los 10 casos de validación y sus vecindarios.
- Las paradas de la ruta.

El resto (banda baja y sin alerta) va solo como conteo en `resumen.json`. La geometría se simplifica a 5 m.

| Archivo de salida | Contenido | Origen |
| --- | --- | --- |
| `data/zonas/resumen.json` | Por zona: total de predios, conteo por banda, resumen de la ruta. Global: bloque `impacto` | `puntaje.parquet`, `ruta_z*.json`, `impacto.json` |
| `data/zonas/{z}/predios.geojson` | Polígono, `predio_id`, comuna, `area_ha`, especie | `predio.parquet` (local), `predio_cultivo.parquet` |
| `data/zonas/{z}/scores.lite.json` | Por predio: campos de la tabla de abajo | `puntaje.parquet` |
| `data/zonas/{z}/series/` | Por predio y fecha: `ndvi`, `ndmi`, `ref_ndvi`, `ref_ndmi`, `en_ventana_seca`, `senal` | `anomalias_predio_elegibles_2025-26.parquet`; para los casos, `anomalias_predio_validacion.parquet` (7 temporadas) |
| `data/zonas/{z}/historial.json` | Solo predios de casos: por temporada, `banda`, `puntaje`, `m3_exceso_min/central/max` | `puntaje_validacion.parquet` |
| `data/zonas/{z}/ruta.json`, `ruta.gpx` | Ruta de M8 sin cambios de formato | `ruta_z*.json`, `ruta_z*.gpx` |
| `data/zonas/{z}/poi.json` | Por predio exportado: hasta 8 puntos con `tipo`, `lon`, `lat`, `razon`, `confianza` | `poi.parquet` |
| `data/zonas/casos.json` | Agrega a cada caso `primera_alerta`, `anos_adelanto`, `m3_antes_inspeccion` | `impacto.py` (función `adelanto`) |

Campos de `scores.lite.json` por predio:

| Campo | Origen en `puntaje.parquet` |
| --- | --- |
| `rank`, `banda`, `puntaje`, `confianza` | `rank_zona`, `banda`, `puntaje`, `confianza` |
| `motivos` | `motivos`, separados por `;` |
| `frac_senal`, `n_fechas` | `frac_senal`, `n_fechas_validas` |
| `consumo_m3` | `[m3_consumo_bruto_min, m3_consumo_bruto_central, m3_consumo_bruto_max]` |
| `derecho_m3`, `derecho_ajeno_m3` | `m3_derecho_asignado`, `m3_derecho_ajeno_disponible_500m` |
| `exceso_m3` | `[m3_exceso_min, m3_exceso_central, m3_exceso_max]` |
| `estado_derechos`, `canal_m` | `estado_derechos`, `dist_canal_m` |
| `fiscalizado_500m` | Calculado como en `impacto.py` (`sin_fiscalizar_500m`) |

Texto de cada motivo para la ficha:

| `motivos` | Texto en pantalla |
| --- | --- |
| `sin_derechos_propios_ubicados` | "Sin derechos de agua ubicados en el predio" |
| `derechos_ajenos_cubren_exceso` | "Hay derechos de vecinos a 500 m que podrían cubrir el consumo" |
| `canal_300m` | "Canal a menos de 300 m: puede regar con acciones de canal" |
| `predio_grande` | "Predio de más de 100 ha: la señal se diluye" |
| `pocos_pixeles` | "Predio chico: pocas mediciones por imagen" |
| `cruce_derechos_media`, `cruce_derechos_baja` | "La ubicación del derecho es incierta" |

## Frontend

Base: `frontend-demo/` (estático, sin build, three.js y MapLibre). No se cambia la estructura de modos ni la precarga.

### F1. Datos reales de M5 (P0)

- La página carga los archivos de `build_m5_web.py`.
- Se quita todo texto "provisional" de bandas, índice y consumo.
- La portada muestra 7.911 predios analizados y el conteo por banda de cada zona.
- El ranking se ordena por `rank`.

### F2. Ficha del predio (P0)

Bloques, de arriba hacia abajo:

1. Encabezado: "Predio candidato", comuna, hectáreas y especie. Sin rol en modo demo.
2. Banda y confianza, con los motivos en texto.
3. Serie NDVI y NDMI de la temporada con la línea del secano de referencia y las ventanas secas sombreadas. Leyenda: "predio" y "cerro seco vecino".
4. Agua: barra con el rango de consumo y una marca en el derecho asignado. Texto: "Consume entre 105.000 y 280.000 m³ al año. Derechos inscritos: 0 m³".
5. Avisos: distancia al canal más cercano, derechos de vecinos, "sin fiscalización de la DGA a 500 m desde 2018".
6. Puntos a revisar (POI): lista y marcadores en el mapa.
7. Botón **Generar expediente**.

### F3. Expediente en vivo (P0)

- El botón llama a `POST /api/expediente`.
- Mientras espera, muestra los pasos reales que devuelve el backend ("leyendo serie", "armando croquis", "generando PDF"). Sin barras de progreso falsas.
- Al terminar, abre el PDF en un visor dentro del panel y ofrece descargarlo.
- Si el backend no responde en 20 segundos o falla, abre el PDF estático de respaldo (`assets/expedientes/{predio_id}.pdf`) y muestra "generado el {fecha}".
- Se elimina la descarga del `.txt` de `js/expediente.js`.

### F4. Ficha del caso sancionado (P0)

- Línea de tiempo por temporada con la banda de Caudal (`historial.json`) y una línea vertical en la fecha de inspección.
- Frase destacada: "Caudal: alerta alta desde 2019-20 · Inspección DGA: 23-11-2021 · al menos 2,0 años antes".
- Multa en UTM y en pesos; imágenes antes y después (ya existen).

### F5. Ruta (P0)

- Usa la ruta de M8: paradas con hora de llegada, minutos y km desde la anterior.
- Botones: abrir en Google Maps y bajar GPX (ya existen).
- Encabezado: "12 predios · 8 horas · 91 km · sale de la Plaza de Quillota".
- Al tocar una parada se abre la ficha del predio.

### F6. Panel de impacto (P0)

Pantalla nueva, con enlace directo `#impacto`. Queda en pantalla durante 45 segundos del pitch, así que tiene pocas cifras, grandes, y en el mismo orden en que se dicen:

| Orden | Cifra en pantalla | Origen |
| --- | --- | --- |
| 1 | 2,6× más infractores que al azar | Fijo en 2,6 con nota "IC 95 %: 1,3–4,4" ([validacion.md](validacion.md)); no usar `lift_alta` de `impacto.json` (3,7, optimista) |
| 2 | 1 predio = el agua de 3.000 personas al año = 220 millones de latas de Monster | Exceso mínimo del candidato `5301984` ÷ 36,5 m³ por persona y ÷ 473 ml |
| 3 | 501 predios en alerta alta sin fiscalizar | `impacto.json`, `candidatos` |
| 4 | Entre 5 y 20 Torres Costanera de agua al año | `escenarios.conservador.m3_ano` y `escenarios.central.m3_ano` ÷ 450.000 m³ |
| 5 | 14 años para revisarlos uno por uno | Candidatos de hasta 100 ha ÷ 33 fiscalizaciones al año |

Las cifras 2 y 4 llevan un dibujo simple (personas, latas, torres) en vez de números con unidades. Pie chico con los valores exactos: "2,1 a 9,3 millones de m³ al año · torre estimada en 450.000 m³".

### F7. Modo demo (P1)

- Enlaces directos: `#caso-FO-0504-95`, `#predio-5301984`, `#z2-ruta`, `#impacto`.
- Teclas 1 a 5 para saltar entre los pasos del guion.
- `?demo=1` oculta el rol en todas las fichas.
- Indicador discreto de precarga lista (`data-warm=done`).

### F8. Filtros del ranking (P2)

Dos filtros: "sin canal a 300 m" y "nunca fiscalizado". Corresponden al escenario conservador de M9.

## Backend

Servicio nuevo `caudal-api` en `api/` (FastAPI, Python 3.12). Importa las funciones de `scripts/models/expediente.py`; no las reescribe.

### Endpoints

| Método y ruta | Prioridad | Qué hace |
| --- | --- | --- |
| `GET /api/health` | P0 | Estado del servicio y de los datos |
| `POST /api/expediente` | P0 | Genera o devuelve del caché el expediente de un predio |
| `GET /api/expediente/{id}/expediente.pdf` | P0 | Entrega el PDF |
| `GET /api/predios/{predio_id}` | P1 | Contexto del predio (M12) para predios que no están en la exportación estática |
| `GET /api/ranking` | P2 | Ranking con filtros, para los 7.911 predios |
| `POST /api/ruta` | P2 | Recalcula la ruta para una jornada o un filtro distintos |

**`GET /api/health`**

```json
{"ok": true, "version": "2026-11-21", "temporada": "2025-26", "predios": 7911, "expedientes_en_cache": 42}
```

**`POST /api/expediente`**

Entrada:

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
  "cache": true,
  "segundos": 0.4,
  "con_imagenes": true,
  "url_pdf": "/api/expediente/CAU-5301984-202611220915/expediente.pdf",
  "creado": "2026-11-22T09:15:03-03:00"
}
```

Reglas:

- La clave del caché es el `hash_insumos` que ya calcula `expediente.py`. Si existe un expediente con ese hash, se devuelve sin regenerar (`cache: true`).
- Si no existe, se genera. Si Earth Search o Esri no responden en 15 segundos, se genera sin imágenes (`con_imagenes: false`) en vez de fallar.
- Tope de 60 segundos por solicitud. Una generación a la vez por predio.
- Errores: 404 si el predio no está en `puntaje.parquet`; 422 si la temporada no tiene datos; 503 con `{"detalle": "..."}` si la generación falla.
- El PDF mantiene las reglas de lenguaje del flujo B: "indicios", rangos, sin nombres.

**`GET /api/predios/{predio_id}`**

Devuelve los mismos campos de `scores.lite.json` más cauce cercano, canal cercano, restricción del acuífero y POI. Es el endpoint de contexto de M12.

**`POST /api/ruta`**

Entrada: `{"zona": "Z2", "jornada_h": 8, "min_visita": 30, "filtro": "sin_canal"}`. Usa solo matrices de OSRM guardadas en la imagen. Si la combinación no está en caché responde 409; nunca llama a OSRM en vivo.

### Datos del backend

| Dato | Cómo llega a la imagen |
| --- | --- |
| `data/processed/*.parquet` (en git) | Se copia al construir |
| `predio.parquet` (no está en git: capa de CIREN) | El script de despliegue lo copia al contexto de construcción, igual que `scripts/cloud/poi/desplegar.sh` |
| Expedientes pregenerados | Carpeta `data/processed/expedientes/` incluida en la imagen |
| Expedientes nuevos | `/tmp` del contenedor (se pierden al reiniciar; sirven para la sesión) |
| Nombres de titulares | No se incluyen |

### Pregeneración (P0)

Antes de desplegar se generan los expedientes del candidato `5301984`, del caso `5301413` (FO-0504-95), de las 12 paradas de la ruta de Z2 y de las 10 de Z1. Con eso, el clic de la demo sale del caché en menos de 2 segundos, y cualquier otro predio se genera de verdad.

## Despliegue en Cloud Run

| Parámetro | `caudal-web` | `caudal-api` |
| --- | --- | --- |
| Origen | `frontend-demo/` (Dockerfile con nginx, ya existe) | `api/Dockerfile` (python:3.12-slim más las bibliotecas de WeasyPrint: pango, cairo, gdk-pixbuf) |
| Región | `southamerica-west1` | `southamerica-west1` |
| CPU y memoria | 1 vCPU, 512 MiB | 2 vCPU, 2 GiB |
| Concurrencia | 80 | 4 |
| Tiempo máximo | 60 s | 120 s |
| Instancias | mínimo 1, máximo 3 | mínimo 1, máximo 2 |
| Acceso | Público | Público, CORS solo desde la URL de `caudal-web` |
| Variables | `PORT` | `PORT`, `ORIGEN_WEB`, `SIN_IMAGENES=0` |

Comandos:

```bash
# Frontend
gcloud run deploy caudal-web --source frontend-demo --project ph-26-caudal \
  --region southamerica-west1 --allow-unauthenticated --min-instances 1

# Backend (el script arma el contexto con predio.parquet y los expedientes pregenerados)
scripts/cloud/api/desplegar.sh
```

Cosas a saber:

- **Cuota:** Cloud Run tiene 20 vCPU y 40 GiB por región. Los trabajos de Gabi corren en `us-west1`, así que no compiten con estos servicios.
- **Cloud Build:** falló con `PERMISSION_DENIED` al desplegar el trabajo de POI. Si falla aquí, construir la imagen en local con Docker y subirla a Artifact Registry.
- **Arranque en frío:** con `min-instances 1` no hay. Volver a 0 después de la final para no gastar.
- **Service worker:** las llamadas a `/api/` no se guardan en caché. Al desplegar una versión nueva de datos hay que subir la versión del caché en `sw.js`.
- **URL para el jurado:** la de `caudal-web` va en `platanus-hack-project.jsonc`.

## Tareas

| ID | Tarea | Prioridad | Responsable sugerido | Depende de | Listo cuando |
| --- | --- | --- | --- | --- | --- |
| T1 | `build_m5_web.py`: exportar M5, series, historial, POI, ruta e impacto | P0 | Tomás | — | `build_zonas_web.py --check` pasa y la página carga con los archivos nuevos |
| T2 | F1 y F2: página con datos de M5 y ficha del predio | P0 | Nico | T1 | El predio `5301984` muestra su banda, sus rangos y sus avisos |
| T3 | F4: línea de tiempo y adelanto en la ficha del caso | P0 | Nico o Felipe | T1 | FO-0504-95 muestra "alerta alta desde 2019-20" |
| T4 | Ruta de M8 en la pestaña Ruta (F5) | P0 | Felipe | T1 | La pestaña muestra 12 paradas con horas |
| T5 | `caudal-api`: `health` y `expediente` con caché | P0 | Gabi | — | `POST /api/expediente` devuelve un PDF en local |
| T6 | Pregenerar expedientes y desplegar `caudal-api` | P0 | Gabi | T5 | El endpoint responde en producción en menos de 2 s para `5301984` |
| T7 | F3: botón que llama al backend, visor de PDF y respaldo estático | P0 | Nico | T5 | El clic abre el PDF en producción; con el backend apagado abre el respaldo |
| T8 | F6: panel de impacto | P0 | Felipe | T1 | `#impacto` muestra las 4 cifras |
| T9 | Desplegar `caudal-web` y llenar `platanus-hack-project.jsonc` | P0 | Nico | T2 a T8 | El recorrido completo funciona en la URL pública |
| T10 | Video de respaldo y 5 ensayos con cronómetro | P0 | Todos | T9 | Video guardado en dos computadores |
| T11 | F7: modo demo (enlaces, teclas, `?demo=1`) | P1 | Nico | T2 | Las teclas 1 a 5 recorren el guion |
| T12 | `GET /api/predios/{id}` (M12) | P1 | Gabi | T5 | Devuelve el contexto de un predio fuera de la exportación |
| T13 | Filtros del ranking y ruta del escenario conservador | P2 | Tomás | T1 | — |
| T14 | `GET /api/ranking` y `POST /api/ruta` | P2 | Gabi | T5 | — |

Orden sugerido para hoy: T1 y T5 parten ya y en paralelo. Con T1 listo parten T2, T3, T4 y T8. T7 necesita T5. T9 y T10 cierran la noche.

## Criterios de aceptación de la demo

- [ ] El recorrido del guion se completa en producción en menos de 1:45, sin recargar.
- [ ] Ninguna pantalla dice "provisional" ni muestra una cifra que no esté en `data/processed/`.
- [ ] El expediente del candidato se abre en menos de 3 segundos y es un PDF con las 7 secciones de la guía de la DGA.
- [ ] Con el backend apagado, el botón abre el PDF de respaldo.
- [ ] Con la red apagada (segunda visita), el recorrido funciona hasta la ruta.
- [ ] En modo demo no aparece ningún rol ni nombre.
- [ ] Las cifras del panel de impacto coinciden con `impacto.md`.

## Fuera de alcance

- Usuarios, sesiones y permisos.
- Envío de la denuncia a la DGA (requiere Clave Única; el expediente queda listo para que la persona lo presente).
- Recalcular series satelitales en vivo.
- Plan de vuelo de dron (M14) y retorno de campo (M15).
- Los 7.911 polígonos en el navegador: se exportan solo las bandas alta y media.
