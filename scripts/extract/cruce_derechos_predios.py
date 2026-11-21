# /// script
# requires-python = ">=3.11"
# dependencies = ["geopandas>=1.0", "pyarrow", "shapely>=2.0"]
# ///
"""Cruza los derechos de agua (D4) con los predios (D3) (tarea D5).

Entradas (correr antes predios_ciren.py y derechos_dga.py):
- data/processed/predio.parquet
- data/processed/derecho.parquet
- data/raw/dga/derecho_titulares.parquet (opcional; sin él no hay cruce por titular)

Salidas:
- data/processed/derecho_predio.parquet: un registro por derecho con predio_id, metodo_cruce,
  confianza_cruce y dist_predio_m. Sin nombres.
- data/processed/predio_derecho.parquet: un registro por predio con rol válido: derechos asignados,
  m³ con derecho (solo sumables) y estado_derechos. Es lo que leen M5 (índice) y M12 (contexto).

Métodos, en orden:
1. punto_en_predio: el punto de captación cae dentro del predio.
2. cercania: el predio válido más cercano a 500 m o menos.
3. titular: el mismo titular tiene otros derechos ubicados en un solo predio de la misma comuna.
Los derechos de 100 l/s o más (gran_derecho) no se asignan: son canales o comunidades de aguas.

Uso: uv run scripts/extract/cruce_derechos_predios.py
"""

import re
import sys
import unicodedata
from pathlib import Path

import geopandas as gpd
import pandas as pd

RAIZ = Path(__file__).resolve().parents[2]
DATA = RAIZ / "data"
CRS_METROS = "EPSG:32719"
RADIO_M = 500
CERCA_M = 100  # hasta aquí, la cercanía vale confianza media; más lejos, baja
NIVELES = ["baja", "media", "alta"]


def bajar(confianza: pd.Series, cond: pd.Series) -> pd.Series:
    """Baja un nivel de confianza donde se cumple cond."""
    idx = confianza.map(NIVELES.index)
    return idx.where(~cond, (idx - 1).clip(lower=0)).map(lambda i: NIVELES[i])


def normalizar_nombre(s: str) -> str:
    s = "".join(c for c in unicodedata.normalize("NFD", str(s)) if unicodedata.category(c) != "Mn").upper()
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    s = re.sub(r"\b(Y OTROS?|Y OTRAS?|SUCESION|SUC)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def main() -> None:
    for f in ("predio.parquet", "derecho.parquet"):
        if not (DATA / "processed" / f).exists():
            sys.exit(f"Falta data/processed/{f}: corre antes predios_ciren.py y derechos_dga.py")

    predios = gpd.read_parquet(DATA / "processed" / "predio.parquet")
    predios = predios[predios["rol_valido"]].to_crs(CRS_METROS)[["predio_id", "zona", "comuna", "area_ha", "geometry"]]
    derechos = gpd.read_parquet(DATA / "processed" / "derecho.parquet").to_crs(CRS_METROS)

    res = pd.DataFrame({
        "derecho_id": derechos["derecho_id"],
        "predio_id": pd.array([pd.NA] * len(derechos), dtype="Int64"),
        "metodo_cruce": pd.Series([None] * len(derechos), dtype="object"),
        "confianza_cruce": pd.Series([None] * len(derechos), dtype="object"),
        "dist_predio_m": pd.Series([float("nan")] * len(derechos)),
    }, index=derechos.index)

    con_punto = derechos.geometry.notna() & ~derechos.geometry.is_empty
    asignables = con_punto & ~derechos["gran_derecho"]
    res.loc[derechos["gran_derecho"], "metodo_cruce"] = "gran_derecho_sin_asignar"

    # 1. Punto dentro del predio. Si cae en dos polígonos que se solapan, gana el más chico.
    pts = derechos.loc[asignables, ["geometry"]]
    dentro = gpd.sjoin(pts, predios, how="inner", predicate="within")
    dentro = dentro.sort_values("area_ha").loc[lambda d: ~d.index.duplicated()]
    res.loc[dentro.index, "predio_id"] = dentro["predio_id"].astype("Int64")
    res.loc[dentro.index, "metodo_cruce"] = "punto_en_predio"
    res.loc[dentro.index, "dist_predio_m"] = 0.0
    res.loc[dentro.index, "confianza_cruce"] = "alta"

    # 2. Predio válido más cercano a RADIO_M o menos (el punto cae en un camino, un cauce o un hueco).
    faltan = pts.index.difference(dentro.index)
    cerca = gpd.sjoin_nearest(pts.loc[faltan], predios, how="inner", max_distance=RADIO_M, distance_col="dist")
    cerca = cerca.loc[~cerca.index.duplicated()]
    res.loc[cerca.index, "predio_id"] = cerca["predio_id"].astype("Int64")
    res.loc[cerca.index, "metodo_cruce"] = "cercania"
    res.loc[cerca.index, "dist_predio_m"] = cerca["dist"].round(0)
    res.loc[cerca.index, "confianza_cruce"] = cerca["dist"].le(CERCA_M).map({True: "media", False: "baja"})

    # Coordenada con supuesto o derecho superficial (la bocatoma no está en el predio que riega): un nivel menos.
    ubicados = res["metodo_cruce"].isin(["punto_en_predio", "cercania"])
    dudoso = (derechos["coord_estado"] != "ok") | (derechos["naturaleza"] == "superficial")
    res.loc[ubicados, "confianza_cruce"] = bajar(res.loc[ubicados, "confianza_cruce"], dudoso[ubicados])

    # 3. Titular: sus otros derechos ubicados caen en un solo predio de la misma comuna.
    titulares_f = DATA / "raw" / "dga" / "derecho_titulares.parquet"
    if titulares_f.exists():
        tit = pd.read_parquet(titulares_f).set_index("derecho_id")["titular"].map(normalizar_nombre)
        clave = derechos["comuna"] + "|" + derechos["derecho_id"].map(tit).fillna("")
        ok = res["predio_id"].notna() & (clave.str.split("|").str[1] != "")
        predios_por_clave = res.loc[ok].groupby(clave[ok])["predio_id"].agg(lambda s: set(s.dropna()))
        unicos = predios_por_clave[predios_por_clave.map(len) == 1].map(lambda s: next(iter(s)))
        sin = res["metodo_cruce"].isna() & clave.isin(unicos.index)
        res.loc[sin, "predio_id"] = clave[sin].map(unicos).astype("Int64")
        res.loc[sin, "metodo_cruce"] = "titular"
        res.loc[sin, "confianza_cruce"] = "baja"
    else:
        print(f"Aviso: no está {titulares_f}; se omite el cruce por titular")

    res.loc[res["metodo_cruce"].isna() & con_punto, "metodo_cruce"] = "sin_predio_a_500m"
    res.loc[res["metodo_cruce"].isna(), "metodo_cruce"] = "sin_coordenada"
    procesados = DATA / "processed"
    res.to_parquet(procesados / "derecho_predio.parquet", index=False)

    # Resumen por predio. Solo los sumables cuentan como volumen con derecho.
    d = derechos[["derecho_id", "sumable", "m3_anual", "naturaleza"]].join(res.drop(columns="derecho_id"))
    asignados = d[d["predio_id"].notna()]
    peor = lambda s: NIVELES[min(NIVELES.index(x) for x in s)]
    por_predio = asignados.groupby("predio_id").agg(
        n_derechos=("derecho_id", "size"),
        n_derechos_sumables=("sumable", "sum"),
        m3_anual_derecho=("m3_anual", lambda s: s[asignados.loc[s.index, "sumable"]].sum()),
        m3_anual_derecho_subterraneo=("m3_anual", lambda s: s[asignados.loc[s.index, "sumable"]
                                                              & (asignados.loc[s.index, "naturaleza"] == "subterranea")].sum()),
        confianza_cruce=("confianza_cruce", peor),
    )
    resumen = predios.drop(columns="geometry").set_index("predio_id").join(por_predio)
    resumen["n_derechos"] = resumen["n_derechos"].fillna(0).astype(int)
    resumen["n_derechos_sumables"] = resumen["n_derechos_sumables"].fillna(0).astype(int)
    for c in ("m3_anual_derecho", "m3_anual_derecho_subterraneo"):
        resumen[c] = resumen[c].fillna(0.0).round(1)
    resumen["m3_mes_derecho"] = (resumen["m3_anual_derecho"] / 12).round(1)

    # Entorno: derechos sumables (sin grandes derechos) con punto a RADIO_M o menos del predio, propios o no.
    # Un pozo inscrito en un lote chico puede regar el predio vecino; si el entorno tiene mucho derecho
    # y el predio poco, M5 debe bajar la confianza en vez de marcarlo como sospechoso.
    pts_sum = derechos.loc[con_punto & derechos["sumable"] & ~derechos["gran_derecho"], ["m3_anual", "geometry"]]
    zona_buffer = predios[["predio_id", "geometry"]].copy()
    zona_buffer["geometry"] = zona_buffer.buffer(RADIO_M)
    entorno = gpd.sjoin(pts_sum, zona_buffer, how="inner", predicate="within").groupby("predio_id")["m3_anual"].sum()
    resumen["m3_anual_derecho_entorno_500m"] = entorno.reindex(resumen.index).fillna(0.0).round(1)

    # Sin derechos asignados: ¿hay algún punto de derecho (de cualquier tipo) a RADIO_M o menos?
    sin = resumen.index[resumen["n_derechos"] == 0]
    todos_pts = derechos.loc[con_punto, ["geometry"]]
    pred_sin = predios.set_index("predio_id").loc[sin, ["geometry"]]
    vecinos = gpd.sjoin_nearest(pred_sin, todos_pts, how="inner", max_distance=RADIO_M)
    con_vecinos = set(vecinos.index)
    resumen["estado_derechos"] = "con_derechos"
    resumen.loc[sin, "estado_derechos"] = [
        "derechos_cerca_de_otro_predio" if p in con_vecinos else "sin_derechos_cerca" for p in sin]
    # "Sin derechos" nunca es alta: el 14 % de los derechos no tiene coordenada.
    resumen.loc[sin, "confianza_cruce"] = "media"
    resumen.loc[resumen["estado_derechos"] == "derechos_cerca_de_otro_predio", "confianza_cruce"] = "baja"
    resumen.reset_index().to_parquet(procesados / "predio_derecho.parquet", index=False)

    print("Derechos por método de cruce:")
    print(pd.crosstab(res["metodo_cruce"], derechos["zona"], margins=True).to_string())
    print("\nConfianza de los derechos asignados:")
    print(res.loc[res["predio_id"].notna(), "confianza_cruce"].value_counts().to_string())
    vol = d.loc[d["sumable"]]
    print(f"\nVolumen sumable asignado a un predio: {vol.loc[vol['predio_id'].notna(), 'm3_anual'].sum() / vol['m3_anual'].sum():.0%}")
    print("\nPredios con rol válido por estado:")
    print(pd.crosstab(resumen["estado_derechos"], resumen["zona"], margins=True).to_string())
    print(f"\n-> {procesados / 'derecho_predio.parquet'}\n-> {procesados / 'predio_derecho.parquet'}")


if __name__ == "__main__":
    main()
