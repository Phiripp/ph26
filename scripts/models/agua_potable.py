# /// script
# requires-python = ">=3.11"
# dependencies = ["geopandas>=1.0", "pandas", "pyarrow", "shapely>=2.0", "numpy", "scikit-learn"]
# ///
"""Candidatos cerca de un pozo de agua potable del mismo acuífero, y su orden (tareas AP1, AP1b y AP9).

Definiciones (docs/spec-agua-potable.md):
- Pozo de agua potable: derecho de derecho.parquet con uso "Bebida/Uso Domestico/Saneamiento", naturaleza
  subterránea, coordenada y m3_anual > 0. Los derechos sin uso declarado quedan fuera: la cifra es una cota inferior.
- Predio cerca de agua potable: el borde de su polígono está a RADIO_M o menos de un pozo de agua potable del mismo
  sector de acuífero (cod_shac de predio_restriccion.parquet). RADIO_M es un criterio, no un radio de influencia
  medido.
- APR del pozo: sistemas de apr.parquet (apr_doh.py) a RADIO_APR_M o menos del pozo. El punto del APR es la
  localidad o el estanque, no la captación: la asociación es por cercanía.
- Candidatos: los de impacto.py (banda alta en 2025-26, sin fiscalización a 500 m desde 2018, hasta 100 ha).
- rank_agua, por zona y solo para candidatos: primero los cerca de agua potable, por beneficiarios_cercanos y
  después por puntaje (de mayor a menor); después el resto, por puntaje. En la práctica, dentro de los cerca ordena
  por beneficiarios: el puntaje no separa a los infractores dentro de la banda alta.
- Ruta de agua potable: candidatos con beneficiarios_cercanos > 0, uno por pozo (el de mayor puntaje), para que
  las paradas queden en pozos distintos y los beneficiarios no se cuenten dos veces. Cada uno pesa
  prioridad = puntaje x (1 + beneficiarios_cercanos / máximo de la zona).

`marcar()` no depende de Z1 y Z2: la etapa `region` de la corrida nacional la puede llamar con los datos de una
región.

Entradas (data/processed/): predio.parquet, derecho.parquet, predio_restriccion.parquet, restriccion.parquet
(polígonos de los SHAC, para ubicar cada pozo), puntaje.parquet,
fiscalizacion.parquet (para los candidatos) y apr.parquet.

Salidas (data/processed/):
- predio_agua_potable.parquet: una fila por predio de puntaje.parquet (contrato en el spec).
- pozo_agua_potable.geojson: pozos de agua potable con n_candidatos_cerca, apr_cercanos y beneficiarios_cercanos.
  Sin titular.
- prioridad_agua.parquet: predio_id, zona, puntaje (= prioridad) de los candidatos que entran a la ruta. Es la
  entrada de `ruta_inspeccion.py --puntajes`.

Uso: uv run scripts/models/agua_potable.py
     uv run scripts/models/ruta_inspeccion.py --zona Z2 --puntajes data/processed/prioridad_agua.parquet \
         --top 40 --max-paradas 5 --salida data/processed/ruta_agua_z2
"""

import json
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from comun.rutas import PROC, mostrar  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from impacto import sin_fiscalizar_500m  # noqa: E402

RADIO_M = 1000
RADIO_APR_M = 2000
CRS_METROS = "EPSG:32719"
USO_AGUA_POTABLE = "Bebida/Uso Domestico/Saneamiento"


def pozos_agua_potable(derechos: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Derechos subterráneos de bebida, uso doméstico y saneamiento, con coordenada y volumen."""
    m = (
        (derechos["uso"] == USO_AGUA_POTABLE)
        & (derechos["naturaleza"] == "subterranea")
        & derechos.geometry.notna()
        & ~derechos.geometry.is_empty
        & (derechos["m3_anual"] > 0)
    )
    return derechos[m]


def pozo_shac(pozos: gpd.GeoDataFrame, predios: gpd.GeoDataFrame, predio_restriccion: pd.DataFrame,
              sectores: gpd.GeoDataFrame | None = None) -> pd.Series:
    """cod_shac de cada pozo.

    Con `sectores` (polígonos de restriccion.parquet): el sector que contiene el pozo. Sin ellos, o si el pozo cae
    fuera de todos: el SHAC del predio más cercano (la corrida nacional solo trae predio_restriccion).
    """
    shac = pd.Series(dtype=object)
    if sectores is not None:
        j = gpd.sjoin(pozos[["derecho_id", "geometry"]].to_crs(sectores.crs), sectores[["cod_shac", "geometry"]],
                      predicate="within")
        shac = j.drop_duplicates("derecho_id").set_index("derecho_id")["cod_shac"]
    falta = pozos[~pozos["derecho_id"].isin(shac.index)]
    if falta.empty:
        return shac
    pr = predios[["predio_id", "geometry"]].merge(predio_restriccion[["predio_id", "cod_shac"]], on="predio_id")
    pr = pr[pr["cod_shac"].notna()].to_crs(CRS_METROS)
    pz = falta[["derecho_id", "geometry"]].to_crs(CRS_METROS)
    j = gpd.sjoin_nearest(pz, pr[["cod_shac", "geometry"]], distance_col="d")
    return pd.concat([shac, j.sort_values("d").drop_duplicates("derecho_id").set_index("derecho_id")["cod_shac"]])


def marcar(predios: gpd.GeoDataFrame, derechos: gpd.GeoDataFrame, predio_restriccion: pd.DataFrame,
           radio_m: int = RADIO_M, sectores: gpd.GeoDataFrame | None = None) -> tuple[pd.DataFrame, gpd.GeoDataFrame]:
    """Pozo de agua potable más cercano del mismo SHAC para cada predio.

    Devuelve (por predio: predio_id, cod_shac, apr_derecho_id, dist_agua_potable_m, apr_m3_anual, agua_potable,
    radio_m) y los pozos de agua potable con su cod_shac (EPSG:4326).
    """
    pozos = pozos_agua_potable(derechos).copy()
    pozos["cod_shac"] = pozos["derecho_id"].map(pozo_shac(pozos, predios, predio_restriccion, sectores))
    pr = predios[["predio_id", "geometry"]].merge(predio_restriccion[["predio_id", "cod_shac"]], on="predio_id")
    pr_m, pz_m = pr.to_crs(CRS_METROS), pozos.to_crs(CRS_METROS)

    partes = []
    for shac, g in pr_m[pr_m["cod_shac"].notna()].groupby("cod_shac"):
        p = pz_m.loc[pz_m["cod_shac"] == shac, ["derecho_id", "m3_anual", "geometry"]]
        if p.empty:
            continue
        j = gpd.sjoin_nearest(g[["predio_id", "geometry"]], p, distance_col="dist_agua_potable_m")
        partes.append(j.sort_values("dist_agua_potable_m").drop_duplicates("predio_id"))
    cerca = pd.concat(partes) if partes else pd.DataFrame(columns=["predio_id", "derecho_id", "m3_anual",
                                                                   "dist_agua_potable_m"])
    cerca = cerca.rename(columns={"derecho_id": "apr_derecho_id", "m3_anual": "apr_m3_anual"})

    out = pr[["predio_id", "cod_shac"]].merge(
        cerca[["predio_id", "apr_derecho_id", "dist_agua_potable_m", "apr_m3_anual"]], on="predio_id", how="left")
    out["dist_agua_potable_m"] = out["dist_agua_potable_m"].round(1)
    out["agua_potable"] = out["dist_agua_potable_m"].le(radio_m)
    out["radio_m"] = radio_m
    return out, pozos


def apr_por_pozo(pozos: gpd.GeoDataFrame, apr: gpd.GeoDataFrame, radio_m: int = RADIO_APR_M) -> pd.DataFrame:
    """Por pozo: APR a radio_m o menos (apr_ids, nombres) y la suma de sus beneficiarios estimados."""
    pz = pozos[["derecho_id", "geometry"]].to_crs(CRS_METROS)
    a = apr[["apr_id", "nombre", "beneficiarios_est", "geometry"]].to_crs(CRS_METROS)
    j = gpd.sjoin(pz.assign(geometry=pz.buffer(radio_m)), a, predicate="intersects")
    g = j.groupby("derecho_id")
    return pd.DataFrame({
        "apr_ids": g["apr_id"].agg(list),
        "apr_cercanos": g["nombre"].agg(list),
        "beneficiarios_cercanos": g["beneficiarios_est"].sum().astype(int),
    }).reindex(pz["derecho_id"]).rename_axis("derecho_id").reset_index()


def candidatos(puntaje: pd.DataFrame) -> pd.DataFrame:
    """Universo de impacto.py: banda alta, sin fiscalización a 500 m desde 2018 y hasta 100 ha."""
    a = puntaje[puntaje["banda"] == "alta"]
    a = a[sin_fiscalizar_500m(a["predio_id"]).to_numpy()]
    return a[~a["predio_grande"].fillna(False).astype(bool)]


def ordenar(marca: pd.DataFrame, cand: pd.DataFrame) -> pd.Series:
    """rank_agua por zona (1 = primero) para los candidatos; nulo para el resto."""
    c = cand[["predio_id", "zona", "puntaje"]].merge(
        marca[["predio_id", "agua_potable", "beneficiarios_cercanos"]], on="predio_id")
    c = c.sort_values(["zona", "agua_potable", "beneficiarios_cercanos", "puntaje", "predio_id"],
                      ascending=[True, False, False, False, True])
    c["rank_agua"] = c.groupby("zona").cumcount() + 1
    return marca["predio_id"].map(c.set_index("predio_id")["rank_agua"]).astype("Int64")


def prioridad_ruta(marca: pd.DataFrame, cand: pd.DataFrame) -> pd.DataFrame:
    """Candidatos que entran a la ruta de agua potable, uno por pozo, con su prioridad como puntaje."""
    c = cand[["predio_id", "zona", "puntaje"]].merge(
        marca[["predio_id", "apr_derecho_id", "beneficiarios_cercanos"]], on="predio_id")
    c = c[c["beneficiarios_cercanos"] > 0]
    c = c.sort_values(["puntaje", "predio_id"], ascending=[False, True]).drop_duplicates("apr_derecho_id")
    tope = c.groupby("zona")["beneficiarios_cercanos"].transform("max")
    c["puntaje_original"] = c["puntaje"]
    c["puntaje"] = (c["puntaje"] * (1 + c["beneficiarios_cercanos"] / tope)).round(4)
    return c[["predio_id", "zona", "puntaje", "puntaje_original", "apr_derecho_id", "beneficiarios_cercanos"]]


def main() -> None:
    puntaje = pd.read_parquet(PROC / "puntaje.parquet")
    predios = gpd.read_parquet(PROC / "predio.parquet", columns=["predio_id", "geometry"])
    predios = predios[predios["predio_id"].isin(puntaje["predio_id"])]
    derechos = gpd.read_parquet(PROC / "derecho.parquet")
    restr = pd.read_parquet(PROC / "predio_restriccion.parquet")
    apr = gpd.read_parquet(PROC / "apr.parquet")

    sectores = gpd.read_parquet(PROC / "restriccion.parquet", columns=["cod_shac", "geometry"])
    marca, pozos = marcar(predios, derechos, restr, sectores=sectores)
    por_pozo = apr_por_pozo(pozos, apr)
    pozos = pozos.merge(por_pozo, on="derecho_id", how="left")
    pozos["beneficiarios_cercanos"] = pozos["beneficiarios_cercanos"].fillna(0).astype(int)

    benef = pozos.set_index("derecho_id")["beneficiarios_cercanos"]
    marca["beneficiarios_cercanos"] = (
        marca["apr_derecho_id"].map(benef).fillna(0).where(marca["agua_potable"], 0).astype(int))
    marca = marca.merge(puntaje[["predio_id", "zona"]], on="predio_id")

    cand = candidatos(puntaje)
    marca["rank_agua"] = ordenar(marca, cand)
    cols = ["predio_id", "zona", "cod_shac", "apr_derecho_id", "dist_agua_potable_m", "apr_m3_anual",
            "agua_potable", "radio_m", "beneficiarios_cercanos", "rank_agua"]
    marca = marca[cols].sort_values(["zona", "predio_id"]).reset_index(drop=True)
    PROC.mkdir(parents=True, exist_ok=True)
    marca.to_parquet(PROC / "predio_agua_potable.parquet", index=False)

    cerca = marca[marca["predio_id"].isin(cand["predio_id"]) & marca["agua_potable"]]
    pozos["n_candidatos_cerca"] = pozos["derecho_id"].map(cerca.groupby("apr_derecho_id").size()).fillna(0).astype(int)
    gj = pozos[["derecho_id", "zona", "comuna", "caudal_ls", "m3_anual", "cod_shac", "n_candidatos_cerca",
                "apr_cercanos", "beneficiarios_cercanos", "geometry"]].to_crs("EPSG:4326")
    gj["apr_cercanos"] = gj["apr_cercanos"].map(lambda v: list(v) if isinstance(v, list) else [])
    (PROC / "pozo_agua_potable.geojson").write_text(gj.to_json(drop_id=True, ensure_ascii=False), encoding="utf-8")

    prio = prioridad_ruta(marca, cand)
    prio.to_parquet(PROC / "prioridad_agua.parquet", index=False)

    # Resumen
    afectados = pozos[pozos["n_candidatos_cerca"] > 0]
    apr_af = apr[apr["apr_id"].isin({i for v in afectados["apr_ids"].dropna() for i in v})]
    print(f"Pozos de agua potable: {len(pozos)} ({pozos.groupby('zona').size().to_dict()}); sin SHAC: "
          f"{pozos['cod_shac'].isna().sum()}")
    print(f"Candidatos: {len(cand)}; cerca de agua potable a {RADIO_M} m: {len(cerca)} "
          f"({cerca.groupby('zona').size().to_dict()})")
    print(f"Pozos con candidatos cerca: {len(afectados)}")
    print(f"APR a {RADIO_APR_M} m de esos pozos: {len(apr_af)}, con {int(apr_af['beneficiarios_est'].sum())} "
          "beneficiarios (cada APR una vez)")
    for zona, g in prio.groupby("zona"):
        print(f"Ruta {zona}: {len(g)} candidatos con APR cerca, uno por pozo "
              f"(de {int(((cerca['zona'] == zona) & (cerca['beneficiarios_cercanos'] > 0)).sum())} antes de "
              "dejar uno por pozo)")
    top = marca[marca["rank_agua"].le(5)].merge(puntaje[["predio_id", "rank_zona"]], on="predio_id")
    print("\nPrimeros de rank_agua por zona:")
    print(top.sort_values(["zona", "rank_agua"])[["zona", "rank_agua", "rank_zona", "predio_id",
                                                   "dist_agua_potable_m", "beneficiarios_cercanos"]].to_string(index=False))
    for p in (5301984, 5301325):
        r = marca[marca["predio_id"] == p]
        if len(r):
            print(f"{p}: {r['dist_agua_potable_m'].iloc[0]} m, agua_potable={bool(r['agua_potable'].iloc[0])}")
    for f in ("predio_agua_potable.parquet", "pozo_agua_potable.geojson", "prioridad_agua.parquet"):
        print(f"-> {mostrar(PROC / f)}")


if __name__ == "__main__":
    main()
