"""Respaldo estático de la API: guarda la respuesta de cada ruta GET como archivo, para que la página funcione sin
backend (docs/spec-demo.md, "Almacenamiento y transporte").

Pide cada ruta a la misma aplicación de api/main.py (en proceso, sin red), así el respaldo y la API no se desalinean.
Una ruta por archivo: /api/zonas/Z2/ranking -> <salida>/zonas/Z2/ranking.json; las que ya tienen extensión (ruta.gpx,
ruta.geojson) se guardan tal cual. `indice.json` lista lo guardado, con la versión de los datos.

Qué predios llevan ficha y serie:
  --predios alerta   (por defecto) los del mapa: banda alta y media, casos, vecindarios de validación y paradas de ruta
  --predios demo     solo los casos, sus vecindarios, las paradas de las rutas y los candidatos de data/demo.json

No incluye el expediente (POST): la página usa los PDF de respaldo de <salida>/expedientes/, que este script no toca.

Uso (desde la raíz del repo):
  uv run --with-requirements api/requirements.txt python -m api.respaldo
  uv run --with-requirements api/requirements.txt python -m api.respaldo --predios demo --salida /tmp/respaldo
"""

import argparse
import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from . import datos
from .main import app

SALIDA = datos.RAIZ / "frontend-demo" / "data" / "respaldo"


def archivo(ruta: str) -> str:
    r = ruta.removeprefix("/api/")
    return r if "." in r.rsplit("/", 1)[-1] else r + ".json"


def predios_demo() -> set[int]:
    d = datos.demo()
    ids = {int(d["candidato"]), int(d.get("alternativa", {}).get("candidato", d["candidato"]))}
    for c in datos.casos()["casos"]:
        ids |= {c["predio_id"], *c["vecindario"]} - {None}
    for z in datos.zonas_def():
        ids |= {int(p["predio_id"]) for p in datos.ruta(z)["paradas"]}
    return ids


def rutas(predios: str) -> list[str]:
    out = ["/api/health", "/api/demo", "/api/impacto", "/api/zonas", "/api/casos"]
    out += [f"/api/casos/{c['expediente']}" for c in datos.casos()["casos"]]
    ids = predios_demo()
    for z in datos.zonas_def():
        out += [f"/api/zonas/{z}/{r}" for r in ("resumen", "ranking", "predios", "ruta", "ruta.gpx", "ruta.geojson")]
        if predios == "alerta":
            ids |= set(datos._seleccion_mapa(z))
    for pid in sorted(ids):
        out += [f"/api/predios/{pid}", f"/api/predios/{pid}/serie"]
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--predios", choices=["alerta", "demo"], default="alerta")
    ap.add_argument("--salida", default=str(SALIDA))
    args = ap.parse_args()
    salida = Path(args.salida)
    # Borra solo lo que escribió la corrida anterior (indice.json): la carpeta también guarda los PDF de respaldo.
    if (salida / "indice.json").exists():
        for x in json.loads((salida / "indice.json").read_text(encoding="utf-8"))["rutas"]:
            (salida / x["archivo"]).unlink(missing_ok=True)
    guardados, fallas, peso = [], [], 0
    with TestClient(app) as cliente:
        for ruta in rutas(args.predios):
            r = cliente.get(ruta)
            if r.status_code != 200:
                fallas.append(f"{ruta}: {r.status_code} {r.text[:120]}")
                continue
            f = salida / archivo(ruta)
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(r.content)
            guardados.append({"ruta": ruta, "archivo": archivo(ruta)})
            peso += len(r.content)
        v = datos.version()
    (salida / "indice.json").write_text(json.dumps(
        {"version": v, "predios": args.predios, "generado_por": "api/respaldo.py", "rutas": guardados},
        ensure_ascii=False), encoding="utf-8")
    print(f"{len(guardados)} rutas guardadas en {salida} ({peso / 1e6:.1f} MB), versión {v.get('commit')}")
    for x in fallas:
        print("FALLA", x, file=sys.stderr)
    return 1 if fallas else 0


if __name__ == "__main__":
    sys.exit(main())
