# caudal-api

API de lectura y expediente PDF de Caudal. Sirve los recursos del contrato de datos de [docs/spec-demo.md](../docs/spec-demo.md): FastAPI, con DuckDB sobre los Parquet de `data/processed/`. No hay base de datos.

> Caudal prioriza, no acusa. Ninguna ruta devuelve nombres de titulares. Las rutas de lectura entregan el rol solo con `?rol=1`, y la página no lo pide.

## Correrla en local

Desde la raíz del repo. Necesita `data/processed/predio.parquet` (no está en git: `uv run scripts/extract/predios_ciren.py`). Sin ese archivo responde igual, pero sin polígonos, centros ni `fiscalizado_500m`.

```bash
uv run --with-requirements api/requirements.txt uvicorn api.main:app --reload --port 8000
```

- Documentación interactiva, con todas las rutas y parámetros: <http://localhost:8000/docs>.
- CORS acepta cualquier puerto de `localhost`. En producción solo acepta los orígenes de `CAUDAL_ORIGENES`.
- El expediente PDF usa WeasyPrint, que en macOS necesita pango (`brew install pango`). Con Docker no hace falta instalar nada:

```bash
SOLO_IMAGEN=1 scripts/cloud/api/desplegar.sh    # construye la imagen local caudal-api (unos 3 minutos)
docker run --rm -p 8000:8080 caudal-api
scripts/cloud/api/probar.sh http://localhost:8000
```

## Rutas

Todas responden JSON. Los `GET` llevan `Cache-Control: public, max-age=300` y un `ETag` con la versión de los datos. Errores: 404 si el predio, la zona o el caso no existe; 422 si existe pero no tiene datos para lo pedido; el cuerpo es `{"detail": "..."}`.

| Ruta | Para qué pantalla | Qué entrega |
| --- | --- | --- |
| `GET /api/health` | — | Estado, commit, fecha de cálculo, fecha de la última imagen, número de predios |
| `GET /api/demo` | Modo demo | Zona, caso y candidato del guion ([data/demo.json](../data/demo.json)) |
| `GET /api/zonas` | Portada | Total de predios analizados y resumen de cada zona |
| `GET /api/zonas/{zona}/resumen` | Zona | Predios, conteo por banda y resumen de la ruta |
| `GET /api/zonas/{zona}/ranking` | Zona | Predios por `rank_zona`. Parámetros: `banda`, `sin_canal`, `sin_fiscalizar`, `limite` (200), `desde` |
| `GET /api/zonas/{zona}/predios` | Mapa | GeoJSON de los predios en alerta alta y media, más casos, vecindarios y paradas de la ruta. Cada polígono trae los campos del ranking |
| `GET /api/zonas/{zona}/ruta` | Ruta | Paradas con horas, km, punto de acceso y enlace de navegación. También `ruta.gpx` y `ruta.geojson` (trazado) |
| `GET /api/predios/{id}` | Ficha | Puntaje, **explicación de la alerta**, agua, puntos a revisar y contexto. Parámetro: `temporada` |
| `GET /api/predios/{id}/serie` | Gráfico | Por imagen: verdor y humedad del predio y del cerro seco, ventana seca, señal, escena. Parámetro: `temporada` |
| `GET /api/casos` | Mapa y portada | Los 10 casos resueltos por la DGA, con banda previa, primera alerta y años de adelanto |
| `GET /api/casos/{expediente}` | Ficha del caso | El caso, el historial por temporada de su predio y la explicación con los datos previos a la inspección |
| `GET /api/impacto` | Impacto | `impacto.json` de M9, con fuentes y supuestos |
| `POST /api/expediente` | Botón de la ficha | Genera el PDF o devuelve el que ya existe |
| `GET /api/expediente/eventos` | Botón de la ficha | Lo mismo, con los pasos reales de la generación |
| `GET /api/expediente/{id}/expediente.pdf` | Visor | El PDF |

`{zona}` es `Z1` o `Z2` (acepta minúsculas).

### Ficha: `GET /api/predios/5301984`

```jsonc
{
  "predio": {"predio_id": 5301984, "zona": "Z2", "comuna": "HIJUELAS", "area_ha": 18.85, "especie": "Palto", "lon": -71.068726, "lat": -32.894499},
  "temporada": "2025-26", "temporadas": ["2025-26"], "caso": null,
  "puntaje": {"banda": "alta", "puntaje": 92.2, "confianza": "media", "motivos": ["sin_derechos_propios_ubicados"], "rank_zona": 72, "predios_zona": 3639},
  "explicacion": {
    "banda": "alta", "confianza": "media",
    "razones": [   // máximo 4: riego_sin_lluvia, consumo, derechos, contexto
      {"id": "riego_sin_lluvia", "titulo": "Riego sin lluvia",
       "texto": "Más verde y más húmedo que el cerro seco vecino en 20 de 20 imágenes tomadas tras 10 días o más sin lluvia.",
       "valor": {"fechas_con_senal": 20, "fechas_validas": 20, "verdor_predio": 0.7, "verdor_secano": 0.37, "desde": "2025-12-03", "hasta": "2026-03-18"},
       "fuente": "Imágenes Sentinel-2 (Copernicus); lluvia de DMC y Open-Meteo",
       "referencia": "https://earth-search.aws.element84.com/v1/collections/sentinel-2-l2a",
       "metodo": "scripts/models/detector_riego.py", "dato_al": "2026-03-18"}
    ],
    "confianza_motivos": ["No encontramos derechos ubicados en el predio; podría tener derechos sin coordenada en el registro"],
    "limites": ["Caudal ve que se riega, no de dónde sale el agua. La infracción la constata un inspector.", "El consumo es una estimación en rango, no una medición."],
    "escenas": [{"fecha": "2025-12-03", "escena_id": "S2C_19HCD_20251203_0_L2A", "senal": true}],
    "metodo": "data/README.md#índice-de-sospecha-m5", "validacion": "docs/validacion.md"
  },
  "agua": {"consumo_m3": [104648, 162924, 280044], "derecho_m3": 0, "derecho_ajeno_500m_m3": 0, "exceso_m3": [104648, 162924, 280044],
           "equivalencias": {"personas_ano": {"valor": 2867, "fuente": "..."}, "latas": {"valor": 221243129, "fuente": "..."}}},
  "poi": [{"tipo": "zona_riego", "lon": -71.069126, "lat": -32.895092, "razon": "...", "confianza": 0.7}],
  "contexto": {"cauce": {"nombre": "Quebrada el Limonal", "dist_m": 1188}, "canal": {"nombre": "Don Bosco de Ocoa", "dist_m": 1192}, "fiscalizado_500m": false},
  "dato_al": "2026-03-28", "calculado": "2026-11-21T09:46:55-03:00", "version_modelo": "188cdb1"
}
```

- Los rangos de m³ van como `[mínimo, central, máximo]`.
- `texto` es la frase para la primera vista; `valor` trae los números crudos para "ver método". `metodo` y `validacion` son rutas dentro del repo.
- La explicación la arma [scripts/models/explicacion.py](../scripts/models/explicacion.py). El PDF usa la misma función: dicen lo mismo.
- Responde para los 7.911 predios elegibles y para los de la validación. Los predios de los casos tienen 7 temporadas.

### Expediente

```bash
curl -X POST localhost:8000/api/expediente -H 'content-type: application/json' -d '{"predio_id": 5301984}'
```

```json
{"id": "CAU-5301984-202611212028", "predio_id": 5301984, "temporada": "2025-26", "banda": "alta", "confianza": "media",
 "reutilizado": true, "segundos": 0.0, "con_imagenes": true, "con_rol": false, "hash_insumos": "4f4fb442c42d",
 "url_pdf": "/api/expediente/CAU-5301984-202611212028/expediente.pdf", "creado": "2026-11-21T20:28:48-03:00"}
```

- `reutilizado: true` significa que ya existía un expediente con los mismos insumos. Muestra `creado`; no lo presentes como recién generado. Con `"regenerar": true` se fuerza uno nuevo.
- **Rol.** El PDF lleva el rol solo si el predio tiene un caso sancionado por la DGA, que es un dato público. Para el resto identifica el predio por su polígono de CIREN y deja el rol para quien presenta la denuncia (`con_rol: false`). Se fuerza con `"rol": true` o `"rol": false` (`&rol=false` en la ruta de eventos); la página manda `rol=false` en modo demo (`?demo=1`).
- Uno nuevo tarda cerca de 20 segundos; casi todo es bajar las imágenes. Si las fuentes de imágenes no responden, sale sin imágenes (`con_imagenes: false`).
- Tope: 180 segundos (`CAUDAL_TOPE_S`; el servicio de Cloud Run corta a los 300). Pasado el tope responde 503; la generación termina en segundo plano y la siguiente solicitud la encuentra hecha.
- Los expedientes del candidato y del caso de `data/demo.json` se generan al construir la imagen, así que en producción abren al instante.

Para mostrar el avance real, en vez del `POST`:

```js
const es = new EventSource(`${API_BASE}/api/expediente/eventos?predio_id=${id}`)
es.addEventListener('paso', e => mostrarPaso(JSON.parse(e.data).texto))        // "Buscando las imágenes satelitales del predio"
es.addEventListener('listo', e => { abrirPdf(API_BASE + JSON.parse(e.data).url_pdf); es.close() })
es.addEventListener('falla', e => { abrirRespaldo(JSON.parse(e.data).detail); es.close() })
es.onerror = () => { abrirRespaldo(); es.close() }                              // sin backend
```

Si el expediente ya existe, llega un solo evento `listo`.

## Respaldo estático

[api/respaldo.py](respaldo.py) guarda la respuesta de cada ruta `GET` como archivo. Pide las rutas a la misma aplicación, así el respaldo y la API no se desalinean.

```bash
uv run --with-requirements api/requirements.txt python -m api.respaldo                   # predios del mapa: 3.500 archivos, 26 MB
uv run --with-requirements api/requirements.txt python -m api.respaldo --predios demo    # casos, rutas y candidatos: 100 archivos, 2,8 MB
```

- Una ruta por archivo: `/api/zonas/Z2/ranking` queda en `frontend-demo/data/respaldo/zonas/Z2/ranking.json`. Las rutas con parámetros no se guardan.
- En git está la versión `--predios demo`: cubre el recorrido del guion. Si la página debe abrir cualquier predio del mapa sin backend, hay que generar la completa.
- El respaldo no incluye el PDF.

En la página, una sola función:

```js
async function api(ruta) {                       // api('/api/zonas/Z2/ranking')
  try {
    const r = await fetch(API_BASE + ruta, {signal: AbortSignal.timeout(5000)})
    if (r.ok) return r.json()
    if (r.status < 500) throw Object.assign(new Error((await r.json()).detail), {status: r.status})   // 404 y 422 son respuestas
  } catch (e) { if (e.status) throw e }
  const archivo = ruta.replace('/api/', '').split('?')[0]
  const r = await fetch(`data/respaldo/${archivo}${/\.\w+$/.test(archivo) ? '' : '.json'}`)
  if (!r.ok) throw new Error('sin datos')
  return Object.assign(await r.json(), {respaldo: true})      // mostrar "datos del {calculado}"
}
```

## Desplegar (Gabi)

```bash
scripts/cloud/api/desplegar.sh                               # construye con Docker, sube a Artifact Registry y despliega
EXPEDIENTE=1 scripts/cloud/api/probar.sh https://caudal-api-....run.app
```

- El script copia los datos a la imagen y escribe `data/VERSION`, que es lo que muestra `/api/health`. Necesita tu `predio.parquet` local y Docker corriendo.
- CORS: toma la URL de `caudal-web` si ya está desplegado. Si no, pásala con `ORIGENES=https://...`; se pueden poner varias, separadas por coma.
- Para actualizar los datos, se corre de nuevo. Cada despliegue es una revisión de Cloud Run.
- La parte de `gcloud` del script no se ha probado (sin acceso a GCP desde donde se escribió); la imagen sí, en local.

## Archivos

| Archivo | Qué hace |
| --- | --- |
| [datos.py](datos.py) | Arma cada recurso desde `data/processed/`. Lo usan las rutas y el respaldo |
| [main.py](main.py) | Rutas, CORS, caché y errores |
| [expedientes.py](expedientes.py) | Genera con `scripts/models/expediente.py`, reutiliza por huella de insumos, cola de una generación |
| [pregenerar.py](pregenerar.py) | Expedientes de la demo al construir la imagen |
| [respaldo.py](respaldo.py) | Respaldo estático |
| `requirements.in`, `requirements.txt` | Dependencias y sus versiones fijas (`uv pip compile`) |
