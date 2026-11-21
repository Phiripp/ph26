# /// script
# requires-python = ">=3.11"
# dependencies = ["geopandas>=1.0", "pyarrow", "shapely>=2.0"]
# ///
"""Especie frutal por predio desde el Catastro Frutícola CIREN 2025 (tarea D7).

Los polígonos del catastro son cuarteles plantados (mediana 1,45 ha), no predios. Por eso el cruce es
por superficie: para cada predio elegible se suma la superficie plantada de cada especie que cae dentro.
El rol del catastro (`rolpredi`) solo se usa para medir la coincidencia con el predio.

Entradas: data/zonas.json y data/processed/predio.parquet (correr antes predios_ciren.py).

Salidas:
- data/raw/ciren_fruticola/cuarteles.parquet: cuarteles de las comunas de Z1 y Z2 (caché; no va a git).
- data/processed/predio_cultivo.parquet: un registro por predio elegible, sin geometría (va a git).

Uso: uv run scripts/extract/cultivos_ciren.py [--refrescar]
"""

import argparse
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

import geopandas as gpd
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from comun.rutas import DATA, ZONAS  # noqa: E402
URL = "https://esri.ciren.cl/server/rest/services/IDEMINAGRI/CATASTRO_FRUTICOLA/MapServer/59/query"
PAGINA = 2000  # maxRecordCount del servicio
CRS_METROS = "EPSG:32719"
MIN_SOLAPE_HA = 0.05  # ignora astillas de borde entre cuarteles y predios vecinos


def descargar(comunas: list[str], destino: Path) -> None:
    where = "desccomu IN ({})".format(",".join(f"'{c}'" for c in comunas))
    partes, offset = [], 0
    while True:
        params = {"where": where, "outFields": "*", "outSR": "4326", "f": "geojson",
                  "resultOffset": offset, "resultRecordCount": PAGINA, "orderByFields": "objectid"}
        req = urllib.request.Request(URL, data=urllib.parse.urlencode(params).encode(),
                                     headers={"User-Agent": "caudal-hackathon/0.1"})
        with urllib.request.urlopen(req, timeout=120) as r:
            cuerpo = json.load(r)
        if "error" in cuerpo:
            sys.exit(f"CIREN devolvió un error: {cuerpo['error']}")
        # from_features: GDAL intenta seguir la paginación de ArcGIS por su cuenta y falla.
        g = gpd.GeoDataFrame.from_features(cuerpo["features"], crs="EPSG:4326")
        partes.append(g)
        offset += len(g)
        if len(g) < PAGINA:
            break
    cuarteles = gpd.GeoDataFrame(pd.concat(partes, ignore_index=True), crs="EPSG:4326")
    if not cuarteles["objectid"].is_unique:
        sys.exit("objectid repetido: la paginación falló")
    destino.parent.mkdir(parents=True, exist_ok=True)
    cuarteles.to_parquet(destino, index=False)
    print(f"Cuarteles descargados: {len(cuarteles)}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--refrescar", action="store_true", help="vuelve a descargar aunque exista la caché")
    args = ap.parse_args()

    if not (DATA / "processed" / "predio.parquet").exists():
        sys.exit("Falta data/processed/predio.parquet: corre antes predios_ciren.py")
    zonas = json.loads((ZONAS).read_text(encoding="utf-8"))["zonas"]
    comunas = [c for z in zonas.values() for c in z["comunas"]]
    crudo = DATA / "raw" / "ciren_fruticola" / "cuarteles.parquet"
    if args.refrescar or not crudo.exists():
        descargar(comunas, crudo)

    cuarteles = gpd.read_parquet(crudo).to_crs(CRS_METROS)
    for c in ("especie_01", "especie_02", "especie_03", "especie_04", "rolpredi", "desccomu"):
        cuarteles[c] = cuarteles[c].fillna("").str.strip()
    # Un cuartel con varias especies se reparte en partes iguales entre ellas.
    largo = cuarteles.melt(id_vars=["objectid", "rolpredi", "desccomu", "geometry"],
                           value_vars=["especie_01", "especie_02", "especie_03", "especie_04"],
                           value_name="especie").query("especie != ''")
    largo["n_especies"] = largo.groupby("objectid")["especie"].transform("size")
    largo = gpd.GeoDataFrame(largo, geometry="geometry", crs=CRS_METROS)

    predios = gpd.read_parquet(DATA / "processed" / "predio.parquet")
    predios = predios[predios["elegible"]].to_crs(CRS_METROS)[["predio_id", "zona", "comuna", "rol", "area_ha", "geometry"]]

    solape = gpd.overlay(predios, largo, how="intersection", keep_geom_type=True)
    solape["ha"] = solape.area / 10_000 / solape["n_especies"]
    solape = solape[solape["ha"] >= MIN_SOLAPE_HA / solape["n_especies"]]
    solape["rol_coincide"] = (solape["rolpredi"] == solape["rol"]) & (solape["desccomu"] == solape["comuna"])

    por_especie = solape.groupby(["predio_id", "especie"])["ha"].sum().reset_index()
    principal = por_especie.sort_values("ha", ascending=False).drop_duplicates("predio_id").set_index("predio_id")
    resumen = solape.groupby("predio_id").agg(
        area_fruticola_ha=("ha", "sum"),
        n_cuarteles=("objectid", "nunique"),
        rol_coincide=("rol_coincide", "any"),
    )
    resumen["especie_principal"] = principal["especie"]
    resumen["especies"] = por_especie.sort_values("ha", ascending=False).groupby("predio_id")["especie"].agg(
        lambda s: ";".join(s))

    salida = predios.drop(columns=["geometry", "rol"]).set_index("predio_id").join(resumen)
    salida["area_fruticola_ha"] = salida["area_fruticola_ha"].fillna(0.0).round(2)
    salida["frac_fruticola"] = (salida["area_fruticola_ha"] / salida["area_ha"]).clip(upper=1.0).round(3)
    salida["n_cuarteles"] = salida["n_cuarteles"].fillna(0).astype(int)
    salida["con_frutales"] = salida["n_cuarteles"] > 0
    salida["rol_coincide"] = salida["rol_coincide"].astype("boolean")
    salida = salida.reset_index()

    destino = DATA / "processed" / "predio_cultivo.parquet"
    salida.to_parquet(destino, index=False)

    con = salida[salida["con_frutales"]]
    print(f"Predios elegibles: {len(salida)}; con frutales: {len(con)} ({len(con) / len(salida):.0%})")
    print(pd.crosstab(salida["zona"], salida["con_frutales"]).to_string())
    print(f"\nSuperficie frutal en predios elegibles: {con['area_fruticola_ha'].sum():,.0f} ha "
          f"de {cuarteles.area.sum() / 10_000:,.0f} ha del catastro en las comunas")
    print(f"Predios con frutales cuyo rol coincide con algún cuartel: {con['rol_coincide'].mean():.0%}")
    print("\nEspecie principal:\n" + con["especie_principal"].value_counts().head(10).to_string())
    print(f"\n-> {destino}")


if __name__ == "__main__":
    main()
