# /// script
# requires-python = ">=3.11"
# dependencies = ["pandas", "pyarrow", "numpy"]
# ///
"""Ventanas secas por celda de clima (tarea M1).

Ventana seca = racha de `--n` o más días seguidos sin lluvia efectiva (lluvia_corr_mm < `--umbral-mm`).
Usa la lluvia corregida de las celdas de Open-Meteo o ERA5-Land (D2), que cubre 2020 a nov-2026 sin huecos; la lluvia
cruda de la grilla sobreestima cerca de 2 veces y no sirve para esto (docs/pruebas-acceso-datos.md).
Para llegar al predio: data/processed/predio_clima.parquet (predio_id -> celda_id).

Salidas en data/processed/:
- ventana_seca.parquet: zona, celda_id, ventana_id, inicio, fin, dias, et0_mm (ET0 acumulada de la ventana),
  lluvia_max_mm (el día más lluvioso permitido dentro de la ventana: siempre < umbral), abierta (True si
  llega al último día con dato: la ventana sigue).
- dias_sin_lluvia.parquet: zona, celda_id, fecha, dias_sin_lluvia (racha en curso, 0 si llovió ese día),
  en_ventana (True si el día pertenece a una ventana seca). Es la feature `dias_sin_lluvia` del spec.

Limitación: en 2026 la lluvia corregida está calzada mes a mes con las estaciones, no día a día; las ventanas
de 2026 son aproximadas. Antes de 2026 el factor mensual no corrige el día exacto de cada lluvia.

Uso: uv run scripts/models/ventana_seca.py [--n 10] [--umbral-mm 1.0]
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from comun.rutas import PROC  # noqa: E402


def rachas(seco: np.ndarray) -> np.ndarray:
    """Largo de la racha de días secos que termina en cada día (0 si el día es húmedo)."""
    out = np.zeros(len(seco), dtype=int)
    c = 0
    for i, s in enumerate(seco):
        c = c + 1 if s else 0
        out[i] = c
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--n", type=int, default=10, help="días mínimos de la ventana")
    ap.add_argument("--umbral-mm", type=float, default=1.0, help="lluvia diaria desde la cual cuenta como efectiva")
    args = ap.parse_args()

    clima = pd.read_parquet(PROC / "clima.parquet")
    om = clima[clima["fuente"].isin(["openmeteo", "era5land"])].rename(columns={"punto_id": "celda_id"})
    ventanas, dias = [], []
    for (zona, celda), g in om.groupby(["zona", "celda_id"]):
        g = g.sort_values("fecha").reset_index(drop=True)
        seco = (g["lluvia_corr_mm"] < args.umbral_mm).to_numpy()
        r = rachas(seco)
        # Un día pertenece a una ventana si su racha final alcanza n; se marca toda la racha hacia atrás.
        en = np.zeros(len(g), dtype=bool)
        fin_idx = [i for i in range(len(g)) if r[i] >= args.n and (i + 1 == len(g) or r[i + 1] == 0)]
        for k, i in enumerate(fin_idx):
            j = i - r[i] + 1
            en[j : i + 1] = True
            w = g.iloc[j : i + 1]
            ventanas.append(
                {"zona": zona, "celda_id": celda, "ventana_id": f"{celda}_{k:03d}", "inicio": w["fecha"].iloc[0],
                 "fin": w["fecha"].iloc[-1], "dias": len(w), "et0_mm": round(w["et0_mm"].sum(), 1),
                 "lluvia_max_mm": round(w["lluvia_corr_mm"].max(), 2), "abierta": i + 1 == len(g)}
            )
        dias.append(pd.DataFrame({"zona": zona, "celda_id": celda, "fecha": g["fecha"],
                                  "dias_sin_lluvia": r, "en_ventana": en}))
    v = pd.DataFrame(ventanas)
    d = pd.concat(dias, ignore_index=True)
    v.to_parquet(PROC / "ventana_seca.parquet", index=False)
    d.to_parquet(PROC / "dias_sin_lluvia.parquet", index=False)

    print(f"n={args.n}, umbral={args.umbral_mm} mm: {len(v)} ventanas en {v['celda_id'].nunique()} celdas")
    v["anio"] = v["inicio"].dt.year
    print(v.groupby(["zona", "anio"]).agg(ventanas=("dias", "size"), dias_mediana=("dias", "median"), dias_max=("dias", "max")).to_string())
    print("\n% de días en ventana seca por zona y mes (todas las celdas):")
    d["mes"] = d["fecha"].dt.month
    print((d.groupby(["zona", "mes"])["en_ventana"].mean().unstack(0) * 100).round(0).to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
