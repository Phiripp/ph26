# /// script
# requires-python = ">=3.11"
# dependencies = ["geopandas>=1.0", "pyarrow", "shapely>=2.0"]
# ///
"""Polígonos de referencia de secano para las zonas de data/zonas.json (tarea D11).

Fuente: CONAF, cambio de uso de la tierra 2001-2019 (región de Valparaíso), servicio
USO_DE_LA_TIERRA_CUT_CONAF, capa 5, en IDE Minagri. Se toman las clases de "Praderas y Matorrales"
(código de uso 03xxxx) de las comunas de cada zona.

La capa no separa riego de secano. Una pradera o un matorral que fue lo mismo en 2001, 2013, 2016, 2017 y 2019
(columna `estable`) casi seguro no se riega: sirve de referencia para las anomalías de verdor y humedad (M2).

CONAF llega hasta 2019, y desde entonces se plantaron huertos en laderas que eran matorral. Para no usar riego como
referencia de secano, se recortan de cada polígono los huertos del Catastro Frutícola de CIREN 2025 (capa 59), con
un margen de 20 m, y se descartan los restos de menos de `--area-min-ha`. Esto solo cubre huertos frutales: otros
riegos posteriores a 2019 no se ven aquí y hay que revisarlos con el NDVI de verano (M2).

Corrida nacional: las zonas de data/regiones.json traen su capa CONAF y el campo de uso (`conaf`); se consulta la
región completa, no por comuna. El uso de referencia es el último año de la capa (2017 en el norte, 2019 de Coquimbo
a O'Higgins, 2021 de Maule al sur) y `estable` exige el mismo uso en todos los años de la capa. Aysén no tiene capa
y queda sin referencia. `ref_id` = número de región x 10^8 + objectid, único entre capas.

Entradas: data/zonas.json (o CAUDAL_ZONAS).
Caché: data/raw/conaf/<COMUNA>.geojson (una por comuna), data/raw/conaf/<ZONA>.geojson (una por región) y data/raw/conaf/catastro_fruticola_2025.geojson (no van a git).
Salida: data/processed/referencia_secano.parquet (GeoParquet, EPSG:4326), una fila por polígono CONAF:
  ref_id, zona, comuna, clase (matorral, matorral_arborescente, matorral_pradera, matorral_suculentas,
  pradera_anual), uso_cod, area_ha (EPSG:32719, después del recorte y antes de simplificar), estable (siempre True),
  recortado_fruta (bool: se le quitó algún huerto), geometry.
Solo quedan los polígonos estables 2001-2019 y no se incluye la estepa andina (cordillera alta, otro régimen de
humedad y sin predios agrícolas). La geometría se simplifica a 10 m (el píxel de Sentinel-2): sin eso la capa
pesa más de 100 MB por los vértices de CONAF.

Uso: uv run scripts/extract/referencia_secano_conaf.py [--refrescar] [--area-min-ha 1] [--simplificar-m 10]
"""

import argparse
import json
import sys
import unicodedata
from pathlib import Path

import geopandas as gpd
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from comun.arcgis import paginar  # noqa: E402
from comun.rutas import DATA, ZONAS, mostrar  # noqa: E402

RAW = DATA / "raw" / "conaf"
URL_SERVICIO = "https://esri.ciren.cl/server/rest/services/IDEMINAGRI/USO_DE_LA_TIERRA_CUT_CONAF/MapServer"
CAPA_VALPARAISO = 5
REF_ID_REGION = 100_000_000  # ref_id nacional = número de región x 10^8 + objectid de CONAF (ids únicos entre capas)
PAGINA = 2000  # maxRecordCount del servicio
GENERALIZAR_GRADOS = 0.00005  # unos 5 m
CRS_METROS = "EPSG:32719"
URL_FRUTICOLA = "https://esri.ciren.cl/server/rest/services/IDEMINAGRI/CATASTRO_FRUTICOLA/MapServer/{capa}/query"
CAPA_FRUTICOLA_VALPARAISO = 59
COLUMNAS = ["ref_id", "zona", "comuna", "clase", "uso_cod", "area_ha", "estable", "recortado_fruta", "geometry"]
MARGEN_HUERTO_M = 20
CAMPOS = "objectid,uso_01,uso_13,uso_16,uso_17,uso_19,des_uso_19,nom_com,sup_ha"
# Código de uso 2019 -> clase de referencia. 0301xx praderas (solo la anual es secano de verano seco),
# 0302 matorral-pradera, 0303 matorral, 0304 matorral arborescente, 0305 matorral con suculentas.
CLASES = {
    "030103": "pradera_anual",
    "030101": "estepa_andina",  # estepa altiplánica (capas del norte)
    "030105": "estepa_andina",
    "030200": "matorral_pradera",
    "030300": "matorral",
    "030400": "matorral_arborescente",
    "030500": "matorral_suculentas",
}


def normalizar(nombre: str) -> str:
    sin_tildes = unicodedata.normalize("NFD", nombre).encode("ascii", "ignore").decode()
    return sin_tildes.upper().strip()


def url_capa(capa: int) -> str:
    return f"{URL_SERVICIO}/{capa}/query"


def descargar(donde: str, campos: str, capa: int, destino: Path, generalizar: bool = False) -> None:
    """Baja por páginas todos los polígonos que cumplen `donde` y los guarda como un GeoJSON.

    `generalizar`: el servidor simplifica a ~5 m (después se simplifica a 10 m igual). Sin esto una página de 2.000
    polígonos de Atacama pesa 139 MB; con esto, 6,6 MB.
    """
    params = {"where": donde, "outFields": campos, "outSR": 4326, "f": "geojson"}
    if generalizar:
        params |= {"maxAllowableOffset": GENERALIZAR_GRADOS, "geometryPrecision": 5}
    features = [f for cuerpo in paginar(url_capa(capa), params, PAGINA) for f in cuerpo["features"]]
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps({"type": "FeatureCollection", "features": features}))


def descargar_comuna(comuna: str, destino: Path) -> None:
    """Praderas y matorrales de una comuna de Valparaíso (capa 5)."""
    # La capa guarda los nombres como "La Ligua"; title() alcanza para las 10 comunas de las zonas.
    descargar(f"nom_com = '{comuna.title()}' AND uso_19 LIKE '03%'", CAMPOS, CAPA_VALPARAISO, destino)


def descargar_region(conaf: dict, destino: Path) -> None:
    """Praderas y matorrales de la región completa, con el campo de uso de la capa (último año de la capa)."""
    usos = [*conaf["campos_historia"], conaf["campo_uso"]]
    descargar(f"{conaf['campo_uso']} LIKE '03%'", ",".join(["objectid", *usos, "nom_com", "sup_ha"]), conaf["capa"], destino, generalizar=True)


def descargar_fruticola(zonas: dict, destino: Path) -> None:
    """Huertos del Catastro Frutícola 2025 que tocan el bounding box de cada zona."""
    features, vistos = [], set()
    for cfg in zonas.values():
        params = {"geometry": ",".join(str(v) for v in cfg["bbox"]), "geometryType": "esriGeometryEnvelope",
                  "inSR": 4326, "spatialRel": "esriSpatialRelIntersects", "outFields": "mslink", "outSR": 4326,
                  "f": "geojson"}
        for cuerpo in paginar(URL_FRUTICOLA.format(capa=cfg.get("fruticola", CAPA_FRUTICOLA_VALPARAISO)), params, 2000):
            features += [f for f in cuerpo["features"] if f["properties"]["mslink"] not in vistos]
            vistos.update(f["properties"]["mslink"] for f in cuerpo["features"])
    destino.write_text(json.dumps({"type": "FeatureCollection", "features": features}))


def cargar_zona(zona: str, cfg: dict, refrescar: bool) -> gpd.GeoDataFrame | None:
    """Polígonos de pradera y matorral de una zona, con las columnas `uso_cod`, `estable` y `ref_id_origen`.

    Z1 y Z2 (con `comunas`): capa 5 por comuna, como antes. Regiones (con `conaf`): una consulta por región.
    """
    if "conaf" in cfg:
        conaf = cfg["conaf"]
        if conaf is None:
            print(f"{zona} sin capa CONAF: queda sin referencia de secano")
            return None
        ruta = RAW / f"{zona}.geojson"
        if refrescar or not ruta.exists():
            descargar_region(conaf, ruta)
        gdf = gpd.read_file(ruta)
        print(f"{zona} {len(gdf):>6} polígonos de pradera y matorral (capa CONAF {conaf['capa']}, {conaf['campo_uso']})")
        gdf["uso_cod"] = gdf[conaf["campo_uso"]]
        gdf["estable"] = gdf[conaf["campos_historia"]].eq(gdf["uso_cod"], axis=0).all(axis=1)
        gdf["comuna"] = gdf["nom_com"].map(normalizar)
        gdf["ref_id"] = cfg["numero"] * REF_ID_REGION + gdf["objectid"].astype("int64")
        gdf["zona"] = zona
        return gdf
    partes = []
    for comuna in cfg["comunas"]:
        ruta = RAW / f"{normalizar(comuna)}.geojson"
        if refrescar or not ruta.exists():
            descargar_comuna(comuna, ruta)
        gdf = gpd.read_file(ruta)
        print(f"{zona} {normalizar(comuna):<10} {len(gdf):>5} polígonos de pradera y matorral")
        if gdf.empty:
            continue
        gdf["zona"], gdf["comuna"] = zona, normalizar(comuna)
        partes.append(gdf)
    gdf = gpd.GeoDataFrame(pd.concat(partes, ignore_index=True), crs="EPSG:4326")
    gdf["uso_cod"] = gdf["uso_19"]
    gdf["estable"] = gdf[["uso_01", "uso_13", "uso_16", "uso_17"]].eq(gdf["uso_19"], axis=0).all(axis=1)
    gdf["ref_id"] = gdf["objectid"].astype(int)
    return gdf


def guardar(gdf: gpd.GeoDataFrame) -> Path:
    salida = DATA / "processed" / "referencia_secano.parquet"
    salida.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_parquet(salida, index=False)
    return salida


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--refrescar", action="store_true")
    ap.add_argument("--area-min-ha", type=float, default=1.0, help="descarta polígonos más chicos (unos 10 píxeles de 10 m)")
    ap.add_argument("--simplificar-m", type=float, default=10.0, help="tolerancia de simplificación en metros")
    args = ap.parse_args()

    zonas = json.loads(ZONAS.read_text())["zonas"]
    partes = [g for z, cfg in zonas.items() if (g := cargar_zona(z, cfg, args.refrescar)) is not None]
    if not partes:
        gdf = gpd.GeoDataFrame({c: [] for c in COLUMNAS[:-1]}, geometry=[], crs="EPSG:4326")
        guardar(gdf)
        return 0
    gdf = gpd.GeoDataFrame(pd.concat(partes, ignore_index=True), crs="EPSG:4326")

    ruta_fruta = RAW / "catastro_fruticola_2025.geojson"
    if args.refrescar or not ruta_fruta.exists():
        descargar_fruticola(zonas, ruta_fruta)
    huertos = gpd.read_file(ruta_fruta).to_crs(CRS_METROS)
    print(f"{len(huertos)} huertos del Catastro Frutícola 2025")

    gdf["clase"] = gdf["uso_cod"].map(CLASES)
    gdf = gdf[gdf["clase"].notna()].copy()
    metros = gdf.to_crs(CRS_METROS)
    metros = metros.set_geometry(metros.make_valid())  # la generalización del servidor deja polígonos inválidos
    mascara = huertos.buffer(MARGEN_HUERTO_M).union_all()
    recortado = metros.difference(mascara)
    gdf["recortado_fruta"] = ~recortado.geom_equals(metros.geometry)
    gdf["geometry"] = recortado.to_crs("EPSG:4326")
    gdf = gdf[~gdf.is_empty].copy()
    gdf["area_ha"] = (gdf.to_crs(CRS_METROS).area / 10_000).round(3)
    gdf = gdf[(gdf["area_ha"] >= args.area_min_ha) & gdf["estable"] & (gdf["clase"] != "estepa_andina")].copy()
    simple = gdf.to_crs(CRS_METROS).simplify(args.simplificar_m, preserve_topology=True)
    gdf["geometry"] = simple.make_valid().to_crs("EPSG:4326")  # la simplificación deja algunos polígonos inválidos
    gdf = gdf.drop_duplicates("ref_id").sort_values(["zona", "comuna", "ref_id"]).reset_index(drop=True)
    salida = guardar(gdf[COLUMNAS])

    print(f"\n{mostrar(salida)}: {len(gdf)} polígonos, {salida.stat().st_size / 1e6:.1f} MB")
    print(f"recortados por huertos: {int(gdf['recortado_fruta'].sum())} polígonos")
    resumen = gdf.groupby(["zona", "estable", "clase"]).agg(poligonos=("ref_id", "size"), ha=("area_ha", "sum")).round(0)
    print(resumen.to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
