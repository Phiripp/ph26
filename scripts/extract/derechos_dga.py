# /// script
# requires-python = ">=3.11"
# dependencies = ["geopandas>=1.0", "pyarrow", "pyproj", "python-calamine", "shapely>=2.0", "truststore"]
# ///
"""Descarga y normaliza los derechos de agua de la DGA para las zonas de data/zonas.json (tarea D4).

Salidas:
- data/raw/dga/Derechos_Concedidos_V_Region.xls: Excel de la DGA (no va a git: trae nombres de titulares).
- data/raw/dga/derecho_titulares.parquet: derecho_id y nombre del titular (no va a git).
- data/processed/derecho.parquet: derechos normalizados, sin nombres, con punto de captación en EPSG:4326.

Normalización (ver docs/spec-v2.md#convenciones-de-datos):
- Coordenadas: se convierten según Datum y Huso de cada fila. Datum vacío o desconocido se toma
  como PSAD56 y se marca. Si la coordenada cae fuera de la región, se prueba el otro huso.
- Caudal: a l/s y a m³ por año usando las columnas de cada mes (días reales del mes).
  m3_mes = m3_anual / 12. "Acciones" y "%" no tienen equivalencia y quedan sin cifra.
  m3_max_dic, m3_max_ene, m3_max_feb, m3_max_mar: máximo extraíble en ese mes según el caudal mensual autorizado
  (columna del mes si las 12 están completas; si no, caudal promedio). Para comparar con el consumo del mes (M5).
- sumable = consuntivo, no eventual y con cifra. Solo los sumables cuentan como derecho del predio.

Uso: uv run scripts/extract/derechos_dga.py [--refrescar]
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
from pyproj import Transformer

# dga.mop.gob.cl envía una cadena GlobalSign que el bundle de Python no valida; el almacén del sistema sí.
truststore.inject_into_ssl()

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from comun.rutas import DATA, ZONAS  # noqa: E402
PAGINA = "https://dga.mop.gob.cl/derechos-de-agua/derechos-registrados/"
ARCHIVO = "Derechos_Concedidos_V_Region.xls"
UA = {"User-Agent": "Mozilla/5.0 (caudal-hackathon/0.1)"}

MESES = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio",
         "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
DIAS_MES = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
SEG_DIA = 86_400

# Factor para pasar cada unidad a l/s. m3/año se trata aparte (es volumen anual).
A_LS = {"lt/s": 1.0, "lt/min": 1 / 60, "m3/s": 1000.0, "m3/min": 1000 / 60,
        "m3/h": 1000 / 3600, "m3/dia": 1000 / SEG_DIA}
SIN_EQUIVALENCIA = {"acciones", "%"}

# EPSG de UTM sur por (datum, huso).
EPSG = {("1956", 19): 24879, ("1969", 19): 29189, ("1984", 19): 32719,
        ("1956", 18): 24878, ("1969", 18): 29188, ("1984", 18): 32718}
DATUM_SUPUESTO = "1956"
GRAN_DERECHO_LS = 100
VOL_RAZON_MIN, VOL_RAZON_MAX = 0.05, 1.05  # Volumen / volumen continuo aceptado como tope anual
DUPLICADO_MAX_M = 600  # VPC y su gemelo: el desfase entre datums llega a ~420 m
POZO_COMPARTIDO_TITULARES = 3
GRILLA_POZO_M = 20
CRS_UTM = "EPSG:32719"
# Región de Valparaíso continental, con margen.
REGION = (-72.0, -34.0, -69.9, -32.0)


def sin_tildes(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def numero(serie: pd.Series) -> pd.Series:
    """'0,0741' -> 0.0741; '1.234,5' -> 1234.5; '71271.36' -> 71271.36; '' -> NaN."""
    s = serie.fillna("").astype(str).str.strip()
    con_coma = s.str.contains(",")
    s = s.where(~con_coma, s.str.replace(".", "", regex=False).str.replace(",", ".", regex=False))
    return pd.to_numeric(s, errors="coerce")


def descargar(destino: Path) -> None:
    with urllib.request.urlopen(urllib.request.Request(PAGINA, headers=UA), timeout=60) as r:
        html = r.read().decode("utf-8", "replace")
    enlaces = re.findall(rf'href="([^"]+/{re.escape(ARCHIVO)})"', html)
    if not enlaces:
        sys.exit(f"No se encontró {ARCHIVO} en {PAGINA}")
    url = enlaces[0]
    print(f"Descargando {url}")
    destino.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=300) as r:
        destino.write_bytes(r.read())


def leer(xls: Path, comunas: dict[str, str]) -> pd.DataFrame:
    df = pd.read_excel(xls, header=6, engine="calamine", dtype=str)
    df.columns = [re.sub(r"\s+", " ", str(c)).strip() for c in df.columns]
    faltan = {"Código de Expediente", "N° Solicitud", "Comuna", "Nombre Solicitante", "Unidad de Caudal",
              "Caudal Anual Prom", "Volumen", "UTM Norte Captación (m)", "UTM Este Captación (m)", "Huso", "Datum",
              *MESES} - set(df.columns)
    if faltan:
        sys.exit(f"El Excel cambió de formato; faltan columnas: {sorted(faltan)}")
    df = df.apply(lambda s: s.str.strip())
    df["comuna_n"] = df["Comuna"].fillna("").map(lambda s: sin_tildes(s).upper())
    df = df[df["comuna_n"].isin(comunas)].copy()
    df["zona"] = df["comuna_n"].map(comunas)
    return df


def caudales(df: pd.DataFrame) -> pd.DataFrame:
    unidad = df["Unidad de Caudal"].fillna("").str.lower().str.strip()
    prom = numero(df["Caudal Anual Prom"])
    meses = pd.concat([numero(df[m]) for m in MESES], axis=1).to_numpy()
    # Solo se usan las columnas mensuales si están completas y no hay negativos (hay filas con meses negativos
    # y caudal promedio positivo: error de carga).
    meses_completos = ~np.isnan(meses).any(axis=1) & (np.nan_to_num(meses) >= 0).all(axis=1)

    factor = unidad.map(A_LS)
    caudal_ls = prom * factor
    m3_anual = caudal_ls * 365 * SEG_DIA / 1000
    # Unidades de caudal con las 12 columnas: volumen con los días reales de cada mes.
    m3_meses = (meses * np.array(DIAS_MES) * SEG_DIA / 1000).sum(axis=1)
    usar_meses = factor.notna().to_numpy() & meses_completos
    m3_anual = m3_anual.where(~usar_meses, m3_meses * factor)
    # m3/año: el caudal promedio ya es el volumen anual.
    es_anual = unidad.eq("m3/año")
    m3_anual = m3_anual.where(~es_anual, prom)
    caudal_ls = caudal_ls.where(~es_anual, prom * 1000 / (365 * SEG_DIA))

    # "Volumen" es el volumen total anual autorizado (tope legal). Suele ser el 20 % o el 100 % del caudal
    # continuo. Se usa como m3_anual cuando es coherente con el caudal; fuera de ese rango es un error de carga.
    m3_continuo = m3_anual
    volumen = numero(df["Volumen"])
    razon = volumen / m3_continuo
    volumen_aplicado = (volumen > 0) & (m3_continuo > 0) & razon.between(VOL_RAZON_MIN, VOL_RAZON_MAX)
    m3_anual = m3_anual.where(~volumen_aplicado, volumen)

    # Máximo extraíble en cada mes de la temporada seca (diciembre a marzo): caudal autorizado de ese mes x días.
    # Usa la columna del mes si las 12 están completas; si no, el caudal promedio. "Volumen" es un tope anual y no
    # limita un mes; m3/año no tiene caudal mensual (queda el promedio).
    por_mes = {}
    for nombre, i in (("dic", 11), ("ene", 0), ("feb", 1), ("mar", 2)):
        ls_mes = pd.Series(meses[:, i], index=df.index) * factor
        ls_mes = ls_mes.where(pd.Series(usar_meses, index=df.index), caudal_ls)
        por_mes[f"m3_max_{nombre}"] = (ls_mes * DIAS_MES[i] * SEG_DIA / 1000).round(1)

    return pd.DataFrame({
        "unidad_origen": df["Unidad de Caudal"],
        "caudal_origen": prom,
        "caudal_ls": caudal_ls.round(4),
        "volumen_origen": volumen,
        "volumen_aplicado": volumen_aplicado,
        "m3_anual_continuo": m3_continuo.round(1),
        "m3_anual": m3_anual.round(1),
        "m3_mes": (m3_anual / 12).round(1),
        **por_mes,
        "unidad_sin_equivalencia": unidad.isin(SIN_EQUIVALENCIA) | unidad.eq(""),
    }, index=df.index)


def puntos(df: pd.DataFrame) -> pd.DataFrame:
    norte = numero(df["UTM Norte Captación (m)"])
    este = numero(df["UTM Este Captación (m)"])
    huso = pd.to_numeric(df["Huso"], errors="coerce")
    datum = df["Datum"].fillna("")

    lon = pd.Series(np.nan, index=df.index)
    lat = pd.Series(np.nan, index=df.index)
    estado = pd.Series("sin_coordenada", index=df.index)
    datum_usado = datum.where(datum.isin(["1956", "1969", "1984"]), DATUM_SUPUESTO)
    huso_decl = huso.fillna(19).astype(int)
    tiene = (norte > 1_000_000) & (este > 100_000)

    dentro = lambda x, y: (x >= REGION[0]) & (x <= REGION[2]) & (y >= REGION[1]) & (y <= REGION[3])
    transformers = {}

    def convertir(idx, h):
        x = np.full(len(idx), np.nan)
        y = np.full(len(idx), np.nan)
        for d in datum_usado.loc[idx].unique():
            sel = (datum_usado.loc[idx] == d).to_numpy()
            key = (d, h)
            if key not in transformers:
                transformers[key] = Transformer.from_crs(EPSG[key], 4326, always_xy=True)
            x[sel], y[sel] = transformers[key].transform(este.loc[idx].to_numpy()[sel], norte.loc[idx].to_numpy()[sel])
        return pd.Series(x, index=idx), pd.Series(y, index=idx)

    for h in (19, 18):
        idx = df.index[tiene & (huso_decl == h)]
        if len(idx) == 0:
            continue
        x, y = convertir(idx, h)
        ok = dentro(x, y)
        lon.loc[idx[ok]], lat.loc[idx[ok]] = x[ok], y[ok]
        estado.loc[idx[ok]] = "ok"
        # Fuera de la región: se prueba el otro huso (huso mal declarado).
        malos = idx[~ok]
        if len(malos):
            x2, y2 = convertir(malos, 37 - h)
            ok2 = dentro(x2, y2)
            lon.loc[malos[ok2]], lat.loc[malos[ok2]] = x2[ok2], y2[ok2]
            estado.loc[malos[ok2]] = "huso_corregido"
            estado.loc[malos[~ok2]] = "fuera_de_region"

    supuesto = (estado == "ok") & ~datum.isin(["1956", "1969", "1984"])
    estado = estado.where(~supuesto, "datum_supuesto")
    return pd.DataFrame({
        "utm_norte": norte, "utm_este": este, "huso_origen": huso, "datum_origen": datum.replace("", None),
        "coord_estado": estado, "lon": lon, "lat": lat,
    }, index=df.index)


def marcar_duplicados_vpc(gdf: gpd.GeoDataFrame, titular: pd.Series) -> pd.Series:
    """Derecho no VPC que repite un VPC: mismo titular, comuna y caudal, a DUPLICADO_MAX_M o menos.

    VPC son resoluciones recientes de la DGA que vuelven a registrar un derecho inscrito antes
    (a veces con otro datum). Se conserva el VPC y el gemelo queda con duplicado_de = derecho_id del VPC.
    """
    g = gdf.assign(titular=titular, prefijo=gdf["expediente"].str.split("-").str[0])
    g = g[g.geometry.notna() & (g["titular"] != "")].to_crs(CRS_UTM)
    claves = ["titular", "comuna", "caudal_origen"]
    vpc = g[g["prefijo"] == "VPC"][claves + ["derecho_id", "geometry"]]
    otros = g[g["prefijo"] != "VPC"][claves + ["derecho_id", "geometry"]]
    pares = vpc.merge(otros, on=claves, suffixes=("_vpc", "_otro"))
    if pares.empty:
        return pd.Series(None, index=gdf.index, dtype="object")
    pares["dist"] = gpd.GeoSeries(pares["geometry_vpc"]).distance(gpd.GeoSeries(pares["geometry_otro"]))
    # Uno a uno, de menor a mayor distancia.
    pares = (pares[pares["dist"] <= DUPLICADO_MAX_M].sort_values("dist")
             .drop_duplicates("derecho_id_otro").drop_duplicates("derecho_id_vpc"))
    mapa = dict(zip(pares["derecho_id_otro"], pares["derecho_id_vpc"]))
    return gdf["derecho_id"].map(mapa)


def marcar_pozos_compartidos(gdf: gpd.GeoDataFrame, titular: pd.Series) -> pd.Series:
    """Punto de captación (celda de GRILLA_POZO_M) con derechos sumables de varios titulares distintos.

    Suelen ser pozos comunitarios o de comunidades de aguas: el agua no riega solo el predio donde está el punto.
    """
    sel = gdf["sumable"] & ~gdf["gran_derecho"] & gdf.geometry.notna()
    p = gdf.loc[sel].to_crs(CRS_UTM)
    celda = ((p.geometry.x / GRILLA_POZO_M).round().astype(int).astype(str) + "_"
             + (p.geometry.y / GRILLA_POZO_M).round().astype(int).astype(str))
    n_tit = titular.loc[sel].groupby(celda).transform("nunique")
    return (n_tit >= POZO_COMPARTIDO_TITULARES).reindex(gdf.index, fill_value=False)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--refrescar", action="store_true", help="vuelve a descargar el Excel aunque exista")
    args = ap.parse_args()

    xls = DATA / "raw" / "dga" / ARCHIVO
    if args.refrescar or not xls.exists():
        descargar(xls)
    zonas = json.loads((ZONAS).read_text(encoding="utf-8"))["zonas"]
    comunas = {c: z for z, d in zonas.items() for c in d["comunas"]}

    df = leer(xls, comunas)
    ejercicio = df["Ejercicio del Derecho"].fillna("")
    tipo = df["Tipo Derecho"].fillna("")
    # Un mismo expediente y solicitud puede tener varias filas con caudales distintos: son derechos
    # distintos. Se agrega la secuencia en el orden del Excel: "ND-0501-3458/1-2".
    clave = df["Código de Expediente"] + "/" + df["N° Solicitud"].fillna("0")
    secuencia = clave.groupby(clave).cumcount() + 1
    repetida = clave.duplicated(keep=False)
    derecho_id = clave.where(~repetida, clave + "-" + secuencia.astype(str))
    base = pd.DataFrame({
        "derecho_id": derecho_id,
        "expediente": df["Código de Expediente"],
        "zona": df["zona"],
        "comuna": df["comuna_n"],
        "fecha_resolucion": pd.to_datetime(df["Fecha de Resolución/ Envío al Juez/ Inscripción C.B.R."],
                                           format="%d/%m/%Y", errors="coerce"),
        "naturaleza": df["Naturaleza del Agua"].fillna("").str.lower().map(
            lambda s: "subterranea" if s.startswith("subterr") else ("superficial" if s.startswith("superf") else None)),
        "fuente": df["Fuente"],
        "uso": df["Uso del Agua"],
        "tipo_derecho": tipo,
        "ejercicio": ejercicio,
        "consuntivo": tipo.eq("Consuntivo"),
        "eventual": ejercicio.str.startswith("Eventual"),
        "provisional": ejercicio.str.contains("Provisional"),
    }, index=df.index)
    if base["derecho_id"].duplicated().any():
        sys.exit(f"derecho_id duplicado: {base.loc[base['derecho_id'].duplicated(), 'derecho_id'].head().tolist()}")

    out = pd.concat([base, caudales(df), puntos(df)], axis=1)
    # Caudal negativo: cesiones, reducciones o errores de carga (hay uno de -41.666 l/s). La magnitud no es
    # confiable, así que se marcan y quedan fuera de la suma en vez de descontarse.
    out["caudal_negativo"] = out["m3_anual"] < 0
    # Derechos de 100 l/s o más: casi siempre canales o comunidades de aguas, no un solo predio.
    # D5 no los asigna a un predio por coordenada sin revisión.
    out["gran_derecho"] = out["caudal_ls"] >= GRAN_DERECHO_LS
    gdf = gpd.GeoDataFrame(out.drop(columns=["lon", "lat"]),
                           geometry=gpd.points_from_xy(out["lon"], out["lat"]), crs="EPSG:4326")
    gdf.loc[out["lon"].isna(), "geometry"] = None

    titular = df["Nombre Solicitante"].fillna("").str.upper().str.replace(r"\s+", " ", regex=True).str.strip()
    gdf["duplicado_de"] = marcar_duplicados_vpc(gdf, titular)
    gdf["sumable"] = (gdf["consuntivo"] & ~gdf["eventual"] & gdf["m3_anual"].notna() & (gdf["m3_anual"] > 0)
                      & gdf["duplicado_de"].isna())
    gdf["pozo_compartido"] = marcar_pozos_compartidos(gdf, titular)

    procesados = DATA / "processed"
    procesados.mkdir(parents=True, exist_ok=True)
    gdf.to_parquet(procesados / "derecho.parquet", index=False)
    titulares = pd.DataFrame({"derecho_id": base["derecho_id"], "titular": df["Nombre Solicitante"]})
    titulares.to_parquet(DATA / "raw" / "dga" / "derecho_titulares.parquet", index=False)

    print(f"Derechos en las zonas: {len(gdf)}")
    print(gdf.groupby("zona").agg(derechos=("derecho_id", "size"), sumables=("sumable", "sum"),
                                  m3_anual_sumable=("m3_anual", lambda s: s[gdf.loc[s.index, "sumable"]].sum()))
          .round(0).to_string())
    grandes = gdf[gdf["sumable"] & gdf["gran_derecho"]]
    print(f"\nGrandes derechos (>= {GRAN_DERECHO_LS} l/s, sumables): {len(grandes)} filas, "
          f"{grandes['m3_anual'].sum() / gdf.loc[gdf['sumable'], 'm3_anual'].sum():.0%} del volumen sumable")
    s = gdf[gdf["sumable"]]
    print(f"Volumen aplicado como tope anual: {gdf['volumen_aplicado'].sum()} derechos; volumen sumable "
          f"{s['m3_anual'].sum() / 1e6:,.0f} Mm³ (con caudal continuo serían {s['m3_anual_continuo'].sum() / 1e6:,.0f})")
    print(f"Posibles duplicados VPC excluidos: {gdf['duplicado_de'].notna().sum()} "
          f"({gdf.loc[gdf['duplicado_de'].notna(), 'm3_anual'].sum() / 1e6:,.1f} Mm³)")
    print(f"Pozos compartidos (>= {POZO_COMPARTIDO_TITULARES} titulares): {gdf['pozo_compartido'].sum()} derechos "
          f"({gdf.loc[gdf['pozo_compartido'], 'm3_anual'].sum() / 1e6:,.0f} Mm³)")
    print(f"Caudal negativo: {gdf['caudal_negativo'].sum()} derechos")
    print("\nEstado de coordenadas:\n" + gdf["coord_estado"].value_counts().to_string())
    print("\nUnidades de origen:\n" + gdf["unidad_origen"].value_counts(dropna=False).to_string())
    print(f"\n-> {procesados / 'derecho.parquet'}")


if __name__ == "__main__":
    main()
