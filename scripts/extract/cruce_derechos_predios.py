# /// script
# requires-python = ">=3.11"
# dependencies = ["geopandas>=1.0", "pyarrow", "shapely>=2.0"]
# ///
"""Cruza los derechos de agua (D4) con los predios (D3) (tarea D5, versión 2).

Entradas (correr antes predios_ciren.py, derechos_dga.py y canales_ciren.py):
- data/processed/predio.parquet
- data/processed/derecho.parquet
- data/raw/dga/derecho_titulares.parquet (opcional: cruce por titular)
- data/raw/ciren_riego/canales.parquet (opcional: distancia a canal)

Salidas:
- data/processed/derecho_predio.parquet: un registro por derecho con predio_id, metodo_cruce,
  confianza_cruce y dist_predio_m. Sin nombres.
- data/processed/predio_derecho.parquet: un registro por predio con rol válido y temporada seca.
  Es lo que leen M5 (índice) y M12 (contexto). Columnas en data/README.md.

Asignación de cada derecho a un predio, en orden:
1. punto_en_predio: el punto de captación cae dentro del predio.
2. cercania: el predio válido más cercano a 500 m o menos.
3. titular: el mismo titular tiene otros derechos ubicados en un solo predio de la misma comuna.
No se asignan: grandes derechos (100 l/s o más), pozos compartidos (3 o más titulares en el mismo punto)
y duplicados VPC. Los dos primeros sí cuentan en los derechos del entorno.

Cambios de la versión 2 (assessment de datos del 21-11-2026):
- Los derechos se agregan por rol (comuna + rol): un rol puede tener varios polígonos.
- Por temporada seca: solo cuentan los derechos otorgados antes del 1 de diciembre de esa temporada.
- Pozos compartidos y duplicados VPC fuera de la asignación (ver derechos_dga.py).
- Distancia al canal de riego más cercano: el agua de canal (acciones) no tiene volumen en los datos.

Uso: uv run scripts/extract/cruce_derechos_predios.py
"""

import re
import sys
import unicodedata
from datetime import date
from pathlib import Path

import geopandas as gpd
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from comun.rutas import DATA  # noqa: E402

CRS_METROS = "EPSG:32719"
RADIO_M = 500
CERCA_M = 100  # hasta aquí, la cercanía vale confianza media; más lejos, baja
CANAL_M = 300
NIVELES = ["baja", "media", "alta"]
PRIMERA_TEMPORADA = 2019


def temporadas() -> list[tuple[str, pd.Timestamp]]:
    """Temporadas secas "2019-20" ... hasta la actual, con su fecha de corte (1 de diciembre)."""
    hoy = date.today()
    ultima = hoy.year if hoy.month == 12 else hoy.year - 1
    return [(f"{a}-{str(a + 1)[2:]}", pd.Timestamp(a, 12, 1)) for a in range(PRIMERA_TEMPORADA, ultima + 1)]


def bajar(confianza: pd.Series, cond: pd.Series) -> pd.Series:
    """Baja un nivel de confianza donde se cumple cond."""
    idx = confianza.map(NIVELES.index)
    return idx.where(~cond, (idx - 1).clip(lower=0)).map(lambda i: NIVELES[i])


def normalizar_nombre(s: str) -> str:
    s = "".join(c for c in unicodedata.normalize("NFD", str(s)) if unicodedata.category(c) != "Mn").upper()
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    s = re.sub(r"\b(Y OTROS?|Y OTRAS?|SUCESION|SUC)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def asignar(derechos: gpd.GeoDataFrame, predios: gpd.GeoDataFrame) -> pd.DataFrame:
    res = pd.DataFrame({
        "derecho_id": derechos["derecho_id"],
        "predio_id": pd.array([pd.NA] * len(derechos), dtype="Int64"),
        "metodo_cruce": pd.Series([None] * len(derechos), dtype="object"),
        "confianza_cruce": pd.Series([None] * len(derechos), dtype="object"),
        "dist_predio_m": pd.Series([float("nan")] * len(derechos)),
    }, index=derechos.index)

    con_punto = derechos.geometry.notna() & ~derechos.geometry.is_empty
    res.loc[derechos["duplicado_de"].notna(), "metodo_cruce"] = "duplicado_vpc"
    res.loc[derechos["pozo_compartido"] & res["metodo_cruce"].isna(), "metodo_cruce"] = "pozo_compartido_sin_asignar"
    res.loc[derechos["gran_derecho"] & res["metodo_cruce"].isna(), "metodo_cruce"] = "gran_derecho_sin_asignar"
    asignables = con_punto & res["metodo_cruce"].isna()

    # 1. Punto dentro del predio. Si cae en dos polígonos que se solapan, gana el más chico.
    pts = derechos.loc[asignables, ["geometry"]]
    dentro = gpd.sjoin(pts, predios[["predio_id", "area_ha", "geometry"]], how="inner", predicate="within")
    dentro = dentro.sort_values("area_ha").loc[lambda d: ~d.index.duplicated()]
    res.loc[dentro.index, "predio_id"] = dentro["predio_id"].astype("Int64")
    res.loc[dentro.index, "metodo_cruce"] = "punto_en_predio"
    res.loc[dentro.index, "dist_predio_m"] = 0.0
    res.loc[dentro.index, "confianza_cruce"] = "alta"

    # 2. Predio válido más cercano a RADIO_M o menos (el punto cae en un camino, un cauce o un hueco).
    faltan = pts.index.difference(dentro.index)
    cerca = gpd.sjoin_nearest(pts.loc[faltan], predios[["predio_id", "geometry"]], how="inner",
                              max_distance=RADIO_M, distance_col="dist")
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
        nombre = derechos["derecho_id"].map(tit).fillna("")
        clave = derechos["comuna"] + "|" + nombre
        ok = res["predio_id"].notna() & (nombre != "")
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
    return res


def distancia_canal(predios: gpd.GeoDataFrame) -> pd.Series:
    canales_f = DATA / "raw" / "ciren_riego" / "canales.parquet"
    if not canales_f.exists():
        print(f"Aviso: no está {canales_f} (corre canales_ciren.py); dist_canal_m queda vacía")
        return pd.Series(float("nan"), index=predios["predio_id"])
    canales = gpd.read_parquet(canales_f).to_crs(CRS_METROS)[["geometry"]]
    cerca = gpd.sjoin_nearest(predios[["predio_id", "geometry"]], canales, how="left",
                              max_distance=5_000, distance_col="dist")
    return cerca.groupby("predio_id")["dist"].min().round(0)


def main() -> None:
    for f in ("predio.parquet", "derecho.parquet"):
        if not (DATA / "processed" / f).exists():
            sys.exit(f"Falta data/processed/{f}: corre antes predios_ciren.py y derechos_dga.py")

    predios = gpd.read_parquet(DATA / "processed" / "predio.parquet")
    predios = predios[predios["rol_valido"]].to_crs(CRS_METROS)
    predios["rol_id"] = predios["comuna"] + ":" + predios["rol"]
    predios = predios[["predio_id", "zona", "comuna", "rol_id", "area_ha", "elegible", "geometry"]]
    derechos = gpd.read_parquet(DATA / "processed" / "derecho.parquet").to_crs(CRS_METROS)
    for col in ("duplicado_de", "pozo_compartido"):
        if col not in derechos:
            sys.exit(f"derecho.parquet no tiene {col}: vuelve a correr derechos_dga.py")

    res = asignar(derechos, predios)
    procesados = DATA / "processed"
    res.to_parquet(procesados / "derecho_predio.parquet", index=False)

    # Base para sumar: solo derechos sumables, con su fecha de otorgamiento.
    d = derechos[["derecho_id", "sumable", "m3_anual", "naturaleza", "fecha_resolucion"]].join(
        res.drop(columns="derecho_id"))
    propios = d[d["sumable"] & d["predio_id"].notna()].merge(
        predios[["predio_id", "rol_id"]], on="predio_id")

    # Entorno: derechos sumables con punto a RADIO_M o menos del predio, incluidos pozos compartidos y grandes
    # derechos no; un pozo inscrito en un lote chico puede regar el predio vecino.
    con_punto = derechos.geometry.notna() & ~derechos.geometry.is_empty
    pts_entorno = derechos.loc[con_punto & derechos["sumable"] & ~derechos["gran_derecho"],
                               ["derecho_id", "m3_anual", "fecha_resolucion", "pozo_compartido", "geometry"]]
    buffers = predios[["predio_id", "geometry"]].copy()
    buffers["geometry"] = buffers.buffer(RADIO_M)
    entorno = gpd.sjoin(pts_entorno, buffers, how="inner", predicate="within").drop(columns="geometry")

    # Atributos fijos por predio.
    area_rol = predios.groupby("rol_id")["area_ha"].sum()
    n_pol = predios.groupby("rol_id").size()
    peor = lambda s: NIVELES[min(NIVELES.index(x) for x in s)]
    conf_propia = propios.groupby("rol_id")["confianza_cruce"].agg(peor)
    base = predios.drop(columns="geometry").set_index("predio_id")
    base["area_rol_ha"] = base["rol_id"].map(area_rol).round(3)
    base["n_poligonos_rol"] = base["rol_id"].map(n_pol)
    base["dist_canal_m"] = distancia_canal(predios).reindex(base.index)
    base["canal_300m"] = base["dist_canal_m"] <= CANAL_M
    base["pozo_compartido_500m"] = base.index.isin(entorno.loc[entorno["pozo_compartido"], "predio_id"])

    filas = []
    for temporada, corte in temporadas():
        vig = lambda f: f["fecha_resolucion"].isna() | (f["fecha_resolucion"] < corte)
        p = propios[vig(propios)]
        e = entorno[vig(entorno)]
        t = base.copy()
        t["temporada"] = temporada
        t["corte"] = corte
        t["n_derechos_predio"] = p.groupby("predio_id").size().reindex(t.index).fillna(0).astype(int)
        t["m3_anual_derecho_predio"] = p.groupby("predio_id")["m3_anual"].sum().reindex(t.index).fillna(0.0)
        t["n_derechos_rol"] = t["rol_id"].map(p.groupby("rol_id").size()).fillna(0).astype(int)
        t["m3_anual_derecho_rol"] = t["rol_id"].map(p.groupby("rol_id")["m3_anual"].sum()).fillna(0.0)
        t["m3_anual_derecho_rol_subterraneo"] = t["rol_id"].map(
            p[p["naturaleza"] == "subterranea"].groupby("rol_id")["m3_anual"].sum()).fillna(0.0)
        t["m3_anual_derecho_entorno_500m"] = e.groupby("predio_id")["m3_anual"].sum().reindex(t.index).fillna(0.0)
        filas.append(t)
    out = pd.concat(filas).reset_index()

    for c in ("m3_anual_derecho_predio", "m3_anual_derecho_rol", "m3_anual_derecho_rol_subterraneo",
              "m3_anual_derecho_entorno_500m"):
        out[c] = out[c].round(1)
    out["m3_ha_derecho_rol"] = (out["m3_anual_derecho_rol"] / out["area_rol_ha"]).round(1)
    out["estado_derechos"] = "sin_derechos_cerca"
    out.loc[out["m3_anual_derecho_entorno_500m"] > 0, "estado_derechos"] = "derechos_cerca_de_otro_rol"
    out.loc[out["m3_anual_derecho_rol"] > 0, "estado_derechos"] = "con_derechos"
    # Confianza del cruce: la peor de los derechos del rol. "Sin derechos" nunca es alta (el 14 % de los
    # derechos no tiene coordenada) y baja si hay derechos cerca de otro rol. El canal no baja la confianza:
    # el 68 % de los predios elegibles tiene un canal a CANAL_M o menos, también todos los casos clave.
    out["confianza_cruce"] = out["rol_id"].map(conf_propia)
    sin = out["estado_derechos"] != "con_derechos"
    out.loc[sin, "confianza_cruce"] = "media"
    out.loc[out["estado_derechos"] == "derechos_cerca_de_otro_rol", "confianza_cruce"] = "baja"
    out = out[["predio_id", "temporada", "corte", "zona", "comuna", "rol_id", "area_ha", "area_rol_ha",
               "n_poligonos_rol", "elegible", "n_derechos_predio", "m3_anual_derecho_predio", "n_derechos_rol",
               "m3_anual_derecho_rol", "m3_anual_derecho_rol_subterraneo", "m3_ha_derecho_rol",
               "m3_anual_derecho_entorno_500m", "pozo_compartido_500m", "dist_canal_m", "canal_300m",
               "estado_derechos", "confianza_cruce"]]
    out.to_parquet(procesados / "predio_derecho.parquet", index=False)

    print("Derechos por método de cruce:")
    print(pd.crosstab(res["metodo_cruce"], derechos["zona"], margins=True).to_string())
    vol = d[d["sumable"]]
    print(f"\nVolumen sumable asignado a un predio: {vol.loc[vol['predio_id'].notna(), 'm3_anual'].sum() / vol['m3_anual'].sum():.0%}")
    print(f"Derechos sumables sin fecha de resolución (cuentan en todas las temporadas): {vol['fecha_resolucion'].isna().sum()}")
    ultima = out[(out["temporada"] == out["temporada"].max()) & out["elegible"]]
    print(f"\nPredios elegibles, temporada {ultima['temporada'].iloc[0]}, por estado:")
    print(pd.crosstab(ultima["estado_derechos"], ultima["zona"], margins=True).to_string())
    print(f"Con canal a {CANAL_M} m o menos: {ultima['canal_300m'].mean():.0%}")
    print(f"\n-> {procesados / 'derecho_predio.parquet'}\n-> {procesados / 'predio_derecho.parquet'} ({len(out)} filas)")


if __name__ == "__main__":
    main()
