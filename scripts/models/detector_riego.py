# /// script
# requires-python = ">=3.11"
# dependencies = ["pandas", "pyarrow", "numpy"]
# ///
"""Detector de riego en ventana seca por predio y temporada (tarea M3).

Una fecha tiene señal de riego cuando z_verdor >= --umbral-verdor y z_humedad >= --umbral-humedad (anomalías de
M2 frente a la referencia de secano) y la fecha cae dentro de una ventana seca de M1 en la celda de clima del predio.
Sin lluvia, verdor y humedad sobre el secano vecino solo se explican con agua aplicada (o con napa somera: ver
limitaciones).

Entradas (data/processed/):
- anomalias_predio.parquet (M2; o --anomalias): z_verdor y z_humedad por predio y fecha, con estado.
- predio_clima.parquet: predio_id -> celda_id de Open-Meteo.
- ventana_seca.parquet (M1): ventanas por celda (inicio, fin); la fecha se une por celda e intervalo.
- dias_sin_lluvia.parquet (M1): racha de días secos en la fecha de la imagen.
- predio.parquet (local) o predio_muestra.geojson: area_ha, para marcar predios grandes.

Salida: data/processed/senal_riego.parquet (o --salida), una fila por (predio_id, temporada):
- n_fechas: escenas del predio en la temporada; n_fechas_ventana: de ellas, en ventana seca (con la racha mínima).
- n_fechas_validas: en ventana seca, despejadas y con referencia (estado "ok" de M2). Es el denominador.
- n_fechas_senal, frac_senal = n_fechas_senal / n_fechas_validas; senal_riego = frac_senal >= --frac-min.
- z_verdor_mediana, z_humedad_mediana, ndvi_mediana, ndmi_mediana: sobre las fechas válidas.
- frac_nublado, frac_sin_referencia: fechas en ventana descartadas por nubes o por falta de referencia.
- frac_sin_clima: fechas sin dato de clima (M1 parte el 01-01-2020: diciembre de 2019 queda sin ventana).
- pix_mediana (n_pix_validos), area_ha, referencia (de M2), confianza (alta, media o baja) y motivos_confianza.

Reglas:
- Fecha en ventana seca: dentro de [inicio, fin] de una ventana de su celda y con dias_sin_lluvia >= --dias-min (10,
  la N de M1). M1 marca la ventana completa hacia atrás, así que la imagen del día 2 después de una lluvia queda
  "en ventana"; exigir la racha evita contar la humedad que dejó esa lluvia.
- Se exigen las dos anomalías: el suelo desnudo tiene NDMI más alto que el matorral seco (control 88-31 en dic-2019
  frente a CONAF: z_humedad +2,5 pero z_verdor -2,0), así que la humedad sola da falsos positivos.
- Umbrales calibrados en M7 (docs/calibracion.md): z_verdor >= 2,5 y z_humedad >= 1,5 (con la escala mínima de M2,
  0,05, al menos 0,125 de NDVI y 0,075 de NDMI sobre el secano) y --frac-min 0,7 (siete de cada diez fechas válidas
  con señal). Los iniciales eran 2, 2 y 0,5. En la grilla de M7 el verdor alto y la fracción alta mandan; los días
  secos (7, 10 o 14) casi no cambian el resultado.
- Confianza: la peor de estas reglas (motivos en motivos_confianza):
  - baja: menos de --min-fechas-baja (3) fechas válidas; sin_referencia en más de la mitad de las fechas en ventana;
    sin clima en más de la mitad de las fechas; mediana de píxeles válidos < 25 (1 ha a 20 m: el borde pesa demasiado).
  - media: menos de --min-fechas-media (6) fechas válidas; más de la mitad de las fechas en ventana nubladas;
    mediana de píxeles < 50; predio de más de 100 ha (el riego de una parte se diluye en el promedio).
  - alta: el resto. Con referencia provisional en M2 la confianza no sube de media ("referencia_provisional").

Limitaciones: vegas, quebradas con napa somera y bordes de río pueden dar señal sin riego; el detector no distingue
agua de pozo, de canal o de río (eso lo hacen M5 con los derechos y el expediente).

Uso:
  uv run scripts/models/detector_riego.py
  uv run scripts/models/detector_riego.py --umbral-verdor 2.5 --umbral-humedad 1.5 --dias-min 7
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from comun.rutas import PROC, RAIZ  # noqa: E402

NIVELES = ["baja", "media", "alta"]
# Umbrales por defecto, calibrados en M7 (docs/calibracion.md). Los importan el expediente, la explicación y la API.
UMBRAL_VERDOR, UMBRAL_HUMEDAD, DIAS_MIN, FRAC_MIN = 2.5, 1.5, 10, 0.7


def ruta(p: str) -> Path:
    q = Path(p)
    return q if q.is_absolute() else RAIZ / q


def area_predios() -> pd.DataFrame:
    if (PROC / "predio.parquet").exists():
        return pd.read_parquet(PROC / "predio.parquet", columns=["predio_id", "area_ha"])
    import json
    feats = json.loads((PROC / "predio_muestra.geojson").read_text())["features"]
    return pd.DataFrame([{k: f["properties"][k] for k in ("predio_id", "area_ha")} for f in feats])


def en_ventana(a: pd.DataFrame) -> pd.DataFrame:
    """Une predio -> celda -> ventana_seca por fecha; agrega ventana_id y dias_sin_lluvia."""
    pc = pd.read_parquet(PROC / "predio_clima.parquet", columns=["predio_id", "celda_id"]).drop_duplicates("predio_id")
    v = pd.read_parquet(PROC / "ventana_seca.parquet", columns=["celda_id", "ventana_id", "inicio", "fin"])
    d = pd.read_parquet(PROC / "dias_sin_lluvia.parquet", columns=["celda_id", "fecha", "dias_sin_lluvia"])
    d = d.drop_duplicates(["celda_id", "fecha"])
    a = a.merge(pc, on="predio_id", how="left")
    w = a[["predio_id", "fecha", "celda_id"]].merge(v, on="celda_id")
    w = w[(w.fecha >= w.inicio) & (w.fecha <= w.fin)].drop_duplicates(["predio_id", "fecha"])
    a = a.merge(w[["predio_id", "fecha", "ventana_id"]], on=["predio_id", "fecha"], how="left")
    return a.merge(d, on=["celda_id", "fecha"], how="left")


VENTANAS = ("seca", "todas", "lluvia")


def marcar_senal(a: pd.DataFrame, umbral_verdor: float = UMBRAL_VERDOR, umbral_humedad: float = UMBRAL_HUMEDAD,
                 dias_min: int = DIAS_MIN, ventana: str = "seca") -> pd.DataFrame:
    """Marca cada fecha (salida de en_ventana): en_ventana (ventana seca con la racha mínima), valida (además
    despejada y con referencia) y senal (además sobre los dos umbrales). Es la regla del docstring.

    `ventana` existe para medir cuánto aporta la condición de sequía (ablacion_ventana.py): "seca" es la regla
    del modelo; "todas" acepta cualquier fecha; "lluvia" solo las fechas con dato de clima que no cumplen la regla."""
    seca = a.ventana_id.notna() & (a.dias_sin_lluvia >= dias_min)
    a["en_ventana"] = {"seca": seca, "todas": True, "lluvia": a.dias_sin_lluvia.notna() & ~seca}[ventana]
    a["valida"] = a.en_ventana & (a.estado == "ok")
    a["senal"] = a.valida & (a.z_verdor >= umbral_verdor) & (a.z_humedad >= umbral_humedad)
    return a


def confianza(r: pd.Series, args) -> tuple[str, str]:
    motivos = []  # (nivel, motivo)
    if r.n_fechas_validas < args.min_fechas_baja:
        motivos.append((0, f"pocas_fechas({r.n_fechas_validas})"))
    elif r.n_fechas_validas < args.min_fechas_media:
        motivos.append((1, f"pocas_fechas({r.n_fechas_validas})"))
    if r.frac_sin_clima > 0.5:
        motivos.append((0, "sin_clima"))
    if r.frac_sin_referencia > 0.5:
        motivos.append((0, "sin_referencia"))
    if r.frac_nublado > 0.5:
        motivos.append((1, f"nubosidad({r.frac_nublado:.0%})"))
    if pd.isna(r.pix_mediana) or r.pix_mediana < 25:
        motivos.append((0, "pocos_pixeles"))
    elif r.pix_mediana < 50:
        motivos.append((1, "pocos_pixeles"))
    if r.area_ha > 100:
        motivos.append((1, "predio_grande"))
    if r.referencia == "provisional":
        motivos.append((1, "referencia_provisional"))
    nivel = min([m[0] for m in motivos], default=2)
    return NIVELES[nivel], ";".join(m[1] for m in motivos)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--anomalias", default="data/processed/anomalias_predio.parquet")
    ap.add_argument("--salida", default="data/processed/senal_riego.parquet")
    ap.add_argument("--umbral-verdor", type=float, default=UMBRAL_VERDOR)
    ap.add_argument("--umbral-humedad", type=float, default=UMBRAL_HUMEDAD)
    ap.add_argument("--dias-min", type=int, default=DIAS_MIN, help="días sin lluvia mínimos en la fecha de la imagen")
    ap.add_argument("--ventana", choices=VENTANAS, default="seca",
                    help="qué fechas cuentan: seca (regla del modelo), todas o lluvia (solo para medir, ver ablacion_ventana.py)")
    ap.add_argument("--frac-min", type=float, default=FRAC_MIN, help="fracción de fechas con señal para senal_riego")
    ap.add_argument("--min-fechas-baja", type=int, default=3)
    ap.add_argument("--min-fechas-media", type=int, default=6)
    args = ap.parse_args()

    a = pd.read_parquet(ruta(args.anomalias))
    a = en_ventana(a)
    sin_celda = a.celda_id.isna().sum()
    if sin_celda:
        print(f"aviso: {sin_celda} filas sin celda de clima (quedan fuera de ventana)")
    a = marcar_senal(a, args.umbral_verdor, args.umbral_humedad, args.dias_min, args.ventana)
    a["nublado_v"] = a.en_ventana & (a.estado == "nublado")
    a["sinref_v"] = a.en_ventana & (a.estado == "sin_referencia")
    a["sin_clima"] = a.dias_sin_lluvia.isna()

    av = a[a.valida]
    claves = ["predio_id", "zona", "temporada"]
    base = a.groupby(claves).agg(
        n_fechas=("fecha", "size"), n_fechas_ventana=("en_ventana", "sum"), n_fechas_validas=("valida", "sum"),
        n_fechas_senal=("senal", "sum"), n_nublado=("nublado_v", "sum"), n_sinref=("sinref_v", "sum"),
        frac_sin_clima=("sin_clima", "mean"), referencia=("referencia", "first"))
    med = av.groupby(claves).agg(
        z_verdor_mediana=("z_verdor", "median"), z_humedad_mediana=("z_humedad", "median"),
        ndvi_mediana=("ndvi", "median"), ndmi_mediana=("ndmi", "median"), pix_mediana=("n_pix_validos", "median"))
    pix_todas = a[a.estado != "nublado"].groupby(claves)["n_pix_validos"].median()
    r = base.join(med).reset_index()
    # Sin fechas válidas, los píxeles salen de cualquier fecha despejada.
    r["pix_mediana"] = r["pix_mediana"].fillna(r.set_index(claves).index.map(pix_todas).to_series(index=r.index))
    nv = r.n_fechas_ventana.replace(0, np.nan)
    r["frac_nublado"] = (r.n_nublado / nv).fillna(0).round(3)
    r["frac_sin_referencia"] = (r.n_sinref / nv).fillna(0).round(3)
    r["frac_sin_clima"] = r.frac_sin_clima.round(3)
    r["frac_senal"] = (r.n_fechas_senal / r.n_fechas_validas.replace(0, np.nan)).round(3)
    r["senal_riego"] = r.frac_senal.fillna(0) >= args.frac_min
    r = r.merge(area_predios(), on="predio_id", how="left")
    r[["confianza", "motivos_confianza"]] = r.apply(lambda x: pd.Series(confianza(x, args)), axis=1)
    cols = ["predio_id", "zona", "temporada", "n_fechas", "n_fechas_ventana", "n_fechas_validas", "n_fechas_senal",
            "frac_senal", "senal_riego", "z_verdor_mediana", "z_humedad_mediana", "ndvi_mediana", "ndmi_mediana",
            "frac_nublado", "frac_sin_referencia", "frac_sin_clima", "pix_mediana", "area_ha", "referencia", "confianza",
            "motivos_confianza"]
    r = r[cols]
    for c in ["z_verdor_mediana", "z_humedad_mediana", "ndvi_mediana", "ndmi_mediana"]:
        r[c] = r[c].round(3)
    r.to_parquet(ruta(args.salida), index=False)

    print(f"umbrales z_verdor >= {args.umbral_verdor}, z_humedad >= {args.umbral_humedad}, "
          f"dias-min {args.dias_min}, frac-min {args.frac_min}")
    print(f"-> {args.salida}: {len(r)} predio-temporadas; referencia {r.referencia.unique().tolist()}")
    print(f"fechas en ventana seca: {a.en_ventana.mean():.0%}; válidas: {a.valida.mean():.0%}; "
          f"sin clima: {a.sin_clima.mean():.0%}")
    print(r.groupby(["zona", "temporada"]).agg(
        predios=("predio_id", "size"), con_senal=("senal_riego", "sum"),
        frac_senal_mediana=("frac_senal", "median"), fechas_validas_mediana=("n_fechas_validas", "median")).to_string())
    print("\nconfianza:")
    print(r.groupby(["zona", "confianza"]).size().unstack(fill_value=0).to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
