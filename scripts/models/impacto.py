# /// script
# requires-python = ">=3.11"
# dependencies = ["geopandas>=1.0", "pandas", "pyarrow", "numpy", "scikit-learn"]
# ///
"""Métricas de impacto de Caudal, todas en rango (tarea M9).

Responde: ¿cuántos casos nuevos encontraría Caudal, cuánta agua y cuánto dinero hay en juego, y cuánto antes
habría detectado los casos que la DGA ya multó?

Entradas (data/processed/): puntaje.parquet (M5, universo 2025-26), puntaje_validacion.parquet (M5, 2019-20 a
2025-26), fiscalizacion.parquet (D6, D18) y la evaluación de M6 (validacion.casos).

Supuestos (fuentes en docs/spec-v2.md, Métricas de impacto):
- Un candidato no es un caso: casos esperados = candidatos x acierto. Acierto bajo y alto: intervalo de Wilson
  de la proporción de infractores entre los fiscalizados detectables cuyo predio del punto Caudal pone en banda
  alta. Acierto central: el 33 % de la DGA (2022–2025), no el de Caudal: son pocos casos, los umbrales de M3 se
  calibraron con ese mismo set (M7) y es el piso que fija el spec.
- Candidatos: predios en banda alta en 2025-26 sin ninguna fiscalización de la DGA desde 2018 a 500 m o menos. Los
  predios de más de 100 ha se reportan aparte (su exceso domina el total y su consumo es el menos seguro).
- m³ en juego = suma del exceso anual de los candidatos x acierto. Escenarios:
  conservador (sin predios con canal a 300 m o menos, exceso mínimo, acierto bajo), central (exceso central,
  acierto de la DGA) y alto (exceso máximo, acierto alto).
- Valor del agua: costo de reponerla con camión aljibe, 4.300 CLP/m³ (2.600–14.000; D14).
- Personas: dotación de 36,5 m³ por persona al año (100 l/día; rango 18,25–62; D14).
- Multas: multa mediana de la DGA por extracción en Z1 y Z2 (de fiscalizacion.parquet) y UTM a 72.450 CLP (la
  equivalencia usada en el spec).
- Adelanto: para cada positivo detectable, primera temporada desde 2019-20 en que el predio del punto estuvo en
  banda alta antes de la inspección. Es una cota inferior (la serie parte en 2019-20). El agua de ese periodo es la
  suma del exceso central de las temporadas en alta entre la alerta y la inspección.

Salidas: docs/impacto.md y data/processed/impacto.json (cifras para el frontend).

Uso: uv run scripts/models/impacto.py
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parents[2]
PROC = RAIZ / "data" / "processed"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from validacion import casos, lift_sin_calibrar, wilson  # noqa: E402

CLP_M3 = {"bajo": 2_600, "central": 4_300, "alto": 14_000}
M3_PERSONA = {"bajo": 62.0, "central": 36.5, "alto": 18.25}  # más m³ por persona = menos personas
UTM_CLP = 72_450
# Equivalencias para comunicar volúmenes (pitch y panel de impacto). Cada una con su fuente.
EQUIVALENCIAS = {
    "m3_persona_ano": {"valor": 36.5, "nota": "100 litros por persona al día",
                       "fuente": "Corte Suprema, 2021 (dotación mínima para Petorca)",
                       "url": "https://www.24horas.cl/regiones/valparaiso/corte-suprema-determina-100-litros-de-agua-por-habitantes-de-petorca-4708851"},
    "lata_monster_ml": {"valor": 473, "nota": "lata de Monster Energy",
                        "fuente": "ficha del producto", "url": "https://andina.micoca-cola.cl/monster-energy-green-473-ml/p"},
    "torre_costanera_m3": {"valor": 107_125 * 4.2, "nota": "estimación propia: 107.125 m² construidos x 4,2 m por piso; "
                           "ninguna fuente publica el volumen", "fuente": "WikiArquitectura (superficie y alturas de piso)",
                           "url": "https://es.wikiarquitectura.com/edificio/gran-torre-santiago-torre-gran-costanera/"},
}
ESC = {"bajo": "bajo", "dga": "central", "alto": "alto"}  # nivel de acierto -> nivel de precio y dotación


def mm(x: float) -> str:
    """Millones con coma decimal."""
    return f"{x / 1e6:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")


def n(x: float) -> str:
    return f"{x:,.0f}".replace(",", ".")


def dec(x: float) -> str:
    return f"{x:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")


def dec2(x: float) -> str:
    return f"{x:.2f}".replace(".", ",")


def pct(x: float) -> str:
    return f"{x:.0%}"


def acierto() -> dict:
    f = casos()
    d = f[f["detectable"] & (f["banda_punto"] == "alta")]
    k, tot = int(d["y"].sum()), len(d)
    lo, hi = wilson(k, tot)
    fis = pd.read_parquet(PROC / "fiscalizacion.parquet")
    fis = fis[fis["extraccion"].fillna(False).astype(bool) & fis["zona"].isin(["Z1", "Z2"])]
    ano = pd.to_datetime(fis["fecha_inspeccion"]).dt.year
    res = fis[fis["etiqueta"].isin(["positivo", "negativo"]) & ano.between(2022, 2025)]  # 107 del spec
    multas = fis.loc[(fis["etiqueta"] == "positivo") & (fis["multa_utm"] > 0), "multa_utm"]
    from sklearn.metrics import roc_auc_score
    pos = f[f["y"] & f["detectable"] & f["banda_punto"].notna()]
    lift = (pos["banda_punto"] == "alta").mean() / pos["azar_punto_alta"].mean()
    dd = f[f["detectable"]]
    return {"k": k, "n": tot, "bajo": lo, "central": k / tot, "alto": hi, "lift_alta": lift,
            "auc": roc_auc_score(dd["y"], dd["puntaje"]),
            "dga": (res["etiqueta"] == "positivo").mean(), "dga_n": len(res),
            "multa_mediana_utm": float(multas.median()), "multa_p25_utm": float(multas.quantile(.25)),
            "multa_p75_utm": float(multas.quantile(.75)), "n_multas": len(multas),
            "inspecciones_por_ano": fis.groupby(pd.to_datetime(fis["fecha_inspeccion"]).dt.year).size(),
            "f": f}


def sin_fiscalizar_500m(ids: pd.Series) -> pd.Series:
    """True si el predio no tiene ninguna fiscalización (cualquier tipo) desde 2018 a 500 m o menos (spec)."""
    import geopandas as gpd
    pr = gpd.read_parquet(PROC / "predio.parquet", columns=["predio_id", "geometry"])
    pr = pr[pr["predio_id"].isin(ids)].to_crs("EPSG:32719")
    fi = gpd.read_parquet(PROC / "fiscalizacion.parquet", columns=["fecha_inspeccion", "geometry"])
    fi = fi[fi.geometry.notna() & ~(pd.to_datetime(fi["fecha_inspeccion"]).dt.year < 2018)].to_crs("EPSG:32719")
    pr["geometry"] = pr.buffer(500)
    con = set(gpd.sjoin(pr, fi, predicate="intersects")["predio_id"])
    return ~ids.isin(con)


def candidatos(ac: dict) -> tuple[dict, pd.DataFrame]:
    u = pd.read_parquet(PROC / "puntaje.parquet")
    a = u[u["banda"] == "alta"]
    alta = a[sin_fiscalizar_500m(a["predio_id"]).to_numpy()]
    chicos = alta[~alta["predio_grande"].fillna(False)]
    grandes = alta[alta["predio_grande"].fillna(False)]
    esc = {
        "conservador": (chicos[~chicos["canal_300m"].fillna(False)], "m3_exceso_min", "bajo"),
        "central": (chicos, "m3_exceso_central", "dga"),
        "alto": (chicos, "m3_exceso_max", "alto"),
    }
    out = {}
    for nombre, (d, col, nivel) in esc.items():
        a = ac[nivel]
        m3 = d[col].sum() * a
        out[nombre] = {
            "candidatos": len(d), "acierto": a, "casos": len(d) * a, "m3_ano": m3,
            "clp_ano": m3 * CLP_M3[ESC[nivel]], "personas": m3 / M3_PERSONA[ESC[nivel]],
            "multas_clp": len(d) * a * {"bajo": ac["multa_p25_utm"], "dga": ac["multa_mediana_utm"],
                                        "alto": ac["multa_p75_utm"]}[nivel] * UTM_CLP,
        }
    resumen = {
        "universo": len(u), "alta": int((u["banda"] == "alta").sum()),
        "alta_fiscalizados": int((u["banda"] == "alta").sum() - len(alta)),
        "candidatos": len(alta), "candidatos_chicos": len(chicos), "candidatos_grandes": len(grandes),
        "grandes_exceso_min_m3": grandes["m3_exceso_min"].sum(),
        "por_zona": alta.groupby("zona").size().to_dict(),
        "con_canal": float(chicos["canal_300m"].fillna(False).mean()),
        "escenarios": out,
    }
    return resumen, alta


def adelanto(f: pd.DataFrame) -> pd.DataFrame:
    pv = pd.read_parquet(PROC / "puntaje_validacion.parquet")
    filas = []
    for _, r in f[f["y"] & f["detectable"] & f["predio_id"].notna()].iterrows():
        g = pv[(pv["predio_id"] == int(r["predio_id"])) & (pv["temporada"] <= r["temporada_previa"])].sort_values("temporada")
        en_alta = g[g["banda"] == "alta"]
        fila = {"expediente": r["expediente"], "zona": r["zona"], "inspeccion": pd.Timestamp(r["fecha_inspeccion"]).date(),
                "multa_utm": r["multa_utm"], "banda_previa": r["banda_punto"]}
        if len(en_alta):
            t0 = en_alta["temporada"].iloc[0]
            inicio = pd.Timestamp(f"{t0[:4]}-12-01")
            fila |= {"primera_alerta": t0, "anos_adelanto": (pd.Timestamp(r["fecha_inspeccion"]) - inicio).days / 365.25,
                     "temporadas_en_alta": len(en_alta), "m3_exceso_central": en_alta["m3_exceso_central"].sum(),
                     "m3_exceso_min": en_alta["m3_exceso_min"].sum(), "censurado": t0 == "2019-20"}
        filas.append(fila)
    return pd.DataFrame(filas)


def main() -> None:
    ac = acierto()
    res, alta = candidatos(ac)
    ad = adelanto(ac["f"])
    det = ad.dropna(subset=["primera_alerta"]) if "primera_alerta" in ad else ad.iloc[0:0]
    e = res["escenarios"]
    insp = ac["inspecciones_por_ano"]
    insp_ano = float(insp[insp.index.isin(range(2020, 2026))].mean())

    L = [
        "# Impacto de Caudal (M9)", "",
        "Generado por `scripts/models/impacto.py` (no editar a mano). Todas las cifras van en rango; los supuestos "
        "están en el encabezado del script y en [spec-v2.md](spec-v2.md#métricas-de-impacto). Un candidato no es un "
        "caso: se multiplica por un acierto (M6 y DGA).", "",
        "## En una frase", "",
        f"En la temporada 2025-26, Caudal marca **{n(res['candidatos'])} predios en banda alta sin ninguna "
        f"fiscalización de la DGA a 500 m desde 2018** en Petorca y Aconcagua bajo. Son unos "
        f"**{n(e['conservador']['casos'])} a {n(e['central']['casos'])} casos** y "
        f"**{mm(e['conservador']['m3_ano'])} a {mm(e['central']['m3_ano'])} millones de m³ al año** sin derecho "
        f"(escenario conservador a central), el agua de **{n(e['conservador']['personas'])} a "
        f"{n(e['central']['personas'])} personas** al año. El escenario alto (tabla) suma todos los extremos y "
        "no se usa como titular.", "",
        "## Acierto", "",
        f"- DGA hoy: {pct(ac['dga'])} de las fiscalizaciones por extracción con resultado terminan en infracción "
        f"({ac['dga_n']} expedientes de Z1 y Z2 inspeccionados entre 2022 y 2025).",
        f"- Caudal, entre los fiscalizados detectables cuyo predio pone en banda alta: {ac['k']} de {ac['n']} "
        f"({pct(ac['central'])}; IC 95 % {pct(ac['bajo'])}–{pct(ac['alto'])}). Con tan pocos casos, el intervalo "
        f"incluye el acierto de la DGA: entre predios que la DGA ya eligió, Caudal no los distingue bien (AUC "
        f"{dec2(ac['auc'])}, ver [validacion.md](validacion.md)).",
        f"- Lo que Caudal agrega es **dónde mirar**: en banda alta encuentra {dec(ac['lift_alta'])} veces más infractores que elegir "
        "predios al azar (M6), y la lista sale del satélite, sin esperar una denuncia.", "",
        "## Candidatos nuevos (2025-26)", "",
        f"- Universo: {n(res['universo'])} predios elegibles; {n(res['alta'])} en banda alta, de los cuales "
        f"{n(res['alta_fiscalizados'])} ya tienen alguna fiscalización de la DGA a 500 m o menos (desde 2018).",
        f"- Candidatos sin fiscalizar: {n(res['candidatos'])} (" + ", ".join(f"{z}: {n(v)}" for z, v in res["por_zona"].items())
        + f"). {n(res['candidatos_grandes'])} son predios de más de 100 ha y van aparte: suman "
        f"{mm(res['grandes_exceso_min_m3'])} millones de m³/año de exceso mínimo, más que todos los demás juntos, y su "
        "consumo es el menos seguro.",
        f"- Capacidad: la DGA hizo en promedio {insp_ano:.0f} fiscalizaciones por extracción al año en Z1 y Z2 "
        f"(2020–2025). A ese ritmo, revisar los {n(res['candidatos_chicos'])} candidatos tomaría "
        f"{res['candidatos_chicos'] / insp_ano:.0f} años: hay que priorizar dentro de la banda (puntaje) y usar la ruta "
        "(M8: 10 a 12 predios por jornada).",
        f"- El {pct(res['con_canal'])} de los candidatos tiene un canal a 300 m o menos: puede regar con acciones de "
        "canal, que no aparecen en los derechos. El escenario conservador los excluye.", "",
        "## Escenarios (predios de hasta 100 ha)", "",
        "| Escenario | Candidatos | Acierto | Casos esperados | m³/año | Valor del agua (CLP/año) | Personas | Multas (CLP) |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for nombre, x in e.items():
        L.append(f"| {nombre} | {n(x['candidatos'])} | {pct(x['acierto'])} | {n(x['casos'])} | "
                 f"{mm(x['m3_ano'])} millones | {mm(x['clp_ano'] / 1e3)} mil millones | {n(x['personas'])} | "
                 f"{mm(x['multas_clp'] / 1e3)} mil millones |")
    L += ["",
          "Conservador: sin predios con canal cerca, exceso mínimo, acierto bajo (cota inferior de Caudal), 2.600 CLP/m³, 62 m³ por persona, "
          "multa p25. Central: exceso central, acierto de la DGA (33 %), 4.300 CLP/m³, 36,5 m³ por persona, multa mediana. Alto: "
          "exceso máximo, acierto alto, 14.000 CLP/m³, 18,25 m³ por persona, multa p75. "
          f"Multa mediana {dec(ac['multa_mediana_utm'])} UTM (p25 {dec(ac['multa_p25_utm'])}, p75 "
          f"{dec(ac['multa_p75_utm'])}; {ac['n_multas']} multas) a {n(UTM_CLP)} CLP/UTM.",
          "",
          "## Adelanto en casos conocidos", "",
          f"Positivos detectables de la validación cuyo predio del punto estuvo en banda alta antes de la inspección: "
          f"{len(det)} de {len(ad)}.", ""]
    if len(det):
        L += ["| Expediente | Zona | Inspección | Primera alerta | Años antes | Temporadas en alta | m³ sobre el derecho (central) | Multa (UTM) |",
              "| --- | --- | --- | --- | --- | --- | --- | --- |"]
        for _, r in det.sort_values("anos_adelanto", ascending=False).iterrows():
            cota = "≥ " if r["censurado"] else ""
            L.append(f"| {r['expediente']} | {r['zona']} | {r['inspeccion']} | {r['primera_alerta']} | "
                     f"{cota}{dec(r['anos_adelanto'])} | {int(r['temporadas_en_alta'])} | {n(r['m3_exceso_central'])} | "
                     f"{dec(r['multa_utm'])} |")
        m3_tot, m3_min = det["m3_exceso_central"].sum(), det["m3_exceso_min"].sum()
        L += ["",
              f"- Mediana: Caudal los habría marcado **al menos {dec(det['anos_adelanto'].median())} años antes** de la inspección "
              f"(cota inferior: la serie parte en 2019-20; {int(det['censurado'].sum())} ya estaban en alta en 2019-20).",
              f"- Agua extraída sobre el derecho entre la primera alerta y la inspección: {mm(m3_min)} a {mm(m3_tot)} "
              f"millones de m³ (mínimo a central) en {len(det)} predios; a 4.300 CLP/m³, {mm(m3_tot * CLP_M3['central'])} "
              f"millones de CLP; el agua de {n(m3_tot / M3_PERSONA['central'])} personas durante un año.", ""]
    L += ["## Limitaciones", "",
          "- El acierto se mide entre predios que la DGA ya eligió y con pocos casos (intervalo ancho).",
          "- El consumo es neto de M4 dividido por la eficiencia; el rango de consumo es ancho (máximo ≈ 2,9 veces el mínimo).",
          "- El agua de canal (acciones) no está en los derechos: el escenario conservador excluye a los predios con canal cerca.",
          "- El 44 % de los positivos no es detectable por verdor: estas cifras no los cuentan.",
          "- Las cifras son agregadas: no se identifican predios ni roles.", ""]
    (RAIZ / "docs" / "impacto.md").write_text("\n".join(L), encoding="utf-8")

    js = {"temporada": "2025-26", "candidatos": res["candidatos"], "candidatos_por_zona": res["por_zona"],
          "candidatos_mas_100ha": res["candidatos_grandes"], "acierto_dga": ac["dga"],
          "acierto_caudal": {k: ac[k] for k in ("bajo", "central", "alto")}, "lift_alta": ac["lift_alta"], "auc_fiscalizados": ac["auc"],
          "escenarios": e, "adelanto_mediana_anos": float(det["anos_adelanto"].median()) if len(det) else None,
          "adelanto_casos": len(det), "supuestos": {"clp_m3": CLP_M3, "m3_persona_ano": M3_PERSONA, "utm_clp": UTM_CLP},
          # Cifra de validación para comunicar: la medida con los umbrales fijados antes de calibrar (M7).
          "lift_alta_sin_calibrar": lift_sin_calibrar(),
          "capacidad": {"fiscalizaciones_por_ano": insp_ano, "candidatos_hasta_100ha": res["candidatos_chicos"],
                        "anos": res["candidatos_chicos"] / insp_ano},
          "equivalencias": EQUIVALENCIAS,
          "torres_costanera_ano": {k: e[k]["m3_ano"] / EQUIVALENCIAS["torre_costanera_m3"]["valor"]
                                   for k in ("conservador", "central")},
          "generado": pd.Timestamp.now().isoformat(timespec="seconds"),
          "fuentes": ["data/processed/puntaje.parquet", "data/processed/puntaje_validacion.parquet",
                      "data/processed/fiscalizacion.parquet", "data/processed/calibracion_grilla.csv"]}
    (PROC / "impacto.json").write_text(json.dumps(js, ensure_ascii=False, indent=2, default=float), encoding="utf-8")
    print("\n".join(L[:12]))
    print("-> docs/impacto.md\n-> data/processed/impacto.json")


if __name__ == "__main__":
    main()
