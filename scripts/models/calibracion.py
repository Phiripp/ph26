# /// script
# requires-python = ">=3.11"
# dependencies = ["geopandas>=1.0", "pandas", "pyarrow", "numpy", "scikit-learn"]
# ///
"""Calibración de los umbrales del detector de riego con la validación de M6 (tarea M7).

Recorre una grilla de parámetros de M3 (umbral de verdor, umbral de humedad, fracción mínima de fechas con señal y
días mínimos sin lluvia). Para cada combinación corre M3 y M5 sobre la serie de validación y sobre el universo de
elegibles 2025-26, y evalúa como M6 (predio del punto de la DGA, positivos detectables, azar = proporción del universo
de su zona en la banda).

Regla de elección (fijada antes de correr; con 19 positivos el máximo de la grilla es ruido):
- Métrica: cota inferior de Wilson del lift en banda alta (recall alto y pocos predios marcados a la vez).
- Se suaviza con los vecinos de la grilla (combinaciones que difieren en un paso de un parámetro): gana la zona
  estable, no un pico aislado.
- Si la ganadora no supera a los valores actuales (2, 2, 0,5, 10) en la métrica suavizada, se mantienen los actuales.

También reporta la definición de "detectable" relativa al secano local (NDVI previo ≥ secano + 0,10) además de la
absoluta de D18 (NDVI previo ≥ 0,30): Z2 tiene secano más verde (NDVI 0,23–0,35).

Salidas: docs/calibracion.md y data/processed/calibracion_grilla.csv.

Uso: uv run scripts/models/calibracion.py [--procesos 6]
"""

import argparse
import itertools
import subprocess
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from comun.rutas import PROC, RAIZ  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent))
from validacion import casos, wilson  # noqa: E402

GRILLA = {"umbral_verdor": [1.5, 2.0, 2.5], "umbral_humedad": [1.5, 2.0, 2.5], "frac_min": [0.3, 0.5, 0.7],
          "dias_min": [7, 10, 14]}
ACTUAL = {"umbral_verdor": 2.0, "umbral_humedad": 2.0, "frac_min": 0.5, "dias_min": 10}
SERIES = {
    "v": ("anomalias_predio_validacion.parquet", "consumo_predio_validacion_temporada.parquet"),
    "u": ("anomalias_predio_elegibles_2025-26.parquet", "consumo_predio_elegibles_2025-26_temporada.parquet"),
}


def correr(cmd: list[str]) -> None:
    r = subprocess.run(["uv", "run", "-q", *cmd], cwd=RAIZ, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(f"{' '.join(cmd)}\n{r.stderr[-2000:]}")


def ndvi_secano_previo() -> pd.Series:
    """NDVI mediano del secano de referencia por (predio_id, temporada) en la serie de validación."""
    a = pd.read_parquet(PROC / "anomalias_predio_validacion.parquet", columns=["predio_id", "temporada", "ref_ndvi_mediana"])
    return a.groupby(["predio_id", "temporada"])["ref_ndvi_mediana"].median()


def evaluar(f: pd.DataFrame, u: pd.DataFrame) -> dict:
    out = {"universo_alta": (u["banda"] == "alta").mean(), "universo_alta_media": u["banda"].isin(["alta", "media"]).mean()}
    for nombre, col in [("abs", "detectable"), ("rel", "detectable_rel")]:
        p = f[f["y"] & f[col] & f["banda_punto"].notna()]
        k, n = int((p["banda_punto"] == "alta").sum()), len(p)
        base = p["azar_punto_alta"].mean()
        lo, hi = wilson(k, n)
        km = int(p["banda_punto"].isin(["alta", "media"]).sum())
        out |= {f"n_pos_{nombre}": n, f"recall_alta_{nombre}": k / n, f"lift_alta_{nombre}": k / n / base,
                f"lift_alta_lo_{nombre}": lo / base, f"recall_am_{nombre}": km / n,
                f"lift_am_{nombre}": km / n / p["azar_punto_alta o media"].mean()}
    d = f[f["detectable"]]
    from sklearn.metrics import roc_auc_score
    out["auc"] = roc_auc_score(d["y"], d["puntaje"])
    return out


def una(combo: dict, secano: pd.Series) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        args_m3 = ["--umbral-verdor", str(combo["umbral_verdor"]), "--umbral-humedad", str(combo["umbral_humedad"]),
                   "--frac-min", str(combo["frac_min"]), "--dias-min", str(combo["dias_min"])]
        for k, (anom, cons) in SERIES.items():
            correr(["scripts/models/detector_riego.py", "--anomalias", str(PROC / anom),
                    "--salida", str(tmp / f"senal_{k}.parquet"), *args_m3])
            correr(["scripts/models/indice_sospecha.py", "--senal", str(tmp / f"senal_{k}.parquet"),
                    "--consumo", str(PROC / cons), "--salida", str(tmp / f"puntaje_{k}.parquet")])
        f = casos(tmp / "puntaje_v.parquet", tmp / "puntaje_u.parquet")
        u = pd.read_parquet(tmp / "puntaje_u.parquet", columns=["banda", "predio_id", "zona"])
    ref = [np.nanmax([secano.get((int(p), r["temporada_previa"]), np.nan) for p in r["vecindario"]] or [np.nan])
           for _, r in f.iterrows()]
    f["detectable_rel"] = f["ndvi_previo"] >= pd.Series(ref, index=f.index) + 0.10
    return combo | evaluar(f, u)


def vecinos(df: pd.DataFrame, col: str) -> pd.Series:
    claves = list(GRILLA)
    idx = {tuple(r[c] for c in claves): i for i, r in df.iterrows()}
    out = []
    for _, r in df.iterrows():
        vals = [r[col]]
        for c in claves:
            pos = GRILLA[c].index(r[c])
            for d in (-1, 1):
                if 0 <= pos + d < len(GRILLA[c]):
                    k = tuple((GRILLA[c][pos + d] if cc == c else r[cc]) for cc in claves)
                    vals.append(df.at[idx[k], col])
        out.append(np.mean(vals))
    return pd.Series(out, index=df.index)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--procesos", type=int, default=6)
    args = ap.parse_args()
    secano = ndvi_secano_previo()
    combos = [dict(zip(GRILLA, v)) for v in itertools.product(*GRILLA.values())]
    with ProcessPoolExecutor(args.procesos) as ex:
        filas = list(ex.map(una, combos, [secano] * len(combos)))
    df = pd.DataFrame(filas)
    df["metrica_suavizada"] = vecinos(df, "lift_alta_lo_abs")
    df = df.sort_values("metrica_suavizada", ascending=False).reset_index(drop=True)
    df.round(4).to_csv(PROC / "calibracion_grilla.csv", index=False)

    es_actual = np.logical_and.reduce([df[c] == v for c, v in ACTUAL.items()])
    actual = df[es_actual].iloc[0]
    mejor = df.iloc[0]
    elegida = mejor if mejor["metrica_suavizada"] > actual["metrica_suavizada"] else actual

    def fila(r: pd.Series, nombre: str) -> str:
        return (f"| {nombre} | {r['umbral_verdor']:g} | {r['umbral_humedad']:g} | {r['frac_min']:g} | {int(r['dias_min'])} | "
                f"{r['universo_alta']:.1%} | {r['recall_alta_abs']:.0%} | {r['lift_alta_abs']:.1f}× | "
                f"{r['lift_alta_lo_abs']:.2f} | {r['metrica_suavizada']:.2f} | {r['recall_am_abs']:.0%} | "
                f"{r['lift_am_abs']:.1f}× | {r['auc']:.2f} | {r['recall_alta_rel']:.0%} ({int(r['n_pos_rel'])}) | "
                f"{r['lift_alta_rel']:.1f}× |")

    enc = ("| Combinación | Verdor | Humedad | Frac. mín. | Días secos | Universo en alta | Recall alta | Lift alta | "
           "Cota inf. lift | Suavizada | Recall alta+media | Lift alta+media | AUC | Recall alta (detectable relativo) | "
           "Lift alta (relativo) |\n| --- |" + " --- |" * 14)
    top = "\n".join(fila(r, f"#{i + 1}") for i, r in df.head(10).iterrows())
    estab = df.groupby("frac_min")["lift_alta_abs"].mean().round(2).to_dict()
    lineas = [
        "# Calibración del detector de riego (M7)", "",
        "Generado por `scripts/models/calibracion.py` (no editar a mano). Grilla completa en "
        "[calibracion_grilla.csv](../data/processed/calibracion_grilla.csv).", "",
        "## Regla", "",
        "Para cada combinación de parámetros de M3 se corren M3 y M5 sobre la validación y el universo 2025-26, y se "
        "evalúa como M6: predio del punto de la DGA, positivos detectables, azar = proporción del universo de su zona. "
        "La métrica es la cota inferior de Wilson del lift en banda alta, suavizada con las combinaciones vecinas de la "
        "grilla. Se cambian los valores actuales solo si la ganadora los supera en esa métrica.", "",
        "## Resultado", "",
        enc, fila(actual, "actual"), fila(elegida, "**elegida**"), "",
        f"**Decisión:** {'se mantienen los valores actuales' if elegida is actual else 'se cambian los valores de M3'}: "
        f"umbral de verdor {elegida['umbral_verdor']:g}, umbral de humedad {elegida['umbral_humedad']:g}, fracción "
        f"mínima {elegida['frac_min']:g}, días secos {int(elegida['dias_min'])}.", "",
        "## Las 10 mejores (suavizadas)", "", enc, top, "",
        "## Estabilidad", "",
        f"- Lift medio en alta según la fracción mínima: {estab}.",
        f"- Rango del lift en alta en la grilla: {df['lift_alta_abs'].min():.1f}× a {df['lift_alta_abs'].max():.1f}×; "
        f"AUC entre fiscalizados: {df['auc'].min():.2f} a {df['auc'].max():.2f}.",
        "- Detectable relativo (NDVI previo ≥ secano local + 0,10) en lugar de ≥ 0,30: cambia el set de positivos "
        "evaluados, sobre todo en Z2 (secano más verde). Se reporta en las últimas columnas.", "",
        "## Limitaciones", "",
        "- 19 positivos detectables: diferencias de uno o dos casos mueven el lift en más de 0,5×. La regla suavizada "
        "evita elegir un pico, pero la calibración es gruesa.",
        "- No se calibra la escala mínima de M2 ni el radio de referencia (rehacer M2 por combinación es caro); quedan "
        "en 0,05 y 10 km.", "",
    ]
    (RAIZ / "docs" / "calibracion.md").write_text("\n".join(lineas), encoding="utf-8")
    print("\n".join(lineas[8:14]))


if __name__ == "__main__":
    main()
