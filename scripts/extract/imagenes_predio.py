# /// script
# requires-python = ">=3.11"
# dependencies = ["geopandas>=1.0", "pyarrow", "shapely>=2.0", "rasterio", "pystac-client", "numpy", "pillow"]
# ///
"""Imágenes Sentinel-2 por predio para el frontend (fichas y "antes y después").

Para cada caso de validación cuyo punto cae dentro de un predio válido (y de hasta --max-ha hectáreas),
baja tres recortes de Sentinel-2 L2A alrededor del predio:
- `seca_previa`: la escena más limpia de la temporada seca (dic-mar) anterior a la inspección.
- `seca_2025_26`: la escena más limpia de la temporada seca 2025-26 (la que usa el ranking).
- `reciente`: la escena limpia más reciente (contexto visual; octubre de 2026 fue lluvioso).
"Limpia" = nubes SCL (3, 8, 9, 10, 11 y sin dato) <= --nubes-max % del recorte.

Entradas: data/casos_validacion.geojson y data/processed/predio_muestra.geojson (o predio.parquet).
Salidas (data/processed/imagenes/):
- <expediente>/<etiqueta>_rgb.png: color real (TCI, B04/B03/B02), 4x de zoom.
- <expediente>/<etiqueta>_ndvi.png: NDVI en rampa café a verde (-0.1 a 0.9); gris = nubes o sin dato.
- manifest.json: por imagen, fecha, escena, nubes del recorte, `esquinas` [NO, NE, SE, SO] en lon/lat (para una
  fuente de imagen de MapLibre), `bbox` y el polígono del predio.
Las imágenes no llevan el contorno del predio: el frontend lo dibuja encima con `predio_geojson`.

Uso: uv run scripts/extract/imagenes_predio.py [--max-ha 100] [--margen-m 120] [--nubes-max 5]
"""

import argparse
import json
import math
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from PIL import Image
from pystac_client import Client
from rasterio.warp import transform, transform_bounds
from rasterio.windows import from_bounds
from shapely.geometry import box, mapping

RAIZ = Path(__file__).resolve().parents[2]
DATA = RAIZ / "data"
SALIDA = DATA / "processed" / "imagenes"
STAC = "https://earth-search.aws.element84.com/v1"
ZOOM = 4
SCL_NUBE = [0, 3, 8, 9, 10, 11]
MAX_CANDIDATAS = 14


def epsg_utm(lon: float, lat: float) -> int:
    return (32600 if lat >= 0 else 32700) + int((lon + 180) // 6) + 1


def recorte_utm(geom_ll, margen_m: float, utm: int):
    """Cuadrado en UTM (múltiplo de 10 m) que contiene el predio más un margen."""
    g = gpd.GeoSeries([geom_ll], crs=4326).to_crs(utm).iloc[0]
    x0, y0, x1, y1 = g.bounds
    lado = max(x1 - x0, y1 - y0) + 2 * margen_m
    lado = max(lado, 300.0)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    lado = math.ceil(lado / 10) * 10
    x0, y0 = round((cx - lado / 2) / 10) * 10, round((cy - lado / 2) / 10) * 10
    return (x0, y0, x0 + lado, y0 + lado), lado // 10


def leer(item, banda, bounds, n, utm, nearest=False):
    from rasterio.enums import Resampling

    with rasterio.Env(AWS_NO_SIGN_REQUEST="YES", GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR"):
        with rasterio.open(item.assets[banda].href) as ds:
            assert ds.crs.to_epsg() == utm, f"{item.id}: crs {ds.crs} != {utm}"
            win = from_bounds(*bounds, transform=ds.transform)
            return ds.read(
                window=win, out_shape=(ds.count, n, n), boundless=True, fill_value=0,
                resampling=Resampling.nearest if nearest else Resampling.bilinear,
            )


def nubes_recorte(item, bounds, n, utm) -> float:
    scl = leer(item, "scl", bounds, n, utm, nearest=True)[0]
    return float(np.isin(scl, SCL_NUBE).mean() * 100)


def elegir(items, bounds, n, utm, nubes_max, ultimo=False):
    """Mejor escena: la más reciente con nubes <= umbral (ultimo) o la de menos nubes (empate: la más tardía)."""
    mejor = None
    for it in sorted(items, key=lambda i: i.datetime, reverse=True)[:MAX_CANDIDATAS * 3]:
        try:
            c = nubes_recorte(it, bounds, n, utm)
        except Exception as e:  # escena sin cobertura o asset roto
            print(f"    omito {it.id}: {e}")
            continue
        if ultimo and c <= nubes_max:
            return it, c
        if not ultimo and (mejor is None or c < mejor[1]):
            mejor = (it, c)
        if not ultimo and c <= nubes_max:
            break
    if not ultimo and mejor and mejor[1] <= nubes_max * 4:
        return mejor
    return (None, None) if ultimo or not mejor else mejor


RAMPA = np.array([[0.00, 140, 100, 60], [0.20, 215, 190, 120], [0.40, 200, 215, 110], [0.60, 90, 170, 70], [0.90, 10, 90, 30]], dtype=float)


def pintar_ndvi(ndvi, malo):
    t = np.clip((ndvi + 0.1) / 1.0, 0, 1)
    xs = (RAMPA[:, 0] + 0.1) / 1.0
    rgb = np.stack([np.interp(t, xs, RAMPA[:, k]) for k in (1, 2, 3)], axis=-1)
    rgb[malo] = (170, 170, 170)
    return rgb.astype("uint8")


def guardar(arr, ruta: Path):
    ruta.parent.mkdir(parents=True, exist_ok=True)
    n = arr.shape[0] * ZOOM
    Image.fromarray(arr).resize((n, n), Image.BICUBIC).save(ruta, optimize=True)


def generar(cat, caso, predio, etiqueta, item, c, bounds, n, utm):
    d = SALIDA / caso["expediente"]
    rgb = leer(item, "visual", bounds, n, utm)[:3].transpose(1, 2, 0).astype("uint8")
    red = leer(item, "red", bounds, n, utm)[0].astype("float32")
    nir = leer(item, "nir", bounds, n, utm)[0].astype("float32")
    scl = leer(item, "scl", bounds, n, utm, nearest=True)[0]
    off = -0.1
    r = np.clip(red * 1e-4 + off, 0, 1.5)
    ni = np.clip(nir * 1e-4 + off, 0, 1.5)
    with np.errstate(invalid="ignore", divide="ignore"):
        ndvi = (ni - r) / (ni + r)
    malo = np.isin(scl, SCL_NUBE) | ~np.isfinite(ndvi) | (red == 0)
    guardar(rgb, d / f"{etiqueta}_rgb.png")
    guardar(pintar_ndvi(np.nan_to_num(ndvi), malo), d / f"{etiqueta}_ndvi.png")
    x0, y0, x1, y1 = bounds
    xs, ys = transform(utm, 4326, [x0, x1, x1, x0], [y1, y1, y0, y0])  # NO, NE, SE, SO
    return {
        "etiqueta": etiqueta,
        "fecha": item.datetime.strftime("%Y-%m-%d"),
        "escena_id": item.id,
        "nubes_recorte_pct": round(c, 1),
        "nubes_escena_pct": round(item.properties.get("eo:cloud_cover", float("nan")), 1),
        "archivos": {"rgb": f"{caso['expediente']}/{etiqueta}_rgb.png", "ndvi": f"{caso['expediente']}/{etiqueta}_ndvi.png"},
        "esquinas": [[round(x, 6), round(y, 6)] for x, y in zip(xs, ys)],
        "pixeles": int(n * ZOOM),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-ha", type=float, default=100)
    ap.add_argument("--margen-m", type=float, default=120)
    ap.add_argument("--nubes-max", type=float, default=5, help="porcentaje de nubes del recorte para aceptar una escena")
    args = ap.parse_args()

    casos = gpd.read_file(DATA / "casos_validacion.geojson")
    pq = DATA / "processed" / "predio.parquet"
    predios = gpd.read_parquet(pq) if pq.exists() else gpd.read_file(DATA / "processed" / "predio_muestra.geojson")
    predios = predios[predios.get("rol_valido", True)]
    cat = Client.open(STAC)
    hoy = np.datetime64("today").astype(str)
    manifest = []

    for _, caso in casos.iterrows():
        j = predios[predios.contains(caso.geometry)]
        if j.empty or j.iloc[0].area_ha > args.max_ha:
            print(f"{caso.expediente}: sin predio válido de <= {args.max_ha} ha, omitido")
            continue
        p = j.iloc[0]
        lon, lat = caso.geometry.x, caso.geometry.y
        utm = epsg_utm(lon, lat)
        bounds, n = recorte_utm(p.geometry, args.margen_m, utm)
        bb = transform_bounds(utm, 4326, *bounds)
        ins = str(caso.fecha_inspeccion)[:10]
        anio = int(ins[:4])
        previa = (f"{anio - 1}-12-01", f"{anio}-03-31")
        ventanas = {
            "seca_previa": (previa, False),
            "seca_2025_26": (("2025-12-01", "2026-03-31"), False),
            "reciente": (("2026-04-01", hoy), True),
        }
        print(f"{caso.expediente} ({p.rol}, {p.area_ha:.1f} ha) recorte {int(n) * 10} m", flush=True)
        imgs, vistos = [], set()
        for et, ((ini, fin), ultimo) in ventanas.items():
            items = list(cat.search(collections=["sentinel-2-l2a"], bbox=bb, datetime=f"{ini}/{fin}", query={"eo:cloud_cover": {"lt": 60}}, max_items=400).items())
            items = [i for i in items if i.assets.get("visual") and i.properties.get("proj:code", f"EPSG:{utm}") == f"EPSG:{utm}"]
            it, c = elegir(items, bounds, n, utm, args.nubes_max, ultimo=ultimo)
            if it is None:
                print(f"  {et}: sin escena limpia en {ini} a {fin} ({len(items)} candidatas)")
                continue
            if it.id in vistos:
                print(f"  {et}: repite escena {it.id}, omitida")
                continue
            vistos.add(it.id)
            print(f"  {et}: {it.datetime:%Y-%m-%d} {it.id} nubes recorte {c:.1f}%", flush=True)
            imgs.append(generar(cat, caso, p, et, it, c, bounds, n, utm))
        manifest.append({
            "expediente": caso.expediente, "papel": caso.papel, "zona": caso.zona, "comuna": caso.comuna,
            "fecha_inspeccion": ins, "predio_id": int(p.predio_id), "rol": p.rol, "area_ha": round(float(p.area_ha), 2),
            "punto_caso": [lon, lat], "bbox": [round(v, 6) for v in bb], "predio_geojson": mapping(p.geometry),
            "imagenes": imgs,
        })

    SALIDA.mkdir(parents=True, exist_ok=True)
    (SALIDA / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1))
    print(f"{sum(len(m['imagenes']) for m in manifest)} imágenes de {len(manifest)} predios -> {SALIDA}")


if __name__ == "__main__":
    main()
