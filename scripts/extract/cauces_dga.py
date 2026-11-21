# /// script
# requires-python = ">=3.11"
# dependencies = ["geopandas>=1.0", "pyarrow", "shapely>=2.0"]
# ///
"""Cauces de la DGA y cauce y canal más cercanos a cada predio elegible (tarea D8).

Fuente: "Red de drenajes - DGA", publicada en el servidor IDE de la SMA (capa 2). El servicio solo
responde en Esri JSON (no GeoJSON) y entrega hasta 1.000 tramos por consulta.

Entradas: data/zonas.json, data/processed/predio.parquet y, para el canal más cercano,
data/raw/ciren_riego/canales.parquet (correr antes canales_ciren.py).

Salidas:
- data/processed/cauce.parquet: tramos de cauces de Z1 y Z2 (DGA, dato público; va a git).
- data/processed/predio_cauce.parquet: por predio elegible, cauce con nombre más cercano, río o estero
  más cercano y canal más cercano, con distancias. Es lo que usa el expediente (campo "cauce cercano").

Uso: uv run scripts/extract/cauces_dga.py
"""

import json
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import MultiLineString

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from comun.arcgis import paginar  # noqa: E402
from comun.rutas import DATA, ZONAS  # noqa: E402

URL = "https://ideserver.sma.gob.cl/arcgis/rest/services/IDE/Recursos_hidricos_glaciares/MapServer/2/query"
PAGINA = 1000
CRS_METROS = "EPSG:32719"
CAMPOS = ["OBJECTID", "NOMBRE", "TIPO", "ESCALA", "COD_CUEN", "COD_SUBC", "COD_SSUBC"]
TIPOS_PRINCIPALES = {"Río", "Estero"}
TIPOS_NO_CAUCE = {"Línea de Costa"}  # no son cursos de agua; quedan en cauce.parquet pero no como cauce cercano
MAX_DIST_M = 20_000


def bajar_bbox(bbox: list[float]) -> gpd.GeoDataFrame:
    params = {"geometry": ",".join(map(str, bbox)), "geometryType": "esriGeometryEnvelope", "inSR": "4326",
              "spatialRel": "esriSpatialRelIntersects", "outFields": ",".join(CAMPOS), "outSR": "4326", "f": "json"}
    filas = []
    for cuerpo in paginar(URL, params, PAGINA, orden="OBJECTID"):
        for f in cuerpo["features"]:
            caminos = f.get("geometry", {}).get("paths") or []
            filas.append({**f["attributes"], "geometry": MultiLineString(caminos) if caminos else None})
    return gpd.GeoDataFrame(filas, geometry="geometry", crs="EPSG:4326")


def mas_cercano(predios: gpd.GeoDataFrame, capa: gpd.GeoDataFrame, prefijo: str, campos: dict) -> pd.DataFrame:
    j = gpd.sjoin_nearest(predios[["predio_id", "geometry"]], capa[list(campos) + ["geometry"]], how="left",
                          max_distance=MAX_DIST_M, distance_col=f"dist_{prefijo}_m")
    j = j.sort_values(f"dist_{prefijo}_m").loc[lambda d: ~d["predio_id"].duplicated()]
    out = j[["predio_id", *campos, f"dist_{prefijo}_m"]].rename(columns=campos)
    out[f"dist_{prefijo}_m"] = out[f"dist_{prefijo}_m"].round(0)
    return out.set_index("predio_id")


def main() -> None:
    if not (DATA / "processed" / "predio.parquet").exists():
        sys.exit("Falta data/processed/predio.parquet: corre antes predios_ciren.py")
    zonas = json.loads(ZONAS.read_text(encoding="utf-8"))["zonas"]
    cauces = pd.concat([bajar_bbox(z["bbox"]) for z in zonas.values()], ignore_index=True)
    cauces = gpd.GeoDataFrame(cauces.drop_duplicates("OBJECTID"), crs="EPSG:4326")
    cauces = cauces[cauces.geometry.notna()].rename(columns=str.lower)
    cauces["nombre"] = cauces["nombre"].fillna("").str.strip().replace("", None)
    procesados = DATA / "processed"
    cauces.to_parquet(procesados / "cauce.parquet", index=False)

    predios = gpd.read_parquet(procesados / "predio.parquet")
    predios = predios[predios["elegible"]].to_crs(CRS_METROS)[["predio_id", "zona", "geometry"]]
    c = cauces.to_crs(CRS_METROS)
    con_nombre = c[c["nombre"].notna() & ~c["tipo"].isin(TIPOS_NO_CAUCE)]
    salida = predios.drop(columns="geometry").set_index("predio_id")
    salida = salida.join(mas_cercano(predios, con_nombre, "cauce",
                                     {"nombre": "cauce_nombre", "tipo": "cauce_tipo", "cod_ssubc": "cod_subsubcuenca"}))
    salida = salida.join(mas_cercano(predios, con_nombre[con_nombre["tipo"].isin(TIPOS_PRINCIPALES)], "rio",
                                     {"nombre": "rio_nombre", "tipo": "rio_tipo"}))
    canales_f = DATA / "raw" / "ciren_riego" / "canales.parquet"
    if canales_f.exists():
        canales = gpd.read_parquet(canales_f).to_crs(CRS_METROS)
        salida = salida.join(mas_cercano(predios, canales, "canal",
                                         {"nomcan": "canal_nombre", "oua": "canal_organizacion", "fuentehid": "canal_fuente"}))
    else:
        print(f"Aviso: no está {canales_f} (corre canales_ciren.py); se omite el canal más cercano")
    salida = salida.reset_index()
    salida.to_parquet(procesados / "predio_cauce.parquet", index=False)

    km = c.length.sum() / 1000
    print(f"Cauces: {len(cauces)} tramos, {km:,.0f} km; con nombre: {cauces['nombre'].notna().mean():.0%}")
    print("Por tipo: " + ", ".join(f"{k} {v}" for k, v in cauces["tipo"].value_counts().head(6).items()))
    print(f"\nPredios elegibles: {len(salida)}")
    for p in ("cauce", "rio", "canal"):
        col = f"dist_{p}_m"
        if col in salida:
            d = salida[col]
            print(f"  {p}: mediana {d.median():,.0f} m, p90 {d.quantile(.9):,.0f} m, sin dato a {MAX_DIST_M // 1000} km: {d.isna().sum()}")
    print(f"\n-> {procesados / 'cauce.parquet'}\n-> {procesados / 'predio_cauce.parquet'}")


if __name__ == "__main__":
    main()
