# /// script
# requires-python = ">=3.11"
# dependencies = ["geopandas>=1.0", "pyarrow", "python-calamine", "shapely>=2.0", "truststore"]
# ///
"""Descarga y etiqueta las fiscalizaciones de la DGA en Z1 y Z2 (tarea D6).

Entradas:
- Planilla de seguimiento de fiscalización de la DGA (se descarga; el enlace cambia cada mes).
- data/processed/predio.parquet (correr antes predios_ciren.py).

Salidas:
- data/raw/dga/planilla_fiscalizacion.xlsx: planilla de la DGA (no va a git; se regenera).
- data/processed/fiscalizacion.parquet: un registro por expediente de Z1 y Z2, con etiqueta y predio.

Etiqueta (de "Decisión de la Resolución" y "Estado de tramitación"):
- en_tramite: el expediente no está resuelto. No se muestra como infractor.
- positivo: constata infracción, acoge o aplica multa.
- negativo: no acoge, cierra, rechaza o archiva. Es un negativo débil: la DGA no encontró infracción ese día.
- otro: acumula a otro expediente, apercibe, etc.

Coordenadas: UTM; la planilla no trae datum, se supone WGS84 (EPSG:32718/32719 según huso).
Zona: la del predio con rol válido a 50 m o menos del punto; si no hay, la de la comuna declarada.

Uso: uv run scripts/extract/fiscalizaciones_dga.py [--refrescar]
"""

import argparse
import json
import re
import sys
import unicodedata
import urllib.request
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import truststore

truststore.inject_into_ssl()  # dga.mop.gob.cl: ver derechos_dga.py

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from comun.rutas import DATA, ZONAS  # noqa: E402
PAGINA = "https://dga.mop.gob.cl/tramites/denunciar/fiscalizacion/"
UA = {"User-Agent": "Mozilla/5.0 (caudal-hackathon/0.1)"}
CRS_METROS = "EPSG:32719"
RADIO_PREDIO_M = 50
# Set de validación (D18)
RADIO_VECINDARIO_M = 30
AREA_GRANDE_HA = 100
INICIO_VENTANA = pd.Timestamp("2020-07-01")  # hay al menos una temporada seca previa en el periodo de análisis
# detectable: NDVI mediano de diciembre a marzo previo a la inspección sobre este umbral en algún predio del vecindario.
# Secano: NDVI 0,16–0,30; suelo desnudo: 0,10–0,15 (control 88-31). Bajo el umbral, ningún índice de verdor lo ve.
NDVI_DETECTABLE = 0.30
NUBOSIDAD_MAX = 30
REGION = (-72.0, -34.0, -69.9, -32.0)

COLUMNAS = {
    "expediente": "ID Codigo Expediente",
    "fecha_admisibilidad": "Fecha admisibilidad del expediente FD / Ingreso FO",
    "tipo_ingreso": "Tipo de ingreso",
    "region": "Región",
    "comuna_declarada": "Comuna",
    "tipo_infraccion": "Tipo de infracción",
    "fecha_inspeccion": "Fecha inspección en terreno",
    "utm_norte": "Coordenada Norte (m)",
    "utm_este": "Coordenada Este (m)",
    "huso": "Huso",
    "resolucion": "Número Resolución",
    "fecha_resolucion": "Fecha Resolución",
    "decision": "Decisión de la Resolución",
    "multa_utm": "Multa",
    "estado_tramitacion": "Estado de tramitación",
    "recurso": "Recurso de Reconsideración",
}


def sin_tildes(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", str(s)) if unicodedata.category(c) != "Mn")


def descargar(destino: Path) -> None:
    with urllib.request.urlopen(urllib.request.Request(PAGINA, headers=UA), timeout=60) as r:
        html = r.read().decode("utf-8", "replace")
    enlaces = re.findall(r'href="([^"]*Planilla[^"]*\.xlsx)"', html, flags=re.I)
    if not enlaces:
        sys.exit(f"No se encontró la planilla .xlsx en {PAGINA}")
    print(f"Descargando {enlaces[0]}")
    destino.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(urllib.request.Request(enlaces[0], headers=UA), timeout=300) as r:
        destino.write_bytes(r.read())


def etiquetar(decision: pd.Series, estado: pd.Series) -> pd.Series:
    d = decision.fillna("").map(sin_tildes).str.lower().str.strip()
    etiqueta = pd.Series("otro", index=d.index)
    negativo = d.str.contains(r"no acoge|cierra|cierre|rechaza|archiv")
    positivo = (d.str.contains(r"constata|acoge|multa") & ~d.str.contains("no acoge"))
    etiqueta[negativo] = "negativo"
    etiqueta[positivo] = "positivo"
    etiqueta[d.str.contains("acumula")] = "otro"  # se fusiona con otro expediente
    etiqueta[estado.fillna("").str.strip().str.lower().eq("en trámite")] = "en_tramite"
    return etiqueta


def marcar_validacion(gdf: gpd.GeoDataFrame, predios: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Columnas del set de validación (D18).

    - vecindario: predios con rol válido a RADIO_VECINDARIO_M o menos del punto. El punto es el pozo,
      que puede estar en el borde y regar al vecino: M6 evalúa el vecindario, no solo predio_id.
    - ambiguo: el vecindario tiene 2 o más predios.
    - predio_grande: el predio mide más de AREA_GRANDE_HA (cerros o fundos enteros; la señal se diluye).
    - etiquetas_mixtas: el predio tiene expedientes positivos y negativos de extracción.
    - con_recurso: el infractor presentó recurso de reconsideración.
    - set_validacion: "limpio" (extracción, positivo o negativo, predio elegible, inspección desde
      INICIO_VENTANA, no ambiguo, no grande; un negativo además sin etiquetas mixtas), "vecindario" (igual
      pero ambiguo, grande o negativo con etiquetas mixtas: evaluar por vecindario) o "fuera".
    """
    pts = gdf.loc[gdf.geometry.notna(), ["expediente", "geometry"]].to_crs(CRS_METROS)
    pts["geometry"] = pts.buffer(RADIO_VECINDARIO_M)
    j = gpd.sjoin(pts, predios[["predio_id", "geometry"]], how="inner", predicate="intersects")
    vecinos = j.groupby(level=0)["predio_id"].agg(lambda s: sorted(set(int(x) for x in s)))
    gdf["vecindario"] = vecinos.reindex(gdf.index)
    gdf["vecindario"] = gdf["vecindario"].map(lambda v: v if isinstance(v, list) else [])
    gdf["n_predios_30m"] = gdf["vecindario"].map(len)
    gdf["ambiguo"] = gdf["n_predios_30m"] >= 2

    area = predios.set_index("predio_id")["area_ha"]
    gdf["predio_grande"] = gdf["predio_id"].map(area).gt(AREA_GRANDE_HA).fillna(False).astype(bool)
    etiquetado = gdf[gdf["extraccion"] & gdf["etiqueta"].isin(["positivo", "negativo"]) & gdf["predio_id"].notna()]
    mixtos = etiquetado.groupby("predio_id")["etiqueta"].nunique()
    gdf["etiquetas_mixtas"] = gdf["predio_id"].isin(mixtos[mixtos == 2].index)
    gdf["con_recurso"] = gdf["recurso"].fillna("").str.contains("present", case=False)

    base = (gdf["extraccion"] & gdf["etiqueta"].isin(["positivo", "negativo"])
            & gdf["predio_elegible"].fillna(False).astype(bool) & (gdf["fecha_inspeccion"] >= INICIO_VENTANA))
    # Etiquetas mixtas: el negativo es el dudoso (la DGA volvió y encontró infracción); el positivo se mantiene.
    dudoso = gdf["ambiguo"] | gdf["predio_grande"] | (gdf["etiquetas_mixtas"] & (gdf["etiqueta"] == "negativo"))
    gdf["set_validacion"] = "fuera"
    gdf.loc[base & dudoso, "set_validacion"] = "vecindario"
    gdf.loc[base & ~dudoso, "set_validacion"] = "limpio"
    return gdf


def marcar_detectable(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Columnas temporada_previa, ndvi_previo y detectable (D18), desde la serie Sentinel-2 de validación.

    temporada_previa: la última temporada seca (diciembre a marzo) que empezó antes de la inspección; solo se usan
    fechas anteriores a la inspección. ndvi_previo: el mayor NDVI mediano de esa temporada entre los predios del
    vecindario (o el predio asignado). detectable: ndvi_previo >= NDVI_DETECTABLE; vacío si no hay serie.
    """
    serie_f = DATA / "processed" / "serie_predio_validacion.parquet"
    gdf["temporada_previa"] = None
    gdf["ndvi_previo"] = np.nan
    gdf["detectable"] = pd.array([pd.NA] * len(gdf), dtype="boolean")
    if not serie_f.exists():
        print(f"Aviso: no está {serie_f} (serie_sentinel2.py --validacion); detectable queda vacío")
        return gdf
    s = pd.read_parquet(serie_f, columns=["predio_id", "fecha", "ndvi", "nubosidad_pct", "n_pix_validos"])
    s = s[(s["n_pix_validos"] > 0) & (s["nubosidad_pct"] <= NUBOSIDAD_MAX)]
    con_fecha = gdf["fecha_inspeccion"].notna()
    f = gdf.loc[con_fecha, "fecha_inspeccion"]
    anio = f.dt.year - (f.dt.month < 12).astype(int)
    anio = anio.where(f > pd.to_datetime(anio.astype(str) + "-12-01"), anio - 1)
    gdf.loc[con_fecha, "temporada_previa"] = anio.astype(str) + "-" + (anio + 1).astype(str).str[2:]
    for idx in gdf.index[con_fecha]:
        ids = list(gdf.at[idx, "vecindario"]) or ([int(gdf.at[idx, "predio_id"])] if pd.notna(gdf.at[idx, "predio_id"]) else [])
        if not ids:
            continue
        a = int(gdf.at[idx, "temporada_previa"][:4])
        ventana = s[s["predio_id"].isin(ids) & (s["fecha"] >= pd.Timestamp(a, 12, 1))
                    & (s["fecha"] <= pd.Timestamp(a + 1, 3, 31)) & (s["fecha"] < gdf.at[idx, "fecha_inspeccion"])]
        if ventana.empty:
            continue
        ndvi = ventana.groupby("predio_id")["ndvi"].median().max()
        gdf.at[idx, "ndvi_previo"] = round(float(ndvi), 3)
        gdf.at[idx, "detectable"] = bool(ndvi >= NDVI_DETECTABLE)
    return gdf


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--refrescar", action="store_true", help="vuelve a descargar la planilla aunque exista")
    args = ap.parse_args()

    xlsx = DATA / "raw" / "dga" / "planilla_fiscalizacion.xlsx"
    if args.refrescar or not xlsx.exists():
        descargar(xlsx)
    if not (DATA / "processed" / "predio.parquet").exists():
        sys.exit("Falta data/processed/predio.parquet: corre antes predios_ciren.py")

    df = pd.read_excel(xlsx, sheet_name="Planilla", engine="calamine")
    df.columns = [" ".join(str(c).split()) for c in df.columns]
    faltan = set(COLUMNAS.values()) - set(df.columns)
    if faltan:
        sys.exit(f"La planilla cambió de formato; faltan columnas: {sorted(faltan)}")
    df = df[list(COLUMNAS.values())].set_axis(list(COLUMNAS), axis=1)
    df = df[df["region"].astype(str).map(sin_tildes).str.upper().str.contains("VALPARAISO")].copy()

    for c in ("expediente", "tipo_ingreso", "tipo_infraccion", "decision", "estado_tramitacion", "recurso"):
        df[c] = df[c].astype("string").str.strip().str.replace(r"\s+", " ", regex=True)
    df["comuna_declarada"] = df["comuna_declarada"].astype(str).map(sin_tildes).str.upper().str.strip()
    for c in ("fecha_admisibilidad", "fecha_inspeccion", "fecha_resolucion"):
        df[c] = pd.to_datetime(df[c], errors="coerce")
    for c in ("utm_norte", "utm_este", "huso", "multa_utm"):
        df[c] = pd.to_numeric(df[c].astype(str).str.replace(",", ".", regex=False), errors="coerce")
    df["resolucion"] = df["resolucion"].astype("string")

    tipo = df["tipo_infraccion"].fillna("").map(sin_tildes).str.lower()
    df["extraccion"] = tipo.str.contains(r"extraccion (?:no autorizada de aguas|de aguas no autorizada)")
    df["etiqueta"] = etiquetar(df["decision"], df["estado_tramitacion"])

    # Coordenadas: WGS84 supuesto; huso vacío = 19.
    huso = df["huso"].fillna(19).astype(int)
    lon = pd.Series(np.nan, index=df.index)
    lat = pd.Series(np.nan, index=df.index)
    valida = (df["utm_norte"] > 1_000_000) & (df["utm_este"] > 100_000)
    for h, epsg in ((19, 32719), (18, 32718)):
        sel = valida & (huso == h)
        if sel.any():
            pts = gpd.GeoSeries(gpd.points_from_xy(df.loc[sel, "utm_este"], df.loc[sel, "utm_norte"]), crs=epsg).to_crs(4326)
            lon[sel], lat[sel] = pts.x.to_numpy(), pts.y.to_numpy()
    fuera = ~(lon.between(REGION[0], REGION[2]) & lat.between(REGION[1], REGION[3]))
    lon[fuera], lat[fuera] = np.nan, np.nan
    gdf = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(lon, lat), crs="EPSG:4326")
    gdf.loc[lon.isna(), "geometry"] = None

    # Predio y zona.
    zonas = json.loads((ZONAS).read_text(encoding="utf-8"))["zonas"]
    comuna_zona = {c: z for z, d in zonas.items() for c in d["comunas"]}
    predios = gpd.read_parquet(DATA / "processed" / "predio.parquet")
    predios = predios[predios["rol_valido"]].to_crs(CRS_METROS)[["predio_id", "zona", "elegible", "area_ha", "geometry"]]
    con_punto = gdf.geometry.notna()
    cerca = gpd.sjoin_nearest(gdf.loc[con_punto, ["geometry"]].to_crs(CRS_METROS), predios, how="inner",
                              max_distance=RADIO_PREDIO_M, distance_col="dist_predio_m")
    cerca = cerca.loc[~cerca.index.duplicated()]
    gdf["predio_id"] = pd.array([pd.NA] * len(gdf), dtype="Int64")
    gdf.loc[cerca.index, "predio_id"] = cerca["predio_id"].astype("Int64")
    gdf["dist_predio_m"] = cerca["dist_predio_m"].round(0).reindex(gdf.index)
    gdf["predio_elegible"] = cerca["elegible"].reindex(gdf.index).astype("boolean")
    gdf["zona"] = cerca["zona"].reindex(gdf.index)
    gdf["zona_origen"] = np.where(gdf["zona"].notna(), "predio", None)
    por_comuna = gdf["zona"].isna() & gdf["comuna_declarada"].isin(comuna_zona)
    gdf.loc[por_comuna, "zona"] = gdf.loc[por_comuna, "comuna_declarada"].map(comuna_zona)
    gdf.loc[por_comuna, "zona_origen"] = "comuna"
    gdf = gdf[gdf["zona"].notna()].drop(columns=["region"])
    gdf = marcar_validacion(gdf, predios)
    gdf = marcar_detectable(gdf)

    if gdf["expediente"].duplicated().any():
        print(f"Aviso: {gdf['expediente'].duplicated().sum()} expedientes repetidos en la planilla")
    salida = DATA / "processed" / "fiscalizacion.parquet"
    gdf.to_parquet(salida, index=False)

    print("\nSet de validación (D18), por etiqueta:")
    print(pd.crosstab(gdf["set_validacion"], gdf["etiqueta"]).loc[["limpio", "vecindario"]].to_string())
    pos = gdf[(gdf["set_validacion"] != "fuera") & (gdf["etiqueta"] == "positivo")]
    print("Positivos del set por detectable (NDVI previo >= %.2f):" % NDVI_DETECTABLE)
    print(pd.crosstab(pos["set_validacion"], pos["detectable"].astype("string").fillna("sin serie")).to_string())
    ext = gdf[gdf["extraccion"]]
    print(f"Fiscalizaciones en Z1 y Z2: {len(gdf)} (extracción no autorizada: {len(ext)})")
    print("\nExtracción no autorizada por etiqueta y zona:")
    print(pd.crosstab(ext["etiqueta"], ext["zona"], margins=True).to_string())
    print("\nExtracción con predio elegible a 50 m o menos, por etiqueta:")
    print(ext[ext["predio_elegible"].fillna(False)]["etiqueta"].value_counts().to_string())
    print(f"\nInspección más reciente: {gdf['fecha_inspeccion'].max():%Y-%m-%d}; "
          f"resolución más reciente: {gdf['fecha_resolucion'].max():%Y-%m-%d}")
    print(f"-> {salida}")


if __name__ == "__main__":
    main()
