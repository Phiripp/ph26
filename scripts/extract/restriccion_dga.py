# /// script
# requires-python = ">=3.11"
# dependencies = ["geopandas>=1.0", "pyarrow", "shapely>=2.0"]
# ///
"""Zonas de prohibición y áreas de restricción de acuíferos de la DGA, y su cruce con los predios (tarea D10).

Fuente: servicio ArcGIS de la DGA, capa 0 de
https://rest-sit.mop.gob.cl/arcgis/rest/services/DGA/Areas_de_Restriccion_y_Zonas_de_Prohibicion/MapServer
(un polígono por sector hidrogeológico, SHAC). El servidor es ArcGIS 10.21: solo responde Esri JSON.

Entradas: data/zonas.json y data/processed/predio.parquet.

Salidas (dato público; va a git):
- data/processed/restriccion.parquet: un polígono por SHAC que toca Z1 o Z2 (`zona` es la primera en que cae; la
  columna `zonas` lista todas), con `tipo_limite` (prohibicion, restriccion o abierto), resolución y fechas.
- data/processed/predio_restriccion.parquet: por predio elegible, el SHAC donde cae la mayor parte de su
  superficie, con `tipo_limite`, `frac_en_shac` y `en_prohibicion` (True si el SHAC dominante es de prohibición) y `toca_prohibicion` (True si el predio
  intersecta algún SHAC de prohibición, aunque el dominante sea otro).
  Un predio sin ningún SHAC queda con `cod_shac` vacío (no es "abierto": no hay dato).

Uso: uv run scripts/extract/restriccion_dga.py
"""

import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import MultiPolygon, Polygon

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from comun.rutas import DATA, ZONAS  # noqa: E402
URL = ("https://rest-sit.mop.gob.cl/arcgis/rest/services/DGA/"
       "Areas_de_Restriccion_y_Zonas_de_Prohibicion/MapServer/0/query")
CAMPOS = ["OBJECTID", "COD_SHAC", "NOM_ACUIF", "SHAC", "TIPO_LIMIT", "RES_DGA", "F_RES_DGA", "F_PUB_DO",
          "TIPOESTUDI", "REGION", "FECHA_ACTUALIZACION"]
CRS_METROS = "EPSG:32719"
PAGINA = 50
TIPOS = {"Zona de Prohibicion": "prohibicion", "Area de Restriccion": "restriccion", "Abierto": "abierto"}


def _area_firmada(anillo: list) -> float:
    return sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(anillo, anillo[1:] + anillo[:1])) / 2


def esri_a_shapely(anillos: list) -> MultiPolygon | Polygon | None:
    """Anillos Esri: horario = exterior, antihorario = hueco (cada hueco va al exterior que lo contiene)."""
    exteriores, huecos = [], []
    for a in anillos:
        pts = [tuple(p[:2]) for p in a]
        if len(pts) < 4:
            continue
        (exteriores if _area_firmada(pts) < 0 else huecos).append(pts)
    if not exteriores:
        return None
    polys = [Polygon(e) for e in exteriores]
    asignados = [[] for _ in polys]
    for h in huecos:
        hp = Polygon(h)
        for i, p in enumerate(polys):
            if p.contains(hp.representative_point()):
                asignados[i].append(h)
                break
    polys = [Polygon(e, hs) for e, hs in zip(exteriores, asignados)]
    return polys[0] if len(polys) == 1 else MultiPolygon(polys)


def bajar_bbox(bbox: list[float]) -> gpd.GeoDataFrame:
    filas, offset = [], 0
    while True:
        params = {"geometry": ",".join(map(str, bbox)), "geometryType": "esriGeometryEnvelope", "inSR": "4326",
                  "spatialRel": "esriSpatialRelIntersects", "outFields": ",".join(CAMPOS), "outSR": "4326",
                  "returnGeometry": "true", "f": "json", "resultOffset": offset, "resultRecordCount": PAGINA,
                  "orderByFields": "OBJECTID"}
        req = urllib.request.Request(URL, data=urllib.parse.urlencode(params).encode(),
                                     headers={"User-Agent": "caudal-hackathon/0.1"})
        with urllib.request.urlopen(req, timeout=180) as r:
            cuerpo = json.load(r)
        if "error" in cuerpo:
            sys.exit(f"El servidor de la DGA devolvió un error: {cuerpo['error']}")
        feats = cuerpo.get("features", [])
        if not feats:
            return gpd.GeoDataFrame(filas, geometry="geometry", crs="EPSG:4326")
        for f in feats:
            geom = esri_a_shapely(f.get("geometry", {}).get("rings") or [])
            filas.append({**f["attributes"], "geometry": geom})
        offset += len(feats)
        if len(feats) < PAGINA and not cuerpo.get("exceededTransferLimit"):
            return gpd.GeoDataFrame(filas, geometry="geometry", crs="EPSG:4326")


def fecha(ms) -> pd.Timestamp:
    return pd.NaT if ms is None or pd.isna(ms) else pd.to_datetime(ms, unit="ms").normalize()


def main() -> None:
    if not (DATA / "processed" / "predio.parquet").exists():
        sys.exit("Falta data/processed/predio.parquet: corre antes predios_ciren.py")
    zonas = json.loads((ZONAS).read_text(encoding="utf-8"))["zonas"]
    partes = []
    for z, info in zonas.items():
        g = bajar_bbox(info["bbox"]).assign(zona=z)
        partes.append(g[g.geometry.notna()])
    todo = pd.concat(partes, ignore_index=True)
    zonas_por_shac = todo.groupby("COD_SHAC")["zona"].agg(lambda s: ",".join(sorted(set(s))))
    capa = gpd.GeoDataFrame(todo.drop_duplicates("COD_SHAC"), crs="EPSG:4326")

    sectores = pd.DataFrame({
        "cod_shac": capa["COD_SHAC"], "acuifero": capa["NOM_ACUIF"], "sector": capa["SHAC"].str.strip(),
        "tipo_limite": capa["TIPO_LIMIT"].map(TIPOS).fillna(capa["TIPO_LIMIT"]),
        "resolucion_dga": capa["RES_DGA"].astype("Int64"),
        "fecha_resolucion": capa["F_RES_DGA"].map(fecha), "fecha_publicacion_do": capa["F_PUB_DO"].map(fecha),
        "tipo_estudio": capa["TIPOESTUDI"], "region": capa["REGION"], "zona": capa["zona"],
        "zonas": capa["COD_SHAC"].map(zonas_por_shac), "geometry": capa.geometry,
    })
    sectores = gpd.GeoDataFrame(sectores, crs="EPSG:4326")
    sectores.to_parquet(DATA / "processed" / "restriccion.parquet", index=False)

    predios = gpd.read_parquet(DATA / "processed" / "predio.parquet")
    if "elegible" not in predios:  # versiones antiguas de predio.parquet: rol válido y 1 ha o más (7.911 predios)
        predios["elegible"] = predios["rol_valido"] & (predios["area_ha"] >= 1)
    predios = predios[predios["elegible"]].to_crs(CRS_METROS)[["predio_id", "zona", "geometry"]]
    predios["area_m2"] = predios.geometry.area
    sec_m = sectores.to_crs(CRS_METROS)[["cod_shac", "sector", "tipo_limite", "resolucion_dga", "fecha_resolucion", "geometry"]]
    inter = gpd.overlay(predios[["predio_id", "geometry"]], sec_m, how="intersection", keep_geom_type=True)
    inter["m2"] = inter.geometry.area
    mejor = inter.sort_values("m2", ascending=False).drop_duplicates("predio_id")
    salida = predios.drop(columns="geometry").merge(
        mejor[["predio_id", "cod_shac", "sector", "tipo_limite", "resolucion_dga", "fecha_resolucion", "m2"]],
        on="predio_id", how="left")
    salida["frac_en_shac"] = (salida["m2"] / salida["area_m2"]).clip(upper=1).round(3)
    salida["en_prohibicion"] = salida["tipo_limite"].eq("prohibicion")
    toca = gpd.sjoin(predios[["predio_id", "geometry"]],
                     sec_m.loc[sec_m["tipo_limite"] == "prohibicion", ["geometry"]], predicate="intersects")
    salida["toca_prohibicion"] = salida["predio_id"].isin(toca["predio_id"])
    salida = salida.drop(columns=["m2", "area_m2"])
    salida.to_parquet(DATA / "processed" / "predio_restriccion.parquet", index=False)

    print(f"SHAC que tocan las zonas: {len(sectores)}")
    print(sectores.groupby(["zona", "tipo_limite"]).size().to_string())
    print(f"\nPredios elegibles: {len(salida)}; sin SHAC: {salida['cod_shac'].isna().sum()}")
    print(salida.groupby(["zona", "tipo_limite"], dropna=False).size().to_string())
    print(f"En prohibición: {salida['en_prohibicion'].mean():.1%}; toca prohibición: {salida['toca_prohibicion'].mean():.1%}")
    print(f"\n-> {DATA / 'processed' / 'restriccion.parquet'}\n-> {DATA / 'processed' / 'predio_restriccion.parquet'}")


if __name__ == "__main__":
    main()
