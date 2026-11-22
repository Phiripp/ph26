# /// script
# requires-python = ">=3.11"
# dependencies = ["geopandas>=1.0", "pandas", "pyarrow", "numpy", "scipy", "shapely>=2.0", "xarray", "zarr", "dask", "fsspec", "aiohttp"]
# ///
"""Lluvia y ET0 diarias de ERA5-Land ARCO (Zarr geo-chunked de ECMWF), por celdas de 0,1° con predios (tarea D2).

Reemplaza a d2_clima_openmeteo.py + d2_clima_unir.py en la corrida nacional: Open-Meteo no alcanza con miles de
celdas (docs/spec-chile.md#clima-era5-land-arco-geo-chunked). Escribe el mismo esquema de clima.parquet y
predio_clima.parquet, con `fuente` y el prefijo de `celda_id` en `era5land`.

Fuente: cuatro Zarr horarios (temperatura, lluvia y presión, viento, radiación) de la misma grilla de 0,1°.
Acceso con la clave de la API de CDS (cuenta gratuita y licencia de ERA5-Land aceptada) como `Authorization: Bearer`,
en la variable CDS_API_KEY. Sin clave, o con el valor `PENDIENTE`, el script termina con un mensaje claro.

De horario a diario (día local, America/Santiago):
- lluvia: suma de la precipitación horaria (mm);
- temperatura: máxima, mínima y media; presión de vapor real desde el punto de rocío medio;
- viento: medio a 10 m, llevado a 2 m con FAO-56 ec. 47;
- radiación: suma en MJ/m².
ET0: Penman-Monteith diario de FAO-56 (ec. 6; Rn desde Rs, Rso y Tmax/Tmin; G = 0), el mismo método de Open-Meteo
(`et0_fao_evapotranspiration`). La altura de la celda sale de la presión de superficie (FAO-56 ec. 7 al revés).
Solo se guardan los días locales completos (24 horas).

Sin corrección de estaciones (`correccion = "ninguna"`, `lluvia_corr_mm = lluvia_mm`): la grilla sobreestima la
lluvia cerca de 2 veces, así que M1 debe correr con `--umbral-mm 2`.

Entradas: data/zonas.json (o CAUDAL_ZONAS) y data/processed/predio.parquet (solo los elegibles);
          data/processed/estacion_clima.parquet (opcional) para enlazar cada predio con su estación.
Salidas: data/processed/clima.parquet y data/processed/predio_clima.parquet.

Verificaciones sin clave:
  uv run scripts/extract/d2_clima_era5land.py --probar        # ET0 contra el ejemplo 18 de FAO-56 y aritmética diaria
  uv run scripts/extract/d2_clima_era5land.py --contrastar    # ET0 mensual de este clima.parquet contra el de Open-Meteo
    (criterio: error menor al 10 % en la suma mensual, ver el spec; --contrastar necesita las celdas de Z1 y Z2)

Uso: uv run scripts/extract/d2_clima_era5land.py [--hilos 4] [--lote 200]
"""

import argparse
import json
import math
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from comun.clima import PASO, enlazar_estacion  # noqa: E402
from comun.rutas import DATA, PROC, ZONAS, mostrar  # noqa: E402

ARCO = "https://arco.datastores.ecmwf.int/{id}/arco/reanalysis_era5_land/{grupo}/geoChunked.zarr"
# Grupo -> (id del Zarr, variables canónicas). Verificado con los .zmetadata de ECMWF: las variables del Zarr son las
# siglas de ERA5 (t2m, d2m, tp, sp, u10, v10, ssrd), float32, dims (time, latitude, longitude), grilla global de 0,1°
# (1801 x 3600) y chunks [33792, 4, 8]: 3,9 años x 0,4° de latitud x 0,8° de longitud. CANDIDATOS acepta además el
# nombre largo del CDS.
GRUPOS = {
    "temperatura": ("cadl-arco-geo-007", "sfc-2m-temperature", ["2m_temperature", "2m_dewpoint_temperature"]),
    "presion_lluvia": ("cadl-arco-geo-009", "sfc-pressure-precipitation", ["total_precipitation", "surface_pressure"]),
    "viento": ("cadl-arco-geo-008", "sfc-wind", ["10m_u_component_of_wind", "10m_v_component_of_wind"]),
    "radiacion": ("cadl-arco-geo-010", "sfc-radiation-heat", ["surface_solar_radiation_downwards"]),
}
CANDIDATOS = {
    "2m_temperature": ["t2m", "2m_temperature"],
    "2m_dewpoint_temperature": ["d2m", "2m_dewpoint_temperature"],
    "total_precipitation": ["tp", "total_precipitation"],
    "surface_pressure": ["sp", "surface_pressure"],
    "10m_u_component_of_wind": ["u10", "10m_u_component_of_wind"],
    "10m_v_component_of_wind": ["v10", "10m_v_component_of_wind"],
    "surface_solar_radiation_downwards": ["ssrd", "surface_solar_radiation_downwards"],
}
NOMBRES_EJE = {"lat": ["latitude", "lat"], "lon": ["longitude", "lon"], "tiempo": ["time", "valid_time"]}
TZ = "America/Santiago"
HORAS_DIA = 24

# --- FAO-56 -----------------------------------------------------------------------------------------------------


def presion_vapor_saturacion(t_c):
    """e°(T) en kPa (FAO-56 ec. 11)."""
    return 0.6108 * np.exp(17.27 * t_c / (t_c + 237.3))


def radiacion_extraterrestre(lat_grados, doy):
    """Ra en MJ/m²/día (FAO-56 ecs. 21 a 25)."""
    phi = np.radians(lat_grados)
    dr = 1 + 0.033 * np.cos(2 * np.pi * doy / 365)
    delta = 0.409 * np.sin(2 * np.pi * doy / 365 - 1.39)
    ws = np.arccos(np.clip(-np.tan(phi) * np.tan(delta), -1, 1))
    gsc = 0.0820
    return 24 * 60 / np.pi * gsc * dr * (ws * np.sin(phi) * np.sin(delta) + np.cos(phi) * np.cos(delta) * np.sin(ws))


def altura_desde_presion(p_kpa):
    """Altura en m desde la presión (FAO-56 ec. 7 al revés)."""
    return (293.0 - 293.0 * (np.asarray(p_kpa) / 101.3) ** (1 / 5.26)) / 0.0065


def et0_fao56(tmax, tmin, tmedia, ea, rs, u2, p_kpa, lat_grados, doy, z=None):
    """ET0 diaria Penman-Monteith (mm/día), con G = 0. Acepta escalares o arreglos de numpy.

    tmax, tmin y tmedia en °C; ea en kPa; rs en MJ/m²/día; u2 en m/s a 2 m; p_kpa presión de superficie; z altura en m
    (si no se da, sale de la presión).
    """
    z = altura_desde_presion(p_kpa) if z is None else z
    es = (presion_vapor_saturacion(tmax) + presion_vapor_saturacion(tmin)) / 2
    delta = 4098 * presion_vapor_saturacion(tmedia) / (tmedia + 237.3) ** 2
    gamma = 0.000665 * p_kpa
    ra = radiacion_extraterrestre(lat_grados, doy)
    rso = (0.75 + 2e-5 * z) * ra
    rns = 0.77 * rs
    sigma = 4.903e-9
    razon = np.clip(rs / np.where(rso > 0, rso, np.nan), 0.3, 1.0)
    razon = np.where(np.isnan(razon), 0.3, razon)
    rnl = sigma * ((tmax + 273.16) ** 4 + (tmin + 273.16) ** 4) / 2 * (0.34 - 0.14 * np.sqrt(np.maximum(ea, 0))) * (1.35 * razon - 0.35)
    rn = rns - rnl
    et0 = (0.408 * delta * rn + gamma * 900 / (tmedia + 273) * u2 * (es - ea)) / (delta + gamma * (1 + 0.34 * u2))
    return np.maximum(et0, 0.0)


def viento_a_2m(u10):
    """FAO-56 ec. 47."""
    return u10 * 4.87 / math.log(67.8 * 10 - 5.42)


# --- De horario a diario ----------------------------------------------------------------------------------------


def desacumular(valor: pd.Series, hora_utc: pd.Series) -> pd.Series:
    """Pasa una variable acumulada desde las 00 UTC a valores por hora (la acumulación se reinicia a la 01 UTC)."""
    previo = valor.shift(1)
    inc = valor - previo
    reinicio = (hora_utc == 1) | previo.isna()
    return inc.where(~reinicio, valor).clip(lower=0)


def es_acumulada(ssrd: pd.Series, hora_utc: pd.Series) -> bool:
    """La radiación acumulada vale su máximo del día a las 00 UTC; la horaria vale cerca de 0 a esa hora en Chile."""
    return bool(ssrd[hora_utc == 0].mean() > ssrd[hora_utc == 12].mean())


def a_diario(h: pd.DataFrame, lat_celda: pd.Series) -> pd.DataFrame:
    """Horario (columnas de `COLUMNAS_HORARIAS`, un registro por celda y hora UTC) a diario local con ET0.

    Entrada en unidades de ERA5: K, Pa, m, m/s y J/m². `h` trae `celda_id` y `hora` (UTC, sin zona).
    """
    h = h.copy()
    h["local"] = pd.DatetimeIndex(h["hora"]).tz_localize("UTC").tz_convert(TZ)
    h["fecha"] = h["local"].dt.tz_localize(None).dt.normalize()
    h["t"] = h["t2m"] - 273.15
    h["td"] = h["d2m"] - 273.15
    h["p"] = h["sp"] / 1000
    h["viento"] = np.hypot(h["u10"], h["v10"])
    g = h.groupby(["celda_id", "fecha"])
    d = pd.DataFrame({
        "n_horas": g["t"].size(),
        "tmax": g["t"].max(), "tmin": g["t"].min(), "tmedia": g["t"].mean(),
        "td": g["td"].mean(), "p": g["p"].mean(), "viento10": g["viento"].mean(),
        "lluvia_mm": g["tp_mm"].sum(), "rs": g["ssrd_mj"].sum(),
    }).reset_index()
    d = d[d["n_horas"] == HORAS_DIA].drop(columns="n_horas")  # solo días locales completos
    d["ea"] = presion_vapor_saturacion(d["td"])
    d["et0_mm"] = et0_fao56(
        d["tmax"].to_numpy(), d["tmin"].to_numpy(), d["tmedia"].to_numpy(), d["ea"].to_numpy(), d["rs"].to_numpy(),
        viento_a_2m(d["viento10"].to_numpy()), d["p"].to_numpy(), d["celda_id"].map(lat_celda).to_numpy(),
        d["fecha"].dt.day_of_year.to_numpy(),
    )
    d["lluvia_mm"] = d["lluvia_mm"].clip(lower=0)
    return d[["celda_id", "fecha", "lluvia_mm", "et0_mm"]].round({"lluvia_mm": 2, "et0_mm": 2})


# --- Lectura del Zarr ----------------------------------------------------------------------------------------------


def clave_cds() -> str:
    clave = os.environ.get("CDS_API_KEY", "").strip()
    if not clave or clave == "PENDIENTE":
        sys.exit("Falta CDS_API_KEY: crea una cuenta en el CDS, acepta la licencia de ERA5-Land y guarda la clave en el "
                 "secreto CDS_API_KEY (docs/spec-chile.md, clima). El paso de clima no puede correr sin ella.")
    return clave


def eje(ds, clave: str) -> str:
    for nombre in NOMBRES_EJE[clave]:
        if nombre in ds.dims or nombre in ds.coords:
            return nombre
    sys.exit(f"El Zarr no tiene un eje {clave} entre {NOMBRES_EJE[clave]}; tiene {list(ds.dims)}")


def variable(ds, canonica: str) -> str:
    for nombre in CANDIDATOS[canonica]:
        if nombre in ds.data_vars:
            return nombre
    sys.exit(f"El Zarr no tiene {canonica} ({CANDIDATOS[canonica]}); tiene {list(ds.data_vars)}")


def abrir(grupo: str, clave: str):
    import xarray as xr

    id_zarr, nombre, _ = GRUPOS[grupo]
    url = ARCO.format(id=id_zarr, grupo=nombre)
    return xr.open_zarr(url, consolidated=True, storage_options={"headers": {"Authorization": f"Bearer {clave}"}})


def indices_celdas(ds, celdas: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    lat, lon = ds[eje(ds, "lat")].to_numpy(), ds[eje(ds, "lon")].to_numpy()
    lon_celdas = celdas["celda_lon"].to_numpy()
    if lon.max() > 180:  # grilla de 0 a 360 en vez de -180 a 180: no se supone, se mira
        lon_celdas = lon_celdas % 360
    ilat = np.abs(lat[:, None] - celdas["celda_lat"].to_numpy()[None, :]).argmin(axis=0)  # sirve con latitud 90 -> -90
    ilon = np.abs(lon[:, None] - lon_celdas[None, :]).argmin(axis=0)
    return ilat, ilon


def leer_celdas(ds, canonicas: list[str], celdas: pd.DataFrame, t0: str, t1: str, hilos: int) -> pd.DataFrame:
    """Serie horaria de las celdas en un grupo. Las celdas se agrupan por chunk del Zarr para bajar cada uno una vez."""
    import xarray as xr

    nombres = [variable(ds, c) for c in canonicas]
    sub = ds[nombres].sel({eje(ds, "tiempo"): slice(t0, t1)})
    ilat, ilon = indices_celdas(ds, celdas)
    chunks = ds[nombres[0]].encoding.get("chunks") or ds[nombres[0]].data.chunksize
    dims = ds[nombres[0]].dims
    clat, clon = chunks[dims.index(eje(ds, "lat"))], chunks[dims.index(eje(ds, "lon"))]
    clave_chunk = pd.Series(list(zip(ilat // clat, ilon // clon)))

    def leer(pos: np.ndarray) -> pd.DataFrame:
        puntos = sub.isel({eje(ds, "lat"): xr.DataArray(ilat[pos], dims="celda"),
                           eje(ds, "lon"): xr.DataArray(ilon[pos], dims="celda")}).load()
        df = puntos.to_dataframe().reset_index()
        df["celda_id"] = celdas["celda_id"].to_numpy()[pos][df["celda"].to_numpy()]
        return df.rename(columns={eje(ds, "tiempo"): "hora", **dict(zip(nombres, canonicas))})[["celda_id", "hora", *canonicas]]

    grupos = [np.array(ix) for ix in clave_chunk.groupby(clave_chunk).groups.values()]
    with ThreadPoolExecutor(hilos) as ex:
        return pd.concat(list(ex.map(leer, grupos)), ignore_index=True)


def horario(celdas: pd.DataFrame, inicio: str, fin: str, hilos: int, acumulacion: str) -> pd.DataFrame:
    """Une los cuatro grupos y deja las unidades listas para `a_diario`."""
    clave = clave_cds()
    t0 = (pd.Timestamp(inicio) - pd.Timedelta(days=1)).strftime("%Y-%m-%dT00:00")  # el día local parte la víspera en UTC
    t1 = (pd.Timestamp(fin) + pd.Timedelta(days=2)).strftime("%Y-%m-%dT00:00")
    partes = []
    for grupo, (_, _, canonicas) in GRUPOS.items():
        print(f"  leyendo {grupo} ({len(celdas)} celdas)")
        partes.append(leer_celdas(abrir(grupo, clave), canonicas, celdas, t0, t1, hilos).set_index(["celda_id", "hora"]))
    h = pd.concat(partes, axis=1).reset_index().sort_values(["celda_id", "hora"]).reset_index(drop=True)
    h = h.rename(columns={"2m_temperature": "t2m", "2m_dewpoint_temperature": "d2m", "surface_pressure": "sp",
                          "10m_u_component_of_wind": "u10", "10m_v_component_of_wind": "v10"})
    hora = pd.DatetimeIndex(h["hora"]).hour
    hora = pd.Series(hora, index=h.index)
    acum = {"si": True, "no": False}.get(acumulacion)
    if acum is None:
        acum = es_acumulada(h["surface_solar_radiation_downwards"], hora)
    print(f"  precipitación y radiación {'acumuladas desde las 00 UTC: se desacumulan' if acum else 'ya vienen por hora'}")
    for origen, destino, factor in (("total_precipitation", "tp_mm", 1000.0), ("surface_solar_radiation_downwards", "ssrd_mj", 1e-6)):
        v = h[origen] * factor
        if acum:
            v = h.assign(v=v).groupby("celda_id")["v"].transform(lambda s: desacumular(s, hora.loc[s.index]))
        h[destino] = v
    return h.drop(columns=["total_precipitation", "surface_solar_radiation_downwards"])


# --- Celdas de los predios ------------------------------------------------------------------------------------------


def celda_id(zona: str, lat: float, lon: float) -> str:
    return f"ERA5_{zona}_{lat:.1f}_{lon:.1f}".replace("-", "m")


def asignar_celdas(predios) -> pd.DataFrame:
    """Predio -> punto de grilla ERA5-Land más cercano (la grilla de 0,1° cae en múltiplos de 0,1)."""
    pts = predios.to_crs("EPSG:32719").geometry.centroid.to_crs("EPSG:4326")  # centroide en metros, no en grados
    df = pd.DataFrame({"predio_id": predios["predio_id"].to_numpy(), "zona": predios["zona"].to_numpy(),
                       "lat": pts.y.to_numpy(), "lon": pts.x.to_numpy()})
    df["celda_lat"] = (np.round(df["lat"] / PASO) * PASO).round(1)
    df["celda_lon"] = (np.round(df["lon"] / PASO) * PASO).round(1)
    df["celda_id"] = [celda_id(z, a, o) for z, a, o in zip(df["zona"], df["celda_lat"], df["celda_lon"])]
    return df


COLUMNAS_CLIMA = ["zona", "punto_id", "fuente", "fecha", "lluvia_mm", "lluvia_corr_mm", "et0_mm", "estacion_ref_id",
                  "lluvia_dato_faltante", "dia_parcial", "correccion"]


def armar_clima(diario: pd.DataFrame, celdas: pd.DataFrame) -> pd.DataFrame:
    """Esquema de clima.parquet (D2). Sin corrección de estaciones: lluvia_corr_mm = lluvia_mm."""
    c = diario.merge(celdas[["celda_id", "zona"]], on="celda_id")
    return pd.DataFrame({
        "zona": c["zona"], "punto_id": c["celda_id"], "fuente": "era5land", "fecha": c["fecha"],
        "lluvia_mm": c["lluvia_mm"], "lluvia_corr_mm": c["lluvia_mm"], "et0_mm": c["et0_mm"],
        "estacion_ref_id": pd.NA, "lluvia_dato_faltante": False, "dia_parcial": False, "correccion": "ninguna",
    })[COLUMNAS_CLIMA].sort_values(["zona", "punto_id", "fecha"]).reset_index(drop=True)


# --- Verificaciones sin clave ------------------------------------------------------------------------------------


def probar() -> int:
    """ET0 contra el ejemplo 18 de FAO-56 (Bruselas, 6 de julio; ET0 = 3,9 mm/día) y aritmética horario -> diario."""
    ea = 1.409  # kPa, del ejemplo (humedad relativa máxima y mínima)
    et0 = float(et0_fao56(21.5, 12.3, 16.9, ea, 22.07, 2.078, 100.1, 50.8, 187, z=100))
    print(f"FAO-56 ejemplo 18: ET0 = {et0:.2f} mm/día (esperado 3,9)")
    assert abs(et0 - 3.9) < 0.1, "ET0 no calza con el ejemplo 18 de FAO-56"

    ra = float(radiacion_extraterrestre(50.8, 187))
    assert abs(ra - 41.09) < 0.2, f"Ra = {ra}"
    assert abs(float(altura_desde_presion(101.3))) < 1e-9 and abs(float(altura_desde_presion(100.1)) - 100) < 10

    # Aritmética horario -> diario: 3 días locales completos con valores constantes y una lluvia de 24 mm repartida.
    horas = pd.date_range("2026-01-10 03:00", periods=24 * 3, freq="h")  # 00:00 local = 03:00 UTC (verano, UTC-3)
    n = len(horas)
    h = pd.DataFrame({
        "celda_id": "ERA5_prueba", "hora": horas, "t2m": 293.15 + 5 * np.sin((horas.hour - 9) / 24 * 2 * np.pi),
        "d2m": 283.15, "sp": 95_000.0, "u10": 2.0, "v10": 0.0, "tp_mm": 24 / 24 * (np.arange(n) < 24),
        "ssrd_mj": np.where((horas.hour >= 12) & (horas.hour <= 23), 3.0, 0.0),
    })
    d = a_diario(h, pd.Series({"ERA5_prueba": -32.5}))
    print(d.to_string(index=False))
    assert len(d) == 3 and abs(d["lluvia_mm"].iloc[0] - 24) < 1e-6 and (d["lluvia_mm"].iloc[1:] == 0).all()
    assert d["et0_mm"].between(1, 9).all(), "ET0 fuera de rango plausible"

    # Desacumulación: acumulado desde las 00 UTC con reinicio a la 01 UTC.
    horas = pd.date_range("2026-01-10 00:00", periods=48, freq="h")
    por_hora = pd.Series(np.where(horas.hour % 6 == 0, 1.0, 0.0))
    acum = por_hora.groupby((horas - pd.Timedelta(hours=1)).normalize()).cumsum()
    rec = desacumular(acum, pd.Series(horas.hour))
    assert np.allclose(rec.iloc[1:].to_numpy(), por_hora.iloc[1:].to_numpy()), "desacumular no recupera la serie horaria"
    print("pruebas ok")
    return 0


def contrastar(salida: Path) -> int:
    """Suma mensual de ET0 de este clima.parquet contra la celda de Open-Meteo más cercana (Z1 y Z2)."""
    era = pd.read_parquet(salida)
    era = era[era["fuente"] == "era5land"]
    om = pd.read_parquet(PROC / "clima.parquet")
    om = om[om["fuente"] == "openmeteo"]

    def coord(punto_id: str) -> tuple[float, float]:
        lat, lon = re.findall(r"m?\d+\.\d+", punto_id)[-2:]
        return float(lat.replace("m", "-")), float(lon.replace("m", "-"))

    om_c = {p: coord(p) for p in om["punto_id"].unique()}
    filas = []
    for p in era["punto_id"].unique():
        la, lo = coord(p)
        cerca = min(om_c, key=lambda q: (om_c[q][0] - la) ** 2 + (om_c[q][1] - lo) ** 2)
        if (om_c[cerca][0] - la) ** 2 + (om_c[cerca][1] - lo) ** 2 > 0.1**2:
            continue  # la celda de Open-Meteo más cercana está a más de 0,1°: no es comparable
        a = era[era["punto_id"] == p].set_index("fecha")["et0_mm"]
        b = om[om["punto_id"] == cerca].set_index("fecha")["et0_mm"]
        j = pd.concat([a.rename("era5"), b.rename("openmeteo")], axis=1, join="inner").dropna()
        m = j.groupby(j.index.to_period("M")).sum()
        m["celda"] = p
        filas.append(m.reset_index(names="mes"))
    if not filas:
        sys.exit("Ninguna celda de ERA5-Land cae a menos de 0,1° de una celda de Open-Meteo (¿hay Z1 y Z2 en clima.parquet?)")
    t = pd.concat(filas)
    t["error_pct"] = (t["era5"] / t["openmeteo"] - 1) * 100
    print(t.groupby("mes")[["era5", "openmeteo", "error_pct"]].mean().round(1).to_string())
    peor = t["error_pct"].abs().max()
    print(f"\nError máximo en la suma mensual: {peor:.1f} % (criterio: menos de 10 %)")
    return 0 if peor < 10 else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--hilos", type=int, default=4, help="chunks del Zarr leídos en paralelo")
    ap.add_argument("--lote", type=int, default=200, help="celdas por lectura (acota la memoria)")
    ap.add_argument("--acumulacion", choices=["auto", "si", "no"], default="auto",
                    help="si la lluvia y la radiación del Zarr vienen acumuladas desde las 00 UTC (confirmar en el piloto)")
    ap.add_argument("--probar", action="store_true", help="verifica ET0 y el paso a diario sin red ni clave")
    ap.add_argument("--contrastar", action="store_true", help="compara con la ET0 de Open-Meteo en data/processed/clima.parquet")
    args = ap.parse_args()
    salida = PROC / "clima.parquet"
    if args.probar:
        return probar()
    if args.contrastar:
        return contrastar(salida)

    import geopandas as gpd

    cfg = json.loads(ZONAS.read_text())
    inicio, fin = cfg["periodo"]["inicio"], cfg["periodo"]["fin"]
    if not fin[:1].isdigit():  # "ultima_escena_limpia": el reanálisis llega hasta unos 5 días antes de hoy
        fin = (date.today() - timedelta(days=6)).isoformat()

    predios = gpd.read_parquet(PROC / "predio.parquet")
    predios = predios[predios["elegible"]]
    print(f"{len(predios)} predios elegibles")
    asignados = enlazar_estacion(asignar_celdas(predios), PROC / "estacion_clima.parquet")
    celdas = asignados.drop_duplicates("celda_id")[["celda_id", "zona", "celda_lat", "celda_lon"]].reset_index(drop=True)
    print(celdas.groupby("zona").size().rename("celdas").to_string())

    clave_cds()  # falla ya, antes de armar nada, si falta la clave
    lat_celda = celdas.set_index("celda_id")["celda_lat"]
    partes = []
    for i in range(0, len(celdas), args.lote):
        lote = celdas.iloc[i : i + args.lote]
        print(f"celdas {i + 1}-{i + len(lote)} de {len(celdas)}")
        d = a_diario(horario(lote, inicio, fin, args.hilos, args.acumulacion), lat_celda)
        partes.append(d[(d["fecha"] >= inicio) & (d["fecha"] <= fin)])
    clima = armar_clima(pd.concat(partes, ignore_index=True), celdas)

    huecos = clima[["lluvia_mm", "et0_mm"]].isna().sum()
    esperados = (pd.Timestamp(fin) - pd.Timestamp(inicio)).days + 1
    incompletas = clima.groupby("punto_id").size().lt(esperados).sum()
    PROC.mkdir(parents=True, exist_ok=True)
    clima.to_parquet(salida, index=False)
    asignados[["predio_id", "zona", "celda_id", "estacion_id", "distancia_estacion_km"]].to_parquet(
        PROC / "predio_clima.parquet", index=False)
    print(f"\n{mostrar(salida)}: {len(clima)} filas, {clima['fecha'].min().date()} a {clima['fecha'].max().date()}")
    print(f"huecos: lluvia {huecos['lluvia_mm']}, et0 {huecos['et0_mm']}; celdas con menos de {esperados} días: {incompletas}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
