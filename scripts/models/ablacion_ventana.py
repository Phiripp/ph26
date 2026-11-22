# /// script
# requires-python = ">=3.11"
# dependencies = ["geopandas>=1.0", "pandas", "pyarrow", "numpy", "scikit-learn", "shapely>=2.0"]
# ///
"""¿Cuánto aporta la condición de sequía del detector de riego? Medición del supuesto "solo confiable sin lluvia".

El detector (M3) solo cuenta imágenes de diciembre a marzo tomadas tras 10 días o más sin lluvia. Ese supuesto
se fijó al diseñar el modelo y no se había medido. Este script lo mide de tres formas y escribe
docs/ablacion-ventana.md. Las hipótesis, las métricas y qué las refutaría se escribieron antes de correrlo
(sección "Antes de medir" del documento, texto fijo en PRERREGISTRO).

A. Ablación contra los casos de la DGA. Corre M3 y M5 sobre la validación y el universo 2025-26 cambiando solo qué
   fechas cuentan (`detector_riego.py --ventana` y `--dias-min`) y evalúa como M6: lift en banda alta del predio
   del punto, AUC entre fiscalizados y cuánto cambia el ranking frente a la regla actual. Se corre con los umbrales
   calibrados en M7 (elegidos con estos mismos casos y con la regla actual: favorecen al control) y con los
   iniciales (fijados antes de mirar).
B. Por imagen, según los días sin lluvia. En las series de verano (validación, 7 temporadas, y universo 2025-26):
   fracción de imágenes despejadas con señal (z sobre los dos umbrales, sin exigir sequía) en huertos del
   Catastro Frutícola (riego seguro) y en predios sin frutales, por tramo de días sin lluvia.
C. Por mes del año, con la muestra de 100 predios que tiene el año completo (serie_predio.parquet). No hay serie
   del secano de CONAF fuera de diciembre a marzo, así que la referencia son los predios de la muestra sin frutales
   y secos en el verano de otras temporadas (NDVI mediano <= NDVI_SECO). Con la misma fórmula de M2 (mediana y
   escala robusta con piso 0,05) y los umbrales de M3: fracción de imágenes de huertos con señal (detección) y de
   predios secos con señal frente a los demás secos (falsa alarma), por mes.

Límites: A y B solo ven el verano (las series procesadas son de diciembre a marzo). C usa una referencia sustituta
y pocos predios; mide el mecanismo, no el desempeño del modelo. La prueba completa fuera del verano necesita bajar
la serie del secano de CONAF para todo el año.

Uso: uv run scripts/models/ablacion_ventana.py [--procesos 6]
"""

import argparse
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parents[2]
PROC = RAIZ / "data" / "processed"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from calibracion import SERIES, correr  # noqa: E402
from detector_riego import DIAS_MIN, FRAC_MIN, UMBRAL_HUMEDAD, UMBRAL_VERDOR, en_ventana  # noqa: E402
from validacion import UMBRALES_INICIALES, auc_ic, casos, wilson  # noqa: E402

CALIBRADOS = {"umbral_verdor": UMBRAL_VERDOR, "umbral_humedad": UMBRAL_HUMEDAD, "frac_min": FRAC_MIN}
INICIALES = {k: UMBRALES_INICIALES[k] for k in CALIBRADOS}
# (nombre, --ventana, --dias-min). La primera es el control: la regla del modelo.
VARIANTES = [("seca, 10 días o más (regla actual)", "seca", DIAS_MIN), ("todas las fechas de verano", "todas", DIAS_MIN),
             ("solo con lluvia reciente", "lluvia", DIAS_MIN), ("seca, sin mínimo de días", "seca", 0),
             ("seca, 5 días o más", "seca", 5), ("seca, 20 días o más", "seca", 20)]
TRAMOS = [(0, 2, "0 a 2"), (3, 5, "3 a 5"), (6, 9, "6 a 9"), (10, 19, "10 a 19"), (20, 10_000, "20 o más")]
HUERTO, NDVI_SECO, MIN_SECOS, ESCALA_MIN, MAD_A_SIGMA = 0.5, 0.30, 5, 0.05, 1.4826
VERANO = (12, 1, 2, 3)
ESTACIONES = {"verano (dic a mar)": (12, 1, 2, 3), "otoño (abr y may)": (4, 5), "invierno (jun a ago)": (6, 7, 8),
              "primavera (sep a nov)": (9, 10, 11)}
MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
UMBRAL_MES = 0.80  # detección mensual desde la cual un mes se lista como utilizable (descriptivo, no es una regla del modelo)
B = 1000

PRERREGISTRO = """## Antes de medir

Escrito antes de correr el script.

**Decisión que cambia.** Si la condición de sequía no aporta, se puede quitar del modelo y de la frase del pitch ("si lleva diez días sin llover…"), y el modelo deja de depender del dato de lluvia. Si el contraste entre regado y secano se cae fuera del verano, el método no se puede llevar tal cual a meses o regiones con lluvia (corrida nacional).

**Población.** A: los fiscalizados por extracción de la validación con vegetación detectable, y el universo de 7.911 predios para el azar. B: todas las imágenes despejadas de verano de esas dos series. C: 100 predios de muestra con el año completo.

| Hipótesis | Métrica | Qué la refuta | Predicción |
| --- | --- | --- | --- |
| H1. Dentro del verano, exigir 10 días sin lluvia mejora el ranking | Lift en alta del predio del punto, AUC entre fiscalizados y predios que cambian de banda, frente a "todas las fechas de verano" | Diferencia de 1 positivo o menos en alta, intervalo de la diferencia de AUC que incluye 0 y 95 % o más del universo en la misma banda | Refutada: casi todas las imágenes de verano ya cumplen la condición |
| H2. Tras una lluvia, los huertos muestran menos señal | Fracción de imágenes de huertos con señal, con menos de 10 días sin lluvia frente a 10 o más | Diferencia menor que 10 puntos | Refutada o débil: en verano llueve poco |
| H3. Fuera del verano el contraste se pierde | Detección en huertos y falsa alarma en predios secos, invierno frente a verano | Detección menos de 20 puntos más baja y falsa alarma menos de 10 puntos más alta | Confirmada: el cerro reverdece con la lluvia |
"""


# ---------------------------------------------------------------- A. ablación contra los casos

def una(tarea: tuple) -> dict:
    nombre, ventana, dias_min, umbrales, etiqueta = tarea
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        m3 = ["--umbral-verdor", str(umbrales["umbral_verdor"]), "--umbral-humedad", str(umbrales["umbral_humedad"]),
              "--frac-min", str(umbrales["frac_min"]), "--dias-min", str(dias_min), "--ventana", ventana]
        for k, (anom, cons) in SERIES.items():
            correr(["scripts/models/detector_riego.py", "--anomalias", str(PROC / anom),
                    "--salida", str(tmp / f"senal_{k}.parquet"), *m3])
            correr(["scripts/models/indice_sospecha.py", "--senal", str(tmp / f"senal_{k}.parquet"),
                    "--consumo", str(PROC / cons), "--salida", str(tmp / f"puntaje_{k}.parquet")])
        f = casos(tmp / "puntaje_v.parquet", tmp / "puntaje_u.parquet")
        u = pd.read_parquet(tmp / "puntaje_u.parquet", columns=["predio_id", "zona", "banda", "puntaje"])
        fechas = {k: pd.read_parquet(tmp / f"senal_{k}.parquet", columns=["n_fechas_validas"])["n_fechas_validas"]
                  for k in SERIES}
    pos = f[f["y"] & f["detectable"] & f["banda_punto"].notna()]
    n, k = len(pos), int((pos["banda_punto"] == "alta").sum())
    base = float(pos["azar_punto_alta"].mean())
    lo, hi = wilson(k, n)
    km = int(pos["banda_punto"].isin(["alta", "media"]).sum())
    d = f[f["detectable"]]
    auc, auc_lo, auc_hi = auc_ic(d["y"].to_numpy(), d["puntaje"].to_numpy(), np.random.default_rng(0))
    return {"nombre": nombre, "umbrales": etiqueta, "n_pos": n, "k_alta": k, "azar_alta": base, "lift": k / n / base,
            "lift_lo": lo / base, "lift_hi": hi / base, "k_alta_media": km, "auc": auc, "auc_lo": auc_lo, "auc_hi": auc_hi,
            "n_auc": len(d), "universo_alta": float((u["banda"] == "alta").mean()),
            "fechas_u": float(fechas["u"].median()), "fechas_v": float(fechas["v"].median()),
            "sin_fechas_u": float((fechas["u"] == 0).mean()),
            "u": u.set_index("predio_id"), "casos": d.set_index("expediente")[["y", "puntaje"]]}


def frente_al_control(r: dict, c: dict) -> dict:
    """Cuánto cambia el ranking del universo y el AUC frente a la regla actual, con los mismos umbrales."""
    u = r["u"].join(c["u"], rsuffix="_c", how="inner")
    alta, alta_c = set(u.index[u["banda"] == "alta"]), set(u.index[u["banda_c"] == "alta"])
    j = r["casos"].join(c["casos"], rsuffix="_c", how="inner")
    y, a, b = j["y"].to_numpy(), j["puntaje"].to_numpy(), j["puntaje_c"].to_numpy()
    from sklearn.metrics import roc_auc_score
    rng, difs = np.random.default_rng(0), []
    for _ in range(B):
        i = rng.integers(0, len(y), len(y))
        if 0 < y[i].sum() < len(i):
            difs.append(roc_auc_score(y[i], a[i]) - roc_auc_score(y[i], b[i]))
    return {"misma_banda": float((u["banda"] == u["banda_c"]).mean()),
            "alta_comun": len(alta & alta_c) / max(len(alta | alta_c), 1),
            "spearman": float(u["puntaje"].corr(u["puntaje_c"], method="spearman")),
            "dif_auc": float(roc_auc_score(y, a) - roc_auc_score(y, b)),
            "dif_auc_lo": float(np.percentile(difs, 2.5)), "dif_auc_hi": float(np.percentile(difs, 97.5))}


# ---------------------------------------------------------------- B. por imagen, según días sin lluvia

def por_lluvia() -> tuple[pd.DataFrame, dict]:
    cols = ["predio_id", "zona", "fecha", "temporada", "estado", "z_verdor", "z_humedad", "ref_ndvi_mediana"]
    a = pd.concat([pd.read_parquet(PROC / anom, columns=cols).assign(serie=k) for k, (anom, _) in SERIES.items()])
    a = en_ventana(a.drop_duplicates(["predio_id", "fecha"]))
    a = a[(a["estado"] == "ok") & a["dias_sin_lluvia"].notna()]
    a["senal"] = (a["z_verdor"] >= UMBRAL_VERDOR) & (a["z_humedad"] >= UMBRAL_HUMEDAD)
    cu = pd.read_parquet(PROC / "predio_cultivo.parquet", columns=["predio_id", "frac_fruticola"])
    a = a.merge(cu, on="predio_id", how="left")
    a["grupo"] = np.where(a["frac_fruticola"] >= HUERTO, "huerto", np.where(a["frac_fruticola"].fillna(0) == 0, "sin_frutal", "mixto"))
    a["tramo"] = pd.cut(a["dias_sin_lluvia"], [t[0] - 0.5 for t in TRAMOS] + [1e9], labels=[t[2] for t in TRAMOS])
    filas = []
    for tramo, g in a.groupby("tramo", observed=True):
        h, s = g[g["grupo"] == "huerto"], g[g["grupo"] == "sin_frutal"]
        filas.append({"tramo": tramo, "imagenes": len(g), "huerto_n": len(h), "huerto_senal": h["senal"].mean(),
                      "huerto_predios": h["predio_id"].nunique(), "sin_n": len(s), "sin_senal": s["senal"].mean(),
                      "z_verdor_huerto": h["z_verdor"].median(), "z_humedad_huerto": h["z_humedad"].median(),
                      "ndvi_secano": g["ref_ndvi_mediana"].median()})
    h = a[a["grupo"] == "huerto"]
    seca = h["dias_sin_lluvia"] >= DIAS_MIN
    rng, difs = np.random.default_rng(0), []
    ids = h["predio_id"].unique()
    por_predio = h.assign(seca=seca).groupby(["predio_id", "seca"])["senal"].agg(["sum", "size"]).unstack(fill_value=0)
    for _ in range(B):  # remuestreo por predio: las imágenes de un mismo predio no son independientes
        m = por_predio.loc[rng.choice(ids, len(ids))]
        difs.append(m[("sum", False)].sum() / max(m[("size", False)].sum(), 1) - m[("sum", True)].sum() / m[("size", True)].sum())
    res = {"seca": float(h.loc[seca, "senal"].mean()), "lluvia": float(h.loc[~seca, "senal"].mean()),
           "n_seca": int(seca.sum()), "n_lluvia": int((~seca).sum()), "dif_lo": float(np.percentile(difs, 2.5)),
           "dif_hi": float(np.percentile(difs, 97.5)), "frac_lluvia": float((a["dias_sin_lluvia"] < DIAS_MIN).mean()),
           "imagenes": len(a)}
    return pd.DataFrame(filas), res


# ---------------------------------------------------------------- C. por mes del año, con la muestra

def robusto(x: np.ndarray) -> tuple[float, float]:
    m = np.median(x)
    return m, max(MAD_A_SIGMA * np.median(np.abs(x - m)), ESCALA_MIN)


def por_mes() -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    s = pd.read_parquet(PROC / "serie_predio.parquet", columns=["predio_id", "zona", "fecha", "ndvi", "ndmi",
                                                               "nubosidad_pct", "n_pix_validos"])
    s = s[s["ndvi"].notna() & s["ndmi"].notna() & (s["nubosidad_pct"] <= 30) & (s["n_pix_validos"] >= 10)]
    s = s.sort_values("n_pix_validos", ascending=False).drop_duplicates(["predio_id", "fecha"])
    s["mes"] = s["fecha"].dt.month
    s["temporada"] = s["fecha"].dt.year - (s["mes"] < 7).astype(int)  # año agrícola, de julio a junio
    cu = pd.read_parquet(PROC / "predio_cultivo.parquet", columns=["predio_id", "frac_fruticola"])
    s = s.merge(cu, on="predio_id", how="left")
    huerto = s["frac_fruticola"] >= HUERTO
    sin_frutal = s["frac_fruticola"].fillna(0) == 0
    # Predio seco de la temporada t: sin frutales y NDVI mediano de verano <= NDVI_SECO en las OTRAS temporadas
    verano = s[sin_frutal & s["mes"].isin(VERANO)].groupby(["predio_id", "temporada"])["ndvi"].median().reset_index()
    filas = []
    for (z, t), g in s.groupby(["zona", "temporada"]):
        otras = verano[verano["temporada"] != t].groupby("predio_id")["ndvi"].median()
        secos = set(otras.index[otras <= NDVI_SECO])
        for fecha, d in g.groupby("fecha"):
            ref = d[d["predio_id"].isin(secos)]
            if len(ref) < MIN_SECOS:
                continue
            rv, rh = ref["ndvi"].to_numpy(), ref["ndmi"].to_numpy()
            mv, ev = robusto(rv)
            mh, eh = robusto(rh)
            for r in d[huerto.loc[d.index]].itertuples():
                filas.append((z, t, fecha, r.mes, r.predio_id, "huerto", r.ndvi, r.ndmi,
                              (r.ndvi - mv) / ev >= UMBRAL_VERDOR and (r.ndmi - mh) / eh >= UMBRAL_HUMEDAD, mv))
            for i, r in enumerate(ref.itertuples()):  # cada predio seco frente a los demás secos
                ov, oh = np.delete(rv, i), np.delete(rh, i)
                m1, e1 = robusto(ov)
                m2, e2 = robusto(oh)
                filas.append((z, t, fecha, r.mes, r.predio_id, "seco", r.ndvi, r.ndmi,
                              (r.ndvi - m1) / e1 >= UMBRAL_VERDOR and (r.ndmi - m2) / e2 >= UMBRAL_HUMEDAD, mv))
    d = pd.DataFrame(filas, columns=["zona", "temporada", "fecha", "mes", "predio_id", "grupo", "ndvi", "ndmi", "senal", "ndvi_ref"])
    lluvia = pd.read_parquet(PROC / "clima.parquet", columns=["zona", "punto_id", "fecha", "lluvia_corr_mm"])
    lluvia = lluvia.groupby(["zona", "punto_id", lluvia["fecha"].dt.year.rename("a"), lluvia["fecha"].dt.month.rename("mes")])[
        "lluvia_corr_mm"].sum().groupby("mes").mean()

    def resumen(g: pd.DataFrame) -> dict:
        h, x = g[g["grupo"] == "huerto"], g[g["grupo"] == "seco"]
        return {"huerto_predios": h["predio_id"].nunique(), "huerto_n": len(h), "deteccion": h["senal"].mean(),
                "seco_predios": x["predio_id"].nunique(), "seco_n": len(x), "falsa_alarma": x["senal"].mean(),
                "ndvi_huerto": h["ndvi"].median(), "ndvi_seco": x["ndvi"].median()}

    meses = pd.DataFrame([{"mes": m, "lluvia_mm": lluvia.get(m, np.nan), **resumen(g)} for m, g in d.groupby("mes")])
    rng = np.random.default_rng(0)
    est = []
    for nombre, ms in ESTACIONES.items():
        g = d[d["mes"].isin(ms)]
        fila = {"estacion": nombre, **resumen(g)}
        for grupo, col in (("huerto", "deteccion"), ("seco", "falsa_alarma")):
            p = g[g["grupo"] == grupo].groupby("predio_id")["senal"].agg(["sum", "size"])
            bs = [(lambda m: m["sum"].sum() / m["size"].sum())(p.loc[rng.choice(p.index, len(p))]) for _ in range(B)]
            fila[f"{col}_lo"], fila[f"{col}_hi"] = np.percentile(bs, 2.5), np.percentile(bs, 97.5)
        est.append(fila)
    est = pd.DataFrame(est)
    d["estacion"] = d["mes"].map({m: n for n, ms in ESTACIONES.items() for m in ms})
    zonas = pd.DataFrame([{"zona": z, "estacion": e, **resumen(g)} for (z, e), g in d.groupby(["zona", "estacion"])])
    info = {"por_zona_estacion": zonas,
            "predios": d["predio_id"].nunique(), "fechas": d["fecha"].nunique(),
            "por_zona": d.groupby("zona")["temporada"].agg(lambda x: f"{x.min()} a {x.max()}").to_dict(),
            "secos_por_zona": d[d["grupo"] == "seco"].groupby("zona")["predio_id"].nunique().to_dict(),
            "huertos_por_zona": d[d["grupo"] == "huerto"].groupby("zona")["predio_id"].nunique().to_dict()}
    return meses, est, info


# ---------------------------------------------------------------- documento

def pct(x, d=0) -> str:
    return "s/d" if x is None or pd.isna(x) else f"{100 * x:.{d}f} %".replace(".", ",")


def dec(x, d=2) -> str:
    return "s/d" if x is None or pd.isna(x) else f"{x:.{d}f}".replace(".", ",")


def veredicto(refutada: bool) -> str:
    return "**Refutada**" if refutada else "**No refutada**"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--procesos", type=int, default=6)
    args = ap.parse_args()

    tareas = [(n, v, dmin, um, et) for et, um in (("calibrados", CALIBRADOS), ("iniciales", INICIALES)) for n, v, dmin in VARIANTES]
    with ProcessPoolExecutor(args.procesos) as ex:
        res = list(ex.map(una, tareas))
    control = {r["umbrales"]: r for r in res if r["nombre"] == VARIANTES[0][0]}
    for r in res:
        r |= frente_al_control(r, control[r["umbrales"]])
    tramos, lluvia = por_lluvia()
    meses, est, info = por_mes()

    todas = {r["umbrales"]: r for r in res if r["nombre"] == VARIANTES[1][0]}
    h1 = all(abs(todas[e]["k_alta"] - control[e]["k_alta"]) <= 1 and todas[e]["dif_auc_lo"] <= 0 <= todas[e]["dif_auc_hi"]
             and todas[e]["misma_banda"] >= 0.95 for e in todas)
    dif_h2 = lluvia["seca"] - lluvia["lluvia"]
    h2 = dif_h2 < 0.10
    e = est.set_index("estacion")
    ver, inv = e.loc["verano (dic a mar)"], e.loc["invierno (jun a ago)"]
    h3 = (ver["deteccion"] - inv["deteccion"] < 0.20) and (inv["falsa_alarma"] - ver["falsa_alarma"] < 0.10)
    pri = e.loc["primavera (sep a nov)"]
    ze = info["por_zona_estacion"].set_index(["zona", "estacion"])
    h3_zona = [f"en {z} la detección pasa de {pct(ze.loc[(z, 'verano (dic a mar)'), 'deteccion'])} en verano a "
               f"{pct(ze.loc[(z, 'invierno (jun a ago)'), 'deteccion'])} en invierno y "
               f"{pct(ze.loc[(z, 'primavera (sep a nov)'), 'deteccion'])} en primavera "
               f"({int(ze.loc[(z, 'verano (dic a mar)'), 'seco_predios'])} predios secos de referencia)"
               for z in sorted({i[0] for i in ze.index})]
    def refutada(z: str) -> bool:  # el mismo criterio escrito antes de medir, por zona
        v, i = ze.loc[(z, "verano (dic a mar)")], ze.loc[(z, "invierno (jun a ago)")]
        return bool(v["deteccion"] - i["deteccion"] < 0.20 and i["falsa_alarma"] - v["falsa_alarma"] < 0.10)

    h3_z = {z: refutada(z) for z in sorted({i[0] for i in ze.index})}
    pu = pd.read_parquet(PROC / "puntaje.parquet", columns=["predio_id", "senal_riego", "frac_fruticola", "confianza"])
    hu = pu[pu["frac_fruticola"] >= HUERTO]
    sf = pu[pu["frac_fruticola"].fillna(0) == 0]
    peor = meses.loc[meses["deteccion"].idxmin()]
    buenos = [m for m in [11, 12, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10] if meses.set_index("mes").loc[m, "deteccion"] >= UMBRAL_MES]

    L = ["# ¿Cuánto aporta la condición de sequía del detector? (ablación de la ventana seca)", "",
         "Generado por `scripts/models/ablacion_ventana.py` (no editar a mano). El detector de riego (M3) solo cuenta "
         "imágenes de diciembre a marzo tomadas tras 10 días o más sin lluvia. Ese supuesto se fijó al diseñar el modelo "
         "y no se había medido.", "",
         "## Resultado", "",
         f"- H1, la condición de 10 días sin lluvia mejora el ranking dentro del verano: {veredicto(h1)}. "
         f"Con todas las fechas de verano, {pct(todas['calibrados']['misma_banda'], 1)} del universo queda en la misma banda "
         f"y el lift en alta pasa de {dec(control['calibrados']['lift'], 1)} a {dec(todas['calibrados']['lift'], 1)} veces "
         f"({control['calibrados']['k_alta']} y {todas['calibrados']['k_alta']} de {control['calibrados']['n_pos']} positivos). "
         f"Solo {pct(lluvia['frac_lluvia'], 1)} de las imágenes despejadas de verano tiene menos de {DIAS_MIN} días sin lluvia.",
         f"- H2, tras una lluvia los huertos muestran menos señal: {veredicto(h2)}. Huertos con señal en {pct(lluvia['seca'], 1)} "
         f"de las imágenes secas y en {pct(lluvia['lluvia'], 1)} de las imágenes con lluvia reciente "
         f"(con lluvia menos seca: {dec(-100 * dif_h2, 1)} puntos; IC 95 % {dec(100 * lluvia['dif_lo'], 1)} a "
         f"{dec(100 * lluvia['dif_hi'], 1)}).",
         f"- H3, fuera del verano el contraste se pierde: {veredicto(h3) if h3 == all(h3_z.values()) else '**Depende de la zona**'}"
         f"{'' if h3 == all(h3_z.values()) else ' (no refutada en ' + ', '.join(z for z, v in h3_z.items() if not v) + ')'}. Detección en huertos: {pct(ver['deteccion'])} en verano "
         f"y {pct(inv['deteccion'])} en invierno. Falsa alarma en predios secos: {pct(ver['falsa_alarma'], 1)} y "
         f"{pct(inv['falsa_alarma'], 1)}. Ese es el criterio escrito antes, con las dos zonas juntas. Por zona el resultado "
         f"cambia: {'; '.join(h3_zona)}. Es una muestra de {info['predios']} predios con una referencia sustituta: "
         "muestra el mecanismo, no el desempeño del modelo.",
         f"- Lo que no estaba en las hipótesis: el contraste sí se cae, pero en primavera y no con la lluvia. La detección baja a "
         f"{pct(pri['deteccion'])} entre septiembre y noviembre, con el mínimo en {MESES[int(peor['mes']) - 1]} "
         f"({pct(peor['deteccion'])}), cuando el NDVI de los predios secos sube a {dec(peor['ndvi_seco'])} "
         f"(en verano es {dec(ver['ndvi_seco'])}). El cerro reverdece después de las lluvias de invierno y tarda en secarse. "
         f"Meses con detección de {pct(UMBRAL_MES)} o más: {', '.join(MESES[m - 1] for m in buenos)}.", "",
         PRERREGISTRO,
         "## A. Ablación contra los casos de la DGA", "",
         "Misma evaluación que M6 (predio del punto de la DGA, positivos detectables, azar = proporción del universo de su "
         "zona en banda alta). Cada fila cambia solo qué fechas cuentan. Las columnas de la derecha comparan con la regla "
         "actual a iguales umbrales.", ""]
    for et, titulo in (("calibrados", f"Umbrales calibrados en M7 ({dec(UMBRAL_VERDOR, 1)}, {dec(UMBRAL_HUMEDAD, 1)} y {dec(FRAC_MIN, 1)})"),
                       ("iniciales", "Umbrales iniciales, fijados antes de mirar (2, 2 y 0,5)")):
        L += [f"### {titulo}", "",
              "| Fechas que cuentan | Fechas válidas por predio (mediana) | Predios sin fechas | Universo en alta | Positivos en alta | "
              "Lift en alta (IC 95 %) | En alta o media | AUC entre fiscalizados (IC 95 %) | Diferencia de AUC (IC 95 %) | "
              "Misma banda que la regla actual | Orden (Spearman) |",
              "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
        for r in [x for x in res if x["umbrales"] == et]:
            L.append(f"| {r['nombre']} | {dec(r['fechas_u'], 0)} | {pct(r['sin_fechas_u'], 1)} | {pct(r['universo_alta'], 1)} | "
                     f"{r['k_alta']} de {r['n_pos']} | {dec(r['lift'], 1)}× ({dec(r['lift_lo'], 1)}–{dec(r['lift_hi'], 1)}) | "
                     f"{r['k_alta_media']} de {r['n_pos']} | {dec(r['auc'])} ({dec(r['auc_lo'])}–{dec(r['auc_hi'])}) | "
                     f"{dec(r['dif_auc'])} ({dec(r['dif_auc_lo'])} a {dec(r['dif_auc_hi'])}) | {pct(r['misma_banda'], 1)} | "
                     f"{dec(r['spearman'], 3)} |")
        L.append("")
    L += ["La fila \"solo con lluvia reciente\" no es comparable: con 3 imágenes por predio el modelo marca confianza baja "
          "y baja la banda. Lo que pasa en las imágenes con lluvia se mide en B.", ""]
    L += [f"El AUC se calcula con {res[0]['n_auc']} fiscalizados detectables. Con tan pocos positivos, un caso mueve el lift "
          "en varias décimas. Los umbrales calibrados se eligieron con estos mismos casos y con la regla actual, así que "
          "esa tabla favorece al control; la de umbrales iniciales no tiene ese sesgo.", "",
          "## B. Por imagen, según los días sin lluvia (verano)", "",
          f"Por predio, con la regla actual (`puntaje.parquet`, 2025-26): el detector marca riego en {int(hu['senal_riego'].sum())} "
          f"de {len(hu)} predios de huerto ({pct(hu['senal_riego'].mean())}) y en {int(sf['senal_riego'].sum())} de {len(sf)} "
          f"predios sin frutales ({pct(sf['senal_riego'].mean())}). Lo primero mide cuánto riego conocido encuentra; lo segundo "
          "no es una tasa de error, porque un predio sin frutales puede regar pradera o cultivos anuales.", "",
          f"Imágenes despejadas y con referencia de las dos series ({lluvia['imagenes']:,} imágenes).".replace(",", ".")
          + f" Señal: z de verdor ≥ {dec(UMBRAL_VERDOR, 1)} y z de humedad ≥ {dec(UMBRAL_HUMEDAD, 1)}, sin exigir sequía. "
          f"Huerto: {pct(HUERTO)} o más de la superficie con frutales en el Catastro Frutícola (riego seguro). "
          "\"Sin frutales\" no es lo mismo que \"sin riego\": sirve de contraste, no de negativo.", "",
          "| Días sin lluvia | Imágenes | Imágenes de huertos | Huertos con señal | Imágenes sin frutales | Sin frutales con señal | "
          "z de verdor en huertos (mediana) | z de humedad en huertos (mediana) | NDVI del secano (mediana) |",
          "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in tramos.itertuples():
        L.append(f"| {r.tramo} | {r.imagenes} | {r.huerto_n} | {pct(r.huerto_senal, 1)} | {r.sin_n} | {pct(r.sin_senal, 1)} | "
                 f"{dec(r.z_verdor_huerto, 1)} | {dec(r.z_humedad_huerto, 1)} | {dec(r.ndvi_secano)} |")
    L += ["", f"Imágenes de huertos: {lluvia['n_seca']} con {DIAS_MIN} días o más sin lluvia y {lluvia['n_lluvia']} con menos.", "",
          "## C. Por mes del año (muestra con el año completo)", "",
          f"{info['predios']} predios de la muestra con serie de todo el año (`serie_predio.parquet`; temporadas por zona: "
          f"{info['por_zona']}). Huertos: {info['huertos_por_zona']}. Predios secos de referencia: {info['secos_por_zona']} "
          f"(sin frutales y con NDVI mediano de verano ≤ {dec(NDVI_SECO)} en las otras temporadas; hacen falta {MIN_SECOS} "
          "con dato en la fecha). Detección: imágenes de huertos con señal frente a los predios secos, con la fórmula de M2 "
          "y los umbrales de M3. Falsa alarma: imágenes de un predio seco con señal frente a los demás secos.", "",
          "| Estación | Imágenes de huertos | Detección (IC 95 %) | Imágenes de predios secos | Falsa alarma (IC 95 %) | "
          "NDVI de huertos | NDVI de predios secos |", "| --- | --- | --- | --- | --- | --- | --- |"]
    for r in est.itertuples():
        L.append(f"| {r.estacion} | {r.huerto_n} | {pct(r.deteccion)} ({pct(r.deteccion_lo)}–{pct(r.deteccion_hi)}) | {r.seco_n} | "
                 f"{pct(r.falsa_alarma, 1)} ({pct(r.falsa_alarma_lo, 1)}–{pct(r.falsa_alarma_hi, 1)}) | {dec(r.ndvi_huerto)} | "
                 f"{dec(r.ndvi_seco)} |")
    L += ["", "| Mes | Lluvia media del mes (mm) | Imágenes de huertos | Detección | Imágenes de predios secos | Falsa alarma | "
          "NDVI de huertos | NDVI de predios secos |", "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in meses.set_index("mes").loc[[7, 8, 9, 10, 11, 12, 1, 2, 3, 4, 5, 6]].reset_index().itertuples():
        L.append(f"| {MESES[r.mes - 1]} | {dec(r.lluvia_mm, 0)} | {r.huerto_n} | {pct(r.deteccion)} | {r.seco_n} | "
                 f"{pct(r.falsa_alarma, 1)} | {dec(r.ndvi_huerto)} | {dec(r.ndvi_seco)} |")
    L += ["", "Por zona (los años son distintos en cada una, así que también separa por año):", "",
          "| Zona | Estación | Predios de huerto | Imágenes de huertos | Detección | Predios secos | Falsa alarma |",
          "| --- | --- | --- | --- | --- | --- | --- |"]
    for r in info["por_zona_estacion"].sort_values(["zona", "estacion"]).itertuples():
        L.append(f"| {r.zona} | {r.estacion} | {r.huerto_predios} | {r.huerto_n} | {pct(r.deteccion)} | {r.seco_predios} | "
                 f"{pct(r.falsa_alarma, 1)} |")
    L += ["", "## Qué cambia", "",
          "- **La regla de 10 días sin lluvia se mantiene, pero no es lo que hace confiable al detector.** En los veranos de "
          "Valparaíso casi todas las imágenes ya la cumplen, y quitarla deja el ranking prácticamente igual. No conviene "
          "presentarla como el corazón del método.",
          "- **Lo que sí importa es la época del año**, y la causa es el verdor del cerro, no la lluvia de los últimos días. "
          "El contraste se pierde cuando el secano reverdece, y eso depende de la zona.",
          "- **Hipótesis para la corrida nacional:** usar una imagen solo si el secano de referencia está seco ese día "
          "(un tope al NDVI de la referencia), en vez de contar días sin lluvia. Serviría igual en zonas con otro régimen de "
          "lluvias. No está probada: hay que bajar la serie del secano de CONAF para todo el año y repetir A con ella.",
          "- **Posible ganancia:** si esa prueba confirma los meses de la tabla C, la ventana útil pasaría de 4 meses a más, "
          "con más imágenes por predio.", ""]
    L += ["## Límites", "",
          "- A y B solo ven el verano: las series procesadas van de diciembre a marzo. No dicen nada del resto del año.",
          f"- A tiene {control['calibrados']['n_pos']} positivos detectables. Sirve para ver si la regla cambia el resultado, "
          "no para afinarla.",
          "- C usa una referencia sustituta (predios de la muestra, no el secano de CONAF) y pocos predios. Los predios "
          "secos se eligen por su verano de otras temporadas, así que en verano la falsa alarma es baja en parte por "
          "construcción; el dato que importa es cómo cambian la detección y la falsa alarma al salir del verano.",
          "- Los huertos son los del Catastro Frutícola 2025: un huerto plantado después de la imagen baja la detección "
          "en todos los meses por igual.",
          "- La prueba completa fuera del verano necesita la serie del secano de CONAF para todo el año "
          "(`serie_sentinel2.py --referencia` sin limitar a diciembre a marzo).", ""]
    (RAIZ / "docs" / "ablacion-ventana.md").write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L[4:9]))


if __name__ == "__main__":
    main()
