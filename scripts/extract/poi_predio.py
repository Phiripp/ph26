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
- captacion: pozo o captación de un expediente DGA dentro o a menos de 100 m (casos_validacion).
- pozo_derecho: captación de un derecho registrado (derecho.parquet, D4) dentro o a menos de 100 m del predio.
- cauce: punto del cauce con nombre más cercano al predio, a menos de 1.500 m (posible bocatoma sin registro).
A cada POI se le agrega elevación y pendiente (Copernicus DEM 30 m) y, si el predio está en senal_riego.parquet (M3),
la señal de riego del predio en la temporada (`senal_riego_m3`, `frac_senal_m3`) como contexto.

Las zonas de riego se localizan dentro del predio con un anillo de 100 a 500 m alrededor como entorno; M2 y M3
dan la señal por predio (no por píxel), así que no la reemplazan: la acompañan.

Entradas: data/processed/predio.parquet (o predio_muestra.geojson), derecho.parquet, cauce.parquet y, si existe,
senal_riego.parquet.
Salida: data/processed/poi.parquet (una fila por POI; se acumula por predio) y, con --png, un mapa de control.

Uso:
  uv run scripts/extract/poi_predio.py                                 # predio de la demo (88-31, La Ligua)
  uv run scripts/extract/poi_predio.py --predios 5330704,5331888 --png
  uv run scripts/extract/poi_predio.py --senal-m3 10                   # los 10 predios con más señal de M3

Todos los elegibles en un Cloud Run Job (ver scripts/cloud/poi/): cada tarea toma su trozo de los predios
elegibles (CLOUD_RUN_TASK_INDEX / CLOUD_RUN_TASK_COUNT), los procesa con --workers procesos en paralelo y deja
poi_NNNN.parquet, hechos_NNNN.json y fallos_NNNN.json en --salida-gcs. Si la tarea se reintenta, retoma los hechos.
  uv run scripts/extract/poi_predio.py --elegibles --workers 8 --salida-gcs gs://BUCKET/poi/corrida
"""

import argparse
import concurrent.futures as cf
import importlib.util
import json
import multiprocessing
import os
import sys
import time
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

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from comun.rutas import DATA, RAIZ  # noqa: E402
CRS_M = "EPSG:32719"
RES = 10
BUF_PIXELES = 50  # m alrededor del predio para buscar tranques
CAUCE_RADIO = 1500  # m
POZO_RADIO = 100  # m
ANILLO = (100, 500)  # m, entorno de comparación provisional
CIREN = "https://esri.ciren.cl/server/rest/services/IDEMINAGRI/INFRAESTRUCTURA_RIEGO/MapServer"
DEM_STAC = "https://earth-search.aws.element84.com/v1"

# Reutiliza el lector de bandas de D1
_spec = importlib.util.spec_from_file_location("s2", Path(__file__).with_name("serie_sentinel2.py"))
s2 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(s2)
s2.RES = RES  # D1 trabaja a 20 m; los POI a 10 m


class SinEscenas(Exception):
    """El predio no tiene escenas limpias en el periodo: no es un error, es un predio sin POI."""


def cargar_predio(pid: int) -> gpd.GeoDataFrame:
    for f in ("predio_muestra.geojson", "predio.parquet"):
        p = DATA / "processed" / f
        if not p.exists():
            continue
        g = gpd.read_file(p) if p.suffix == ".geojson" else gpd.read_parquet(p)
        g = g[g.predio_id == pid]
        if len(g):
            return g.iloc[:1][["predio_id", "zona", "geometry"]].set_crs(4326, allow_override=True).reset_index(drop=True)
    raise ValueError(f"predio {pid} no encontrado")


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
    params = {"where": "1=1", "geometry": ",".join(map(str, bbox)), "geometryType": "esriGeometryEnvelope",
              "inSR": 4326, "outSR": 4326, "spatialRel": "esriSpatialRelIntersects", "outFields": "*", "f": "geojson"}
    for intento in range(5):  # el servidor de CIREN falla a ratos; con muchos predios en paralelo se reintenta
        try:
            r = requests.get(f"{CIREN}/{i}/query", timeout=60, params=params)
            r.raise_for_status()
            fs = r.json().get("features", [])
            break
        except Exception:
            if intento == 4:
                raise
            time.sleep(2 ** intento)
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


def argumentos():
    ap = argparse.ArgumentParser()
    ap.add_argument("--predios", default="5304670", help="mslink CIREN separados por coma; por defecto 88-31 (demo)")
    ap.add_argument("--senal-m3", type=int, metavar="N",
                    help="en vez de --predios: los N predios con más z_verdor_mediana entre los de senal_riego=True (M3)")
    ap.add_argument("--inicio", default="2025-12-01", help="inicio del periodo de escenas (temporada seca 2025-26)")
    ap.add_argument("--fin", default="2026-03-31")
    ap.add_argument("--nubes-max", type=float, default=30)
    ap.add_argument("--max-escenas", type=int, default=8)
    ap.add_argument("--z-umbral", type=float, default=1.0)
    ap.add_argument("--max-poi", type=int, default=8)
    ap.add_argument("--elegibles", action="store_true", help="todos los predios elegibles (predio.parquet), ordenados por predio_id")
    ap.add_argument("--limit", type=int, help="solo los primeros N predios de la lista (prueba)")
    ap.add_argument("--tarea", type=int, default=int(os.environ.get("CLOUD_RUN_TASK_INDEX", 0)),
                    help="índice de este trozo (por defecto CLOUD_RUN_TASK_INDEX)")
    ap.add_argument("--tareas", type=int, default=int(os.environ.get("CLOUD_RUN_TASK_COUNT", 1)),
                    help="cantidad de trozos (por defecto CLOUD_RUN_TASK_COUNT)")
    ap.add_argument("--workers", type=int, default=1, help="predios en paralelo dentro de la tarea (procesos)")
    ap.add_argument("--salida-gcs", help="gs://bucket/prefijo: deja ahí poi_NNNN.parquet, hechos y fallos de esta tarea")
    ap.add_argument("--silencio", action="store_true", help="no imprime el detalle de cada predio")
    ap.add_argument("--png", action="store_true")
    ap.add_argument("--salida", default=str(DATA / "processed/poi.parquet"))
    return ap.parse_args()


def contexto() -> dict:
    """Capas que no dependen del predio: se leen una vez."""
    ctx = {}
    d = gpd.read_parquet(DATA / "processed/derecho.parquet")
    ctx["derechos"] = d[d.geometry.notna() & d["duplicado_de"].isna() & (d["coord_estado"] != "fuera_de_region")].to_crs(CRS_M)
    c = gpd.read_parquet(DATA / "processed/cauce.parquet")
    ctx["cauces"] = c[c["nombre"].notna() & (c["tipo"] != "Línea de Costa")].to_crs(CRS_M)
    f = DATA / "processed/senal_riego.parquet"
    ctx["senal"] = (pd.read_parquet(f).sort_values("temporada").drop_duplicates("predio_id", keep="last")
                    .set_index("predio_id") if f.exists() else pd.DataFrame())
    return ctx


def procesa(a, ctx):
    pred = cargar_predio(a.predio_id)
    zona = pred.zona.iloc[0]
    pm = pred.to_crs(CRS_M)
    area = pm.geometry.iloc[0]
    amplio = gpd.GeoDataFrame(pred[["predio_id", "zona"]], geometry=[area.buffer(ANILLO[1])], crs=CRS_M).to_crs(4326)
    bbox = tuple(amplio.total_bounds)
    if not a.silencio:
        print(f"predio {a.predio_id} ({zona}), {area.area/1e4:.2f} ha", flush=True)

    its = escenas(bbox, a.inicio, a.fin, a.nubes_max, a.max_escenas)
    if not its:
        raise SinEscenas("sin escenas limpias en el periodo")
    if not a.silencio:
        print(f"{len(its)} escenas: {[i.datetime.date().isoformat() for i in its]}", flush=True)
    # Cerca del borde de un tile llegan escenas vecinas que no cubren el predio (Tile.vacio, sin `bounds`): se descartan,
    # y el tile de referencia es el de la primera escena que sí lo cubre. Un predio en dos tiles usa solo el primero.
    cubren = [(it, t) for it, t in ((it, s2.Tile(it, amplio)) for it in its) if not t.vacio]
    if not cubren:
        raise SinEscenas("ninguna escena cubre el predio")
    tile = cubren[0][1]
    pila = {"ndvi": [], "ndwi": [], "ndmi": []}
    validas, fechas = [], []
    for it, t in cubren:
        if t.bounds != tile.bounds:  # otro tile: se salta
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
    sm3 = ctx["senal"].loc[a.predio_id] if a.predio_id in ctx["senal"].index else None
    ctx_m3 = ({"senal_riego_m3": bool(sm3["senal_riego"]), "frac_senal_m3": float(sm3["frac_senal"])} if sm3 is not None
              else {"senal_riego_m3": None, "frac_senal_m3": np.nan})

    def agrega(tipo, geom_m, razon, conf, area_ha=np.nan, extra=None):
        c = gpd.GeoSeries([geom_m.centroid], crs=CRS_M).to_crs(4326).iloc[0]
        e, p = muestrea(zdem, pend, trd, c.x, c.y)
        filas.append({"predio_id": a.predio_id, "zona": zona, "tipo": tipo, "lon": c.x, "lat": c.y, "area_ha": area_ha,
                      "razon": razon, "fecha_imagen": max(fechas), "n_escenas": len(fechas), "confianza": round(conf, 2),
                      "elev_m": e, "pend_pct": p, **ctx_m3, **(extra or {})})

    for geom, npx, m in componentes(regado, tr, 10)[:3]:
        ha = npx * RES * RES / 1e4
        medz = float(np.nanmean(np.minimum(zv[m], zh[m])))
        agrega("zona_riego", geom, f"NDVI y NDMI sobre el entorno (z={medz:.1f}) en {len(fechas)} escenas del periodo seco",
               min(0.9, 0.3 + 0.15 * medz) * min(1, len(fechas) / 4), ha)
    for geom, npx, m in componentes(agua, tr, 4)[:2]:
        ha = npx * RES * RES / 1e4
        agrega("posible_tranque", geom, f"agua (NDWI) en {int(np.median(agua_n[m]))} de {len(fechas)} escenas", 0.5, ha)

    for tipo, i, rad, col in (("bocatoma", 0, 500, "nom_can"), ("canal", 1, 200, "nom_can")):
        g = capa_ciren(i, bbox)  # si falla tras los reintentos, el predio queda en fallos (no se omite en silencio)
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

    # captaciones de derechos registrados (D4) dentro o a menos de POZO_RADIO m del predio
    dd = ctx["derechos"]
    dd = dd[dd.distance(area) <= POZO_RADIO]
    dd = dd.assign(d=dd.distance(area)).sort_values("d").head(2)
    for _, r in dd.iterrows():
        cau = f"{r['caudal_ls']:.1f} l/s" if pd.notna(r.get("caudal_ls")) else "caudal sin dato"
        agrega("pozo_derecho", r.geometry, f"captación del derecho {r['expediente']} ({r.get('fuente') or 'fuente sin dato'}, {cau}), "
                                          f"a {r.d:.0f} m del predio; coordenada {r['coord_estado']}",
               0.7 if r["coord_estado"] == "ok" else 0.4)

    # cauce con nombre más cercano: posible bocatoma sin registro
    cc = ctx["cauces"]
    cc = cc[cc.distance(area) <= CAUCE_RADIO]
    if len(cc):
        r = cc.assign(d=cc.distance(area)).sort_values("d").iloc[0]
        agrega("cauce", nearest_points(r.geometry, area)[0], f"{r['tipo']} '{r['nombre']}' a {r.d:.0f} m del predio: revisar si hay bocatoma o bombeo",
               0.3)

    poi = pd.DataFrame(filas)
    if poi.empty:
        if not a.silencio:
            print("sin POI: el predio no muestra señal; la ruta irá solo al acceso")
    else:
        poi = poi.assign(orden=poi.tipo.map({"captacion": 0, "pozo_derecho": 1, "zona_riego": 2, "posible_tranque": 3, "bocatoma": 4, "cauce": 5, "canal": 6})
                         ).sort_values(["orden", "confianza"], ascending=[True, False]).head(a.max_poi).drop(columns="orden")
        poi.insert(0, "poi_id", [f"{a.predio_id}-{i+1}" for i in range(len(poi))])
        poi = gpd.GeoDataFrame(poi, geometry=gpd.points_from_xy(poi.lon, poi.lat), crs=4326)
        if not a.silencio:
            print(poi[["poi_id", "tipo", "area_ha", "elev_m", "pend_pct", "confianza", "razon"]].to_string(index=False))

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
                for tipo, c in (("captacion", "black"), ("pozo_derecho", "gray"), ("zona_riego", "red"), ("posible_tranque", "blue"), ("bocatoma", "magenta"), ("cauce", "cyan"), ("canal", "orange")):
                    s = pm_pts[(pm_pts.tipo == tipo) & (pm_pts.predio_id == a.predio_id)]
                    axx.scatter(s.geometry.x, s.geometry.y, c=c, s=40, label=tipo, edgecolor="w")
            axx.set_title(f"{t} {min(fechas)}..{max(fechas)}")
        ax[0].legend(loc="lower left", fontsize=8)
        sp = RAIZ / f"data/raw/poi_{a.predio_id}.png"
        fig.savefig(sp, dpi=110, bbox_inches="tight")
        print("mapa de control:", sp)
    return poi


_A = None
_CTX = None


def _inicia(a):
    global _A, _CTX
    _A, _CTX = a, contexto()


def _trabaja(pid: int):
    """Un predio en un proceso hijo; devuelve (pid, POI o None, error o None)."""
    a = argparse.Namespace(**vars(_A))
    a.predio_id = int(pid)
    try:
        return pid, procesa(a, _CTX), None
    except SinEscenas:
        return pid, None, None
    except Exception as e:  # el predio queda en fallos; el resto sigue
        return pid, None, f"{type(e).__name__}: {e}"


class SalidaGCS:
    """Resultados de una tarea en GCS: poi_NNNN.parquet, hechos_NNNN.json (incluye predios sin POI) y fallos_NNNN.json."""

    def __init__(self, destino: str, tarea: int):
        from google.cloud import storage

        bucket, _, prefijo = destino.removeprefix("gs://").partition("/")
        self.bucket = storage.Client().bucket(bucket)
        self.base = prefijo.strip("/")
        self.n = f"{tarea:04d}"

    def blob(self, nombre):
        return self.bucket.blob(f"{self.base}/{nombre}_{self.n}")

    def retoma(self):
        """(POI previos, predios hechos) de un intento anterior de esta tarea."""
        b = self.blob("hechos")
        if not b.exists():
            return pd.DataFrame(), set()
        hechos = set(json.loads(b.download_as_text()))
        poi = pd.DataFrame()
        bp = self.blob("poi")
        if bp.exists():
            bp.download_to_filename(f"/tmp/poi_prev_{self.n}.parquet")
            poi = gpd.read_parquet(f"/tmp/poi_prev_{self.n}.parquet")
        return poi, hechos

    def guarda(self, poi, hechos, fallos):
        if len(poi):
            ruta = f"/tmp/poi_{self.n}.parquet"
            gpd.GeoDataFrame(poi, geometry="geometry", crs=4326).to_parquet(ruta, index=False)
            self.blob("poi").upload_from_filename(ruta + "")
        self.blob("hechos").upload_from_string(json.dumps(sorted(hechos)))
        self.blob("fallos").upload_from_string(json.dumps(fallos))


def main():
    a = argumentos()
    ctx = contexto()
    if a.elegibles:
        pr = gpd.read_parquet(DATA / "processed/predio.parquet")
        if "elegible" not in pr:
            pr["elegible"] = pr["rol_valido"] & (pr["area_ha"] >= 1)
        ids = sorted(pr.loc[pr["elegible"], "predio_id"].astype(int))
    elif a.senal_m3:
        s = ctx["senal"]
        ids = s[s["senal_riego"]].sort_values("z_verdor_mediana", ascending=False).head(a.senal_m3).index.tolist()
    else:
        ids = [int(x) for x in a.predios.split(",")]
    if a.limit:
        ids = ids[: a.limit]
    ids = [x for k, x in enumerate(ids) if k % a.tareas == a.tarea]  # reparto intercalado: tareas parejas
    print(f"tarea {a.tarea + 1}/{a.tareas}: {len(ids)} predios, {a.workers} en paralelo", flush=True)

    gcs = SalidaGCS(a.salida_gcs, a.tarea) if a.salida_gcs else None
    poi_total, hechos = (gcs.retoma() if gcs else (pd.DataFrame(), set()))
    pendientes = [x for x in ids if x not in hechos]
    if hechos:
        print(f"retomando: {len(hechos)} hechos, {len(pendientes)} pendientes", flush=True)
    partes, fallos, t0 = [poi_total] if len(poi_total) else [], {}, time.time()

    def checkpoint():
        if gcs:
            gcs.guarda(pd.concat(partes, ignore_index=True) if partes else pd.DataFrame(), hechos, fallos)

    ctx_mp = multiprocessing.get_context("spawn")
    contador = [0]

    def corre(lista, workers):
        """Procesa `lista` en un pool; si un proceso muere (p. ej. sin memoria), devuelve los predios que no terminaron."""
        en_vuelo = set(lista)
        try:
            with cf.ProcessPoolExecutor(max_workers=workers, mp_context=ctx_mp, initializer=_inicia, initargs=(a,)) as ex:
                futs = {ex.submit(_trabaja, pid): pid for pid in lista}
                for f in cf.as_completed(futs):
                    pid, poi, err = f.result()
                    en_vuelo.discard(pid)
                    if err:
                        fallos[str(pid)] = err
                        print(f"predio {pid}: {err}", file=sys.stderr, flush=True)
                    else:
                        hechos.add(pid)
                        if poi is not None and len(poi):
                            partes.append(poi)
                    contador[0] += 1
                    if contador[0] % 10 == 0:
                        checkpoint()
                        print(f"  {contador[0]}/{len(pendientes)} predios, {(time.time() - t0) / 60:.1f} min", flush=True)
        except cf.process.BrokenProcessPool:
            checkpoint()
            print(f"un proceso murió (¿memoria?): quedan {len(en_vuelo)} predios sin terminar", file=sys.stderr, flush=True)
            return sorted(en_vuelo)
        return []

    resto = corre(pendientes, a.workers)
    # Tras una caída, los que quedaron se reintentan de a uno: así un predio que agota la memoria no tumba a los demás.
    while resto:
        pid, resto = resto[0], resto[1:]
        if corre([pid], 1):
            fallos[str(pid)] = "proceso terminado de golpe (probablemente sin memoria)"
            print(f"predio {pid}: sin memoria incluso solo; queda en fallos", file=sys.stderr, flush=True)
    checkpoint()

    poi = pd.concat(partes, ignore_index=True) if partes else pd.DataFrame()
    if not gcs and len(poi):  # local: se acumula en poi.parquet, reemplazando los predios procesados
        sal = Path(a.salida)
        if sal.exists():
            prev = gpd.read_parquet(sal)
            poi = pd.concat([prev[~prev.predio_id.isin(poi.predio_id.unique())], poi], ignore_index=True)
        sal.parent.mkdir(parents=True, exist_ok=True)
        gpd.GeoDataFrame(poi, geometry="geometry", crs=4326).to_parquet(sal, index=False)
    print(f"\n{len(hechos & set(ids))} de {len(ids)} predios procesados, {len(fallos)} con fallo, "
          f"{len(poi)} POI, {(time.time() - t0) / 60:.1f} min" + (f"; fallaron {list(fallos)[:20]}" if fallos else ""))
    # Los predios con fallo quedan en fallos_NNNN.json; salir con 0 evita que Cloud Run repita la tarea entera por ellos.
    return 0


if __name__ == "__main__":
    sys.exit(main())
