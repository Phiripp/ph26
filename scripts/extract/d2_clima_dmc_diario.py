# /// script
# requires-python = ">=3.11"
# dependencies = ["pandas", "pyarrow"]
# ///
"""Acumula la lluvia diaria reciente de las estaciones DMC en una serie propia (tarea D2, paso 5).

La DMC no tiene lluvia diaria histórica después de 2025. El servicio getEmaResumenDiario entrega los últimos
días (unos 4) de cada estación, así que correrlo cada día o cada pocos días arma la serie de 2026 en adelante.
Si pasan más de 3 días sin correrlo, esos días quedan sin dato de estación (se cubren con la lluvia corregida
de Open-Meteo, ver d2_clima_unir.py).

Estaciones: las no descartadas de data/processed/estacion_clima.parquet (corre antes d2_clima_dmc.py).
Credenciales: DMC_USER y DMC_TOKEN, desde el entorno o desde .env.
Además baja los totales mensuales de 2026 (getAguaCaidaMensualAnual), que sí están en línea: sirven para escalar
la lluvia diaria de Open-Meteo de los días que no se alcanzaron a acumular (d2_clima_unir.py).
Salidas (no van a git):
- data/raw/clima/dmc/2026_acumulado.parquet: una fila por (estación, fecha).
- data/raw/clima/dmc/2026_mensual.parquet: una fila por (estación, mes) con lluvia_mm y numero_datos (días con registro).
Es idempotente: si un día ya está, se conserva la versión con más minutos de datos (`minutos_dato`),
porque el día en curso llega incompleto y los siguientes llamados lo completan.

Uso: uv run scripts/extract/d2_clima_dmc_diario.py
Ejemplo de cron diario (a las 06:00): 0 6 * * * cd <repo> && uv run scripts/extract/d2_clima_dmc_diario.py
"""

import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parents[2]
DATA = RAIZ / "data"
SALIDA = DATA / "raw" / "clima" / "dmc" / "2026_acumulado.parquet"
URL = "https://climatologia.meteochile.gob.cl/application/servicios/getEmaResumenDiario/{codigo}"
# Ojo: este servicio vive en `serviciosb`, no en `servicios`.
URL_MENSUAL = "https://climatologia.meteochile.gob.cl/application/serviciosb/getAguaCaidaMensualAnual/{codigo}"
SALIDA_MENSUAL = DATA / "raw" / "clima" / "dmc" / "2026_mensual.parquet"
MINUTOS_DIA_COMPLETO = 1380  # de 1440; menos que esto se marca como día parcial


def cargar_env() -> None:
    env = RAIZ / ".env"
    if not env.exists():
        return
    for linea in env.read_text().splitlines():
        linea = linea.strip()
        if linea and not linea.startswith("#") and "=" in linea:
            k, v = linea.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def pedir(codigo: str, reintentos: int = 3, base: str = URL) -> dict:
    url = base.format(codigo=codigo) + "?" + urllib.parse.urlencode(
        {"usuario": os.environ["DMC_USER"], "token": os.environ["DMC_TOKEN"]}
    )
    for intento in range(reintentos):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return json.loads(r.read())
        except Exception as e:  # noqa: BLE001
            if intento == reintentos - 1:
                # No imprimir la URL: lleva el token.
                raise RuntimeError(f"falló la consulta a la DMC ({type(e).__name__})") from None
            time.sleep(2 * (intento + 1))
    raise AssertionError("inalcanzable")


def filas_de(codigo: str, resp: dict, capturado: str) -> list[dict]:
    """aguaCaidaDiaria = {"dd-mm-aaaa": {"valor": mm, "total": {"datos": minutos con registro}}}."""
    filas = []
    for dia, v in (resp.get("datos", {}).get("aguaCaidaDiaria") or {}).items():
        mm = v.get("valor")
        filas.append(
            {
                "punto_id": codigo,
                "fuente": "dmc",
                "fecha": pd.to_datetime(dia, format="%d-%m-%Y"),
                "lluvia_mm": None if mm is None else float(mm),
                "minutos_dato": int((v.get("total") or {}).get("datos") or 0),
                "capturado": capturado,
            }
        )
    return filas


def filas_mensuales(codigo: str, resp: dict) -> list[dict]:
    anos = ((resp.get("datosHistoricos") or {}).get("mensuales") or {}).get("anos", {})
    filas = []
    for mes, v in (anos.get("2026") or {}).items():
        mm = v.get("total") if v.get("total") is not None else v.get("parcial")
        filas.append(
            {
                "punto_id": codigo,
                "mes": f"2026-{int(mes):02d}",
                "lluvia_mm": None if mm is None else round(float(mm), 2),
                "numero_datos": v.get("numeroDeDatos"),
                "mes_completo": v.get("total") is not None,
            }
        )
    return filas


def main() -> int:
    cargar_env()
    if not (os.environ.get("DMC_USER") and os.environ.get("DMC_TOKEN")):
        print("Faltan DMC_USER y DMC_TOKEN (ver .env.example).", file=sys.stderr)
        return 1
    ruta_est = DATA / "processed" / "estacion_clima.parquet"
    if not ruta_est.exists():
        print("Falta data/processed/estacion_clima.parquet: corre antes d2_clima_dmc.py.", file=sys.stderr)
        return 1
    est = pd.read_parquet(ruta_est)
    est = est[~est["descartada"]].drop_duplicates("punto_id")

    capturado = pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%d %H:%M")
    nuevas, mensuales, fallidas = [], [], []
    for codigo in est["punto_id"]:
        try:
            nuevas += filas_de(codigo, pedir(codigo), capturado)
            mensuales += filas_mensuales(codigo, pedir(codigo, base=URL_MENSUAL))
        except RuntimeError as e:
            fallidas.append(codigo)
            print(f"  {codigo}: {e}", file=sys.stderr)
        time.sleep(0.5)
    if not nuevas:
        print("No se obtuvo ninguna fila.", file=sys.stderr)
        return 1

    df = pd.DataFrame(nuevas)
    if SALIDA.exists():
        df = pd.concat([pd.read_parquet(SALIDA), df], ignore_index=True)
    # Por (estación, fecha) se queda la versión con más minutos de dato; a igualdad, la más reciente.
    df = (
        df.sort_values(["punto_id", "fecha", "minutos_dato", "capturado"])
        .drop_duplicates(["punto_id", "fecha"], keep="last")
        .reset_index(drop=True)
    )
    df["dia_parcial"] = df["minutos_dato"] < MINUTOS_DIA_COMPLETO
    # Solo 2026 en adelante: lo anterior viene de d2_clima_dmc.py.
    df = df[df["fecha"] >= "2026-01-01"]
    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(SALIDA, index=False)

    if mensuales:
        pd.DataFrame(mensuales).sort_values(["punto_id", "mes"]).to_parquet(SALIDA_MENSUAL, index=False)
        print(f"{SALIDA_MENSUAL.relative_to(RAIZ)}: {len(mensuales)} filas")
    print(f"{SALIDA.relative_to(RAIZ)}: {len(df)} filas, {df['punto_id'].nunique()} estaciones, "
          f"{df['fecha'].min().date()} a {df['fecha'].max().date()}")
    print(f"días parciales: {int(df['dia_parcial'].sum())}; estaciones con falla: {fallidas or 'ninguna'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
