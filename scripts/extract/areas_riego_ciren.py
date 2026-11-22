# /// script
# requires-python = ">=3.11"
# dependencies = ["geopandas>=1.0", "pyarrow", "shapely>=2.0"]
# ///
"""Áreas de riego de CIREN por canal y tipo de agua, Región de Valparaíso (estudio FNDR de infraestructura de riego).

Capa 4 ("AREAS DE RIEGO") del servicio PROYECTOS_CIREN/FNDR_INFRA_RIEGO: 8.576 polígonos con el canal matriz y el
canal de la zona de riego que los abastece (`nom_can_ma`, `nom_can_zr`) y `tipo_agu` (SUPERFICIAL, SUBTERRANEA,
MIXTO). Sirve para saber si un predio riega con agua de canal (acciones de una comunidad de aguas o asociación de
canalistas), que no aparece predio a predio en el registro de derechos de la DGA. Es mejor indicio que `canal_300m`
(distancia a un canal): dice qué superficie abastece cada canal, no solo por dónde pasa.

Solo existe para Valparaíso (el estudio es regional): el bbox de otra región devuelve cero polígonos.

Salida: data/raw/ciren_riego/areas_riego.parquet (no va a git: capa de CIREN, sin términos de uso).

Uso: uv run scripts/extract/areas_riego_ciren.py
"""

import json
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from comun.arcgis import paginar  # noqa: E402
from comun.rutas import DATA, ZONAS  # noqa: E402

URL = "https://esri.ciren.cl/server/rest/services/PROYECTOS_CIREN/FNDR_INFRA_RIEGO/MapServer/4/query"
PAGINA = 1000
CAMPOS = ["objectid", "nom_com", "cod_cue", "cod_scue", "tipo_agu", "cod_can_ma", "nom_can_ma", "cod_can_zr",
          "nom_can_zr", "area_has", "acuiferos"]


def bajar_bbox(bbox: list[float]) -> gpd.GeoDataFrame:
    params = {"geometry": ",".join(map(str, bbox)), "geometryType": "esriGeometryEnvelope", "inSR": "4326",
              "spatialRel": "esriSpatialRelIntersects", "outFields": ",".join(CAMPOS), "outSR": "4326", "f": "geojson"}
    partes = [gpd.GeoDataFrame.from_features(c["features"], crs="EPSG:4326") for c in paginar(URL, params, PAGINA)]
    if not partes:
        return gpd.GeoDataFrame(columns=[*CAMPOS, "geometry"], geometry="geometry", crs="EPSG:4326")
    return gpd.GeoDataFrame(pd.concat(partes, ignore_index=True), crs="EPSG:4326")


def main() -> None:
    zonas = json.loads(ZONAS.read_text(encoding="utf-8"))["zonas"]
    areas = pd.concat([bajar_bbox(z["bbox"]) for z in zonas.values()], ignore_index=True)
    areas = gpd.GeoDataFrame(areas.drop_duplicates("objectid"), crs="EPSG:4326")
    areas["tipo_agu"] = areas["tipo_agu"].fillna("").str.strip().str.upper()
    destino = DATA / "raw" / "ciren_riego" / "areas_riego.parquet"
    destino.parent.mkdir(parents=True, exist_ok=True)
    areas.to_parquet(destino, index=False)
    ha = areas.to_crs("EPSG:32719").area.groupby(areas["tipo_agu"]).sum() / 10_000
    print(f"Áreas de riego: {len(areas)} polígonos -> {destino}")
    print(pd.DataFrame({"poligonos": areas["tipo_agu"].value_counts(), "ha": ha.round(0)}).to_string())


if __name__ == "__main__":
    main()
