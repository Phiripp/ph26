"""caudal-api: recursos de lectura y expediente PDF de Caudal (docs/spec-demo.md, "Backend").

Cada ruta GET llama a una función de api/datos.py; el expediente, a api/expedientes.py. Documentación interactiva
en /docs (OpenAPI).

Local, desde la raíz del repo:
  uv run --with-requirements api/requirements.txt uvicorn api.main:app --reload --port 8000
En Cloud Run: api/Dockerfile (lo despliega scripts/cloud/api/desplegar.sh).

Variables de entorno:
  CAUDAL_ORIGENES     orígenes permitidos por CORS, separados por coma (la URL de caudal-web). localhost siempre puede.
  CAUDAL_EXPEDIENTES  carpeta de los expedientes nuevos (por defecto data/processed/expedientes).
  CAUDAL_RAIZ         raíz del repo o de la imagen (por defecto, la carpeta que contiene api/).
"""

import asyncio
import json
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from . import datos, expedientes

CACHE = "public, max-age=300"
SIN_CACHE = ("/api/health", "/api/expediente")


@asynccontextmanager
async def arranque(app: FastAPI):
    await run_in_threadpool(datos.casos)  # abre la base, marca las fechas y deja listos los casos antes de atender
    yield


app = FastAPI(title="caudal-api", version="1", lifespan=arranque,
              description="Predios priorizados por indicios de riego sin derechos de agua. Caudal prioriza, no acusa.")
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.environ.get("CAUDAL_ORIGENES", "").split(",") if o.strip()],
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_methods=["GET", "POST"], allow_headers=["*"], expose_headers=["ETag"])


@app.middleware("http")
async def cache(request: Request, call_next):
    """Los GET de lectura llevan Cache-Control y un ETag igual a la versión de los datos; con If-None-Match, 304."""
    cacheable = request.method == "GET" and request.url.path.startswith("/api/") and not request.url.path.startswith(SIN_CACHE)
    etag = f'"{datos.version().get("commit") or "local"}"' if cacheable else None
    if cacheable and request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag, "Cache-Control": CACHE})
    r = await call_next(request)
    if cacheable and r.status_code == 200:
        r.headers["Cache-Control"], r.headers["ETag"] = CACHE, etag
    return r


@app.exception_handler(datos.NoExiste)
async def no_existe(_, err):
    return JSONResponse({"detail": str(err)}, status_code=404)


@app.exception_handler(datos.SinDatos)
async def sin_datos(_, err):
    return JSONResponse({"detail": str(err)}, status_code=422)


@app.exception_handler(expedientes.FallaGeneracion)
async def falla_generacion(_, err):
    return JSONResponse({"detail": str(err)}, status_code=503)


# ---------------------------------------------------------------- servicio

@app.get("/api/health", tags=["servicio"])
def health():
    """Estado del servicio y versión de los datos (commit, fecha de cálculo, última imagen, número de predios)."""
    return {"estado": "ok", "con_geometria": datos.con_geometria(), **datos.version()}


@app.get("/api/demo", tags=["servicio"])
def demo():
    """Caso y candidato que abre el guion de la demo (data/demo.json)."""
    return datos.demo()


@app.get("/api/impacto", tags=["servicio"])
def impacto():
    """impacto.json de M9: candidatos, lift, escenarios, capacidad y equivalencias, con fuentes y supuestos."""
    return datos.impacto()


# ---------------------------------------------------------------- zonas

@app.get("/api/zonas", tags=["zonas"])
def zonas():
    """Total de predios analizados y resumen de cada zona (para la portada)."""
    return datos.resumen()


@app.get("/api/zonas/{zona}/resumen", tags=["zonas"])
def zona_resumen(zona: str):
    """Predios analizados, conteo por banda y resumen de la ruta de la zona (Z1 o Z2)."""
    return datos.resumen_zona(zona)


@app.get("/api/zonas/{zona}/ranking", tags=["zonas"])
def zona_ranking(zona: str, banda: str | None = Query(None, description="alta, media, baja o sin_alerta; varias con coma"),
                 sin_canal: bool = Query(False, description="solo predios sin canal a 300 m"),
                 sin_fiscalizar: bool = Query(False, description="solo predios sin fiscalización a 500 m desde 2018"),
                 limite: int = Query(200, ge=1, le=5000), desde: int = Query(0, ge=0)):
    """Predios de la zona ordenados por rank_zona."""
    return datos.ranking(zona, banda, sin_canal, sin_fiscalizar, limite, desde)


@app.get("/api/zonas/{zona}/predios", tags=["zonas"])
def zona_predios(zona: str, rol: bool = Query(False, description="incluir el rol (no pedir en modo demo)")):
    """GeoJSON de los predios en alerta alta y media (más casos, vecindarios y paradas de la ruta), simplificado a 5 m."""
    return JSONResponse(datos.predios_geojson(datos.zona_id(zona), rol), media_type="application/geo+json")


@app.get("/api/zonas/{zona}/ruta", tags=["zonas"])
def zona_ruta(zona: str):
    """Ruta de inspección de M8: paradas con horas, km, punto de acceso y enlace de navegación."""
    return datos.ruta(datos.zona_id(zona))


@app.get("/api/zonas/{zona}/ruta.gpx", tags=["zonas"])
def zona_ruta_gpx(zona: str):
    return FileResponse(datos.ruta_archivo(zona, "gpx"), media_type="application/gpx+xml",
                        filename=f"caudal_ruta_{datos.zona_id(zona).lower()}.gpx")


@app.get("/api/zonas/{zona}/ruta.geojson", tags=["zonas"])
def zona_ruta_geojson(zona: str):
    """Trazado de la ruta por caminos (OSRM, guardado; la API no llama a OSRM)."""
    return FileResponse(datos.ruta_archivo(zona, "geojson"), media_type="application/geo+json")


# ---------------------------------------------------------------- predios y casos

@app.get("/api/predios/{predio_id}", tags=["predios"])
def predio(predio_id: int, temporada: str | None = None,
           rol: bool = Query(False, description="incluir el rol (no pedir en modo demo)")):
    """Ficha del predio: puntaje, explicación de la alerta (razones con fuente, confianza y límites), agua, puntos a
    revisar y contexto. Responde para los predios elegibles y para los de la validación."""
    return datos.ficha(predio_id, temporada, rol)


@app.get("/api/predios/{predio_id}/serie", tags=["predios"])
def predio_serie(predio_id: int, temporada: str | None = None):
    """Serie por imagen: verdor y humedad del predio y del cerro seco vecino, con las marcas del detector de riego."""
    return datos.serie(predio_id, temporada)


@app.get("/api/casos", tags=["casos"])
def casos():
    """Los casos resueltos por la DGA que usa la demo, con la banda previa y los años de adelanto."""
    return datos.casos()


@app.get("/api/casos/{expediente}", tags=["casos"])
def caso(expediente: str):
    """Un caso con el historial por temporada de su predio y la explicación con los datos previos a la inspección."""
    return datos.caso(expediente)


# ---------------------------------------------------------------- expediente

class SolicitudExpediente(BaseModel):
    predio_id: int
    temporada: str | None = None
    regenerar: bool = False


@app.post("/api/expediente", tags=["expediente"])
def expediente(s: SolicitudExpediente):
    """Genera el expediente PDF del predio, o devuelve el que ya existe con los mismos insumos (`reutilizado`)."""
    return expedientes.solicitar(s.predio_id, s.temporada, s.regenerar)


@app.get("/api/expediente/eventos", tags=["expediente"])
async def expediente_eventos(predio_id: int, temporada: str | None = None, regenerar: bool = False):
    """Lo mismo que el POST, como eventos (text/event-stream) para mostrar el avance real: un evento `paso` por cada
    paso de la generación, y al final `listo` (la respuesta del POST) o `falla`. Con EventSource:

        const es = new EventSource(API + '/api/expediente/eventos?predio_id=5301984')
        es.addEventListener('paso', e => mostrar(JSON.parse(e.data).texto))
        es.addEventListener('listo', e => { abrir(JSON.parse(e.data).url_pdf); es.close() })
        es.addEventListener('falla', e => { respaldo(JSON.parse(e.data).detail); es.close() })
    """
    t0 = time.time()
    clave, r = await run_in_threadpool(expedientes.encolar, predio_id, temporada, regenerar)

    def evento(nombre: str, dato: dict) -> str:
        return f"event: {nombre}\ndata: {json.dumps(dato, ensure_ascii=False)}\n\n"

    async def flujo():
        if isinstance(r, dict):
            yield evento("listo", r)
            return
        vistos = 0
        while True:
            hecho = r.done()
            ps = expedientes.pasos(clave)
            for p in ps[vistos:]:
                yield evento("paso", {"n": vistos + 1, "texto": p, "segundos": round(time.time() - t0, 1)})
                vistos += 1
            if hecho:
                break
            if time.time() - t0 > expedientes.TOPE_S:
                yield evento("falla", {"detail": f"La generación superó los {expedientes.TOPE_S} s y sigue en segundo plano"})
                return
            await asyncio.sleep(0.25)
        try:
            yield evento("listo", expedientes.esperar(r, t0))
        except expedientes.FallaGeneracion as err:
            yield evento("falla", {"detail": str(err)})

    return StreamingResponse(flujo(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/expediente/{eid}/expediente.pdf", tags=["expediente"])
def expediente_pdf(eid: str):
    f = expedientes.ruta_pdf(eid)
    if f is None:
        raise HTTPException(404, f"No existe el expediente {eid}")
    return FileResponse(f, media_type="application/pdf", filename=f"{eid}.pdf", content_disposition_type="inline")
