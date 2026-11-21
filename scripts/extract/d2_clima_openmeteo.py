# /// script
# requires-python = ">=3.11"
# dependencies = ["geopandas>=1.0", "pandas", "pyarrow", "requests", "shapely>=2.0"]
# ///
"""ET0 y lluvia diaria de Open-Meteo, por celdas que contienen predios (tarea D2, paso 3).

Open-Meteo tiene unos 10 km de resolución, así que no se pide un punto por predio: se asigna cada predio
a una celda de 0,1° (según su centroide) y se piden solo las celdas únicas.

Entradas: data/zonas.json y data/processed/predio.parquet (si no existe, predio_muestra.geojson).
          data/processed/estacion_clima.parquet (opcional, de d2_clima_dmc.py) para enlazar cada predio con su estación.
Caché: data/raw/clima/openmeteo/<celda_id>.json (no va a git).
Salidas:
- data/raw/clima/openmeteo_diario.parquet: una fila por (celda, fecha) con lluvia_mm y et0_mm.
- data/processed/predio_clima.parquet: predio_id, zona, celda_id, estacion_id y distancia_estacion_km.

Open-Meteo sobreestima la lluvia cerca de 2 veces frente a las estaciones (docs/pruebas-acceso-datos.md):
aquí se guarda cruda; la corrección va en d2_clima_unir.py. La ET0 sí se usa tal cual.

Uso: uv run scripts/extract/d2_clima_openmeteo.py [--refrescar] [--lote 5]
"""

import argparse
import json
import math
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import geopandas as gpd
import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from comun.rutas import DATA, ZONAS, mostrar  # noqa: E402
RAW = DATA / "raw" / "clima" / "openmeteo"
URL = "https://archive-api.open-meteo.com/v1/archive"
PASO = 0.1  # grados
KM_POR_GRADO = 111.32


def centro_celda(valor: float) -> float:
    return round(math.floor(valor / PASO) * PASO + PASO / 2, 2)


def celda_id(zona: str, lat: float, lon: float) -> str:
    return f"OM_{zona}_{lat:.2f}_{lon:.2f}".replace("-", "m")


def leer_predios() -> gpd.GeoDataFrame:
    parquet = DATA / "processed" / "predio.parquet"
    if parquet.exists():
        gdf = gpd.read_parquet(parquet)
        origen = parquet
    else:
        origen = DATA / "processed" / "predio_muestra.geojson"
        gdf = gpd.read_file(origen)
    if "rol_valido" in gdf:
        gdf = gdf[gdf["rol_valido"]]
    print(f"{len(gdf)} predios válidos desde {mostrar(origen)}")
    return gdf


def asignar_celdas(gdf: gpd.GeoDataFrame) -> pd.DataFrame:
    # Centroide en metros (EPSG:32719) y de vuelta a grados, para no calcular centroides en grados.
    pts = gdf.to_crs("EPSG:32719").geometry.centroid.to_crs("EPSG:4326")
    df = pd.DataFrame(
        {"predio_id": gdf["predio_id"].to_numpy(), "zona": gdf["zona"].to_numpy(), "lat": pts.y.to_numpy(), "lon": pts.x.to_numpy()}
    )
    df["celda_lat"] = df["lat"].map(centro_celda)
    df["celda_lon"] = df["lon"].map(centro_celda)
    df["celda_id"] = [celda_id(z, a, o) for z, a, o in zip(df["zona"], df["celda_lat"], df["celda_lon"])]
    return df


def km(lat1, lon1, lat2, lon2) -> float:
    dy = (lat2 - lat1) * KM_POR_GRADO
    dx = (lon2 - lon1) * KM_POR_GRADO * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot(dx, dy)


def enlazar_estacion(predios: pd.DataFrame) -> pd.DataFrame:
    """Estación DMC más cercana (con serie válida) al centroide de cada predio."""
    ruta = DATA / "processed" / "estacion_clima.parquet"
    predios = predios.assign(estacion_id=pd.NA, distancia_estacion_km=float("nan"))
    if not ruta.exists():
        print("Sin estacion_clima.parquet: predio_clima queda sin estación (corre d2_clima_dmc.py).")
        return predios
    est = pd.read_parquet(ruta)
    est = est[~est["descartada"]].drop_duplicates("punto_id")
    mejor_id, mejor_d = [], []
    for lat, lon in zip(predios["lat"], predios["lon"]):
        ds = [km(lat, lon, la, lo) for la, lo in zip(est["lat"], est["lon"])]
        i = min(range(len(ds)), key=ds.__getitem__)
        mejor_id.append(est["punto_id"].iloc[i])
        mejor_d.append(round(ds[i], 1))
    predios["estacion_id"] = mejor_id
    predios["distancia_estacion_km"] = mejor_d
    return predios


def pedir_lote(celdas: pd.DataFrame, inicio: str, fin: str) -> list[dict]:
    params = {
        "latitude": ",".join(f"{v:.2f}" for v in celdas["celda_lat"]),
        "longitude": ",".join(f"{v:.2f}" for v in celdas["celda_lon"]),
        "start_date": inicio,
        "end_date": fin,
        "daily": "precipitation_sum,et0_fao_evapotranspiration",
        "timezone": "America/Santiago",
    }
    for intento in range(6):
        r = requests.get(URL, params=params, timeout=120)
        if r.status_code == 200:
            data = r.json()
            return data if isinstance(data, list) else [data]
        if r.status_code == 429:
            espera = 30 * (intento + 1)
            print(f"  límite de Open-Meteo (429); espero {espera} s", file=sys.stderr)
            time.sleep(espera)
            continue
        r.raise_for_status()
    raise RuntimeError("Open-Meteo siguió respondiendo 429")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--refrescar", action="store_true")
    ap.add_argument("--lote", type=int, default=5, help="celdas por llamada")
    args = ap.parse_args()

    cfg = json.loads((ZONAS).read_text())
    inicio = cfg["periodo"]["inicio"]
    # `fin` puede ser "ultima_escena_limpia" (no es una fecha): el clima llega hasta hace unos días.
    fin = cfg["periodo"]["fin"]
    if not fin[:1].isdigit():
        fin = (date.today() - timedelta(days=6)).isoformat()

    predios = enlazar_estacion(asignar_celdas(leer_predios()))
    celdas = predios.drop_duplicates("celda_id")[["celda_id", "zona", "celda_lat", "celda_lon"]].reset_index(drop=True)
    print(celdas.groupby("zona").size().rename("celdas").to_string())

    RAW.mkdir(parents=True, exist_ok=True)
    pendientes = celdas if args.refrescar else celdas[~celdas["celda_id"].map(lambda c: (RAW / f"{c}.json").exists())]
    for i in range(0, len(pendientes), args.lote):
        lote = pendientes.iloc[i : i + args.lote]
        print(f"  pidiendo {i + 1}-{i + len(lote)} de {len(pendientes)}")
        for (_, fila), resp in zip(lote.iterrows(), pedir_lote(lote, inicio, fin)):
            (RAW / f"{fila['celda_id']}.json").write_text(json.dumps(resp["daily"]))
        time.sleep(1)

    partes = []
    for _, fila in celdas.iterrows():
        d = json.loads((RAW / f"{fila['celda_id']}.json").read_text())
        df = pd.DataFrame(
            {"fecha": pd.to_datetime(d["time"]), "lluvia_mm": d["precipitation_sum"], "et0_mm": d["et0_fao_evapotranspiration"]}
        )
        df.insert(0, "zona", fila["zona"])
        df.insert(1, "punto_id", fila["celda_id"])
        partes.append(df)
    diario = pd.concat(partes, ignore_index=True)
    diario.insert(2, "fuente", "openmeteo")

    salida_raw = DATA / "raw" / "clima" / "openmeteo_diario.parquet"
    salida_pc = DATA / "processed" / "predio_clima.parquet"
    salida_pc.parent.mkdir(parents=True, exist_ok=True)
    diario.to_parquet(salida_raw, index=False)
    predios[["predio_id", "zona", "celda_id", "estacion_id", "distancia_estacion_km"]].to_parquet(salida_pc, index=False)

    huecos = diario[["lluvia_mm", "et0_mm"]].isna().sum()
    print(f"\n{mostrar(salida_raw)}: {len(diario)} filas, {diario['fecha'].min().date()} a {diario['fecha'].max().date()}")
    print(f"huecos: lluvia {huecos['lluvia_mm']}, et0 {huecos['et0_mm']}")
    print(f"{mostrar(salida_pc)}: {len(predios)} predios")
    return 0


if __name__ == "__main__":
    sys.exit(main())
