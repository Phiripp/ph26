# /// script
# requires-python = ">=3.11"
# dependencies = ["geopandas>=1.0", "pyarrow", "shapely>=2.0"]
# ///
"""Polígonos de referencia de secano para las zonas de data/zonas.json (tarea D11).

Fuente: CONAF, cambio de uso de la tierra 2001-2019 (región de Valparaíso), servicio
USO_DE_LA_TIERRA_CUT_CONAF, capa 5, en IDE Minagri. Se toman las clases de "Praderas y Matorrales"
(código de uso 03xxxx) de las comunas de cada zona.

La capa no separa riego de secano. Una pradera o un matorral que fue lo mismo en 2001, 2013, 2016, 2017 y 2019
(columna `estable`) casi seguro no se riega: sirve de referencia para las anomalías de verdor y humedad (M2).

CONAF llega hasta 2019, y desde entonces se plantaron huertos en laderas que eran matorral. Para no usar riego como
referencia de secano, se recortan de cada polígono los huertos del Catastro Frutícola de CIREN 2025 (capa 59), con
un margen de 20 m, y se descartan los restos de menos de `--area-min-ha`. Esto solo cubre huertos frutales: otros
riegos posteriores a 2019 no se ven aquí y hay que revisarlos con el NDVI de verano (M2).

Entradas: data/zonas.json.
Caché: data/raw/conaf/<COMUNA>.geojson (una por comuna) y data/raw/conaf/catastro_fruticola_2025.geojson (no van a git).
Salida: data/processed/referencia_secano.parquet (GeoParquet, EPSG:4326), una fila por polígono CONAF:
  ref_id, zona, comuna, clase (matorral, matorral_arborescente, matorral_pradera, matorral_suculentas,
  pradera_anual), uso_cod, area_ha (EPSG:32719, después del recorte y antes de simplificar), estable (siempre True),
  recortado_fruta (bool: se le quitó algún huerto), geometry.
Solo quedan los polígonos estables 2001-2019 y no se incluye la estepa andina (cordillera alta, otro régimen de
humedad y sin predios agrícolas). La geometría se simplifica a 10 m (el píxel de Sentinel-2): sin eso la capa
pesa más de 100 MB por los vértices de CONAF.

Uso: uv run scripts/extract/referencia_secano_conaf.py [--refrescar] [--area-min-ha 1] [--simplificar-m 10]
"""

import argparse
import json
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path

import geopandas as gpd
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from comun.rutas import DATA, ZONAS, mostrar  # noqa: E402
RAW = DATA / "raw" / "conaf"
URL = "https://esri.ciren.cl/server/rest/services/IDEMINAGRI/USO_DE_LA_TIERRA_CUT_CONAF/MapServer/5/query"
PAGINA = 2000  # maxRecordCount del servicio
CRS_METROS = "EPSG:32719"
URL_FRUTICOLA = "https://esri.ciren.cl/server/rest/services/IDEMINAGRI/CATASTRO_FRUTICOLA/MapServer/59/query"
MARGEN_HUERTO_M = 20
CAMPOS = "objectid,uso_01,uso_13,uso_16,uso_17,uso_19,des_uso_19,nom_com,sup_ha"
# Código de uso 2019 -> clase de referencia. 0301xx praderas (solo la anual es secano de verano seco),
# 0302 matorral-pradera, 0303 matorral, 0304 matorral arborescente, 0305 matorral con suculentas.
CLASES = {
    "030103": "pradera_anual",
    "030105": "estepa_andina",
    "030200": "matorral_pradera",
    "030300": "matorral",
    "030400": "matorral_arborescente",
    "030500": "matorral_suculentas",
}


def normalizar(nombre: str) -> str:
    sin_tildes = unicodedata.normalize("NFD", nombre).encode("ascii", "ignore").decode()
    return sin_tildes.upper().strip()


def pedir(params: dict, reintentos: int = 3) -> dict:
    url = URL + "?" + urllib.parse.urlencode(params)
    for intento in range(reintentos):
        try:
            with urllib.request.urlopen(url, timeout=120) as r:
                return json.loads(r.read())
        except Exception as e:  # noqa: BLE001
            if intento == reintentos - 1:
                raise RuntimeError(f"falló la consulta a CONAF: {type(e).__name__}") from None
            time.sleep(3 * (intento + 1))
    raise AssertionError("inalcanzable")


def descargar_comuna(comuna: str, destino: Path) -> None:
    """Baja por páginas todos los polígonos de pradera y matorral de una comuna."""
    donde = f"nom_com = '{comuna.title()}' AND uso_19 LIKE '03%'"
    # La capa guarda los nombres como "La Ligua"; title() alcanza para las 10 comunas de las zonas.
    features, offset = [], 0
    while True:
        resp = pedir(
            {
                "where": donde,
                "outFields": CAMPOS,
                "outSR": 4326,
                "orderByFields": "objectid",
                "resultOffset": offset,
                "resultRecordCount": PAGINA,
                "f": "geojson",
            }
        )
        if "error" in resp:
            raise RuntimeError(f"CONAF devolvió un error: {resp['error']}")
        lote = resp.get("features", [])
        features += lote
        if len(lote) < PAGINA:
            break
        offset += PAGINA
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps({"type": "FeatureCollection", "features": features}))


def descargar_fruticola(zonas: dict, destino: Path) -> None:
    """Huertos del Catastro Frutícola 2025 que tocan el bounding box de cada zona."""
    features, vistos = [], set()
    for cfg in zonas.values():
        offset = 0
        while True:
            url = URL_FRUTICOLA + "?" + urllib.parse.urlencode(
                {
                    "geometry": ",".join(str(v) for v in cfg["bbox"]),
                    "geometryType": "esriGeometryEnvelope",
                    "inSR": 4326,
                    "spatialRel": "esriSpatialRelIntersects",
                    "outFields": "mslink",
                    "outSR": 4326,
                    "orderByFields": "objectid",
                    "resultOffset": offset,
                    "resultRecordCount": 2000,
                    "f": "geojson",
                }
            )
            with urllib.request.urlopen(url, timeout=120) as r:
                lote = json.loads(r.read()).get("features", [])
            features += [f for f in lote if f["properties"]["mslink"] not in vistos]
            vistos.update(f["properties"]["mslink"] for f in lote)
            if len(lote) < 2000:
                break
            offset += 2000
    destino.write_text(json.dumps({"type": "FeatureCollection", "features": features}))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--refrescar", action="store_true")
    ap.add_argument("--area-min-ha", type=float, default=1.0, help="descarta polígonos más chicos (unos 10 píxeles de 10 m)")
    ap.add_argument("--simplificar-m", type=float, default=10.0, help="tolerancia de simplificación en metros")
    args = ap.parse_args()

    zonas = json.loads((ZONAS).read_text())["zonas"]
    partes = []
    for zona, cfg in zonas.items():
        for comuna in cfg["comunas"]:
            ruta = RAW / f"{normalizar(comuna)}.geojson"
            if args.refrescar or not ruta.exists():
                descargar_comuna(comuna, ruta)
            gdf = gpd.read_file(ruta)
            print(f"{zona} {normalizar(comuna):<10} {len(gdf):>5} polígonos de pradera y matorral")
            if gdf.empty:
                continue
            gdf["zona"], gdf["comuna"] = zona, normalizar(comuna)
            partes.append(gdf)
    gdf = gpd.GeoDataFrame(pd.concat(partes, ignore_index=True), crs="EPSG:4326")

    ruta_fruta = RAW / "catastro_fruticola_2025.geojson"
    if args.refrescar or not ruta_fruta.exists():
        descargar_fruticola(zonas, ruta_fruta)
    huertos = gpd.read_file(ruta_fruta).to_crs(CRS_METROS)
    print(f"{len(huertos)} huertos del Catastro Frutícola 2025")

    gdf["uso_cod"] = gdf["uso_19"]
    gdf["clase"] = gdf["uso_cod"].map(CLASES)
    gdf = gdf[gdf["clase"].notna()].copy()
    gdf["estable"] = (gdf[["uso_01", "uso_13", "uso_16", "uso_17"]].eq(gdf["uso_19"], axis=0)).all(axis=1)
    metros = gdf.to_crs(CRS_METROS)
    mascara = huertos.buffer(MARGEN_HUERTO_M).union_all()
    recortado = metros.difference(mascara)
    gdf["recortado_fruta"] = ~recortado.geom_equals(metros.geometry)
    gdf["geometry"] = recortado.to_crs("EPSG:4326")
    gdf = gdf[~gdf.is_empty].copy()
    gdf["area_ha"] = (gdf.to_crs(CRS_METROS).area / 10_000).round(3)
    gdf = gdf[(gdf["area_ha"] >= args.area_min_ha) & gdf["estable"] & (gdf["clase"] != "estepa_andina")].copy()
    simple = gdf.to_crs(CRS_METROS).simplify(args.simplificar_m, preserve_topology=True)
    gdf["geometry"] = simple.make_valid().to_crs("EPSG:4326")  # la simplificación deja algunos polígonos inválidos
    gdf["ref_id"] = gdf["objectid"].astype(int)
    gdf = gdf.drop_duplicates("ref_id").sort_values(["zona", "comuna", "ref_id"]).reset_index(drop=True)
    gdf = gdf[["ref_id", "zona", "comuna", "clase", "uso_cod", "area_ha", "estable", "recortado_fruta", "geometry"]]

    salida = DATA / "processed" / "referencia_secano.parquet"
    salida.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_parquet(salida, index=False)

    print(f"\n{mostrar(salida)}: {len(gdf)} polígonos, {salida.stat().st_size / 1e6:.1f} MB")
    print(f"recortados por huertos: {int(gdf['recortado_fruta'].sum())} polígonos")
    resumen = gdf.groupby(["zona", "estable", "clase"]).agg(poligonos=("ref_id", "size"), ha=("area_ha", "sum")).round(0)
    print(resumen.to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
