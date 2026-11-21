# /// script
# requires-python = ">=3.11"
# dependencies = ["geopandas>=1.0", "pyarrow", "shapely>=2.0", "rasterio", "pystac-client", "numpy", "pandas"]
# ///
"""Series NDVI, NDWI y NDMI por predio y escena Sentinel-2 L2A (tarea D1).

Para cada escena que cruza una zona, lee las bandas recortadas a los predios (a 20 m),
enmascara nubes con SCL y promedia los índices dentro de cada predio.

Entradas: data/zonas.json y, según el modo, data/processed/predio_muestra.geojson, predio.parquet,
fiscalizacion.parquet o referencia_secano.parquet.
Caché: data/raw/s2/<zona>/<escena>_<modo>_v2.parquet, una por escena y modo (se puede cortar y reanudar; no va a git).
Salida: data/processed/serie_predio.parquet (o --salida), una fila por (predio_id, escena_id).

Modos (qué polígonos se procesan; por defecto, la muestra):
- --elegibles: los 7.911 predios elegibles (rol válido y 1 ha o más), universo del ranking.
- --validacion: predios elegibles de los vecindarios del set de validación (D18: set_validacion != "fuera").
- --referencia: polígonos de referencia de secano (D11). La columna predio_id lleva el ref_id.
- --predios ARCHIVO: lista de predio_id (una por línea, o CSV/Parquet con columna predio_id).
- --todos: todos los polígonos con rol válido y 0,5 ha o más (20.050 en la capa; lento).

Reflectancia = DN * 1e-4, sin offset (D15). Los COG de Earth Search ya traen el -0.1 aplicado en todos los baselines,
aunque raster:bands declare offset -0.1 y aunque earthsearch:boa_offset_applied diga False: el mar frente a La Ligua
y Quintero da DN roja 50-290 (con offset estaría sobre 1000) y la superposición 19HBD/19HCD coincide en ±20 DN.
No leer el offset de los metadatos.

Índices:
- NDVI = (B08 - B04) / (B08 + B04)
- NDWI = (B03 - B08) / (B03 + B08)   (McFeeters: agua abierta, tranques)
- NDMI = (B8A - B11) / (B8A + B11)   (humedad de la vegetación)
Píxel válido: SCL en {4 vegetación, 5 suelo desnudo, 6 agua, 7 sin clasificar} y reflectancias > 0.

Uso:
  uv run scripts/extract/serie_sentinel2.py                      # muestra, periodo prioritario de cada zona
  uv run scripts/extract/serie_sentinel2.py --zona Z2 --periodo completo
  uv run scripts/extract/serie_sentinel2.py --inicio 2025-12-01 --fin 2026-03-31   # temporada seca 2025-26
  uv run scripts/extract/serie_sentinel2.py --todos              # los 20.050 predios (lento)
  uv run scripts/extract/serie_sentinel2.py --validacion --temporadas 2019-20:2024-25 \
      --salida data/processed/serie_predio_validacion.parquet       # diciembre a marzo de cada temporada
"""

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from shapely.geometry import box
from pystac_client import Client
from rasterio.enums import Resampling
from rasterio.features import rasterize
from rasterio.transform import Affine
from rasterio.warp import transform_bounds
from rasterio.windows import from_bounds

RAIZ = Path(__file__).resolve().parents[2]
DATA = RAIZ / "data"
STAC = "https://earth-search.aws.element84.com/v1"
RES = 20  # metros; B11 y SCL son nativas de 20 m
SCL_VALIDO = [4, 5, 6, 7]
BANDAS = ["green", "red", "nir", "nir08", "swir16", "scl"]
AREA_MIN_HA = 0.5
HILOS = 6
ESPERA_BASE = 15  # s; reintento k espera ESPERA_BASE * 2**k
PAUSA_FINAL = 120  # s antes de la pasada final de escenas fallidas


def nd(a, b):
    with np.errstate(invalid="ignore", divide="ignore"):
        return (a - b) / (a + b)


def leer_ids(ruta: str) -> set[int]:
    f = Path(ruta)
    if f.suffix == ".parquet":
        return set(pd.read_parquet(f, columns=["predio_id"])["predio_id"].astype(int))
    if f.suffix == ".csv":
        return set(pd.read_csv(f)["predio_id"].astype(int))
    return {int(x) for x in f.read_text().split() if x.strip()}


def ids_validacion() -> set[int]:
    """Predios de los vecindarios del set de validación (D18), solo los elegibles."""
    f = gpd.read_parquet(DATA / "processed/fiscalizacion.parquet")
    f = f[f["set_validacion"] != "fuera"]
    return {int(i) for v in f["vecindario"] for i in v} | set(f["predio_id"].dropna().astype(int))


def modo(args) -> str:
    return ("referencia" if args.referencia else "validacion" if args.validacion else
            "elegibles" if args.elegibles else "todos" if args.todos else
            f"predios-{Path(args.predios).stem}" if args.predios else "muestra")


def cargar_predios(zona: str, args) -> gpd.GeoDataFrame:
    m = modo(args)
    if m == "referencia":
        g = gpd.read_parquet(DATA / "processed/referencia_secano.parquet").rename(columns={"ref_id": "predio_id"})
    elif m == "muestra":
        g = gpd.read_file(DATA / "processed/predio_muestra.geojson")
    else:
        g = gpd.read_parquet(DATA / "processed/predio.parquet")
        if m == "todos":
            g = g[g.rol_valido & (g.area_ha >= AREA_MIN_HA)]
        elif m == "elegibles":
            g = g[g.elegible]
        else:
            ids = ids_validacion() if m == "validacion" else leer_ids(args.predios)
            g = g[g.elegible & g.predio_id.isin(ids)]
    g = g[g.zona == zona][["predio_id", "zona", "geometry"]]
    return g.reset_index(drop=True)


def periodos_temporadas(rango: str) -> list[dict]:
    """'2019-20:2024-25' -> diciembre a marzo de cada temporada seca del rango."""
    a, _, b = rango.partition(":")
    ini, fin = int(a[:4]), int((b or a)[:4])
    return [{"inicio": f"{y}-12-01", "fin": f"{y + 1}-03-31"} for y in range(ini, fin + 1)]


class Tile:
    """Grilla de 20 m y máscara de predios de un tile; se calcula una vez y sirve a todas sus escenas."""

    def __init__(self, item, predios: gpd.GeoDataFrame):
        self.crs = rasterio.crs.CRS.from_string(item.properties.get("proj:code") or f"EPSG:{item.properties['proj:epsg']}")
        pg = predios.to_crs(self.crs)
        x0t, y0t = item.assets["red"].extra_fields["proj:transform"][2], item.assets["red"].extra_fields["proj:transform"][5]
        shp = item.assets["red"].extra_fields["proj:shape"]
        ext = (x0t, y0t - shp[0] * 10, x0t + shp[1] * 10, y0t)  # xmin, ymin, xmax, ymax del tile
        pg = pg[pg.intersects(box(*ext))]
        self.vacio = pg.empty
        if self.vacio:
            return
        xmin, ymin, xmax, ymax = pg.total_bounds
        xmin, ymin = max(xmin, ext[0]), max(ymin, ext[1])
        xmax, ymax = min(xmax, ext[2]), min(ymax, ext[3])
        # Alinea a la grilla de 20 m del tile
        xmin = ext[0] + np.floor((xmin - ext[0]) / RES) * RES
        ymax = ext[3] - np.floor((ext[3] - ymax) / RES) * RES
        w = int(np.ceil((xmax - xmin) / RES))
        h = int(np.ceil((ymax - ymin) / RES))
        self.bounds = (xmin, ymax - h * RES, xmin + w * RES, ymax)
        self.transform = Affine(RES, 0, xmin, 0, -RES, ymax)
        self.shape = (h, w)
        self.ids = pg.predio_id.to_numpy()
        formas = ((g, i + 1) for i, g in enumerate(pg.geometry))
        self.mascara = rasterize(formas, out_shape=self.shape, transform=self.transform, fill=0, dtype="int32")
        self.n = len(self.ids)


def leer(item, banda, tile: Tile):
    a = item.assets[banda]
    metodo = Resampling.nearest if banda == "scl" else Resampling.average
    with rasterio.Env(AWS_NO_SIGN_REQUEST="YES", GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR"):
        with rasterio.open(a.href) as ds:
            win = from_bounds(*tile.bounds, transform=ds.transform)
            x = ds.read(1, window=win, out_shape=tile.shape, resampling=metodo, boundless=True, fill_value=0)
    return x.astype("float32")


def procesar_escena(item, tile: Tile) -> pd.DataFrame:
    datos = {}
    for b in BANDAS:
        x = leer(item, b, tile)
        datos[b] = x if b == "scl" else np.where(x > 0, np.clip(x * 1e-4, 0, 1.5), 0)
    scl = datos["scl"]
    refl = [datos[b] for b in ("green", "red", "nir", "nir08", "swir16")]
    # "dato" = píxel con información (el borde del tile viene en cero); "valido" = además sin nubes
    dato = scl > 0
    valido = np.isin(scl, SCL_VALIDO) & np.all([r > 0 for r in refl], axis=0)
    ndvi = nd(datos["nir"], datos["red"])
    ndwi = nd(datos["green"], datos["nir"])
    ndmi = nd(datos["nir08"], datos["swir16"])
    lab = tile.mascara.ravel()
    n = tile.n + 1

    def cuenta(m):
        return np.bincount(lab, weights=m.ravel().astype("float64"), minlength=n)[1:]

    n_dato = cuenta(dato)
    n_val = cuenta(valido)
    out = {"predio_id": tile.ids, "n_pix_total": n_dato.astype(int), "n_pix_validos": n_val.astype(int)}
    with np.errstate(invalid="ignore", divide="ignore"):
        for nombre, v in (("ndvi", ndvi), ("ndwi", ndwi), ("ndmi", ndmi)):
            vv = np.where(valido & np.isfinite(v), v, 0)
            out[nombre] = np.bincount(lab, weights=vv.ravel(), minlength=n)[1:] / n_val
        vv = np.where(valido & np.isfinite(ndvi), ndvi, 0)
        m2 = np.bincount(lab, weights=(vv**2).ravel(), minlength=n)[1:] / n_val
        out["ndvi_std"] = np.sqrt(np.maximum(m2 - out["ndvi"] ** 2, 0))
        out["nubosidad_pct"] = 100 * (1 - n_val / np.where(n_dato > 0, n_dato, np.nan))
    df = pd.DataFrame(out)
    df = df[df.n_pix_total > 0]
    df["escena_id"] = item.id
    df["fecha"] = pd.Timestamp(item.datetime).tz_localize(None).normalize()
    df["nubes_escena_pct"] = item.properties.get("eo:cloud_cover")
    return df


def buscar(z: dict, inicio: str, fin: str, nubes_max: float):
    cat = Client.open(STAC)
    busq = cat.search(
        collections=["sentinel-2-l2a"],
        bbox=z["bbox"],
        datetime=f"{inicio}/{fin}",
        query={"eo:cloud_cover": {"lt": nubes_max}},
        max_items=5000,
    )
    return sorted(busq.items(), key=lambda i: i.datetime)


def periodos(zonas: dict, z: dict, modo: str) -> list[dict]:
    """Periodos a descargar. 'ultima_escena_limpia' se resuelve a hoy: la búsqueda STAC solo trae lo que existe."""
    hoy = pd.Timestamp.today().strftime("%Y-%m-%d")
    ps = [zonas["periodo"]] if modo == "completo" else z["periodos_prioritarios"]
    return [{"inicio": p["inicio"], "fin": hoy if p["fin"] == "ultima_escena_limpia" else p["fin"]} for p in ps]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--zona", choices=["Z1", "Z2"], action="append")
    ap.add_argument("--periodo", choices=["prioritario", "completo"], default="prioritario")
    ap.add_argument("--inicio", help="YYYY-MM-DD; con --fin reemplaza el periodo (misma ventana para todas las zonas)")
    ap.add_argument("--fin", help="YYYY-MM-DD")
    ap.add_argument("--nubes-max", type=float, default=70, help="porcentaje de nubes de la escena; el SCL filtra por píxel")
    sel = ap.add_mutually_exclusive_group()
    sel.add_argument("--todos", action="store_true", help="todos los polígonos con rol válido y 0,5 ha o más")
    sel.add_argument("--elegibles", action="store_true", help="los predios elegibles (rol válido y 1 ha o más)")
    sel.add_argument("--validacion", action="store_true", help="predios de los vecindarios del set de validación (D18)")
    sel.add_argument("--referencia", action="store_true", help="polígonos de referencia de secano (D11)")
    sel.add_argument("--predios", help="archivo con predio_id (una por línea, o CSV/Parquet con columna predio_id)")
    ap.add_argument("--temporadas", help="rango de temporadas secas, p. ej. 2019-20:2024-25 (diciembre a marzo de cada una)")
    ap.add_argument("--limite", type=int, help="procesar solo las primeras N escenas por zona (pruebas)")
    ap.add_argument("--reintentos", type=int, default=3, help="reintentos por escena ante errores de lectura (espera 15, 30, 60 s...)")
    ap.add_argument("--salida", default=str(DATA / "processed/serie_predio.parquet"))
    args = ap.parse_args()

    zonas = json.loads((DATA / "zonas.json").read_text())
    resultados, fallidas = [], []
    for zid in args.zona or ["Z1", "Z2"]:
        z = zonas["zonas"][zid]
        if args.temporadas:
            ps = periodos_temporadas(args.temporadas)
        elif args.inicio and args.fin:
            ps = [{"inicio": args.inicio, "fin": args.fin}]
        else:
            ps = periodos(zonas, z, args.periodo)
        predios = cargar_predios(zid, args)
        if predios.empty:
            print(f"{zid}: sin polígonos en este modo", flush=True)
            continue
        print(f"{zid}: {len(predios)} predios, periodos {[(p['inicio'], p['fin']) for p in ps]}", flush=True)
        vistos = {}
        for p in ps:
            for it in buscar(z, p["inicio"], p["fin"], args.nubes_max):
                vistos[it.id] = it
        items = sorted(vistos.values(), key=lambda i: i.datetime)
        if args.limite:
            items = items[: args.limite]
        print(f"{zid}: {len(items)} escenas", flush=True)
        cache = DATA / "raw/s2" / zid
        cache.mkdir(parents=True, exist_ok=True)
        tiles: dict[str, Tile] = {}
        pend = []
        for it in items:
            # _v2: sin offset (D15); los parquet sin sufijo se calcularon restando -0.1 y no deben reutilizarse
            f = cache / f"{it.id}_{modo(args)}_v2.parquet"
            if f.exists():
                resultados.append(pd.read_parquet(f).assign(zona=zid))
                continue
            tk = it.id.split("_")[1]
            if tk not in tiles:
                tiles[tk] = Tile(it, predios)
            if not tiles[tk].vacio:
                pend.append((it, tiles[tk], f))

        def trabajo(a):
            it, tile, f = a
            for intento in range(args.reintentos + 1):
                try:
                    df = procesar_escena(it, tile)
                    break
                except Exception as e:  # una escena rota no debe tumbar la corrida; la red falla a ratos
                    if intento == args.reintentos:
                        print(f"  ERROR {it.id} (sin más reintentos): {e}", file=sys.stderr, flush=True)
                        return a, None
                    espera = ESPERA_BASE * 2**intento
                    print(f"  reintento {intento + 1}/{args.reintentos} de {it.id} en {espera} s: {e}", file=sys.stderr, flush=True)
                    time.sleep(espera)
            df.to_parquet(f, index=False)
            return a, df.assign(zona=zid)

        def pasada(lista):
            malas = []
            with ThreadPoolExecutor(HILOS) as ex:
                for i, (a, df) in enumerate(ex.map(trabajo, lista), 1):
                    if df is None:
                        malas.append(a)
                    else:
                        resultados.append(df)
                    if i % 10 == 0 or i == len(lista):
                        print(f"  {zid}: {i}/{len(lista)} escenas", flush=True)
            return malas

        malas = pasada(pend)
        if malas:
            # un corte de red largo agota los reintentos por escena: una pasada más al final, después de una pausa
            print(f"  {zid}: {len(malas)} escenas fallidas; pasada final en {PAUSA_FINAL} s", file=sys.stderr, flush=True)
            time.sleep(PAUSA_FINAL)
            malas = pasada(malas)
        fallidas += [it.id for it, _, _ in malas]

    if not resultados:
        sys.exit("Sin resultados")
    s = pd.concat(resultados, ignore_index=True)
    cols = ["predio_id", "zona", "fecha", "ndvi", "ndwi", "ndmi", "ndvi_std", "nubosidad_pct",
            "n_pix_validos", "n_pix_total", "nubes_escena_pct", "escena_id"]
    # Earth Search a veces publica la misma pasada dos veces (sufijos _0 y _1): se queda la de más píxeles válidos
    s = s.sort_values(["predio_id", "fecha", "n_pix_validos"], ascending=[True, True, False])
    s = s.drop_duplicates(["predio_id", "fecha"])
    s = s[cols].sort_values(["predio_id", "fecha"]).reset_index(drop=True)
    Path(args.salida).parent.mkdir(parents=True, exist_ok=True)
    s.to_parquet(args.salida, index=False)
    ok = s.n_pix_validos > 0
    print(f"{len(s)} filas, {s.predio_id.nunique()} predios, {s.escena_id.nunique()} escenas; "
          f"{ok.mean():.0%} con píxeles válidos -> {args.salida}")
    if fallidas:
        # la salida queda escrita, pero incompleta: volver a correr el mismo comando lee el caché y pide solo estas
        print(f"INCOMPLETO: {len(fallidas)} escenas fallaron después de los reintentos; vuelve a correr el mismo comando:\n  "
              + "\n  ".join(fallidas), file=sys.stderr, flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
