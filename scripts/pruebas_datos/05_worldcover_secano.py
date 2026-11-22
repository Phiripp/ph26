# /// script
# requires-python = ">=3.11"
# dependencies = ["geopandas>=1.0", "numpy", "pandas", "pyarrow", "rasterio>=1.3", "shapely>=2.0"]
# ///
"""Prueba D20-B: ¿sirve ESA WorldCover 10 m (v200, 2021) como referencia de secano en vez de CONAF?

Fuente: ESA WorldCover 2021 v200, un COG por tile de 3° x 3°. Sin registro:
- AWS Open Data: https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/<tile>_Map.tif (HTTP sin firma).
- Planetary Computer: colección `esa-worldcover` del STAC; el asset hay que firmarlo con /api/sas/v1/sign (sin cuenta).
Licencia CC BY 4.0. Clases: 10 árboles, 20 matorral, 30 pradera, 40 cultivo, 50 construido, 60 suelo desnudo o
vegetación rala, 80 agua, 90 humedal herbáceo.

Qué mide, para el bbox de cada zona de data/zonas.json:
1. Tiempo de lectura remota de la ventana del bbox (y, con --tile-completo, de la descarga del tile entero).
2. Porcentaje de superficie por clase.
3. Para los polígonos de data/processed/referencia_secano.parquet (CONAF): porcentaje de su superficie en cada clase,
   total, por clase CONAF y por polígono.
4. Al revés: cuánto del matorral, pradera y suelo desnudo de WorldCover queda fuera de la referencia CONAF.
5. Control con riego conocido (si existe data/raw/ciren_fruticola/cuarteles.parquet): qué clase le pone WorldCover
   a los huertos del Catastro Frutícola 2025. Lo que caiga en 20, 30 o 60 sería riego dentro de la "referencia".

La superficie sale de contar píxeles de 1/12000° con el área real de cada franja de latitud (esfera autálica).

Caché: data/raw/worldcover/<zona>_worldcover_2021_v200.tif (recorte del bbox; no va a git).

Uso: uv run scripts/pruebas_datos/05_worldcover_secano.py [--refrescar] [--tile-completo]
"""

import argparse
import json
import math
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.features import rasterize
from rasterio.windows import from_bounds
from rasterio.windows import transform as window_transform

RAIZ = Path(__file__).resolve().parents[2]
ZONAS = RAIZ / "data" / "zonas.json"
REFERENCIA = RAIZ / "data" / "processed" / "referencia_secano.parquet"
HUERTOS = RAIZ / "data" / "raw" / "ciren_fruticola" / "cuarteles.parquet"
CACHE = RAIZ / "data" / "raw" / "worldcover"

UA = {"User-Agent": "Mozilla/5.0 (prueba-acceso-datos/0.1)"}
BUCKET = "https://esa-worldcover.s3.eu-central-1.amazonaws.com"
PREFIJO = "v200/2021/map/ESA_WorldCover_10m_2021_v200_{tile}_Map.tif"
STAC_PC = "https://planetarycomputer.microsoft.com/api/stac/v1/search"
FIRMA_PC = "https://planetarycomputer.microsoft.com/api/sas/v1/sign"

CLASES = {10: "arboles", 20: "matorral", 30: "pradera", 40: "cultivo", 50: "construido", 60: "desnudo_ralo",
          70: "nieve", 80: "agua", 90: "humedal", 95: "manglar", 100: "musgo", 0: "sin_dato"}
CODIGOS = sorted(CLASES)
INDICE = np.full(256, len(CODIGOS) - 1 if 0 not in CODIGOS else CODIGOS.index(0), dtype=np.int64)
for i, c in enumerate(CODIGOS):
    INDICE[c] = i
NOMBRES = [CLASES[c] for c in CODIGOS]
SECANO_WC = ["matorral", "pradera", "desnudo_ralo"]
RADIO_M = 6_371_007.2  # esfera autálica de WGS84
FRANJA = 256  # filas por franja de latitud al contar


def pedir(url: str, metodo: str = "GET", leer: int = 0) -> tuple[int | str, float, bytes]:
    """Estado HTTP (o el error), segundos y los primeros `leer` bytes."""
    t = time.time()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA, method=metodo), timeout=60) as r:
            return r.status, time.time() - t, r.read(leer) if leer else b""
    except urllib.error.HTTPError as e:
        return e.code, time.time() - t, b""
    except Exception as e:  # red caída, DNS, etc.
        return type(e).__name__, time.time() - t, b""


def tile_de(bbox: list[float]) -> str:
    """Tile de 3° que contiene el bbox (esquina suroeste en múltiplos de 3)."""
    lon0, lat0 = math.floor(bbox[0] / 3) * 3, math.floor(bbox[1] / 3) * 3
    if math.floor(bbox[2] / 3) * 3 != lon0 or math.floor(bbox[3] / 3) * 3 != lat0:
        sys.exit(f"El bbox {bbox} cruza más de un tile de WorldCover; esta prueba lee uno solo")
    return f"{'S' if lat0 < 0 else 'N'}{abs(lat0):02d}{'W' if lon0 < 0 else 'E'}{abs(lon0):03d}"


def probar_accesos(tile: str, bbox_total: list[float]) -> None:
    url_aws = f"{BUCKET}/{PREFIJO.format(tile=tile)}"
    lista = f"{BUCKET}/?list-type=2&prefix={urllib.parse.quote(PREFIJO.format(tile=tile))}"
    print("== Acceso sin registro")
    for nombre, url, metodo in (("AWS listado", lista, "GET"), ("AWS COG (HEAD)", url_aws, "HEAD")):
        estado, seg, _ = pedir(url, metodo)
        print(f"{nombre}: {estado} en {seg:.1f} s  {url}")
    q = f"{STAC_PC}?collections=esa-worldcover&bbox={','.join(map(str, bbox_total))}&limit=20"
    estado, seg, cuerpo = pedir(q, leer=2_000_000)
    print(f"Planetary Computer STAC: {estado} en {seg:.1f} s  {q}")
    if estado != 200:
        return
    items = json.loads(cuerpo)["features"]
    print("  items:", [f["id"] for f in items])
    href = next(f["assets"]["map"]["href"] for f in items if "2021_v200" in f["id"])
    estado, seg, _ = pedir(href, "HEAD")
    print(f"  asset sin firmar (HEAD): {estado} en {seg:.1f} s  {href}")
    estado, seg, cuerpo = pedir(f"{FIRMA_PC}?href={urllib.parse.quote(href, safe='')}", leer=10_000)
    print(f"  firma anónima /api/sas/v1/sign: {estado} en {seg:.1f} s")
    if estado == 200:
        estado, seg, _ = pedir(json.loads(cuerpo)["href"], "HEAD")
        print(f"  asset firmado (HEAD): {estado} en {seg:.1f} s")


def leer_ventana(tile: str, zona: str, bbox: list[float], refrescar: bool):
    """Recorte del bbox: desde la caché o leyendo el COG remoto por rangos HTTP."""
    destino = CACHE / f"{zona}_worldcover_2021_v200.tif"
    if destino.exists() and not refrescar:
        with rasterio.open(destino) as ds:
            print(f"{zona}: caché {destino.relative_to(RAIZ)} ({destino.stat().st_size / 1e6:.1f} MB)")
            return ds.read(1), ds.transform
    url = f"{BUCKET}/{PREFIJO.format(tile=tile)}"
    t = time.time()
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", GDAL_HTTP_USERAGENT=UA["User-Agent"]):
        with rasterio.open(url) as ds:
            w = from_bounds(*bbox, transform=ds.transform).round_offsets().round_lengths()
            datos = ds.read(1, window=w)
            tr = window_transform(w, ds.transform)
            perfil = {"driver": "GTiff", "dtype": "uint8", "count": 1, "crs": ds.crs, "transform": tr,
                      "height": datos.shape[0], "width": datos.shape[1], "compress": "deflate", "tiled": True}
    seg = time.time() - t
    CACHE.mkdir(parents=True, exist_ok=True)
    with rasterio.open(destino, "w", **perfil) as out:
        out.write(datos, 1)
    print(f"{zona}: lectura remota de {datos.shape[1]} x {datos.shape[0]} px ({datos.size / 1e6:.0f} M) en {seg:.1f} s "
          f"-> {destino.relative_to(RAIZ)} ({destino.stat().st_size / 1e6:.1f} MB)")
    return datos, tr


def descargar_tile(tile: str) -> None:
    """Baja el tile entero con curl: en la prueba urllib bajó a 0,5 MB/s y curl a ~5 MB/s desde el mismo equipo."""
    url = f"{BUCKET}/{PREFIJO.format(tile=tile)}"
    destino = CACHE / url.rsplit("/", 1)[1]
    CACHE.mkdir(parents=True, exist_ok=True)
    t = time.time()
    subprocess.run(["curl", "-sS", "-f", "-A", UA["User-Agent"], "-o", str(destino), url], check=True)
    print(f"Tile completo: {destino.stat().st_size / 1e6:.0f} MB en {time.time() - t:.1f} s -> {destino.relative_to(RAIZ)}")


def ha_por_grupo(wc: np.ndarray, tr, grupo: np.ndarray | None, n_grupos: int) -> np.ndarray:
    """Hectáreas por (grupo, clase WorldCover). grupo = None: todo el recorte es el grupo 0."""
    k = len(CODIGOS)
    total = np.zeros(n_grupos * k)
    dlon, dlat = math.radians(abs(tr.a)), math.radians(abs(tr.e))
    for f0 in range(0, wc.shape[0], FRANJA):
        f1 = min(f0 + FRANJA, wc.shape[0])
        lat = tr.f + tr.e * (f0 + f1) / 2
        ha_px = RADIO_M**2 * dlon * dlat * math.cos(math.radians(lat)) / 1e4
        clave = INDICE[wc[f0:f1]]
        if grupo is not None:
            g = grupo[f0:f1]
            clave = (clave + g.astype(np.int64) * k)[g > 0]
        total += np.bincount(clave.ravel(), minlength=n_grupos * k) * ha_px
    return total.reshape(n_grupos, k)


def tabla_pct(ha: np.ndarray, etiquetas: list[str]) -> pd.DataFrame:
    df = pd.DataFrame(ha, index=etiquetas, columns=NOMBRES)
    df = df.loc[:, df.sum() > 0]
    pct = df.div(df.sum(axis=1), axis=0).mul(100).round(1)
    pct.insert(0, "ha", df.sum(axis=1).round(0))
    return pct


def rasterizar(geoms, valores, forma, tr, dtype="uint16") -> np.ndarray:
    return rasterize(zip(geoms, valores), out_shape=forma, transform=tr, fill=0, dtype=dtype)


def analizar(zona: str, nombre: str, wc: np.ndarray, tr, ref: gpd.GeoDataFrame, huertos) -> dict:
    print(f"\n== {zona} {nombre}")
    todo = ha_por_grupo(wc, tr, None, 1)
    print("Superficie del bbox por clase (%):")
    print(tabla_pct(todo, ["bbox"]).to_string())

    ref = ref[ref["zona"] == zona].reset_index(drop=True)
    ids = np.arange(1, len(ref) + 1)
    t = time.time()
    capa = rasterizar(ref.geometry, ids, wc.shape, tr)
    por_pol = ha_por_grupo(wc, tr, capa, len(ref) + 1)[1:]
    df = pd.DataFrame(por_pol, columns=NOMBRES)
    ha_pol = df.sum(axis=1)
    print(f"\nReferencia CONAF: {len(ref)} polígonos, {ref['area_ha'].sum():,.0f} ha en el parquet; "
          f"rasterizados {ha_pol.sum():,.0f} ha ({(ha_pol == 0).sum()} polígonos sin píxeles en el bbox); "
          f"{time.time() - t:.1f} s")

    total = df.sum()
    pct = (total / total.sum() * 100).round(1)
    print("Superficie CONAF de secano por clase WorldCover (%):")
    print(pct[pct > 0].to_string())
    bajo = pct[SECANO_WC].sum()
    print(f"-> matorral o pradera: {pct['matorral'] + pct['pradera']:.1f} %; con suelo desnudo o ralo: {bajo:.1f} %; "
          f"árboles: {pct['arboles']:.1f} %; cultivo: {pct['cultivo']:.1f} %; construido: {pct['construido']:.1f} %")

    print("\nPor clase CONAF (%):")
    clases = sorted(ref["clase"].unique())
    print(tabla_pct(df.groupby(ref["clase"]).sum().loc[clases].to_numpy(), clases).to_string())

    con = df[ha_pol > 0]
    frac = con.div(con.sum(axis=1), axis=0)
    f_bajo = frac[SECANO_WC].sum(axis=1)
    print(f"\nPor polígono ({len(con)} con píxeles): mediana de matorral+pradera+ralo {f_bajo.median():.0%}; "
          f"con 80 % o más: {(f_bajo >= 0.8).sum()} ({(f_bajo >= 0.8).mean():.0%}); "
          f"con mayoría de árboles: {(frac['arboles'] > 0.5).sum()} ({(frac['arboles'] > 0.5).mean():.0%}); "
          f"con 10 % o más de cultivo: {(frac['cultivo'] >= 0.1).sum()} ({(frac['cultivo'] >= 0.1).mean():.0%})")

    # Al revés: el "secano" de WorldCover que CONAF no usa como referencia.
    dentro = df[SECANO_WC].sum().sum()
    wc_bajo = pd.Series(todo[0], index=NOMBRES)[SECANO_WC].sum()
    print(f"\nMatorral+pradera+ralo de WorldCover en el bbox: {wc_bajo:,.0f} ha; dentro de la referencia CONAF "
          f"{dentro:,.0f} ha ({dentro / wc_bajo:.0%}); fuera {wc_bajo - dentro:,.0f} ha")

    res = {"zona": zona, "pct_matorral_pradera": pct["matorral"] + pct["pradera"], "pct_bajo": bajo,
           "pct_arboles": pct["arboles"], "pct_cultivo": pct["cultivo"]}
    if huertos is not None:
        h = huertos.cx[tr.c:tr.c + tr.a * wc.shape[1], tr.f + tr.e * wc.shape[0]:tr.f]
        capa = rasterizar(h.geometry, np.ones(len(h), dtype="uint8"), wc.shape, tr, "uint8")
        fr = pd.Series(ha_por_grupo(wc, tr, capa, 2)[1], index=NOMBRES)
        p = (fr / fr.sum() * 100).round(1)
        print(f"\nControl con riego conocido: {len(h)} cuarteles del Catastro Frutícola 2025, {fr.sum():,.0f} ha. "
              f"Clase WorldCover (%):")
        print(p[p > 0].to_string())
        print(f"-> {p[SECANO_WC].sum():.1f} % de la superficie de huertos caería en la 'referencia' WorldCover "
              f"({fr[SECANO_WC].sum():,.0f} ha)")
        res["pct_huertos_en_secano_wc"] = p[SECANO_WC].sum()
    return res


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--refrescar", action="store_true", help="vuelve a leer los recortes aunque estén en caché")
    ap.add_argument("--tile-completo", action="store_true", help="además baja el tile entero y mide el tiempo")
    args = ap.parse_args()

    zonas = json.loads(ZONAS.read_text(encoding="utf-8"))["zonas"]
    cajas = [z["bbox"] for z in zonas.values()]
    total = [min(b[0] for b in cajas), min(b[1] for b in cajas), max(b[2] for b in cajas), max(b[3] for b in cajas)]
    tile = tile_de(total)
    print(f"Tile WorldCover para Z1 y Z2: {tile}")
    probar_accesos(tile, total)

    print("\n== Lectura")
    if args.tile_completo:
        descargar_tile(tile)
    ref = gpd.read_parquet(REFERENCIA)
    huertos = gpd.read_parquet(HUERTOS, columns=["geometry"]) if HUERTOS.exists() else None
    if huertos is None:
        print(f"(sin {HUERTOS.relative_to(RAIZ)}: se omite el control con huertos)")
    recortes = {z: leer_ventana(tile, z, d["bbox"], args.refrescar) for z, d in zonas.items()}
    resumen = [analizar(z, zonas[z]["nombre"], *recortes[z], ref, huertos) for z in zonas]

    print("\n== Resumen")
    print(pd.DataFrame(resumen).set_index("zona").round(1).to_string())


if __name__ == "__main__":
    main()
