"""Consultas a servidores ArcGIS REST con reintentos y paginación.

Los servidores de CIREN, DGA y SMA se caen o limitan cuando 14 tareas piden a la vez (docs/spec-chile.md, riesgos):
`pedir` reintenta con espera exponencial y `paginar` sigue por `orderByFields` + `resultOffset` hasta recibir una
página vacía, sin confiar en `maxRecordCount` ni en `exceededTransferLimit` (que no todos los servicios informan).
"""

import json
import sys
import time
import urllib.parse
import urllib.request
from collections.abc import Iterator

USER_AGENT = "caudal-hackathon/0.1"


def pedir(url: str, params: dict, reintentos: int = 6, timeout: int = 180) -> dict:
    """POST a un endpoint /query; reintenta errores de red, HTTP y los `error` de ArcGIS."""
    datos = urllib.parse.urlencode(params).encode()
    for intento in range(reintentos):
        try:
            req = urllib.request.Request(url, data=datos, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                cuerpo = json.load(r)
            if "error" in cuerpo:
                raise RuntimeError(f"el servidor devolvió un error: {cuerpo['error']}")
            return cuerpo
        except Exception as e:  # noqa: BLE001
            if intento == reintentos - 1:
                raise RuntimeError(f"falló la consulta a {url.split('/rest/services/')[-1]}: {type(e).__name__}: {e}") from None
            espera = 3 * 2**intento
            print(f"  reintento {intento + 1}/{reintentos - 1} en {espera} s ({type(e).__name__})", file=sys.stderr)
            time.sleep(espera)
    raise AssertionError("inalcanzable")


def paginar(url: str, params: dict, pagina: int, orden: str = "objectid", inicio: int = 0) -> Iterator[dict]:
    """Entrega el cuerpo de cada página (con `features`) hasta que llega una vacía o una repetida.

    Algunos servidores (el de restricciones de la DGA en rest-sit.mop.gob.cl) ignoran `resultOffset` y devuelven
    siempre la primera página: sin el corte por página repetida, el bucle no termina nunca.
    """
    offset = inicio
    anterior = None
    while True:
        cuerpo = pedir(url, {**params, "orderByFields": orden, "resultOffset": offset, "resultRecordCount": pagina})
        features = cuerpo.get("features", [])
        if not features:
            return
        huella = json.dumps([features[0], features[-1], len(features)], sort_keys=True, default=str)
        if huella == anterior:
            return
        anterior = huella
        yield cuerpo
        offset += len(features)
