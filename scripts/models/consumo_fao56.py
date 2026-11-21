# /// script
# requires-python = ">=3.11"
# dependencies = ["pandas", "pyarrow", "numpy"]
# ///
"""Consumo de riego estimado por predio con FAO-56 simplificado (tarea M4).

V_riego = Σ_mes max(0, Kc(NDVI) · ET0 − P_ef) · A, siempre como rango (mínimo, central, máximo), nunca una cifra.
Es consumo neto (lo que evapotranspira el cultivo y no cubre la lluvia), no agua extraída: el agua extraída es
mayor por la eficiencia de aplicación (microaspersión ≈ 85 %, Ferreyra y Selles, INIA, Redagrícola 2017).

Entradas (data/processed/):
- serie_predio_temporada_2025-26.parquet (o --serie): NDVI por predio y escena Sentinel-2 (D1, sin offset: D15).
  Sirven igual serie_predio_validacion.parquet y serie_predio_elegibles_2025-26.parquet (mismo esquema).
- clima.parquet + predio_clima.parquet: ET0 y lluvia corregida (lluvia_corr_mm) de la celda Open-Meteo del predio
  (D2). Se deduplica por (punto_id, fecha) (gap D17). Las estaciones DMC no traen ET0.
- predio_cultivo.parquet: especie_principal y frac_fruticola (D7), solo para ajustar el Kc.
- predio.parquet: area_ha.
- Opcional --serie-referencia: serie de los polígonos de secano (D11, modo --referencia de D1) para el NDVI de secano.

Salidas (data/processed/):
- consumo_predio.parquet: una fila por predio y mes de temporada seca (diciembre a marzo). Columnas: estado del mes
  (observado, interpolado, faltante), n_escenas, ndvi_mes, fc, kc_min/kc_central/kc_max, et0_mm, lluvia_mm,
  pef_min_mm/pef_max_mm, lamina_*_mm y m3_min/m3_central/m3_max.
- consumo_predio_temporada.parquet: una fila por predio y temporada: m3 y m3/ha de la temporada (solo si los 4 meses
  tienen NDVI observado o interpolado) y anual extrapolado, con columnas de calidad y `supuestos`.

Reglas:
1. Escena válida: nubosidad_pct <= 20 en el predio y NDVI no nulo. NDVI del mes = mediana de las escenas válidas
   (la mediana resiste escenas con nube o sombra mal enmascarada, p. ej. 61-6 el 02-01-2026: 96 % nubes, NDVI 0,39).
2. Mes sin escena válida: si hay meses observados antes y después dentro de la misma temporada, NDVI interpolado
   lineal (estado = interpolado). Si no, faltante: sin m3 en ese mes y sin total de temporada. No se inventa.
3. Kc(NDVI), tres relaciones; fc = (NDVI − NDVI_suelo) / (NDVI_veg − NDVI_suelo) recortada a [0, 1]
   (modelo de mezcla lineal de Gutman e Ignatov, 1998):
   - Lineal (Campos et al., 2010, Agric. Water Manag. 98:45-54): Kcb = 1,44·NDVI − 0,10. Se ancla en 0 en el suelo
     desnudo: Kc = 1,44·(NDVI − NDVI_suelo). Kamble et al. (2013, Remote Sens. 5:1588) dan casi la misma pendiente
     (Kc = 1,457·NDVI − 0,1725) con datos de flujo de varios cultivos.
   - Densidad (Allen y Pereira, 2009, Irrig. Sci. 28:17-34; FAO-56 ec. 98): Kcb = Kd·Kcb_full,
     Kd = min(1, ML·fc, fc^(1/(1+h))), ML = 1,5. Kcb_full y h salen de la especie (FAO-56 tabla 17) si existe.
     Es cóncava: da más Kc que la lineal en huertos ralos (sombra de árboles altos).
   - Secano: la lineal anclada en el NDVI del secano (matorral y pradera en verano): Kc = 1,44·(NDVI − NDVI_secano).
     Atribuye al riego solo el verdor por sobre la vegetación natural, que en verano vive del agua del suelo.
   Kc_min = secano; Kc_max = max(lineal, densidad); Kc_central = promedio de secano y lineal (con NDVI >=
   NDVI_secano es la pendiente de Campos anclada a mitad de camino: 1,44·(NDVI − (NDVI_suelo + NDVI_secano)/2)).
   Contraste local: en palto adulto (61-6, NDVI 0,71) da Kc 0,70, como el 0,72 medido en Quillota (Gardiazabal et
   al., 2003, Actas V Congreso Mundial del Aguacate, pp. 329-334) y el 0,70-0,76 de Chile y California (Ferreyra y
   Selles, INIA, 2017); la lineal pura da 0,80 (sobreestima) y la de secano 0,59.
   El Kc_min de FAO-56 (0,15-0,20, evaporación del suelo desnudo) se toma como 0: tras semanas sin lluvia la
   evaporación del suelo seco tiende a 0 (FAO-56 cap. 7, Kr = 0 con la capa superficial agotada) y nadie riega suelo
   desnudo. Control: 88-31 (suelo desnudo) da 0.
4. Ajuste por especie (solo ajusta; el Kc sale del NDVI): tope Kc_tope = f·Kc_mid_especie + (1−f)·1,20, con f =
   frac_fruticola, Kc_mid de FAO-56 tabla 12 (palto 0,85, cítricos 0,70, nogal 1,10…) y 1,20 el Kc máximo típico
   (FAO-56 ec. 72). Kcb_full de la relación de densidad = f·Kcb_full_especie + (1−f)·1,0. Sin especie: f = 0.
5. ET0: suma mensual de la celda Open-Meteo. Meses sin clima (clima.parquet parte en 2020: diciembre de 2019 en la
   temporada 2019-20) usan la climatología de la celda (clima_climatologia = True). Banda de ±10 % (--et0-incert)
   en mínimo y máximo: la ET0 de grilla no está calibrada con estaciones (las DMC no traen ET0; la calibración con
   estaciones está pendiente en el spec v2).
6. P_ef mensual: USDA-SCS (P·(125 − 0,2·P)/125 si P <= 250 mm; 125 + 0,1·P si no) para mínimo y central;
   FAO/AGLW "lluvia confiable" (0,6·P − 10 si P <= 70 mm; 0,8·P − 24 si no) para máximo. Ambas son las de CROPWAT
   (Smith, 1992). En diciembre a marzo la lluvia es casi 0 y P_ef no pesa; sí pesa en el anual.
7. A = area_ha del polígono completo. El NDVI es el promedio del predio y la relación lineal es lineal: Kc(NDVI medio)
   · A = Σ Kc(NDVI_píxel) · a_píxel, así que la fracción no vegetada ya está descontada en el Kc. Multiplicar A por fc
   o por frac_fruticola la descontaría dos veces. Como dato se entrega area_verde_ha = fc · area_ha.
8. Anual (12 meses de abril a marzo de la temporada): con solo diciembre a marzo de NDVI, el Kc de abril a noviembre
   es el Kc medio de la temporada (palto y cítricos son perennes; Gardiazabal et al., 2003, proponen Kc constante de
   0,72 todo el año para palto en Quillota). En especies caducas (f >= 0,5) el Kc de mayo a agosto es 0 (sin hojas).
   ET0 y lluvia de esos meses son las observadas de la celda; si no hay (antes de 2020), la climatología de la celda.
   anual_metodo = extrapolado_kc_temporada. Solo se entrega si la temporada está completa.

Limitaciones: predios de más de 100 ha (predio_grande) mezclan huerto y cerro; el NDVI medio diluye el huerto y el
Kc central cuenta el matorral como consumo: para ellos usar el mínimo. Hortalizas y cultivos anuales sin especie en el
catastro usan los valores genéricos. El NDVI no ve el estrés: un huerto regado de menos tiene NDVI alto por semanas.

Uso:
  uv run scripts/models/consumo_fao56.py
  uv run scripts/models/consumo_fao56.py --serie data/processed/serie_predio_validacion.parquet \\
      --salida data/processed/consumo_predio_validacion.parquet
  uv run scripts/models/consumo_fao56.py --serie data/processed/serie_predio_elegibles_2025-26.parquet \\
      --serie-referencia data/processed/serie_referencia_2025-26.parquet
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parents[2]
PROC = RAIZ / "data" / "processed"

MESES_TEMPORADA = [12, 1, 2, 3]
NUBOSIDAD_MAX = 20.0
NDVI_SUELO = 0.15  # control 88-31 (FO-0501-462, suelo desnudo): mediana 0,145 en dic-2025 a mar-2026
NDVI_VEG = 0.90  # cobertura completa en Sentinel-2
NDVI_SECANO = 0.30  # sin D11: predios de la muestra sin frutales de más de 100 ha dan 0,22-0,34 en verano
PENDIENTE = 1.44  # Campos et al. (2010)
ML = 1.5  # Allen y Pereira (2009): 1,5 a 2,0; 1,5 es el conservador
KC_MAX_GENERICO = 1.20  # FAO-56 ec. 72
KCB_FULL_GENERICO = 1.00
H_GENERICO = 2.0

# Especie: (Kc_mid FAO-56 tabla 12, Kcb_full ≈ Kcb_mid FAO-56 tabla 17, altura m, caduca)
ESPECIE = {
    "PALTO": (0.85, 0.80, 3.0, False),  # avocado, no ground cover
    "CHIRIMOYO": (0.85, 0.80, 3.0, False),  # no está en FAO-56: supuesto igual a palto (subtropical perenne)
    "LUCUMO": (0.85, 0.80, 3.0, False),  # ídem
    "LIMONERO": (0.70, 0.70, 4.0, False),  # citrus, 70 % canopy; Kcb_full 0,70 (FAO-56 nota 22)
    "NARANJO": (0.70, 0.70, 4.0, False),
    "MANDARINO": (0.70, 0.70, 4.0, False),
    "POMELO": (0.70, 0.70, 4.0, False),
    "NOGAL": (1.10, 1.05, 4.5, True),  # walnut orchard
    "ALMENDRO": (0.90, 0.85, 5.0, True),  # almonds, no ground cover
    "CEREZO": (0.95, 0.90, 4.0, True),  # apples/cherries/pears, no frosts
    "DURAZNERO TIPO CONSERVERO": (0.90, 0.85, 3.0, True),  # stone fruit, no frosts
    "NECTARINO": (0.90, 0.85, 3.0, True),
    "OLIVO": (0.70, 0.65, 4.0, False),  # olives, 40-60 % ground cover
    "KIWI": (1.05, 1.00, 3.0, True),
    "KIWI GOLD O KIWI AMARILLO": (1.05, 1.00, 3.0, True),
    "ARANDANO AMERICANO": (1.05, 1.00, 1.5, True),  # berries (bushes)
}


def temporada_de(fecha: pd.Series) -> pd.Series:
    anio = fecha.dt.year - (fecha.dt.month <= 6).astype(int)
    return anio.astype(str) + "-" + ((anio + 1) % 100).astype(str).str.zfill(2)


def pef_usda(p):
    p = np.asarray(p, dtype=float)
    return np.where(p <= 250, p * (125 - 0.2 * p) / 125, 125 + 0.1 * p)


def pef_aglw(p):
    p = np.asarray(p, dtype=float)
    return np.clip(np.where(p <= 70, 0.6 * p - 10, 0.8 * p - 24), 0, None)


def kc_densidad(fc, kcb_full, h):
    """Allen y Pereira (2009): Kcb = Kd·Kcb_full con Kc_min = 0."""
    with np.errstate(invalid="ignore", divide="ignore"):
        kd = np.minimum.reduce([np.ones_like(fc), ML * fc, np.power(fc, 1.0 / (1.0 + h))])
    return kd * kcb_full


def ndvi_mensual(serie: pd.DataFrame) -> pd.DataFrame:
    s = serie[(serie["nubosidad_pct"] <= NUBOSIDAD_MAX) & serie["ndvi"].notna()].copy()
    s["mes"] = s["fecha"].dt.to_period("M").dt.to_timestamp()
    return s.groupby(["predio_id", "mes"]).agg(ndvi_mes=("ndvi", "median"), n_escenas=("ndvi", "size")).reset_index()


def grilla_meses(serie: pd.DataFrame) -> pd.DataFrame:
    """Todos los meses de diciembre a marzo de cada temporada presente en la serie, por predio."""
    s = serie[serie["fecha"].dt.month.isin(MESES_TEMPORADA)][["predio_id", "zona", "fecha"]].copy()
    s["temporada"] = temporada_de(s["fecha"])
    pt = s[["predio_id", "zona", "temporada"]].drop_duplicates()
    filas = []
    for t in pt["temporada"].unique():
        a = int(t[:4])
        for m in MESES_TEMPORADA:
            filas.append({"temporada": t, "mes": pd.Timestamp(a if m == 12 else a + 1, m, 1)})
    return pt.merge(pd.DataFrame(filas), on="temporada")


def interpolar(g: pd.DataFrame) -> pd.DataFrame:
    g = g.sort_values("mes").copy()
    obs = g["ndvi_mes"].notna()
    g["estado"] = np.where(obs, "observado", "faltante")
    if obs.sum() >= 2:
        x = g["mes"].map(pd.Timestamp.toordinal).to_numpy()
        xi, yi = x[obs.to_numpy()], g.loc[obs, "ndvi_mes"].to_numpy()
        interior = (~obs) & (x > xi.min()) & (x < xi.max())
        g.loc[interior, "ndvi_mes"] = np.interp(x[interior.to_numpy()], xi, yi)
        g.loc[interior, "estado"] = "interpolado"
    return g


def clima_mensual() -> pd.DataFrame:
    c = pd.read_parquet(PROC / "clima.parquet", columns=["punto_id", "fuente", "fecha", "lluvia_corr_mm", "et0_mm"])
    c = c[c["fuente"] == "openmeteo"].drop_duplicates(["punto_id", "fecha"])  # D17
    c["mes"] = c["fecha"].dt.to_period("M").dt.to_timestamp()
    m = c.groupby(["punto_id", "mes"]).agg(et0_mm=("et0_mm", "sum"), lluvia_mm=("lluvia_corr_mm", "sum"),
                                           dias=("fecha", "size")).reset_index()
    m = m[m["dias"] >= 28].drop(columns="dias")  # meses completos (el último mes puede venir cortado)
    return m.rename(columns={"punto_id": "celda_id"})


def ndvi_secano_por_mes(ruta: Path | None) -> pd.DataFrame | None:
    if ruta is None or not ruta.exists():
        return None
    r = pd.read_parquet(ruta)
    r = r[(r["nubosidad_pct"] <= NUBOSIDAD_MAX) & r["ndvi"].notna()]
    r["mes"] = r["fecha"].dt.to_period("M").dt.to_timestamp()
    return r.groupby(["zona", "mes"])["ndvi"].median().rename("ndvi_secano").reset_index()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--serie", default=str(PROC / "serie_predio_temporada_2025-26.parquet"))
    ap.add_argument("--serie-referencia", default=None, help="serie de secano (D11); si no, NDVI_secano constante")
    ap.add_argument("--ndvi-secano", type=float, default=NDVI_SECANO)
    ap.add_argument("--et0-incert", type=float, default=0.10, help="banda relativa de ET0 para mínimo y máximo")
    ap.add_argument("--salida", default=str(PROC / "consumo_predio.parquet"))
    args = ap.parse_args()
    salida = Path(args.salida)
    salida_temp = salida.with_name(salida.stem + "_temporada.parquet")

    serie = pd.read_parquet(args.serie)
    serie["predio_id"] = serie["predio_id"].astype("int64")

    # 1-2. NDVI mensual, grilla de meses e interpolación
    g = grilla_meses(serie).merge(ndvi_mensual(serie), on=["predio_id", "mes"], how="left")
    g["n_escenas"] = g["n_escenas"].fillna(0).astype(int)
    g = pd.concat([interpolar(x) for _, x in g.groupby(["predio_id", "temporada"])], ignore_index=True)

    # Atributos del predio
    predio = pd.read_parquet(PROC / "predio.parquet", columns=["predio_id", "area_ha"])
    cultivo = pd.read_parquet(PROC / "predio_cultivo.parquet", columns=["predio_id", "especie_principal", "frac_fruticola"])
    pc = pd.read_parquet(PROC / "predio_clima.parquet", columns=["predio_id", "celda_id"])
    g = g.merge(predio, on="predio_id", how="left").merge(cultivo, on="predio_id", how="left").merge(pc, on="predio_id", how="left")
    g["frac_fruticola"] = g["frac_fruticola"].fillna(0.0)
    esp = g["especie_principal"].map(ESPECIE)
    conocida = esp.notna()
    g["especie_ajuste"] = np.where(conocida & (g["frac_fruticola"] > 0), g["especie_principal"], None)
    f = np.where(g["especie_ajuste"].notna(), g["frac_fruticola"], 0.0)
    kc_mid = np.where(conocida, esp.map(lambda e: e[0] if isinstance(e, tuple) else np.nan), KC_MAX_GENERICO)
    kcb_full = np.where(conocida, esp.map(lambda e: e[1] if isinstance(e, tuple) else np.nan), KCB_FULL_GENERICO)
    h = np.where(conocida & (f >= 0.5), esp.map(lambda e: e[2] if isinstance(e, tuple) else np.nan), H_GENERICO)
    g["caduca"] = conocida & (f >= 0.5) & esp.map(lambda e: bool(e[3]) if isinstance(e, tuple) else False)
    g["kc_tope"] = f * kc_mid + (1 - f) * KC_MAX_GENERICO
    g["kcb_full"] = f * kcb_full + (1 - f) * KCB_FULL_GENERICO
    g["h_m"] = h

    # NDVI de secano
    ref = ndvi_secano_por_mes(Path(args.serie_referencia) if args.serie_referencia else None)
    if ref is not None:
        g = g.merge(ref, on=["zona", "mes"], how="left")
        g["ndvi_secano"] = g["ndvi_secano"].fillna(args.ndvi_secano)
        fuente_secano = "referencia_d11"
    else:
        g["ndvi_secano"] = args.ndvi_secano
        fuente_secano = f"constante_{args.ndvi_secano}"

    # 3-4. Kc
    ndvi = g["ndvi_mes"].to_numpy()
    g["fc"] = np.clip((ndvi - NDVI_SUELO) / (NDVI_VEG - NDVI_SUELO), 0, 1)
    k_lin = np.clip(PENDIENTE * (ndvi - NDVI_SUELO), 0, None)
    k_den = kc_densidad(g["fc"].to_numpy(), g["kcb_full"].to_numpy(), g["h_m"].to_numpy())
    k_sec = np.clip(PENDIENTE * (ndvi - g["ndvi_secano"].to_numpy()), 0, None)
    tope = g["kc_tope"].to_numpy()
    g["kc_min"] = np.minimum(k_sec, tope)
    g["kc_central"] = np.minimum((k_lin + k_sec) / 2, tope)
    g["kc_max"] = np.minimum(np.fmax(k_lin, k_den), tope)

    # 5-6. Clima y lámina
    cm = clima_mensual()
    clim = cm.assign(m=cm["mes"].dt.month).groupby(["celda_id", "m"])[["et0_mm", "lluvia_mm"]].mean().reset_index()
    g = g.merge(cm, on=["celda_id", "mes"], how="left")
    g["clima_climatologia"] = g["et0_mm"].isna()  # mes fuera de clima.parquet (antes de 2020): climatología de la celda
    g = g.assign(m=g["mes"].dt.month).merge(clim, on=["celda_id", "m"], how="left", suffixes=("", "_clim"))
    for c in ["et0_mm", "lluvia_mm"]:
        g[c] = g[c].fillna(g.pop(f"{c}_clim"))
    g = g.drop(columns="m")
    g["pef_min_mm"] = pef_aglw(g["lluvia_mm"])  # P_ef baja -> consumo máximo
    g["pef_max_mm"] = pef_usda(g["lluvia_mm"])  # P_ef alta -> consumo mínimo y central
    e = args.et0_incert
    g["lamina_min_mm"] = np.clip(g["kc_min"] * g["et0_mm"] * (1 - e) - g["pef_max_mm"], 0, None)
    g["lamina_central_mm"] = np.clip(g["kc_central"] * g["et0_mm"] - g["pef_max_mm"], 0, None)
    g["lamina_max_mm"] = np.clip(g["kc_max"] * g["et0_mm"] * (1 + e) - g["pef_min_mm"], 0, None)
    # 7. Área: 1 mm sobre 1 ha = 10 m3
    for k in ["min", "central", "max"]:
        g[f"m3_{k}"] = g[f"lamina_{k}_mm"] * 10 * g["area_ha"]
    g["area_verde_ha"] = g["fc"] * g["area_ha"]
    g["predio_grande"] = g["area_ha"] > 100
    faltan_clima = g["et0_mm"].isna() & g["ndvi_mes"].notna()
    if faltan_clima.any():
        print(f"Aviso: {faltan_clima.sum()} predio-meses sin clima de la celda", file=sys.stderr)

    cols = ["predio_id", "zona", "temporada", "mes", "estado", "n_escenas", "ndvi_mes", "fc", "ndvi_secano",
            "especie_principal", "frac_fruticola", "especie_ajuste", "kc_tope", "kc_min", "kc_central", "kc_max",
            "celda_id", "et0_mm", "lluvia_mm", "pef_min_mm", "pef_max_mm", "lamina_min_mm", "lamina_central_mm",
            "lamina_max_mm", "clima_climatologia", "area_ha", "area_verde_ha", "predio_grande", "m3_min", "m3_central",
            "m3_max"]
    mes = g[cols].sort_values(["predio_id", "mes"]).reset_index(drop=True)
    for c in ["ndvi_mes", "fc", "kc_tope", "kc_min", "kc_central", "kc_max"]:
        mes[c] = mes[c].round(4)
    for c in ["et0_mm", "lluvia_mm", "pef_min_mm", "pef_max_mm", "lamina_min_mm", "lamina_central_mm",
              "lamina_max_mm", "area_verde_ha", "m3_min", "m3_central", "m3_max"]:
        mes[c] = mes[c].round(1)
    mes.to_parquet(salida, index=False)

    # Temporada y anual
    t = g.groupby(["predio_id", "temporada"]).agg(
        zona=("zona", "first"), area_ha=("area_ha", "first"), especie_principal=("especie_principal", "first"),
        frac_fruticola=("frac_fruticola", "first"), especie_ajuste=("especie_ajuste", "first"),
        caduca=("caduca", "first"), celda_id=("celda_id", "first"), predio_grande=("predio_grande", "first"),
        n_escenas=("n_escenas", "sum"), meses_observados=("estado", lambda x: (x == "observado").sum()),
        meses_interpolados=("estado", lambda x: (x == "interpolado").sum()),
        meses_faltantes=("estado", lambda x: (x == "faltante").sum()), ndvi_medio=("ndvi_mes", "mean"),
        kc_min=("kc_min", "mean"), kc_central=("kc_central", "mean"), kc_max=("kc_max", "mean"),
        et0_mm=("et0_mm", "sum"), m3_min=("m3_min", "sum"), m3_central=("m3_central", "sum"), m3_max=("m3_max", "sum"),
        sin_clima=("et0_mm", lambda x: x.isna().any()), clima_clim_temp=("clima_climatologia", "any"),
    ).reset_index()
    completa = (t["meses_faltantes"] == 0) & ~t["sin_clima"]
    t["temporada_completa"] = completa
    for k in ["min", "central", "max"]:
        t[f"m3_temporada_{k}"] = t.pop(f"m3_{k}").where(completa)
        t[f"m3_ha_temporada_{k}"] = t[f"m3_temporada_{k}"] / t["area_ha"]

    # 8. Anual extrapolado: abril a noviembre con el Kc medio de la temporada
    resto = []
    for tt in t["temporada"].unique():
        a = int(tt[:4])
        for m in range(4, 12):
            resto.append({"temporada": tt, "mes": pd.Timestamp(a, m, 1), "m": m})
    resto = t[["predio_id", "temporada", "celda_id", "caduca", "kc_min", "kc_central", "kc_max", "area_ha"]].merge(
        pd.DataFrame(resto), on="temporada")
    resto = resto.merge(cm, on=["celda_id", "mes"], how="left")
    usa_clim = resto["et0_mm"].isna()
    resto = resto.merge(clim, on=["celda_id", "m"], how="left", suffixes=("", "_clim"))
    for c in ["et0_mm", "lluvia_mm"]:
        resto[c] = resto[c].fillna(resto[f"{c}_clim"])
    resto["usa_clim"] = usa_clim
    sin_hojas = resto["caduca"] & resto["m"].between(5, 8)
    for k in ["kc_min", "kc_central", "kc_max"]:
        resto.loc[sin_hojas, k] = 0.0
    pmin, pmax = pef_aglw(resto["lluvia_mm"]), pef_usda(resto["lluvia_mm"])
    resto["r_min"] = np.clip(resto["kc_min"] * resto["et0_mm"] * (1 - e) - pmax, 0, None) * 10 * resto["area_ha"]
    resto["r_central"] = np.clip(resto["kc_central"] * resto["et0_mm"] - pmax, 0, None) * 10 * resto["area_ha"]
    resto["r_max"] = np.clip(resto["kc_max"] * resto["et0_mm"] * (1 + e) - pmin, 0, None) * 10 * resto["area_ha"]
    ra = resto.groupby(["predio_id", "temporada"]).agg(r_min=("r_min", "sum"), r_central=("r_central", "sum"),
                                                        r_max=("r_max", "sum"), clima_climatologia=("usa_clim", "any"))
    t = t.merge(ra.reset_index(), on=["predio_id", "temporada"], how="left")
    t["clima_climatologia"] = t["clima_climatologia"].fillna(False) | t.pop("clima_clim_temp")
    for k in ["min", "central", "max"]:
        t[f"m3_anual_{k}"] = (t[f"m3_temporada_{k}"] + t.pop(f"r_{k}")).where(completa)
        t[f"m3_ha_anual_{k}"] = t[f"m3_anual_{k}"] / t["area_ha"]
    t["anual_metodo"] = np.where(completa, "extrapolado_kc_temporada", None)

    def supuestos(r) -> str:
        s = [f"ndvi_secano={fuente_secano}", "area=poligono", f"et0=openmeteo±{int(e * 100)}%"]
        s.append(f"especie={r['especie_ajuste']}(f={r['frac_fruticola']:.2f})" if pd.notna(r["especie_ajuste"]) else "especie=generica")
        if r["meses_interpolados"]:
            s.append(f"interpolados={r['meses_interpolados']}")
        if r["caduca"]:
            s.append("caduca_kc0_may-ago")
        if r["clima_climatologia"]:
            s.append("clima_con_climatologia")
        if r["predio_grande"]:
            s.append("predio_grande_usar_min")
        return ";".join(s)

    t["supuestos"] = t.apply(supuestos, axis=1)
    t = t.drop(columns=["sin_clima"])
    num = [c for c in t.columns if c.startswith(("m3_", "et0"))]
    t[num] = t[num].round(0)
    t[["ndvi_medio", "kc_min", "kc_central", "kc_max"]] = t[["ndvi_medio", "kc_min", "kc_central", "kc_max"]].round(3)
    t = t.sort_values(["predio_id", "temporada"]).reset_index(drop=True)
    t.to_parquet(salida_temp, index=False)

    print(f"{len(mes)} predio-meses ({mes['predio_id'].nunique()} predios) -> {salida}")
    print(mes["estado"].value_counts().to_string())
    print(f"{len(t)} predio-temporadas, {t['temporada_completa'].sum()} completas -> {salida_temp}")
    print("\nm3/ha de la temporada (dic-mar) en predios completos, por zona:")
    print(t.groupby("zona")[["m3_ha_temporada_min", "m3_ha_temporada_central", "m3_ha_temporada_max"]]
          .describe(percentiles=[0.5]).round(0).T.to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
