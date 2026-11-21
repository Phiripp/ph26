# /// script
# requires-python = ">=3.11"
# dependencies = ["geopandas>=1.0", "pyarrow", "shapely>=2.0"]
# ///
"""Canales de riego CNR/CIREN 2020 para las zonas de data/zonas.json (parte de la tarea D8).

Capa 1 de INFRAESTRUCTURA_RIEGO (la capa 0 son bocatomas). Sirve para:
- marcar predios que pueden regar con agua de canal (acciones), que no aparece como derecho con volumen;
- el campo "canal cercano" del expediente.

Salida: data/raw/ciren_riego/canales.parquet (no va a git: capa de CIREN, sin términos de uso).

Uso: uv run scripts/extract/canales_ciren.py
"""

import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

import geopandas as gpd
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from comun.rutas import DATA, ZONAS  # noqa: E402
URL = "https://esri.ciren.cl/server/rest/services/IDEMINAGRI/INFRAESTRUCTURA_RIEGO/MapServer/1/query"
PAGINA = 2000
CAMPOS = ["objectid", "codcan", "nomcan", "tipo_canal", "fuentehid", "origen", "oua", "oua_tipo", "jv", "n_acciones"]


def bajar_bbox(bbox: list[float]) -> gpd.GeoDataFrame:
    partes, offset = [], 0
    while True:
        params = {"geometry": ",".join(map(str, bbox)), "geometryType": "esriGeometryEnvelope", "inSR": "4326",
                  "spatialRel": "esriSpatialRelIntersects", "outFields": ",".join(CAMPOS), "outSR": "4326",
                  "f": "geojson", "resultOffset": offset, "resultRecordCount": PAGINA, "orderByFields": "objectid"}
        req = urllib.request.Request(URL, data=urllib.parse.urlencode(params).encode(),
                                     headers={"User-Agent": "caudal-hackathon/0.1"})
        with urllib.request.urlopen(req, timeout=120) as r:
            cuerpo = json.load(r)
        if "error" in cuerpo:
            sys.exit(f"CIREN devolvió un error: {cuerpo['error']}")
        g = gpd.GeoDataFrame.from_features(cuerpo["features"], crs="EPSG:4326")  # ver cultivos_ciren.py
        partes.append(g)
        offset += len(g)
        if len(g) < PAGINA:
            return gpd.GeoDataFrame(pd.concat(partes, ignore_index=True), crs="EPSG:4326")


def main() -> None:
    zonas = json.loads((ZONAS).read_text(encoding="utf-8"))["zonas"]
    canales = pd.concat([bajar_bbox(z["bbox"]) for z in zonas.values()], ignore_index=True)
    canales = gpd.GeoDataFrame(canales.drop_duplicates("objectid"), crs="EPSG:4326")
    destino = DATA / "raw" / "ciren_riego" / "canales.parquet"
    destino.parent.mkdir(parents=True, exist_ok=True)
    canales.to_parquet(destino, index=False)
    km = canales.to_crs("EPSG:32719").length.sum() / 1000
    print(f"Canales: {len(canales)} tramos, {km:,.0f} km -> {destino}")


if __name__ == "__main__":
    main()
