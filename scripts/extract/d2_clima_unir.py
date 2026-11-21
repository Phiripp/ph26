# /// script
# requires-python = ">=3.11"
# dependencies = ["pandas", "pyarrow", "numpy", "matplotlib"]
# ///
"""Corrige la lluvia de Open-Meteo con las estaciones DMC y arma clima.parquet (tarea D2, pasos 4 y 6).

Entradas (las generan d2_clima_dmc.py, d2_clima_dmc_diario.py y d2_clima_openmeteo.py):
- data/processed/estacion_clima.parquet
- data/raw/clima/dmc_lluvia_diaria.parquet (2020-2025), dmc/2026_acumulado.parquet y dmc/2026_mensual.parquet
- data/raw/clima/openmeteo_diario.parquet

Corrección de la lluvia (Open-Meteo sobreestima cerca de 2 veces, ver docs/pruebas-acceso-datos.md):
1. A cada celda se le asigna la estación DMC más cercana con al menos 1.000 días con dato.
2. Factor por mes del año = (mm de estación + L * r) / (mm de Open-Meteo + L * 1), con r el cociente anual y L = 20 mm
   de peso previo: los meses secos casi no tienen lluvia y su cociente solo sería ruido, así que se acercan a r.
   Se usa solo los días en que la estación tiene dato, 2020-2025. El factor se limita a [0,05 ; 1,5].
3. 2026: se reescala cada mes para que la suma de Open-Meteo calce con el total mensual de la estación
   (si el total es 0, todos los días en 0; si Open-Meteo casi no registra lluvia ese mes, se usa el factor del paso 2).
   Un mes en curso se calza con los días que la estación ya tiene.
4. Lo corregido bajo 0,2 mm se pone en 0: los pluviómetros no registran garúa y Open-Meteo sí, y eso alarga o
   corta ventanas secas de forma artificial.

Salidas:
- data/processed/clima.parquet: zona, punto_id, fuente, fecha, lluvia_mm, lluvia_corr_mm, et0_mm, estacion_ref_id,
  lluvia_dato_faltante, dia_parcial. Una estación que sirve a dos zonas aparece en cada una.
- data/processed/clima_validacion.csv y docs/img/clima_validacion.png: contraste de la corrección.

Uso: uv run scripts/extract/d2_clima_unir.py
"""

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parents[2]
DATA = RAIZ / "data"
RAW = DATA / "raw" / "clima"
KM_POR_GRADO = 111.32
MIN_DIAS_ESTACION = 1000
PESO_PREVIO_MM = 20.0
FACTOR_MIN, FACTOR_MAX = 0.05, 1.5
UMBRAL_GARUA_MM = 0.2
OM_MIN_MES_2026_MM = 1.0
FACTOR_MAX_2026 = 3.0
DIA_LLUVIOSO_MM = 1.0


def km(lat1, lon1, lat2, lon2) -> float:
    dy = (lat2 - lat1) * KM_POR_GRADO
    dx = (lon2 - lon1) * KM_POR_GRADO * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot(dx, dy)


def coords_celda(celda_id: str) -> tuple[float, float]:
    """OM_Z1_m32.45_m71.05 -> (-32.45, -71.05)."""
    _, _, lat, lon = celda_id.split("_")
    return float(lat.replace("m", "-")), float(lon.replace("m", "-"))


def lluvia_estaciones() -> pd.DataFrame:
    """Lluvia diaria de estaciones, una fila por (punto_id, fecha), sin duplicar por zona."""
    hist = pd.read_parquet(RAW / "dmc_lluvia_diaria.parquet").drop_duplicates(["punto_id", "fecha"])
    hist = hist[["punto_id", "fecha", "lluvia_mm", "lluvia_dato_faltante"]].assign(dia_parcial=False)
    partes = [hist]
    acum = RAW / "dmc" / "2026_acumulado.parquet"
    if acum.exists():
        a = pd.read_parquet(acum)
        a = a.assign(lluvia_dato_faltante=a["lluvia_mm"].isna())[
            ["punto_id", "fecha", "lluvia_mm", "lluvia_dato_faltante", "dia_parcial"]
        ]
        partes.append(a)
    df = pd.concat(partes, ignore_index=True)
    # Si un día está en el histórico y en el acumulado, manda el acumulado (más reciente).
    return df.drop_duplicates(["punto_id", "fecha"], keep="last")


def estacion_mas_cercana(celdas: pd.DataFrame, est: pd.DataFrame, dias_validos: pd.Series) -> dict[str, str]:
    candidatas = est[est["punto_id"].map(dias_validos).fillna(0) >= MIN_DIAS_ESTACION].drop_duplicates("punto_id")
    ref = {}
    for celda_id in celdas:
        lat, lon = coords_celda(celda_id)
        d = [km(lat, lon, la, lo) for la, lo in zip(candidatas["lat"], candidatas["lon"])]
        ref[celda_id] = candidatas["punto_id"].iloc[int(np.argmin(d))]
    return ref


def factores_climatologicos(om: pd.DataFrame, est: pd.DataFrame) -> np.ndarray:
    """Factor por mes del año (índice 1..12; la posición 0 no se usa)."""
    ambos = om.merge(est, on="fecha", suffixes=("_om", "_est"))
    ambos = ambos[(~ambos["lluvia_dato_faltante"]) & (ambos["fecha"] < "2026-01-01")]
    if ambos["lluvia_mm_om"].sum() <= 0:
        return np.ones(13)
    r_anual = ambos["lluvia_mm_est"].sum() / ambos["lluvia_mm_om"].sum()
    mes = ambos["fecha"].dt.month
    s_est = ambos.groupby(mes)["lluvia_mm_est"].sum().reindex(range(1, 13), fill_value=0.0)
    s_om = ambos.groupby(mes)["lluvia_mm_om"].sum().reindex(range(1, 13), fill_value=0.0)
    f = (s_est + PESO_PREVIO_MM * r_anual) / (s_om + PESO_PREVIO_MM)
    return np.concatenate([[1.0], np.clip(f.to_numpy(), FACTOR_MIN, FACTOR_MAX)])


def corregir_celda(om: pd.DataFrame, fclim: np.ndarray, mensual: pd.DataFrame) -> pd.Series:
    om = om.sort_values("fecha").reset_index(drop=True)
    factor = pd.Series(fclim[om["fecha"].dt.month.to_numpy()], index=om.index)
    for _, m in mensual.iterrows():
        if m["lluvia_mm"] is None or pd.isna(m["lluvia_mm"]):
            continue
        en_mes = (om["fecha"].dt.strftime("%Y-%m") == m["mes"])
        # Mes en curso: solo los primeros `numero_datos` días tienen registro de la estación.
        dia = om["fecha"].dt.day
        usados = en_mes & (dia <= int(m["numero_datos"] or 31))
        om_mm = om.loc[usados, "lluvia_mm"].sum()
        if m["lluvia_mm"] == 0:
            factor[en_mes] = 0.0
        elif om_mm >= OM_MIN_MES_2026_MM:
            factor[en_mes] = min(m["lluvia_mm"] / om_mm, FACTOR_MAX_2026)
    corr = om["lluvia_mm"] * factor
    return corr.where(corr >= UMBRAL_GARUA_MM, 0.0).round(2)


def validar(om_all: pd.DataFrame, est_dia: pd.DataFrame, ref: dict[str, str]) -> pd.DataFrame:
    filas = []
    for celda, g in om_all.groupby("punto_id"):
        e = est_dia[(est_dia["punto_id"] == ref[celda]) & (~est_dia["lluvia_dato_faltante"])]
        m = g.merge(e, on="fecha", suffixes=("_om", "_est"))
        for periodo, sel in (("2020-2025", m["fecha"] < "2026-01-01"), ("2025", m["fecha"].dt.year == 2025)):
            x = m[sel]
            if x.empty:
                continue
            est_si = x["lluvia_mm_est"] >= DIA_LLUVIOSO_MM
            filas.append(
                {
                    "celda": celda,
                    "estacion_ref": ref[celda],
                    "periodo": periodo,
                    "mm_estacion": round(x["lluvia_mm_est"].sum(), 1),
                    "mm_openmeteo": round(x["lluvia_mm_om"].sum(), 1),
                    "mm_corregida": round(x["lluvia_corr_mm"].sum(), 1),
                    "acierto_dia_lluvioso_crudo": round(((x["lluvia_mm_om"] >= DIA_LLUVIOSO_MM) == est_si).mean(), 3),
                    "acierto_dia_lluvioso_corr": round(((x["lluvia_corr_mm"] >= DIA_LLUVIOSO_MM) == est_si).mean(), 3),
                }
            )
    return pd.DataFrame(filas)


def grafico(om_all: pd.DataFrame, est_dia: pd.DataFrame, ref: dict[str, str], destino: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    celdas = sorted(om_all["punto_id"].unique())
    fig, ejes = plt.subplots(len(celdas), 1, figsize=(10, 2.4 * len(celdas)), sharex=True, squeeze=False)
    for ax, celda in zip(ejes[:, 0], celdas):
        g = om_all[om_all["punto_id"] == celda].set_index("fecha")
        e = est_dia[(est_dia["punto_id"] == ref[celda]) & (~est_dia["lluvia_dato_faltante"])].set_index("fecha")
        mens = pd.DataFrame(
            {
                "Open-Meteo crudo": g["lluvia_mm"].resample("MS").sum(),
                "Open-Meteo corregido": g["lluvia_corr_mm"].resample("MS").sum(),
                "Estación": e["lluvia_mm"].resample("MS").sum(),
            }
        )
        mens.plot(ax=ax, linewidth=1.2)
        ax.set_title(f"{celda}  (estación {ref[celda]})", fontsize=9, loc="left")
        ax.set_ylabel("mm/mes")
        ax.legend(fontsize=7, loc="upper left")
    plt.tight_layout()
    destino.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(destino, dpi=110)


def main() -> int:
    est = pd.read_parquet(DATA / "processed" / "estacion_clima.parquet")
    est_ok = est[~est["descartada"]]
    est_dia = lluvia_estaciones()
    est_dia = est_dia[est_dia["punto_id"].isin(est_ok["punto_id"])]
    mensual_path = RAW / "dmc" / "2026_mensual.parquet"
    mensual = pd.read_parquet(mensual_path) if mensual_path.exists() else pd.DataFrame(columns=["punto_id", "mes", "lluvia_mm", "numero_datos"])

    om_all = pd.read_parquet(RAW / "openmeteo_diario.parquet")
    dias_validos = est_dia[~est_dia["lluvia_dato_faltante"]].groupby("punto_id").size()
    ref = estacion_mas_cercana(om_all["punto_id"].unique(), est_ok, dias_validos)

    partes = []
    for celda, g in om_all.groupby("punto_id"):
        e = est_dia[est_dia["punto_id"] == ref[celda]]
        f = factores_climatologicos(g[["fecha", "lluvia_mm"]], e[["fecha", "lluvia_mm", "lluvia_dato_faltante"]])
        g = g.sort_values("fecha").reset_index(drop=True)
        g["lluvia_corr_mm"] = corregir_celda(g, f, mensual[mensual["punto_id"] == ref[celda]])
        g["estacion_ref_id"] = ref[celda]
        partes.append(g)
        print(f"{celda}: estación {ref[celda]}, factores por mes {np.round(f[1:], 2).tolist()}")
    om_all = pd.concat(partes, ignore_index=True)

    # Estaciones: una fila por zona en que cae la estación.
    zonas_est = est_ok[["punto_id", "zona"]].drop_duplicates()
    dmc = est_dia.merge(zonas_est, on="punto_id")
    dmc = dmc.assign(fuente="dmc", lluvia_corr_mm=np.nan, et0_mm=np.nan, estacion_ref_id=pd.NA)

    om_out = om_all.assign(lluvia_dato_faltante=False, dia_parcial=False)
    cols = ["zona", "punto_id", "fuente", "fecha", "lluvia_mm", "lluvia_corr_mm", "et0_mm", "estacion_ref_id",
            "lluvia_dato_faltante", "dia_parcial"]
    clima = pd.concat([dmc[cols], om_out[cols]], ignore_index=True).sort_values(["zona", "fuente", "punto_id", "fecha"])

    # Comprobaciones.
    assert not clima.duplicated(["zona", "punto_id", "fecha"]).any(), "fechas duplicadas por punto"
    huecos = om_out[["lluvia_mm", "et0_mm"]].isna().sum().sum()
    assert huecos == 0, f"Open-Meteo con {huecos} huecos"
    print(f"\nOpen-Meteo: {om_all['punto_id'].nunique()} celdas, {om_all['fecha'].min().date()} a {om_all['fecha'].max().date()}, sin huecos")

    val = validar(om_all, est_dia, ref)
    val.to_csv(DATA / "processed" / "clima_validacion.csv", index=False)
    print("\nContraste con la estación de referencia (en muestra: la estación calibró el factor):")
    print(val.to_string(index=False))
    grafico(om_all, est_dia, ref, RAIZ / "docs" / "img" / "clima_validacion.png")

    salida = DATA / "processed" / "clima.parquet"
    clima.to_parquet(salida, index=False)
    print(f"\n{salida.relative_to(RAIZ)}: {len(clima)} filas ({clima['fuente'].value_counts().to_dict()})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
