"""Expediente PDF desde la API: genera con scripts/models/expediente.py (no lo reescribe) o devuelve uno ya generado.

Reglas (docs/spec-demo.md, "Expediente"):
- Dos solicitudes con los mismos insumos devuelven el mismo expediente. La clave es predio, temporada y la huella de
  insumos de expediente.py (`hash_insumos` del registro). La respuesta lo dice (`reutilizado`) y trae la fecha de
  creación: no se presenta como recién generado algo que no lo es. Con `regenerar` se fuerza uno nuevo.
- El rol solo va en el PDF de un predio con un caso sancionado por la DGA (dato público). Para el resto, el PDF
  identifica el predio por su polígono de CIREN, salvo que se pida con `rol=True` (quien presenta la denuncia lo necesita).
- Una generación a la vez (las figuras usan pyplot, que no es seguro entre hilos); las solicitudes simultáneas del
  mismo predio esperan la misma generación.
- Si Earth Search o Esri no responden, expediente.py sigue sin imágenes (`con_imagenes: false`).
- Tope de TOPE_S segundos por solicitud: pasado el tope responde 503, y la generación termina en segundo plano; la
  siguiente solicitud la encuentra hecha.

Dónde quedan: los pregenerados van en data/processed/expedientes/ (dentro de la imagen); los nuevos, en
CAUDAL_EXPEDIENTES (en Cloud Run, /tmp/expedientes: duran lo que dura la instancia).
"""

import os
import re
import sys
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as Tardanza
from functools import lru_cache
from pathlib import Path

import pandas as pd

from . import datos

sys.path.insert(0, str(datos.RAIZ / "scripts" / "models"))

PREGENERADOS = datos.PROC / "expedientes"
NUEVOS = Path(os.environ.get("CAUDAL_EXPEDIENTES") or PREGENERADOS)
TOPE_S = int(os.environ.get("CAUDAL_TOPE_S") or 180)  # debe quedar bajo el tiempo máximo del servicio en Cloud Run (300 s)
ID = re.compile(r"^CAU-\d+-\d{12}$")

_cola = ThreadPoolExecutor(max_workers=1, thread_name_prefix="expediente")
_candado = threading.Lock()
Clave = tuple[int, str, bool]  # predio, temporada, sin rol
_en_curso: dict[Clave, Future] = {}
_pasos: dict[Clave, list[str]] = {}


class FallaGeneracion(RuntimeError):
    """La generación falló o superó el tope (503)."""


def _carpetas() -> list[Path]:
    return [NUEVOS] if NUEVOS == PREGENERADOS else [NUEVOS, PREGENERADOS]


def ruta_pdf(eid: str) -> Path | None:
    if not ID.match(eid):
        return None
    return next((c / eid / "expediente.pdf" for c in _carpetas() if (c / eid / "expediente.pdf").exists()), None)


@lru_cache(maxsize=512)
def huella(predio_id: int, temporada: str) -> str:
    """Huella de los insumos del predio (los datos no cambian mientras vive el proceso)."""
    from expediente import huella_insumos
    return huella_insumos(predio_id, temporada)


def sancionado(predio_id: int) -> bool:
    """El predio tiene un caso con multa entre los casos resueltos por la DGA (datos.casos)."""
    return any(c["predio_id"] == predio_id and (c["multa_utm"] or 0) > 0 for c in datos.casos()["casos"])


def buscar(predio_id: int, temporada: str, sin_rol: bool = False) -> dict | None:
    """El expediente más reciente del predio y la temporada generado con los insumos actuales, si su PDF existe."""
    h = huella(predio_id, temporada)
    filas = []
    for c in _carpetas():
        if (c / "registro.csv").exists():
            filas.append(pd.read_csv(c / "registro.csv", dtype={"hash_insumos": str}))
    if not filas:
        return None
    r = pd.concat(filas, ignore_index=True)
    if "sin_rol" not in r:
        r["sin_rol"] = False  # registros anteriores a la opción: todos llevan rol
    r = r[(r.predio_id == predio_id) & (r.temporada == temporada) & (r.hash_insumos == h)
          & (r.sin_rol.fillna(False).astype(bool) == sin_rol)].sort_values("fecha_creacion")
    for x in reversed(r.to_dict("records")):
        if ruta_pdf(x["id"]):
            con = x.get("con_imagenes")
            return _respuesta(x["id"], predio_id, temporada, x.get("banda_m5") or None, None, x["fecha_creacion"],
                              None if pd.isna(con) else bool(con), not sin_rol, reutilizado=True, segundos=0.0)
    return None


def _respuesta(eid, predio_id, temporada, banda, confianza, creado, con_imagenes, con_rol, reutilizado, segundos) -> dict:
    return {"id": eid, "predio_id": predio_id, "temporada": temporada, "banda": banda, "confianza": confianza,
            "reutilizado": reutilizado, "segundos": round(segundos, 1), "con_imagenes": con_imagenes, "con_rol": con_rol,
            "hash_insumos": huella(predio_id, temporada), "url_pdf": f"/api/expediente/{eid}/expediente.pdf",
            "creado": creado}


def _generar(clave: Clave) -> dict:
    from expediente import generar
    pid, t, sin_rol = clave
    e = generar(predio_id=pid, temporada=t, salida=NUEVOS, avisar=_pasos[clave].append, sin_rol=sin_rol)
    return _respuesta(e["id"], pid, t, e["banda"], e["confianza"], e["creado"], e["con_imagenes"], not sin_rol,
                      reutilizado=False, segundos=e["segundos"])


def encolar(predio_id: int, temporada: str | None = None, regenerar: bool = False,
            rol: bool | None = None) -> tuple[Clave, dict | Future]:
    """Devuelve la clave (predio, temporada, sin rol) y el expediente existente, o la generación en curso (o recién
    encolada). `rol`: None lo muestra solo si el predio tiene un caso sancionado; True o False lo fuerzan.
    Lanza datos.NoExiste o datos.SinDatos si el predio no tiene puntaje."""
    m5, _ = datos._fila_m5(predio_id, temporada)
    clave = (predio_id, m5["temporada"], not (sancionado(predio_id) if rol is None else rol))
    with _candado:
        f = _en_curso.get(clave)
        if f is not None and not f.done():
            return clave, f
        if not regenerar:
            e = buscar(*clave)
            if e:
                e["banda"], e["confianza"] = m5["banda"], m5["confianza"]
                return clave, e
        _pasos[clave] = []
        f = _en_curso[clave] = _cola.submit(_generar, clave)
        return clave, f


def esperar(f: Future, desde: float) -> dict:
    try:
        return f.result(timeout=max(TOPE_S - (time.time() - desde), 0.1))
    except Tardanza:
        raise FallaGeneracion(f"La generación superó los {TOPE_S} s y sigue en segundo plano; reintenta en unos "
                              f"segundos") from None
    except (datos.NoExiste, datos.SinDatos):
        raise
    except Exception as err:  # WeasyPrint, datos faltantes del predio en expediente.py, disco
        raise FallaGeneracion(f"No se pudo generar el expediente: {type(err).__name__}: {err}") from err


def solicitar(predio_id: int, temporada: str | None = None, regenerar: bool = False, rol: bool | None = None) -> dict:
    t0 = time.time()
    _, r = encolar(predio_id, temporada, regenerar, rol)
    return r if isinstance(r, dict) else esperar(r, t0)


def pasos(clave: Clave) -> list[str]:
    return list(_pasos.get(clave, []))
