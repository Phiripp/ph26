# /// script
# requires-python = ">=3.11"
# dependencies = ["geopandas>=1.0", "pandas", "pyarrow", "numpy", "scikit-learn"]
# ///
"""Validación del índice de sospecha contra las fiscalizaciones de la DGA (tarea M6).

Pregunta que responde: si un inspector hubiera recorrido los predios que Caudal marca, ¿cuántos de los casos que la
DGA multó habría encontrado, comparado con elegir predios al azar? La pregunta "¿distingue infractores de no
infractores entre los fiscalizados?" se reporta aparte (AUC) como límite: la DGA ya elige predios regados.

Entradas (data/processed/):
- fiscalizacion.parquet (D6, D18): expedientes de extracción de aguas con etiqueta, vecindario (predios a 30 m o
  menos del punto), set_validacion, temporada_previa y detectable.
- puntaje_validacion.parquet (M5 sobre la serie de validación): banda y puntaje por predio y temporada.
- puntaje.parquet (M5 sobre los 7.911 elegibles, 2025-26): universo para la línea base.

Reglas:
- Cada expediente se evalúa en su temporada previa (la última de diciembre a marzo antes de la inspección) de dos
  formas: (1) principal, el predio que contiene el punto de la DGA (la unidad que visita un inspector; si el punto
  cae en el predio equivocado el recall baja, así que es conservadora); (2) sensibilidad, por vecindario: la mejor
  banda y el mayor puntaje entre los predios a 30 m o menos (D18).
- Solo etiquetas positivo y negativo (un expediente en trámite no es infracción), de extracción de aguas, con
  set_validacion distinto de "fuera". Negativo fuerte = "No acoge"; "Cierra expediente" suele ser archivo.
- Línea base del azar por expediente: proporción p del universo de su zona en la banda (predio del punto) o
  probabilidad de que al menos uno de los n predios del vecindario caiga en ella, 1 - (1 - p)^n. Tomar la mejor
  banda de varios predios sube el recall y también el azar: sin este ajuste el lift sale inflado.
  Lift = recall / media de esa probabilidad.
- Recall con intervalo de Wilson al 95 %; AUC con intervalo por remuestreo (3.000).

Limitación: el universo solo existe para 2025-26; los expedientes son de 2019-20 a 2024-25. Se asume que la
proporción de predios en cada banda es parecida entre temporadas.

Salidas:
- docs/validacion.md: métricas y casos clave (se sobrescribe).
- data/processed/validacion_casos.geojson: un punto por expediente evaluado, con etiqueta, banda y puntaje (para el
  mapa; GitHub lo muestra como mapa).

Uso: uv run scripts/models/validacion.py
"""

import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

RAIZ = Path(__file__).resolve().parents[2]
PROC = RAIZ / "data" / "processed"
ORDEN = {"alta": 3, "media": 2, "baja": 1, "sin_alerta": 0}
NIVELES = {"alta": ["alta"], "alta o media": ["alta", "media"], "cualquier alerta": ["alta", "media", "baja"]}
CASOS_CLAVE = ["FO-0504-95", "FD-0501-181", "FO-0504-157", "FD-0504-257"]
B = 3000


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (np.nan, np.nan)
    p = k / n
    c = (p + z * z / (2 * n)) / (1 + z * z / n)
    h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (c - h, c + h)


def auc_ic(y: np.ndarray, s: np.ndarray, rng: np.random.Generator) -> tuple[float, float, float]:
    a = roc_auc_score(y, s)
    bs = []
    for _ in range(B):
        i = rng.integers(0, len(y), len(y))
        if 0 < y[i].sum() < len(i):
            bs.append(roc_auc_score(y[i], s[i]))
    return a, np.percentile(bs, 2.5), np.percentile(bs, 97.5)


UMBRALES_INICIALES = {"umbral_verdor": 2.0, "umbral_humedad": 2.0, "frac_min": 0.5, "dias_min": 10}  # antes de M7


def lift_sin_calibrar() -> dict | None:
    """Lift en banda alta con los umbrales de M3 fijados antes de calibrar: es la cifra sin sesgo de elección.
    Se lee de la grilla de M7 (calibracion_grilla.csv); None si la grilla no existe."""
    f = PROC / "calibracion_grilla.csv"
    if not f.exists():
        return None
    g = pd.read_csv(f)
    r = g[np.logical_and.reduce([np.isclose(g[c], v) for c, v in UMBRALES_INICIALES.items()])]
    if r.empty:
        return None
    r = r.iloc[0]
    n = int(r["n_pos_abs"])
    k = int(round(r["recall_alta_abs"] * n))
    azar = r["recall_alta_abs"] / r["lift_alta_abs"]
    lo, hi = wilson(k, n)
    return {"valor": float(r["lift_alta_abs"]), "ic_bajo": lo / azar, "ic_alto": hi / azar, "positivos": k, "de": n,
            "umbrales": UMBRALES_INICIALES}


def nota_calibracion() -> list[str]:
    x = lift_sin_calibrar()
    if x is None:
        return []
    return ["- **Umbrales calibrados con este mismo set (M7).** Los umbrales de M3 se eligieron en "
            "[calibracion.md](calibracion.md) con estos positivos, así que el lift es optimista. Con los umbrales "
            f"iniciales (fijados antes de mirar) era {x['valor']:.1f} veces (IC 95 % {x['ic_bajo']:.1f}–{x['ic_alto']:.1f}): "
            "esa es la cifra sin sesgo de elección."]


def casos(validacion: Path = PROC / "puntaje_validacion.parquet",
          universo: Path = PROC / "puntaje.parquet") -> gpd.GeoDataFrame:
    f = gpd.read_parquet(PROC / "fiscalizacion.parquet")
    f = f[f["extraccion"].fillna(False).astype(bool) & f["etiqueta"].isin(["positivo", "negativo"])
          & (f["set_validacion"] != "fuera") & f["temporada_previa"].notna()].copy()
    pv = pd.read_parquet(validacion)
    pvi = pv.set_index(["predio_id", "temporada"])
    u = pd.read_parquet(universo)
    share = {(z, nivel): u.loc[u["zona"] == z, "banda"].isin(bandas).mean()
             for z in u["zona"].unique() for nivel, bandas in NIVELES.items()}

    filas = []
    for i, r in f.iterrows():
        g = pv[pv["predio_id"].isin(list(r["vecindario"])) & (pv["temporada"] == r["temporada_previa"])]
        fila = {"n_predios": len(g)}
        clave = (int(r["predio_id"]), r["temporada_previa"]) if pd.notna(r["predio_id"]) else None
        if clave in pvi.index:
            fila["banda_punto"] = pvi.at[clave, "banda"]
            fila["puntaje_punto"] = pvi.at[clave, "puntaje"]
            for nivel in NIVELES:
                fila[f"azar_punto_{nivel}"] = share[(r["zona"], nivel)]
        if len(g):
            fila["banda"] = max(g["banda"], key=ORDEN.get)
            fila["puntaje"] = g["puntaje"].max()
            fila["senal_riego"] = bool(g["senal_riego"].any())
            fila["con_derechos"] = bool((g.sort_values("puntaje").iloc[-1]["estado_derechos"]) == "con_derechos")
            for nivel in NIVELES:
                fila[f"azar_{nivel}"] = 1 - (1 - share[(r["zona"], nivel)]) ** len(g)
        filas.append(pd.Series(fila, name=i))
    f = f.join(pd.DataFrame(filas))
    f = f[f["n_predios"] > 0].copy()
    f["y"] = f["etiqueta"] == "positivo"
    f["negativo_fuerte"] = f["decision"].str.lower().str.contains("no acoge", na=False)
    f["detectable"] = f["detectable"].fillna(False).astype(bool)
    return f


def tabla_recall(pos: pd.DataFrame, punto: bool = True) -> list[str]:
    banda, azar = ("banda_punto", "azar_punto_") if punto else ("banda", "azar_")
    pos = pos[pos[banda].notna()]
    out = ["| Nivel | Positivos encontrados | Recall (IC 95 %) | Azar esperado | Lift (IC 95 %) |", "| --- | --- | --- | --- | --- |"]
    for nivel, bandas in NIVELES.items():
        k, n = int(pos[banda].isin(bandas).sum()), len(pos)
        lo, hi = wilson(k, n)
        base = pos[f"{azar}{nivel}"].mean()
        out.append(f"| {nivel} | {k} de {n} | {k / n:.0%} ({lo:.0%}–{hi:.0%}) | {base:.0%} | "
                   f"{k / n / base:.1f}× ({lo / base:.1f}–{hi / base:.1f}) |")
    return out


def main() -> None:
    rng = np.random.default_rng(0)
    f = casos()
    det = f[f["detectable"]]
    lineas = [
        "# Validación del índice de sospecha (M6)",
        "",
        "Generado por `scripts/models/validacion.py` (no editar a mano). Datos: `fiscalizacion.parquet` (D6, D18), "
        "`puntaje_validacion.parquet` y `puntaje.parquet` (M5). Mapa: [validacion_casos.geojson](../data/processed/validacion_casos.geojson).",
        "",
        "## Resumen",
        "",
    ]
    pos_d = det[det["y"]]
    pp = pos_d[pos_d["banda_punto"].notna()]
    k_a, n_p = int((pp["banda_punto"] == "alta").sum()), len(pp)
    lo_a, hi_a = wilson(k_a, n_p)
    base_a = pp["azar_punto_alta"].mean()
    k_am = int(pp["banda_punto"].isin(NIVELES["alta o media"]).sum())
    base_am = pp["azar_punto_alta o media"].mean()
    kv = int(pos_d["banda"].isin(NIVELES["alta o media"]).sum())
    y, s = det["y"].to_numpy(), det["puntaje"].to_numpy()
    auc, auc_lo, auc_hi = auc_ic(y, s, rng)
    pt = f[f["y"] & f["banda_punto"].notna()]
    kt, bt = int((pt["banda_punto"] == "alta").sum()), pt["azar_punto_alta"].mean()
    lift_todos, (lt_lo, lt_hi) = kt / len(pt) / bt, [w / bt for w in wilson(kt, len(pt))]
    lineas += [
        f"- **Prioriza mejor que el azar en la banda alta.** De los {n_p} positivos detectables por verdor, el predio "
        f"del punto de la DGA cae en banda alta en {k_a} ({k_a / n_p:.0%}), contra {base_a:.0%} al azar: "
        f"**{k_a / n_p / base_a:.1f} veces** (IC 95 % {lo_a / base_a:.1f}–{hi_a / base_a:.1f}). En alta o media: "
        f"{k_am} ({k_am / n_p:.0%}) contra {base_am:.0%} ({k_am / n_p / base_am:.1f} veces).",
        f"- **Por vecindario el lift es menor.** Con la mejor banda de los predios a 30 m, {kv} de {len(pos_d)} "
        f"positivos quedan en alta o media, pero el azar también sube (varios predios): "
        f"{kv / len(pos_d) / pos_d['azar_alta o media'].mean():.1f} veces (IC 95 % "
        f"{wilson(kv, len(pos_d))[0] / pos_d['azar_alta o media'].mean():.1f}–"
        f"{wilson(kv, len(pos_d))[1] / pos_d['azar_alta o media'].mean():.1f}).",
        f"- **No distingue infractores entre fiscalizados.** AUC {auc:.2f} (IC 95 % {auc_lo:.2f}–{auc_hi:.2f}) entre "
        f"{int(y.sum())} positivos y {int((~y).sum())} negativos detectables. La DGA ya fiscaliza predios regados: "
        f"tienen señal de riego el {det.loc[det['y'], 'senal_riego'].mean():.0%} de los positivos y el "
        f"{det.loc[~det['y'], 'senal_riego'].mean():.0%} de los negativos.",
        f"- **El verdor no ve todo.** {int((~f['detectable'] & f['y']).sum())} de {int(f['y'].sum())} positivos "
        "no son detectables por verdor (NDVI previo bajo 0,30 en el vecindario: suelo desnudo o sequía). Contándolos, "
        f"el lift en alta baja a {lift_todos:.1f} veces (IC 95 % {lt_lo:.1f}–{lt_hi:.1f}).",
        *nota_calibracion(),
        "- **Muestra chica.** Los intervalos son anchos: sirven para decir si hay señal, no para afinar umbrales.",
        "",
        "## Recall frente al azar: predio del punto (principal)",
        "",
        "Banda del predio que contiene el punto de la inspección, en la temporada previa. Azar: proporción del "
        "universo de su zona en esa banda (2025-26).",
        "",
        f"### Positivos detectables ({n_p})",
        "",
        *tabla_recall(pos_d),
        "",
    ]
    limpio = pos_d[pos_d["set_validacion"] == "limpio"]
    lineas += [f"### Positivos detectables del set limpio ({len(limpio)})", "",
               "Sin otro predio a 30 m, sin etiquetas mixtas ni recurso (D18).", "", *tabla_recall(limpio), ""]
    pos_all = f[f["y"]]
    lineas += [f"### Todos los positivos, detectables o no ({int(pos_all['banda_punto'].notna().sum())})", "",
               *tabla_recall(pos_all), ""]
    for z in sorted(pos_d["zona"].unique()):
        pz = pos_d[pos_d["zona"] == z]
        lineas += [f"### Positivos detectables de {z} ({int(pz['banda_punto'].notna().sum())})", "", *tabla_recall(pz), ""]
    lineas += ["## Recall frente al azar: vecindario (sensibilidad)", "",
               "Mejor banda entre los predios a 30 m o menos del punto. Azar: probabilidad de que al menos uno de los n "
               "predios del vecindario caiga en la banda, 1 − (1 − p)^n.", "",
               f"### Positivos detectables ({len(pos_d)})", "", *tabla_recall(pos_d, punto=False), "",
               f"### Todos los positivos ({len(pos_all)})", "", *tabla_recall(pos_all, punto=False), ""]

    # AUC entre fiscalizados.
    lineas += ["## Entre fiscalizados (límite)", "",
               "| Comparación | Positivos | Negativos | AUC (IC 95 %) |", "| --- | --- | --- | --- |"]
    for nombre, d in [("Detectables, todos los negativos", det),
                      ("Detectables, solo \"No acoge\"", det[det["y"] | det["negativo_fuerte"]]),
                      ("Todos (detectables o no)", f)]:
        a, lo, hi = auc_ic(d["y"].to_numpy(), d["puntaje"].to_numpy(), rng)
        lineas.append(f"| {nombre} | {int(d['y'].sum())} | {int((~d['y']).sum())} | {a:.2f} ({lo:.2f}–{hi:.2f}) |")
    am = det["banda"].isin(NIVELES["alta o media"])
    lineas += ["", f"Acierto entre fiscalizados detectables: {det['y'].mean():.0%} en general y "
               f"{det.loc[am, 'y'].mean():.0%} entre los que Caudal pone en alta o media "
               f"({int(det.loc[am, 'y'].sum())} de {int(am.sum())}).", ""]

    # Por banda y etiqueta.
    ct = pd.crosstab([det["etiqueta"]], det["banda"]).reindex(columns=list(ORDEN), fill_value=0)
    lineas += ["## Bandas de los fiscalizados detectables", "", "| Etiqueta | " + " | ".join(ORDEN) + " |",
               "| --- |" + " --- |" * len(ORDEN)]
    for et, row in ct.iterrows():
        lineas.append(f"| {et} | " + " | ".join(str(int(v)) for v in row) + " |")
    lineas.append("")

    # Casos clave.
    lineas += ["## Casos clave", "", "| Expediente | Zona | Etiqueta | Temporada previa | Detectable | Banda | Puntaje | Derechos propios |",
               "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for e in CASOS_CLAVE:
        c = f[f["expediente"] == e]
        if c.empty:
            continue
        c = c.iloc[0]
        lineas.append(f"| {e} | {c['zona']} | {c['etiqueta']} | {c['temporada_previa']} | "
                      f"{'sí' if c['detectable'] else 'no'} | {c['banda']} | {c['puntaje']:.0f} | "
                      f"{'sí' if c['con_derechos'] else 'no'} |")
    lineas += ["",
               "## Por qué el AUC es bajo y qué se probó", "",
               "- Sesgo de selección: la DGA fiscaliza por denuncia u oficio predios que ya riegan; entre ellos el verdor satura.",
               "- Negativos débiles: más de la mitad son \"Cierra expediente\" (archivo), no \"No acoge\".",
               "- La infracción no siempre es de volumen: de los positivos detectables con derechos, la mayoría consume según "
               "M4 menos de la mitad de lo inscrito; su falta es de punto de captación, caudal instantáneo o traslado.",
               "- Rango de consumo ancho (máximo ≈ 2,9 veces el mínimo): solo se detectan excesos grandes.",
               "- Prueba de variantes de M5 (exceso anual o mensual × orden por volumen o por hectárea): mensual + hectárea "
               "dio el mayor AUC (0,558 contra 0,532) con el mismo recall. Ver `data/README.md`, sección M5.",
               "",
               "## Limitaciones", "",
               "- El universo de la línea base es 2025-26; los expedientes son de 2019-20 a 2024-25.",
               "- La ubicación del expediente es el punto declarado por la DGA; el vecindario de 30 m absorbe parte del error.",
               "- El 44 % de los positivos no es detectable por verdor: Caudal no los ve con esta señal.",
               "- Una cifra anterior (2,8 veces en alta, 2,3 en alta o media) comparaba la mejor banda del vecindario con "
               "la proporción de un solo predio: estaba inflada. Las cifras de este documento la reemplazan.",
               ""]
    (RAIZ / "docs" / "validacion.md").write_text("\n".join(lineas), encoding="utf-8")

    cols = ["expediente", "zona", "etiqueta", "decision", "fecha_inspeccion", "temporada_previa", "set_validacion",
            "detectable", "banda", "puntaje", "senal_riego", "con_derechos", "n_predios", "geometry"]
    g = f[cols].copy()
    g["fecha_inspeccion"] = g["fecha_inspeccion"].astype(str)
    g["marker-color"] = g["etiqueta"].map({"positivo": "#b7472a", "negativo": "#4a7c59"})
    g["marker-symbol"] = g["banda"].map({"alta": "3", "media": "2", "baja": "1", "sin_alerta": "0"})
    gpd.GeoDataFrame(g, geometry="geometry", crs=f.crs).to_crs("EPSG:4326").to_file(
        PROC / "validacion_casos.geojson", driver="GeoJSON")
    print("\n".join(lineas[:20]))
    print(f"\n-> docs/validacion.md\n-> {PROC / 'validacion_casos.geojson'} ({len(g)} expedientes)")


if __name__ == "__main__":
    main()
