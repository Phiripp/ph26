# /// script
# requires-python = ">=3.11"
# dependencies = ["geopandas>=1.0", "pyarrow", "shapely>=2.0"]
# ///
"""Descarga los predios de CIREN para las zonas de data/zonas.json (tarea D3).

Salidas:
- data/raw/ciren/<COMUNA>.geojson: respuesta cruda de CIREN, una por comuna (caché; no va a git).
- data/processed/predio.parquet: todos los predios de Z1 y Z2 (no va a git: es la capa completa de CIREN).
- data/processed/predio_muestra.geojson: 50 predios por zona alrededor de los casos de validación (va a git).

Uso: uv run scripts/extract/predios_ciren.py [--refrescar]
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
URL = "https://esri.ciren.cl/server/rest/services/IDEMINAGRI/PROPIEDADES_RURALES/MapServer/4/query"
LIMITE_SERVICIO = 10_000
CRS_METROS = "EPSG:32719"
# Rol SII con formato manzana-predio (p. ej. "87-3"). Lo demás no es un predio:
# SR (sin rol), BC (bien común), ríos, caminos, vialidad (VP-*, RV-*), reservas.
PATRON_ROL = r"\d+-\d+"
MUESTRA_POR_ZONA = 50
# Universo elegible: rol válido y 1 ha o más (100 píxeles de 10 m). Cubre el 93 % de los predios
# con infracción por extracción de aguas en Z1 y Z2 y deja fuera el 57 % de los predios (parcelas y lotes de pozo).
ELEGIBLE_MIN_HA = 1.0


def descargar_comuna(comuna: str, destino: Path) -> None:
    params = {
        "where": f"desccomu = '{comuna}'",
        "outFields": "*",
        "outSR": "4326",
        "f": "geojson",
    }
    req = urllib.request.Request(
        URL,
        data=urllib.parse.urlencode(params).encode(),
        headers={"User-Agent": "caudal-hackathon/0.1"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        cuerpo = json.load(resp)
    if "error" in cuerpo:
        sys.exit(f"CIREN devolvió un error para {comuna}: {cuerpo['error']}")
    n = len(cuerpo.get("features", []))
    if cuerpo.get("exceededTransferLimit") or n >= LIMITE_SERVICIO:
        sys.exit(f"{comuna}: {n} predios, se llegó al límite del servicio; hay que paginar")
    if n == 0:
        sys.exit(f"{comuna}: 0 predios; revisa el nombre de la comuna en data/zonas.json")
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(cuerpo), encoding="utf-8")
    print(f"  {comuna}: {n} predios descargados")


def cargar_predios(zonas: dict, refrescar: bool) -> gpd.GeoDataFrame:
    partes = []
    for zona_id, zona in zonas.items():
        for comuna in zona["comunas"]:
            crudo = DATA / "raw" / "ciren" / f"{comuna}.geojson"
            if refrescar or not crudo.exists():
                descargar_comuna(comuna, crudo)
            gdf = gpd.read_file(crudo)
            gdf["zona"] = zona_id
            partes.append(gdf)
    gdf = gpd.GeoDataFrame(pd.concat(partes, ignore_index=True), crs="EPSG:4326")

    gdf["rol"] = gdf["rol"].fillna("").astype(str).str.strip()
    salida = gpd.GeoDataFrame(
        {
            # mslink es único en la capa; el rol se repite dentro de una comuna y a veces es "SR".
            "predio_id": gdf["mslink"].astype("int64"),
            "zona": gdf["zona"],
            "comuna": gdf["desccomu"],
            "rol": gdf["rol"],
            "rol_valido": gdf["rol"].str.fullmatch(PATRON_ROL),
            "area_ha": (gdf.to_crs(CRS_METROS).area / 10_000).round(3),
        },
        geometry=gdf.geometry,
        crs="EPSG:4326",
    )
    if salida["predio_id"].duplicated().any():
        sys.exit("predio_id (mslink) duplicado; revisa la descarga")
    salida.insert(6, "elegible", salida["rol_valido"] & (salida["area_ha"] >= ELEGIBLE_MIN_HA))
    return salida


def armar_muestra(predios: gpd.GeoDataFrame, casos: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Los predios más cercanos a cada caso de validación, MUESTRA_POR_ZONA por zona."""
    p = predios[predios["elegible"]].to_crs(CRS_METROS)
    c = casos.to_crs(CRS_METROS)
    elegidos = []
    for zona_id, casos_zona in c.groupby("zona"):
        candidatos = p[p["zona"] == zona_id]
        filas = []
        for _, caso in casos_zona.iterrows():
            dist = candidatos.distance(caso.geometry).round(0)
            filas.append(candidatos.assign(
                caso_cercano=caso["expediente"],
                dist_caso_m=dist,
                turno=dist.rank(method="first"),
            ))
        # Por turnos: el más cercano de cada caso, luego el segundo de cada caso, etc.
        # Así los casos que comparten vecinos no dejan la zona con menos de MUESTRA_POR_ZONA.
        zona_muestra = (
            pd.concat(filas)
            .sort_values(["turno", "dist_caso_m"])
            .drop_duplicates("predio_id")
            .head(MUESTRA_POR_ZONA)
            .drop(columns="turno")
        )
        elegidos.append(zona_muestra)
    return gpd.GeoDataFrame(pd.concat(elegidos), crs=CRS_METROS).to_crs("EPSG:4326")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--refrescar", action="store_true", help="vuelve a descargar aunque exista la caché")
    args = ap.parse_args()

    zonas = json.loads((ZONAS).read_text(encoding="utf-8"))["zonas"]
    print("Predios CIREN por comuna:")
    predios = cargar_predios(zonas, args.refrescar)

    procesados = DATA / "processed"
    procesados.mkdir(parents=True, exist_ok=True)
    predios.to_parquet(procesados / "predio.parquet", index=False)

    casos = gpd.read_file(DATA / "casos_validacion.geojson")
    muestra = armar_muestra(predios, casos)
    muestra.to_file(procesados / "predio_muestra.geojson", driver="GeoJSON")

    print("\nResumen:")
    print(predios.groupby("zona").agg(predios=("predio_id", "size"), rol_valido=("rol_valido", "sum"),
                                      elegibles=("elegible", "sum"),
                                      area_ha=("area_ha", "sum")).round(0).to_string())
    print(f"\nMuestra: {len(muestra)} predios -> {procesados / 'predio_muestra.geojson'}")
    print(muestra.groupby(["zona", "caso_cercano"]).size().to_string())


if __name__ == "__main__":
    main()
