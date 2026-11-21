# /// script
# requires-python = ">=3.11"
# dependencies = ["geopandas>=1.0", "pyarrow", "shapely>=2.0", "rasterio", "pystac-client", "numpy", "pandas", "scipy", "requests", "matplotlib"]
# ///
"""Puntos de interés (POI) por predio (tarea M10, flujo A1 de docs/spec-flujos-poligono.md).

Prototipo por predio: dice a dónde ir dentro del predio, no si hay infracción.
Tipos de POI:
- zona_riego: parches dentro del predio con NDVI y NDMI sobre su entorno durante la ventana seca.
- posible_tranque: píxeles con agua (NDWI alto y verdor bajo) en varias escenas, en el predio o a menos de 50 m.
- bocatoma: bocatoma CIREN/CNR a menos de 500 m del predio.
- canal: canal de riego a menos de 200 m del predio.
- captacion: pozo o captación de un expediente DGA dentro o a menos de 100 m (casos_validacion; luego derechos).
A cada POI se le agrega elevación y pendiente (Copernicus DEM 30 m).

Provisional: sin la referencia de secano (D11/M2), el "entorno" es un anillo de 100 a 500 m alrededor del predio.
Cuando M2 y M3 existan, zona_riego debe usar z_verdor y z_humedad en vez del anillo.

Entradas: data/processed/predio_muestra.geojson (o predio.parquet si el predio no está en la muestra).
Salida: data/processed/poi.parquet (una fila por POI; se acumula por predio) y, con --png, un mapa de control.

Uso:
  uv run scripts/extract/poi_predio.py                      # predio de la demo (88-31, La Ligua), verano 2024-25
  uv run scripts/extract/poi_predio.py --predio-id 5304670 --inicio 2024-12-01 --fin 2025-03-31 --png
"""

import argparse
import importlib.util
import json
import sys
from pathlib import Path

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rasterio
import requests
from pystac_client import Client
from rasterio.features import rasterize, shapes
from rasterio.windows import from_bounds
from scipy import ndimage as ndi
from shapely.geometry import Point, shape
from shapely.ops import nearest_points

RAIZ = Path(__file__).resolve().parents[2]
DATA = RAIZ / "data"
CRS_M = "EPSG:32719"
RES = 10
BUF_PIXELES = 50  # m alrededor del predio para buscar tranques
ANILLO = (100, 500)  # m, entorno de comparación provisional
CIREN = "https://esri.ciren.cl/server/rest/services/IDEMINAGRI/INFRAESTRUCTURA_RIEGO/MapServer"
DEM_STAC = "https://earth-search.aws.element84.com/v1"

# Reutiliza el lector de bandas de D1
_spec = importlib.util.spec_from_file_location("s2", Path(__file__).with_name("serie_sentinel2.py"))
s2 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(s2)
s2.RES = RES  # D1 trabaja a 20 m; los POI a 10 m


def cargar_predio(pid: int) -> gpd.GeoDataFrame:
    for f in ("predio_muestra.geojson", "predio.parquet"):
        p = DATA / "processed" / f
        if not p.exists():
            continue
        g = gpd.read_file(p) if p.suffix == ".geojson" else gpd.read_parquet(p)
        g = g[g.predio_id == pid]
        if len(g):
            return g.iloc[:1][["predio_id", "zona", "geometry"]].set_crs(4326, allow_override=True).reset_index(drop=True)
    sys.exit(f"predio {pid} no encontrado")


def escenas(bbox, inicio, fin, nubes_max, max_n):
    items = list(Client.open(s2.STAC).search(
        collections=["sentinel-2-l2a"], bbox=bbox, datetime=f"{inicio}/{fin}",
        query={"eo:cloud_cover": {"lt": nubes_max}}, max_items=500).items())
    items = sorted(items, key=lambda i: i.datetime)
    # una por pasada (Earth Search duplica con sufijos _0/_1) y repartidas en el periodo
    uniq = {i.datetime.date(): i for i in items}
    items = list(uniq.values())
    if len(items) > max_n:
        idx = np.linspace(0, len(items) - 1, max_n).round().astype(int)
        items = [items[i] for i in sorted(set(idx))]
    return items


def indices(item, tile):
    d = {}
    for b in ("green", "red", "nir", "nir08", "swir16"):
        x = s2.leer(item, b, tile)
        d[b] = np.where(x > 0, np.clip(x * 1e-4, 0, 1.5), np.nan)  # sin offset (D15, ver serie_sentinel2.py)
    scl = s2.leer(item, "scl", tile)
    ok = np.isin(scl, s2.SCL_VALIDO) & np.all([np.isfinite(v) for v in d.values()], axis=0)
    nd = s2.nd
    out = {"ndvi": nd(d["nir"], d["red"]), "ndwi": nd(d["green"], d["nir"]), "ndmi": nd(d["nir08"], d["swir16"])}
    return {k: np.where(ok, v, np.nan) for k, v in out.items()}, ok


def dem(bbox4326):
    """Elevación y pendiente (%) de Copernicus DEM 30 m recortada al bbox; devuelve (z, pend, transform, crs)."""
    it = next(Client.open(DEM_STAC).search(collections=["cop-dem-glo-30"], bbox=bbox4326, max_items=1).items())
    href = it.assets["data"].href.replace("s3://copernicus-dem-30m/", "https://copernicus-dem-30m.s3.amazonaws.com/")
    with rasterio.Env(AWS_NO_SIGN_REQUEST="YES"):
        with rasterio.open(href) as ds:
            win = from_bounds(*bbox4326, transform=ds.transform)
            z = ds.read(1, window=win, boundless=True, fill_value=np.nan).astype("float32")
            tr = ds.window_transform(win)
    lat = (bbox4326[1] + bbox4326[3]) / 2
    dy = abs(tr.e) * 111_320
    dx = abs(tr.a) * 111_320 * np.cos(np.radians(lat))
    gy, gx = np.gradient(z, dy, dx)
    return z, 100 * np.hypot(gx, gy), tr


def muestrea(z, pend, tr, lon, lat):
    c, r = ~tr * (lon, lat)
    r, c = int(r), int(c)
    if 0 <= r < z.shape[0] and 0 <= c < z.shape[1]:
        return float(z[r, c]), float(pend[r, c])
    return np.nan, np.nan


def capa_ciren(i, bbox):
    r = requests.get(f"{CIREN}/{i}/query", timeout=60, params={
        "where": "1=1", "geometry": ",".join(map(str, bbox)), "geometryType": "esriGeometryEnvelope",
        "inSR": 4326, "outSR": 4326, "spatialRel": "esriSpatialRelIntersects", "outFields": "*", "f": "geojson"})
    r.raise_for_status()
    fs = r.json().get("features", [])
    return gpd.GeoDataFrame.from_features(fs, crs=4326) if fs else gpd.GeoDataFrame(geometry=[], crs=4326)


def componentes(mask, transform, min_px):
    lab, n = ndi.label(mask)
    res = []
    for k in range(1, n + 1):
        m = lab == k
        if m.sum() < min_px:
            continue
        geom = shape(next(shapes(m.astype("uint8"), mask=m, transform=transform))[0])
        res.append((geom, int(m.sum()), m))
    return sorted(res, key=lambda t: -t[1])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--predio-id", type=int, default=5304670, help="mslink CIREN; por defecto 88-31 (demo)")
    ap.add_argument("--inicio", default="2024-12-01")
    ap.add_argument("--fin", default="2025-03-31")
    ap.add_argument("--nubes-max", type=float, default=30)
    ap.add_argument("--max-escenas", type=int, default=8)
    ap.add_argument("--z-umbral", type=float, default=1.0)
    ap.add_argument("--max-poi", type=int, default=8)
    ap.add_argument("--png", action="store_true")
    ap.add_argument("--salida", default=str(DATA / "processed/poi.parquet"))
    a = ap.parse_args()

    pred = cargar_predio(a.predio_id)
    zona = pred.zona.iloc[0]
    pm = pred.to_crs(CRS_M)
    area = pm.geometry.iloc[0]
    amplio = gpd.GeoDataFrame(pred[["predio_id", "zona"]], geometry=[area.buffer(ANILLO[1])], crs=CRS_M).to_crs(4326)
    bbox = tuple(amplio.total_bounds)
    print(f"predio {a.predio_id} ({zona}), {area.area/1e4:.2f} ha", flush=True)

    its = escenas(bbox, a.inicio, a.fin, a.nubes_max, a.max_escenas)
    if not its:
        sys.exit("sin escenas limpias en el periodo")
    print(f"{len(its)} escenas: {[i.datetime.date().isoformat() for i in its]}", flush=True)
    tile = s2.Tile(its[0], amplio)
    pila = {"ndvi": [], "ndwi": [], "ndmi": []}
    validas, fechas = [], []
    for it in its:
        if s2.Tile(it, amplio).bounds != tile.bounds:  # otro tile: se salta (el predio cae en uno solo)
            continue
        ix, ok = indices(it, tile)
        for k in pila:
            pila[k].append(ix[k])
        validas.append(ok)
        fechas.append(it.datetime.date())
    nval = np.sum(validas, axis=0)
    med = {k: np.nanmedian(np.stack(v), axis=0) for k, v in pila.items()}
    tr = tile.transform

    m_pred = rasterize([(area, 1)], out_shape=tile.shape, transform=tr, fill=0, dtype="uint8").astype(bool)
    h, w = tile.shape
    dist_m = ndi.distance_transform_edt(~m_pred) * RES  # m al predio
    anillo = (dist_m > ANILLO[0]) & (dist_m <= ANILLO[1]) & np.isfinite(med["ndvi"]) & np.isfinite(med["ndmi"])

    def z(k):
        ref = med[k][anillo]
        mu, mad = np.median(ref), 1.4826 * np.median(np.abs(ref - np.median(ref))) + 1e-6
        return (med[k] - mu) / mad

    zv, zh = z("ndvi"), z("ndmi")
    regado = m_pred & (zv > a.z_umbral) & (zh > a.z_umbral)

    # tranque: agua en al menos 2 escenas (o la mitad) dentro del predio o a 50 m
    cerca = dist_m <= BUF_PIXELES
    agua_n = np.sum([(np.nan_to_num(v, nan=-1) > 0.05) & (np.nan_to_num(g, nan=1) < 0.25)
                     for v, g in zip(pila["ndwi"], pila["ndvi"])], axis=0)
    agua = cerca & (agua_n >= max(2, len(fechas) // 2))

    zdem, pend, trd = dem(bbox)
    filas = []

    def agrega(tipo, geom_m, razon, conf, area_ha=np.nan, extra=None):
        c = gpd.GeoSeries([geom_m.centroid], crs=CRS_M).to_crs(4326).iloc[0]
        e, p = muestrea(zdem, pend, trd, c.x, c.y)
        filas.append({"predio_id": a.predio_id, "zona": zona, "tipo": tipo, "lon": c.x, "lat": c.y, "area_ha": area_ha,
                      "razon": razon, "fecha_imagen": max(fechas), "n_escenas": len(fechas), "confianza": round(conf, 2),
                      "elev_m": e, "pend_pct": p, **(extra or {})})

    for geom, npx, m in componentes(regado, tr, 10)[:3]:
        ha = npx * RES * RES / 1e4
        medz = float(np.nanmean(np.minimum(zv[m], zh[m])))
        agrega("zona_riego", geom, f"NDVI y NDMI sobre el entorno (z={medz:.1f}) en {len(fechas)} escenas del periodo seco",
               min(0.9, 0.3 + 0.15 * medz) * min(1, len(fechas) / 4), ha)
    for geom, npx, m in componentes(agua, tr, 4)[:2]:
        ha = npx * RES * RES / 1e4
        agrega("posible_tranque", geom, f"agua (NDWI) en {int(np.median(agua_n[m]))} de {len(fechas)} escenas", 0.5, ha)

    for tipo, i, rad, col in (("bocatoma", 0, 500, "nom_can"), ("canal", 1, 200, "nom_can")):
        try:
            g = capa_ciren(i, bbox)
        except Exception as e:
            print(f"  aviso: capa CIREN {i}: {e}", file=sys.stderr)
            continue
        if g.empty:
            continue
        gm = g.to_crs(CRS_M)
        d = gm.distance(area)
        gm = gm[d <= rad].assign(d=d[d <= rad]).sort_values("d").head(2)
        for _, r in gm.iterrows():
            nm = r.get(col) or "sin nombre"
            pto = nearest_points(r.geometry, area)[0]  # punto del canal más cercano al predio, no el centroide
            agrega(tipo, pto, f"{tipo} CIREN/CNR '{nm}' a {r.d:.0f} m del predio", 0.6 if tipo == "bocatoma" else 0.4)

    # captación conocida: pozos de expedientes DGA (casos de validación) dentro o a menos de 100 m
    # TODO: sumar los puntos de captación de derechos.parquet (D4/D5) cuando existan
    cv = DATA / "casos_validacion.geojson"
    if cv.exists():
        c = gpd.read_file(cv).to_crs(CRS_M)
        c = c[c.distance(area) <= 100]
        for _, r in c.iterrows():
            cod = r.get("expediente") or r.get("codigo") or "expediente DGA"
            agrega("captacion", r.geometry, f"captación del expediente {cod} (inspección DGA), a {r.geometry.distance(area):.0f} m del predio", 0.9)

    poi = pd.DataFrame(filas)
    if poi.empty:
        print("sin POI: el predio no muestra señal; la ruta irá solo al acceso")
    else:
        poi = poi.assign(orden=poi.tipo.map({"captacion": 0, "zona_riego": 1, "posible_tranque": 2, "bocatoma": 3, "canal": 4})
                         ).sort_values(["orden", "confianza"], ascending=[True, False]).head(a.max_poi).drop(columns="orden")
        poi.insert(0, "poi_id", [f"{a.predio_id}-{i+1}" for i in range(len(poi))])
        poi = gpd.GeoDataFrame(poi, geometry=gpd.points_from_xy(poi.lon, poi.lat), crs=4326)
        sal = Path(a.salida)
        if sal.exists():
            prev = gpd.read_parquet(sal)
            poi = pd.concat([prev[prev.predio_id != a.predio_id], poi], ignore_index=True)
            poi = gpd.GeoDataFrame(poi, geometry="geometry", crs=4326)
        sal.parent.mkdir(parents=True, exist_ok=True)
        poi.to_parquet(sal, index=False)
        print(poi[poi.predio_id == a.predio_id][["poi_id", "tipo", "area_ha", "elev_m", "pend_pct", "confianza", "razon"]].to_string(index=False))

    if a.png:
        fig, ax = plt.subplots(1, 2, figsize=(12, 6))
        ext = (tr.c, tr.c + w * RES, tr.f - h * RES, tr.f)
        ax[0].imshow(med["ndvi"], cmap="YlGn", vmin=0, vmax=0.8, extent=ext)
        ax[1].imshow(med["ndmi"], cmap="BrBG", vmin=-0.3, vmax=0.4, extent=ext)
        x, y = area.exterior.xy
        pm_pts = gpd.GeoDataFrame(poi, crs=4326).to_crs(CRS_M) if len(poi) else None
        for axx, t in zip(ax, ("NDVI mediano", "NDMI mediano")):
            axx.plot(x, y, "k-", lw=1)
            if pm_pts is not None:
                for tipo, c in (("captacion", "black"), ("zona_riego", "red"), ("posible_tranque", "blue"), ("bocatoma", "magenta"), ("canal", "orange")):
                    s = pm_pts[(pm_pts.tipo == tipo) & (pm_pts.predio_id == a.predio_id)]
                    axx.scatter(s.geometry.x, s.geometry.y, c=c, s=40, label=tipo, edgecolor="w")
            axx.set_title(f"{t} {min(fechas)}..{max(fechas)}")
        ax[0].legend(loc="lower left", fontsize=8)
        sp = RAIZ / f"data/raw/poi_{a.predio_id}.png"
        fig.savefig(sp, dpi=110, bbox_inches="tight")
        print("mapa de control:", sp)


if __name__ == "__main__":
    main()
