# /// script
# requires-python = ">=3.11"
# dependencies = ["pandas", "pyarrow"]
# ///
"""Estaciones y lluvia diaria de la DMC para las zonas de data/zonas.json (tarea D2, pasos 1 y 2).

Paso 1: baja el catálogo de estaciones EMA y deja las que caen dentro de cada zona más un margen.
Paso 2: baja la lluvia diaria histórica (getAguaCaidaDiaria) de cada una y la guarda en formato largo.

Credenciales: DMC_USER y DMC_TOKEN, desde el entorno o desde .env (que no va a git).
Entradas: data/zonas.json.
Caché: data/raw/clima/dmc/catalogo.json y data/raw/clima/dmc/<codigo>.json (no van a git).
Salidas:
- data/processed/estacion_clima.parquet: una fila por (estación, zona), con distancia a la zona y rango de fechas con lluvia.
- data/raw/clima/dmc_lluvia_diaria.parquet: una fila por (estación, fecha); `lluvia_dato_faltante` marca los días sin registro.

La lluvia diaria de la DMC llega hasta fines de 2025; 2026 se acumula con d2_clima_dmc_diario.py.

Uso: uv run scripts/extract/d2_clima_dmc.py [--refrescar] [--margen-km 20] [--max-faltantes 0.3]
"""

import argparse
import json
import math
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from comun.rutas import DATA, RAIZ, ZONAS, mostrar  # noqa: E402
RAW = DATA / "raw" / "clima" / "dmc"
URL_CATALOGO = "https://climatologia.meteochile.gob.cl/application/servicios/getEstacionesRedEma"
# Ojo: este servicio vive en `serviciosb`, no en `servicios`.
URL_LLUVIA = "https://climatologia.meteochile.gob.cl/application/serviciosb/getAguaCaidaDiaria/{codigo}"
KM_POR_GRADO = 111.32


def cargar_env() -> None:
    env = RAIZ / ".env"
    if not env.exists():
        return
    for linea in env.read_text().splitlines():
        linea = linea.strip()
        if linea and not linea.startswith("#") and "=" in linea:
            k, v = linea.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def pedir(url: str, params: dict | None = None, reintentos: int = 3) -> bytes:
    if params:
        url += "?" + urllib.parse.urlencode(params)
    for intento in range(reintentos):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001 - se reintenta cualquier fallo de red
            if intento == reintentos - 1:
                # No imprimir la URL: lleva el token.
                raise RuntimeError(f"falló la consulta a la DMC ({type(e).__name__})") from None
            time.sleep(2 * (intento + 1))
    raise AssertionError("inalcanzable")


def arreglar_acentos(texto: str) -> str:
    """La DMC devuelve UTF-8 leído como latin-1 en algunos nombres."""
    try:
        return texto.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return texto


def distancia_a_bbox_km(lat: float, lon: float, bbox: list[float]) -> float:
    """Distancia aproximada desde un punto al rectángulo (0 si está dentro)."""
    lon_min, lat_min, lon_max, lat_max = bbox
    dlat = max(lat_min - lat, 0, lat - lat_max)
    dlon = max(lon_min - lon, 0, lon - lon_max)
    return math.hypot(dlat * KM_POR_GRADO, dlon * KM_POR_GRADO * math.cos(math.radians(lat)))


def catalogo(refrescar: bool) -> list[dict]:
    destino = RAW / "catalogo.json"
    if refrescar or not destino.exists():
        RAW.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(pedir(URL_CATALOGO))
    return json.loads(destino.read_text())["datosEstacion"]


def estaciones_candidatas(zonas: dict, margen_km: float, refrescar: bool) -> pd.DataFrame:
    filas = []
    for est in catalogo(refrescar):
        lat, lon = float(est["latitud"]), float(est["longitud"])
        for zona, cfg in zonas.items():
            d = distancia_a_bbox_km(lat, lon, cfg["bbox"])
            if d <= margen_km:
                filas.append(
                    {
                        "punto_id": str(est["codigoNacional"]),
                        "fuente": "dmc",
                        "nombre": arreglar_acentos(est["nombreEstacion"]),
                        "lat": lat,
                        "lon": lon,
                        "altura_m": est.get("altura"),
                        "zona": zona,
                        "distancia_a_zona_km": round(d, 1),
                    }
                )
    return pd.DataFrame(filas)


def descargar_lluvia(codigo: str, refrescar: bool) -> dict:
    destino = RAW / f"{codigo}.json"
    if refrescar or not destino.exists():
        crudo = pedir(
            URL_LLUVIA.format(codigo=codigo),
            {"usuario": os.environ["DMC_USER"], "token": os.environ["DMC_TOKEN"]},
        )
        destino.write_bytes(crudo)
        time.sleep(0.5)
    return json.loads(destino.read_text())


def lluvia_larga(codigo: str, resp: dict) -> pd.DataFrame:
    """Aplana datosHistoricos.diaria[año][mes][día] = {total, parcial, traza} a una fila por día."""
    filas = []
    for anio, meses in (resp.get("datosHistoricos") or {}).get("diaria", {}).items():
        for mes, dias in meses.items():
            for dia, v in dias.items():
                try:
                    fecha = date(int(anio), int(mes), int(dia))
                except ValueError:
                    continue  # el servicio rellena hasta 31 días en todos los meses
                mm = v.get("total") if v.get("total") is not None else v.get("parcial")
                filas.append((codigo, fecha, None if mm is None else float(mm)))
    df = pd.DataFrame(filas, columns=["punto_id", "fecha", "lluvia_mm"])
    df["fecha"] = pd.to_datetime(df["fecha"])
    df["lluvia_dato_faltante"] = df["lluvia_mm"].isna()
    return df


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--refrescar", action="store_true", help="volver a bajar aunque exista caché")
    ap.add_argument("--margen-km", type=float, default=20.0)
    ap.add_argument("--max-faltantes", type=float, default=0.3, help="fracción máxima de días sin dato")
    args = ap.parse_args()

    cargar_env()
    if not (os.environ.get("DMC_USER") and os.environ.get("DMC_TOKEN")):
        print("Faltan DMC_USER y DMC_TOKEN (ver .env.example).", file=sys.stderr)
        return 1

    cfg = json.loads((ZONAS).read_text())
    zonas = cfg["zonas"]
    inicio = pd.Timestamp(cfg["periodo"]["inicio"])
    # `fin` puede ser "ultima_escena_limpia" (no es una fecha): se baja todo lo que la DMC tenga.
    fin_cfg = cfg["periodo"]["fin"]
    fin = pd.Timestamp(fin_cfg) if fin_cfg[:1].isdigit() else pd.Timestamp(date.today())

    est = estaciones_candidatas(zonas, args.margen_km, args.refrescar)
    if est.empty:
        print("Ninguna estación dentro de las zonas.", file=sys.stderr)
        return 1
    print(f"{est['punto_id'].nunique()} estaciones candidatas (margen {args.margen_km:g} km):")
    print(est.to_string(index=False))

    largos = []
    for codigo in est["punto_id"].unique():
        try:
            df = lluvia_larga(codigo, descargar_lluvia(codigo, args.refrescar))
        except RuntimeError as e:
            print(f"  {codigo}: {e}", file=sys.stderr)
            continue
        df = df[(df["fecha"] >= inicio) & (df["fecha"] <= fin)]
        print(f"  {codigo}: {len(df)} días, {int(df['lluvia_dato_faltante'].sum())} sin dato")
        largos.append(df)
    lluvia = pd.concat(largos, ignore_index=True) if largos else pd.DataFrame()
    if lluvia.empty:
        print("No se bajó lluvia de ninguna estación.", file=sys.stderr)
        return 1

    # Rango con dato y fracción de días faltantes dentro de lo que la estación cubre.
    con_dato = lluvia[~lluvia["lluvia_dato_faltante"]]
    resumen = con_dato.groupby("punto_id")["fecha"].agg(primera_fecha="min", ultima_fecha="max")
    falt = lluvia.merge(resumen, on="punto_id")
    falt = falt[(falt["fecha"] >= falt["primera_fecha"]) & (falt["fecha"] <= falt["ultima_fecha"])]
    frac = falt.groupby("punto_id")["lluvia_dato_faltante"].mean().rename("frac_faltantes").round(3)
    est = est.merge(resumen, on="punto_id", how="left").merge(frac, on="punto_id", how="left")
    est["descartada"] = est["frac_faltantes"].isna() | (est["frac_faltantes"] > args.max_faltantes)

    lluvia = lluvia.merge(est[["punto_id", "zona"]].drop_duplicates(), on="punto_id")
    lluvia.insert(1, "fuente", "dmc")
    salida_raw = DATA / "raw" / "clima" / "dmc_lluvia_diaria.parquet"
    salida_est = DATA / "processed" / "estacion_clima.parquet"
    salida_raw.parent.mkdir(parents=True, exist_ok=True)
    salida_est.parent.mkdir(parents=True, exist_ok=True)
    lluvia.to_parquet(salida_raw, index=False)
    est.to_parquet(salida_est, index=False)

    print("\nResumen por estación:")
    print(est[["punto_id", "nombre", "zona", "distancia_a_zona_km", "primera_fecha", "ultima_fecha",
               "frac_faltantes", "descartada"]].to_string(index=False))
    print(f"\n{mostrar(salida_raw)}: {len(lluvia)} filas\n{mostrar(salida_est)}: {len(est)} filas")
    return 0


if __name__ == "__main__":
    sys.exit(main())
