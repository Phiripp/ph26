"""Rutas de datos compartidas por todos los scripts.

- CAUDAL_DATA: carpeta `data/` (por defecto, la del repo). En Cloud Run apunta a una carpeta de trabajo local
  armada desde el bucket montado en /datos.
- CAUDAL_ZONAS: archivo de zonas (por defecto data/zonas.json). En la corrida nacional es config/regiones.json,
  con el mismo esquema y zona = región.

Sin variables de entorno todo queda como antes: <repo>/data y <repo>/data/zonas.json.
"""

import os
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
DATA = Path(os.environ.get("CAUDAL_DATA") or RAIZ / "data")
PROC = DATA / "processed"
ZONAS = Path(os.environ.get("CAUDAL_ZONAS") or DATA / "zonas.json")


def mostrar(ruta: Path) -> Path:
    """Ruta relativa al repo si está dentro, para los mensajes; si no, la ruta completa."""
    ruta = Path(ruta)
    return ruta.relative_to(RAIZ) if ruta.is_relative_to(RAIZ) else ruta
