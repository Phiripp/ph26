# /// script
# requires-python = ">=3.11"
# dependencies = ["geopandas>=1.0", "pyarrow", "shapely>=2.0", "truststore"]
# ///
"""Sistemas de Agua Potable Rural (APR, hoy Servicios Sanitarios Rurales, SSR) de Z1 y Z2 (tarea D12).

Fuente: Dirección de Obras Hidráulicas (DOH) del MOP, Subdirección de Servicios Sanitarios Rurales, en el servidor
ArcGIS del MOP (rest-sit.mop.gob.cl), servicio DOH/APR, capa 0 "Agua Potable Rural". El servicio
DOH/SSR_Clasificados_Ley_20998 (capa 0) publica los mismos registros y queda de respaldo. Un punto por sistema; el
punto es el estanque, la captación, la oficina o la localidad (columna `punto_referencia`), no el área de servicio.
La DOH la declara base dinámica, de libre uso citando la fuente; la fecha del dato va en `fecha_actualizacion`.
La capa "Agua Potable Rural - DOH" del servidor IDE de la SMA es la misma serie a enero de 2017: no se usa.
Estos dos servicios no aceptan `orderByFields` ni `resultOffset` (responden error 400), así que se pide cada bbox
en una sola consulta y el script se detiene si la respuesta llega al límite del servicio (1.000 registros).

No se guarda el RUT del operador ni nombres de personas: `nombre` es el nombre del sistema (la localidad).

Entradas: data/zonas.json (bbox y comunas de cada zona). Opcionales: data/processed/puntaje.parquet (M5) y
predio.parquet (local), para contar los predios en alerta alta cerca de cada sistema.

Salidas:
- data/raw/apr/<zona>.json: respuesta cruda del servidor por zona (no va a git).
- data/processed/apr.parquet: sistemas dentro del bbox de Z1 o Z2 (GeoParquet, EPSG:4326). `zona` sale de la comuna
  cuando es una comuna de estudio (`en_comunas_zona`); si no, del primer bbox que contiene el punto. Los bbox
  incluyen comunas vecinas: para las cifras del pitch hay que filtrar por `en_comunas_zona`.
  Con puntaje.parquet y predio.parquet agrega `n_alta_1km`, `n_alta_2km` (predios en banda alta de la temporada del
  ranking con el borde a esa distancia o menos del punto) y `dist_alta_m` (al más cercano). Cercanía no es causa: no
  dice que el predio y el sistema saquen agua de la misma fuente.

Uso: uv run scripts/extract/apr_doh.py
"""

import json
import sys
import unicodedata
from pathlib import Path

import geopandas as gpd
import pandas as pd
import truststore

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from comun import arcgis  # noqa: E402
from comun.rutas import DATA, PROC, ZONAS, mostrar  # noqa: E402

truststore.inject_into_ssl()  # rest-sit.mop.gob.cl: cadena GlobalSign, ver derechos_dga.py
arcgis.USER_AGENT = "Mozilla/5.0 (compatible; data-fetch/1.0)"  # genérico: sin el nombre del proyecto

BASE = "https://rest-sit.mop.gob.cl/arcgis/rest/services/DOH"
URLS = [f"{BASE}/APR/MapServer/0/query", f"{BASE}/SSR_Clasificados_Ley_20998/MapServer/0/query"]
LIMITE = 1000  # maxRecordCount del servicio DOH/APR
CRS_METROS = "EPSG:32719"
CAMPOS = {  # campo del servicio -> columna de apr.parquet
    "ID_IDE": "apr_id", "NOMBRE_SSR": "nombre", "REGION": "region", "PROVINCIA": "provincia", "COMUNA": "comuna",
    "TIPO_ORG": "tipo_organizacion", "CLAS_OP": "clasificacion", "URBAN_RURAL": "urbano_rural",
    "ANO_PTA_MCH": "anio_puesta_marcha", "CANT_ARR": "arranques", "BENEF_EST": "beneficiarios_est",
    "CANT_UD": "unidades_domiciliarias", "PTO_REF": "punto_referencia", "FECHA_ACTUALIZACION": "fecha_actualizacion",
}
ENTEROS = ["anio_puesta_marcha", "arranques", "beneficiarios_est", "unidades_domiciliarias"]
ALIAS_COMUNA = {"CALERA": "LA CALERA"}  # la DOH la escribe sin artículo; zonas.json y CIREN, con artículo


def sin_tildes(s: pd.Series) -> pd.Series:
    return s.fillna("").map(lambda t: unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode().strip().upper())


def bajar_bbox(zona_id: str, bbox: list[float]) -> tuple[pd.DataFrame, str]:
    params = {"where": "1=1", "geometry": ",".join(map(str, bbox)), "geometryType": "esriGeometryEnvelope",
              "inSR": "4326", "spatialRel": "esriSpatialRelIntersects", "outFields": ",".join(CAMPOS),
              "outSR": "4326", "f": "json"}
    for i, url in enumerate(URLS):
        try:
            cuerpo = arcgis.pedir(url, params, reintentos=3)
            break
        except RuntimeError as e:
            if i == len(URLS) - 1:
                raise
            print(f"Aviso: {e}; se prueba el servicio de respaldo", file=sys.stderr)
    features = cuerpo.get("features", [])
    if cuerpo.get("exceededTransferLimit") or len(features) >= LIMITE:
        sys.exit(f"{zona_id}: {len(features)} sistemas, se llegó al límite del servicio; hay que dividir el bbox")
    crudo = DATA / "raw" / "apr" / f"{zona_id}.json"
    crudo.parent.mkdir(parents=True, exist_ok=True)
    crudo.write_text(json.dumps({"url": url, "features": features}, ensure_ascii=False), encoding="utf-8")
    filas = [{**f["attributes"], "lon": f["geometry"]["x"], "lat": f["geometry"]["y"], "zona_bbox": zona_id}
             for f in features if f.get("geometry")]
    return pd.DataFrame(filas), url


def cerca_de_alerta(apr: gpd.GeoDataFrame) -> pd.DataFrame | None:
    """Por sistema: predios en banda alta a 1 y 2 km o menos (borde del polígono) y distancia al más cercano."""
    if not ((PROC / "puntaje.parquet").exists() and (PROC / "predio.parquet").exists()):
        return None
    alta = pd.read_parquet(PROC / "puntaje.parquet", columns=["predio_id", "banda"]).query("banda == 'alta'")
    pr = gpd.read_parquet(PROC / "predio.parquet", columns=["predio_id", "geometry"])
    pr = pr[pr["predio_id"].isin(alta["predio_id"])].to_crs(CRS_METROS)
    pts = apr[["apr_id", "geometry"]].to_crs(CRS_METROS)
    out = pts[["apr_id"]].copy()
    for km in (1, 2):
        n = gpd.sjoin(pr, pts.assign(geometry=pts.buffer(km * 1000)), predicate="intersects").groupby("apr_id").size()
        out[f"n_alta_{km}km"] = out["apr_id"].map(n).fillna(0).astype(int)
    d = gpd.sjoin_nearest(pts, pr, distance_col="d").groupby("apr_id")["d"].min()
    out["dist_alta_m"] = out["apr_id"].map(d).round().astype("Int64")
    return out


def main() -> None:
    zonas = json.loads(ZONAS.read_text(encoding="utf-8"))["zonas"]
    partes, urls = zip(*(bajar_bbox(z, d["bbox"]) for z, d in zonas.items()))
    apr = pd.concat(partes, ignore_index=True)
    if apr.empty:
        sys.exit("La DOH no devolvió ningún sistema en los bbox de data/zonas.json; no se escribe apr.parquet")
    apr = apr.drop_duplicates("ID_IDE").rename(columns=CAMPOS)

    for c in ("nombre", "region", "provincia", "tipo_organizacion", "clasificacion", "urbano_rural", "punto_referencia"):
        apr[c] = apr[c].str.strip()
    apr["comuna"] = sin_tildes(apr["comuna"]).replace(ALIAS_COMUNA)
    for c in ENTEROS:  # la DOH usa -99 y 0 como "sin dato"
        apr[c] = pd.to_numeric(apr[c], errors="coerce").where(lambda v: v > 0).astype("Int64")
    apr["fecha_actualizacion"] = pd.to_datetime(apr["fecha_actualizacion"], unit="ms").dt.date
    comuna_zona = {c: z for z, d in zonas.items() for c in d.get("comunas", [])}
    apr["zona"] = apr["comuna"].map(comuna_zona)
    apr["en_comunas_zona"] = apr["zona"].notna()
    apr["zona"] = apr["zona"].fillna(apr["zona_bbox"])
    apr["fuente"] = "DOH-MOP, " + urls[0].split("/rest/services/")[-1].removesuffix("/query")

    orden = ["apr_id", "nombre", "zona", "en_comunas_zona", "comuna", "provincia", "region", "tipo_organizacion",
             "clasificacion", "urbano_rural", "anio_puesta_marcha", "arranques", "beneficiarios_est",
             "unidades_domiciliarias", "punto_referencia", "fecha_actualizacion", "fuente", "lon", "lat"]
    apr = apr[orden].sort_values(["zona", "comuna", "nombre"]).reset_index(drop=True)
    salida = gpd.GeoDataFrame(apr, geometry=gpd.points_from_xy(apr["lon"], apr["lat"]), crs="EPSG:4326")
    cerca = cerca_de_alerta(salida)
    if cerca is not None:
        salida = salida.merge(cerca, on="apr_id", how="left")
    PROC.mkdir(parents=True, exist_ok=True)
    salida.to_parquet(PROC / "apr.parquet", index=False)

    fechas = sorted(set(apr["fecha_actualizacion"].dropna()))
    print(f"Sistemas APR/SSR en los bbox: {len(apr)}; en comunas de estudio: {apr['en_comunas_zona'].sum()}")
    print(f"Fecha del dato (DOH): {fechas[0]} a {fechas[-1]}" if fechas else "Fecha del dato: sin informar")
    estudio = apr[apr["en_comunas_zona"]]
    resumen = {"sistemas": ("apr_id", "size"), "arranques": ("arranques", "sum"),
               "beneficiarios_est": ("beneficiarios_est", "sum"), "sin_arranques": ("arranques", lambda s: s.isna().sum())}
    print("\nPor zona (solo comunas de estudio):")
    print(estudio.groupby("zona").agg(**resumen).to_string())
    print("\nPor comuna (solo comunas de estudio):")
    print(estudio.groupby(["zona", "comuna"]).agg(**resumen).to_string())
    print("\nDentro del bbox pero en otra comuna, por zona: "
          + ", ".join(f"{z} {n}" for z, n in apr[~apr["en_comunas_zona"]].groupby("zona").size().items()))
    if cerca is not None:
        e = salida[salida["en_comunas_zona"]]
        for km in (1, 2):
            c = e[e[f"n_alta_{km}km"] > 0]
            print(f"Sistemas de las comunas de estudio con un predio en alerta alta a {km} km o menos: {len(c)} de {len(e)} "
                  f"({int(c['beneficiarios_est'].sum())} beneficiarios estimados)")
    else:
        print("Sin puntaje.parquet o predio.parquet: no se calcula la cercanía a predios en alerta")
    print(f"\n-> {mostrar(PROC / 'apr.parquet')}")


if __name__ == "__main__":
    main()
