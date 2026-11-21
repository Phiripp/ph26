"""Funciones de clima compartidas por los extractores de celdas (Open-Meteo y ERA5-Land)."""

import math
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

PASO = 0.1  # grados: lado de la celda de clima
KM_POR_GRADO = 111.32


def km(lat1, lon1, lat2, lon2) -> float:
    """Distancia en km con la aproximación equirectangular (suficiente a decenas de km)."""
    dy = (lat2 - lat1) * KM_POR_GRADO
    dx = (lon2 - lon1) * KM_POR_GRADO * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot(dx, dy)


def enlazar_estacion(predios: pd.DataFrame, ruta_estaciones: Path) -> pd.DataFrame:
    """Estación DMC más cercana (con serie válida) al centroide de cada predio.

    `predios` trae `lat` y `lon`. Se busca con un cKDTree en km locales; la distancia que se guarda se calcula igual
    que antes (`km`) para la estación elegida. Un bucle predio por estación en Python no escala a 400 mil predios.
    """
    predios = predios.assign(estacion_id=pd.NA, distancia_estacion_km=float("nan"))
    if not ruta_estaciones.exists():
        print("Sin estacion_clima.parquet: predio_clima queda sin estación (corre d2_clima_dmc.py).")
        return predios
    est = pd.read_parquet(ruta_estaciones)
    est = est[~est["descartada"]].drop_duplicates("punto_id").reset_index(drop=True)
    if est.empty:
        return predios
    cos_lat = math.cos(math.radians(float(predios["lat"].mean())))

    def plano(lat, lon):
        return np.column_stack([np.asarray(lat) * KM_POR_GRADO, np.asarray(lon) * KM_POR_GRADO * cos_lat])

    # El árbol usa un plano local y `km` usa el coseno de la latitud media de cada par: se toman los 4 candidatos del
    # árbol y se elige el más cercano con `km`, así el resultado es el mismo que comparar con todas las estaciones.
    k = min(4, len(est))
    _, cand = cKDTree(plano(est["lat"], est["lon"])).query(plano(predios["lat"], predios["lon"]), k=k)
    cand = cand.reshape(len(predios), k)
    lat, lon = predios["lat"].to_numpy()[:, None], predios["lon"].to_numpy()[:, None]
    dy = (est["lat"].to_numpy()[cand] - lat) * KM_POR_GRADO
    dx = (est["lon"].to_numpy()[cand] - lon) * KM_POR_GRADO * np.cos(np.radians((est["lat"].to_numpy()[cand] + lat) / 2))
    dist = np.hypot(dx, dy)
    mejor = dist.argmin(axis=1)
    i = cand[np.arange(len(predios)), mejor]
    predios["estacion_id"] = est["punto_id"].to_numpy()[i]
    predios["distancia_estacion_km"] = dist[np.arange(len(predios)), mejor].round(1)
    return predios
