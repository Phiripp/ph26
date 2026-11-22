# /// script
# requires-python = ">=3.11"
# dependencies = ["geopandas>=1.0", "pyarrow", "shapely>=2.0", "rasterio", "pystac-client", "numpy", "pandas"]
# ///
"""Etapa `plan` de la corrida nacional: qué escenas Sentinel-2 se leen, qué polígonos toca cada tile y cómo se reparten.

1. Lee los predios elegibles y la referencia de secano de las regiones (base/predio, base/referencia_secano).
2. Descubre los tiles que tocan polígonos (una búsqueda corta por región) y busca en STAC POR TILE (`grid:code`), no por
   bbox de región (las búsquedas por bbox con max_items=5000 se cortan a escala nacional), las escenas de la
   temporada con `eo:cloud_cover` bajo el umbral. Descarta los duplicados `_0`/`_1` de la misma pasada y se queda con el
   de `s2:generation_time` mayor.
3. Escribe plan/poligonos_tile/<tile>.parquet: poligono_id, tipo (predio o secano), region y geometría de cada polígono
   que toca el tile. El mismo predio puede venir en dos regiones (98 mslink repetidos entre capas de CIREN): queda uno.
4. Calcula las celdas ocupadas de cada tile (comun/celdas.py, las mismas que lee serie_sentinel2.py) y reparte los
   tiles en N partes con un reparto codicioso por costo (escenas del tile x celdas ocupadas) de trozos de tile: las
   escenas de cada tile se cortan en trozos contiguos y cada parte toca pocos tiles. Los trozos se reparten
   por prioridad de región (primero el centro), así las primeras escenas que terminan son las de prioridad 1.
5. Escribe plan/partes/<k>.jsonl con los ítems STAC serializados (las tareas no vuelven a consultar STAC),
   plan/regiones_tiles.json (los tiles de cada región, para el control de completitud de la etapa region) y
   plan/escenas.parquet: escena_id, tile, fecha, nubes, parte, prioridad.

Entradas: CAUDAL_ZONAS (config/regiones.json) y CAUDAL_DATA (/datos): base/predio/region=RXX.parquet y
base/referencia_secano/region=RXX.parquet.

Uso: uv run scripts/cloud/chile/plan.py [--partes 40] [--nubes-max 40] [--rehacer]
"""

import argparse
import math
import json
import sys
import tempfile
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from pystac_client import Client
from shapely.geometry import box

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from comun.celdas import celdas_ocupadas, grilla_de_item  # noqa: E402
from comun.rutas import DATA, ZONAS  # noqa: E402

STAC = "https://earth-search.aws.element84.com/v1"
VENTANAS_DESCUBRIMIENTO = [("2025-12-01", "2025-12-15"), ("2026-02-01", "2026-02-15")]
PRIORIDAD_SIN_REGION = 9


def con_reintentos(f, reintentos: int = 6):
    """Earth Search responde 502 a ratos: espera exponencial."""
    for intento in range(reintentos):
        try:
            return f()
        except Exception as e:  # noqa: BLE001
            if intento == reintentos - 1:
                raise
            espera = 5 * 2**intento
            print(f"  STAC falló ({type(e).__name__}); reintento en {espera} s", file=sys.stderr, flush=True)
            time.sleep(espera)


def nombre_tile(item) -> str:
    return item.properties["grid:code"].removeprefix("MGRS-")


def crs_item(item) -> rasterio.crs.CRS:
    return rasterio.crs.CRS.from_string(item.properties.get("proj:code") or f"EPSG:{item.properties['proj:epsg']}")


def descubrir_tiles(zonas: dict, catalogo: Client) -> dict:
    """Un ítem por tile con huella en alguna región: dos ventanas cortas por bbox de región (pocos ítems)."""
    por_tile = {}
    for zona, cfg in zonas.items():
        for ini, fin in VENTANAS_DESCUBRIMIENTO:
            items = con_reintentos(lambda: list(catalogo.search(
                collections=["sentinel-2-l2a"], bbox=cfg["bbox"], datetime=f"{ini}/{fin}", max_items=2000).items()))
            for it in items:
                por_tile.setdefault(nombre_tile(it), it)
        print(f"  {zona}: {len(por_tile)} tiles en total", flush=True)
    return por_tile


def caja_tile_4326(item) -> gpd.GeoSeries:
    g = grilla_de_item(item)
    return gpd.GeoSeries([box(g.x0, g.y0 - g.alto * 20, g.x0 + g.ancho * 20, g.y0)], crs=crs_item(item)).to_crs(4326)


def poligonos_de_region(zona: str) -> gpd.GeoDataFrame:
    """Predios elegibles y secano de una región, con las columnas poligono_id, tipo y region."""
    partes = []
    ruta = DATA / "base" / "predio" / f"region={zona}.parquet"
    if ruta.exists():
        p = gpd.read_parquet(ruta, columns=["predio_id", "elegible", "geometry"])
        p = p[p["elegible"]].rename(columns={"predio_id": "poligono_id"}).assign(tipo="predio")
        partes.append(p[["poligono_id", "tipo", "geometry"]])
    ruta = DATA / "base" / "referencia_secano" / f"region={zona}.parquet"
    if ruta.exists():
        s = gpd.read_parquet(ruta, columns=["ref_id", "geometry"]).rename(columns={"ref_id": "poligono_id"}).assign(tipo="secano")
        if len(s):
            partes.append(s[["poligono_id", "tipo", "geometry"]])
    if not partes:
        return gpd.GeoDataFrame({"poligono_id": [], "tipo": [], "region": []}, geometry=[], crs="EPSG:4326")
    g = pd.concat(partes, ignore_index=True)
    return gpd.GeoDataFrame(g, geometry="geometry", crs="EPSG:4326").assign(region=zona)


def deduplicar(items: list) -> list:
    """Misma pasada publicada dos veces (`_0` y `_1`): se queda la de `s2:generation_time` mayor."""
    mejor = {}
    for it in items:
        satelite, tile, dia = it.id.split("_")[:3]
        k = (satelite, tile, dia)
        if k not in mejor or it.properties.get("s2:generation_time", "") > mejor[k].properties.get("s2:generation_time", ""):
            mejor[k] = it
    return sorted(mejor.values(), key=lambda i: (i.datetime, i.id))


def buscar_escenas(catalogo: Client, tile: str, inicio: str, fin: str, nubes_max: float) -> list:
    items = con_reintentos(lambda: list(catalogo.search(
        collections=["sentinel-2-l2a"], datetime=f"{inicio}T00:00:00Z/{fin}T23:59:59Z",
        query={"grid:code": {"eq": f"MGRS-{tile}"}, "eo:cloud_cover": {"lt": nubes_max}}, max_items=1000).items()))
    return deduplicar(items)


def periodo_tile(zonas: dict, regiones, inicio: str, fin: str) -> tuple[str, str]:
    """Temporada seca, salvo que alguna región del tile pida un período propio (`periodo_satelite`): entonces la unión.

    Un tile que toca Valparaíso trae el año completo también para los polígonos vecinos que caen en él; la etapa region
    recorta la serie a la temporada antes de los modelos, así que el ranking de esas regiones no cambia.
    """
    hoy = pd.Timestamp.today().strftime("%Y-%m-%d")
    propios = [zonas[r]["periodo_satelite"] for r in regiones if zonas[r].get("periodo_satelite")]
    if not propios:
        return inicio, fin
    inicios = [p["inicio"] for p in propios] + [inicio]
    fines = [hoy if p["fin"] == "hoy" else p["fin"] for p in propios] + [fin]
    return min(inicios), max(fines)


def repartir(tiles: list[tuple[str, list, int]], n: int, min_escenas: int = 5) -> list[list[tuple[str, object]]]:
    """Reparte por trozos de tile: cada (tile, escenas, celdas), en orden de prioridad, va a las partes en trozos.

    El costo de un tile es escenas x celdas ocupadas. Sus escenas (en orden de fecha) se cortan en k = max(1,
    ceil(costo / (0.7 x objetivo))) trozos contiguos, con objetivo = costo total / n y al menos `min_escenas` escenas por
    trozo. Los trozos se asignan, más grandes primero dentro de cada prioridad, a la parte con menos carga. Así cada
    parte toca pocos tiles: la máscara de un tile pesado (decenas de miles de polígonos) cuesta minutos y se arma una
    vez por tile y por parte. Repartir escena por escena esparcía cada tile por todas las partes y rehacía esa máscara
    en cada tarea.
    """
    objetivo = sum(len(es) * c for _, es, c in tiles) / n
    trozos = []  # (orden de tile, costo, tile, escenas)
    for i, (tile, escenas, celdas) in enumerate(tiles):
        if not escenas:
            continue
        k = max(1, min(math.ceil(len(escenas) * celdas / (0.7 * objetivo)), len(escenas) // min_escenas)) if objetivo else 1
        corte = np.array_split(np.arange(len(escenas)), k)
        trozos += [(i, len(ix) * celdas, tile, [escenas[j] for j in ix]) for ix in corte]
    partes: list[list[tuple[str, object]]] = [[] for _ in range(n)]
    carga = np.zeros(n)
    # Los tiles ya vienen por prioridad; dentro de cada tile, el trozo más grande primero.
    for _, costo, tile, escenas in sorted(trozos, key=lambda t: (t[0], -t[1])):
        k = int(carga.argmin())
        partes[k] += [(tile, it) for it in escenas]
        carga[k] += costo
    return partes


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--partes", type=int, default=40, help="N: tareas satelitales en total (4 regiones x 10)")
    ap.add_argument("--nubes-max", type=float, default=40)
    ap.add_argument("--rehacer", action="store_true", help="rehace el plan aunque plan/escenas.parquet exista")
    args = ap.parse_args()

    plan = DATA / "plan"
    if (plan / "escenas.parquet").exists() and not args.rehacer:
        print(f"{plan / 'escenas.parquet'} ya existe: nada que hacer (--rehacer para volver a planificar)")
        return 0
    cfg = json.loads(ZONAS.read_text())
    zonas = cfg["zonas"]
    inicio, fin = cfg["temporada"]["inicio"], cfg["temporada"]["fin"]
    catalogo = Client.open(STAC)

    print("Tiles que tocan alguna región:")
    tiles = descubrir_tiles(zonas, catalogo)
    cajas = {t: caja_tile_4326(it) for t, it in tiles.items()}

    # Por región: los polígonos que tocan cada tile, a /tmp (así no se tienen las 14 regiones en memoria a la vez).
    tmp = Path(tempfile.mkdtemp(prefix="plan_"))
    for zona in zonas:
        g = poligonos_de_region(zona)
        if g.empty:
            print(f"{zona}: sin polígonos en base/ (¿corrió la etapa base?)")
            continue
        arbol = g.sindex
        for t, caja in cajas.items():
            cerca = arbol.query(caja.iloc[0], predicate="intersects")
            if len(cerca):
                g.iloc[cerca].to_parquet(tmp / f"{t}__{zona}.parquet", index=False)
        print(f"{zona}: {(g['tipo'] == 'predio').sum()} predios y {(g['tipo'] == 'secano').sum()} polígonos de secano", flush=True)

    orden_region = {z: i for i, z in enumerate(zonas)}
    (plan / "poligonos_tile").mkdir(parents=True, exist_ok=True)
    filas, por_tile, tiles_region = [], {}, {}
    for t, item in sorted(tiles.items()):
        archivos = sorted(tmp.glob(f"{t}__*.parquet"), key=lambda f: orden_region[f.stem.split("__")[1]])
        if not archivos:
            continue
        g = gpd.GeoDataFrame(pd.concat([gpd.read_parquet(a) for a in archivos], ignore_index=True), crs="EPSG:4326")
        g = g.drop_duplicates(["poligono_id", "tipo"])  # un predio repetido entre capas: queda el de la primera región
        celdas = celdas_ocupadas(g.to_crs(crs_item(item)).geometry, grilla_de_item(item))
        if not celdas:
            continue
        ini_t, fin_t = periodo_tile(zonas, g["region"].unique(), inicio, fin)
        escenas = buscar_escenas(catalogo, t, ini_t, fin_t, args.nubes_max)
        prioridad = min(zonas[r]["prioridad"] for r in g["region"].unique())
        g.to_parquet(plan / "poligonos_tile" / f"{t}.parquet", index=False)
        por_tile[t] = {"escenas": escenas, "celdas": len(celdas), "prioridad": prioridad}
        for r in g["region"].unique():
            tiles_region.setdefault(r, []).append(t)
        print(f"tile {t}: {len(g)} polígonos, {len(celdas)} celdas ocupadas, {len(escenas)} escenas, prioridad {prioridad}", flush=True)
    if not por_tile:
        sys.exit("Ningún tile toca polígonos: ¿están base/predio y base/referencia_secano?")

    # Escenas en orden de prioridad del tile (las del centro terminan antes en todas las partes) y, dentro, por fecha.
    orden = sorted(por_tile, key=lambda t: (por_tile[t]["prioridad"], -por_tile[t]["celdas"], t))
    unidades = [(t, por_tile[t]["escenas"], por_tile[t]["celdas"]) for t in orden]
    partes = repartir(unidades, args.partes)

    (plan / "partes").mkdir(parents=True, exist_ok=True)
    for k, lista in enumerate(partes):
        with (plan / "partes" / f"{k}.jsonl").open("w", encoding="utf-8") as f:
            for t, it in lista:
                f.write(json.dumps(it.to_dict()) + "\n")
                filas.append({"escena_id": it.id, "tile": t, "fecha": pd.Timestamp(it.datetime).tz_localize(None).normalize(),
                              "nubes": it.properties.get("eo:cloud_cover"), "parte": k, "prioridad": por_tile[t]["prioridad"]})
    (plan / "regiones_tiles.json").write_text(json.dumps(tiles_region, indent=1), encoding="utf-8")  # control de completitud
    esc = pd.DataFrame(filas)
    esc.to_parquet(plan / "escenas.parquet", index=False)  # al final: es la marca de plan terminado

    carga = [sum(por_tile[t]["celdas"] for t, _ in lista) for lista in partes]
    ntiles = [len({t for t, _ in lista}) for lista in partes]
    print(f"\n{len(esc)} escenas en {len(por_tile)} tiles, {args.partes} partes; costo por parte: "
          f"mín {min(carga):,.0f}, máx {max(carga):,.0f}, media {np.mean(carga):,.0f}; "
          f"tiles por parte: mín {min(ntiles)}, máx {max(ntiles)}")
    print(esc.groupby("prioridad").agg(tiles=("tile", "nunique"), escenas=("escena_id", "size")).to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
