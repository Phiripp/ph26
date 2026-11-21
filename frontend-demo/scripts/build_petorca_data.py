#!/usr/bin/env python3
"""Caudal v2 - datos de la demo del valle de Petorca.

Genera en ../data/petorca/:
  predios.geojson  poligonos reales de OSM (Overpass) + scores (m3_derecho ilustrativo)
  clima.json       clima diario real Open-Meteo (ERA5) 2022-2024, agregados mensuales, ventanas secas
  series.json      NDVI/NDMI mensual por predio (Sentinel-2 L2A real via Earth Search, o ilustrativo)
  ruta.json        ruta de inspeccion (OR-Tools + OSRM, con fallbacks)
  ruta.gpx         la misma ruta en GPX
  README.md        metodo (corto, en espanol)

Uso:
  python3 scripts/build_petorca_data.py            # intenta Sentinel-2 real (lento, ~10-20 min la 1a vez; cachea)
  python3 scripts/build_petorca_data.py --no-s2    # series ilustrativas (rapido)

Dependencias: shapely, numpy; opcionales: pystac-client + rasterio (Sentinel-2), ortools (TSP).
Las respuestas de servicios externos se cachean en scripts/.cache/petorca/ para no repetir llamadas.
"""
import datetime as dt
import hashlib
import json
import math
import os
import random
import sys
import time
import urllib.parse
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED

import numpy as np
from shapely.geometry import Polygon, MultiPolygon, box, mapping, shape, Point
from shapely.ops import unary_union
from shapely.validation import make_valid

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.normpath(os.path.join(HERE, "..", "data", "petorca"))
CACHE = os.path.join(HERE, ".cache", "petorca")
UA = "caudal-hackathon-mockup"

BBOX = dict(west=-71.02, south=-32.31, east=-70.83, north=-32.19)
CLIMA_PT = (-70.93, -32.25)  # lon, lat
PLAZA = dict(nombre="Plaza de Petorca", lon=-70.9330, lat=-32.2525, hora="08:30")
START, END = "2022-01-01", "2024-12-31"
MONTHS = [f"{y}-{m:02d}" for y in (2022, 2023, 2024) for m in range(1, 13)]
SCORE_YEAR = "2024"
N_MIN, N_MAX = 25, 34
MIN_HA = 1.5
LLUVIA_EFECTIVA_MM = 1.0
VENTANA_MIN_DIAS = 10
N_RUTA = 8
PERMANENCIA_MIN = 20
S2_RES = 40          # m; se leen overviews de los COG para que la descarga sea liviana
S2_BUDGET_S = 1800   # tope de tiempo para Sentinel-2
S2_TILE = "19HCE"    # cubre 100% del bbox

# Kc(NDVI) lineal simple (documentado en README)
KC_A, KC_B, KC_MIN, KC_MAX = 1.25, 0.10, 0.15, 1.15
PEF_FACTOR = 0.8
CONF_W = {"alta": 1.0, "media": 0.85, "baja": 0.65}
CONF_RANGO = {"alta": 0.20, "media": 0.27, "baja": 0.35}
BANDAS = [("alta", 0.60), ("media", 0.30), ("baja", 0.10), ("sin_alerta", -1)]

os.makedirs(OUT, exist_ok=True)
os.makedirs(CACHE, exist_ok=True)
LAT0 = math.radians((BBOX["south"] + BBOX["north"]) / 2)
M_PER_DEG_LAT = 111_320.0
M_PER_DEG_LON = 111_320.0 * math.cos(LAT0)


def log(*a):
    print(*a, flush=True)


# ---------------------------------------------------------------- http + cache
def http(url, data=None, timeout=90):
    try:
        req = urllib.request.Request(url, data=data, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.URLError as ex:
        # el Python de macOS (LibreSSL 2.8) falla el handshake TLS con algunos servidores -> curl
        if "SSL" not in str(ex):
            raise
        import subprocess
        cmd = ["curl", "-sS", "--fail", "-A", UA, "--max-time", str(timeout), url]
        if data is not None:
            cmd += ["--data-binary", "@-"]
        return subprocess.run(cmd, input=data, capture_output=True, check=True).stdout


def cached_json(name, fetcher):
    p = os.path.join(CACHE, name)
    if os.path.exists(p):
        with open(p) as f:
            return json.load(f)
    d = fetcher()
    with open(p, "w") as f:
        json.dump(d, f)
    return d


def area_ha(geom):
    """Area aprox. en ha con proyeccion equirectangular local (error <1% a esta escala)."""
    from shapely.affinity import scale
    return scale(geom, M_PER_DEG_LON, M_PER_DEG_LAT, origin=(0, 0)).area / 1e4


def hash01(s):
    return int(hashlib.md5(s.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF


def haversine_km(a, b):
    lon1, lat1, lon2, lat2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(h))


# ---------------------------------------------------------------- 1. predios (OSM)
def fetch_osm():
    b = f"{BBOX['south']},{BBOX['west']},{BBOX['north']},{BBOX['east']}"
    q = (f'[out:json][timeout:60];('
         f'way["landuse"~"^(orchard|farmland)$"]({b});'
         f'relation["landuse"~"^(orchard|farmland)$"]({b});'
         f'way["crop"]({b}););out geom tags;')
    raw = http("https://overpass-api.de/api/interpreter", data=urllib.parse.urlencode({"data": q}).encode())
    return json.loads(raw)


def osm_polygons(osm):
    polys = []
    for el in osm.get("elements", []):
        tags = el.get("tags", {})
        try:
            if el["type"] == "way":
                g = el.get("geometry") or []
                if len(g) < 4:
                    continue
                geom = Polygon([(p["lon"], p["lat"]) for p in g])
            elif el["type"] == "relation":
                outers = [m for m in el.get("members", []) if m.get("role") == "outer" and m.get("geometry")]
                rings = [Polygon([(p["lon"], p["lat"]) for p in m["geometry"]]) for m in outers if len(m["geometry"]) >= 4]
                if not rings:
                    continue
                geom = unary_union(rings)
            else:
                continue
        except Exception:
            continue
        geom = make_valid(geom)
        polys.append(dict(osm_id=f"{el['type']}/{el['id']}", tags=tags, geom=geom))
    return polys


def largest_polygon(g):
    if isinstance(g, Polygon):
        return g
    parts = [p for p in getattr(g, "geoms", []) if isinstance(p, Polygon)]
    return max(parts, key=lambda p: p.area) if parts else None


def build_predios():
    osm = cached_json("overpass.json", fetch_osm)
    bb = box(BBOX["west"], BBOX["south"], BBOX["east"], BBOX["north"])
    cands = []
    for p in osm_polygons(osm):
        g = largest_polygon(make_valid(p["geom"].intersection(bb)))
        if g is None or g.is_empty:
            continue
        g = g.simplify(0.00004, preserve_topology=True)  # ~4 m
        g = largest_polygon(make_valid(g))
        if g is None or not g.is_valid:
            continue
        a = area_ha(g)
        if a >= MIN_HA:
            cands.append(dict(p, geom=g, area_ha=a))
    cands.sort(key=lambda c: -c["area_ha"])
    chosen = []
    for c in cands:
        if any(c["geom"].intersection(o["geom"]).area > 0.3 * c["geom"].area for o in chosen):
            continue
        chosen.append(c)
        if len(chosen) >= N_MAX:
            break
    for c in chosen:
        c["fuente_geom"] = "OSM"
    # complemento ilustrativo si OSM trae pocos
    if len(chosen) < N_MIN:
        log(f"  OSM trajo {len(chosen)} poligonos; se complementan rectangulos ilustrativos")
        rnd = random.Random(7)
        valley = [(-70.95, -32.262), (-70.92, -32.256), (-70.90, -32.248), (-70.87, -32.232), (-70.85, -32.222)]
        while len(chosen) < N_MIN:
            lon, lat = rnd.choice(valley)
            lon += rnd.uniform(-0.012, 0.012); lat += rnd.uniform(-0.004, 0.004)
            w, h = rnd.uniform(0.002, 0.005), rnd.uniform(0.0015, 0.003)
            g = box(lon - w / 2, lat - h / 2, lon + w / 2, lat + h / 2)
            if any(g.intersects(o["geom"]) for o in chosen):
                continue
            chosen.append(dict(osm_id=None, tags={}, geom=g, area_ha=area_ha(g), fuente_geom="ilustrativo"))
    # IDs ordenados oeste->este (no revelan el ranking)
    chosen.sort(key=lambda c: c["geom"].centroid.x)
    for i, c in enumerate(chosen, 1):
        c["id"] = f"P-{i:03d}"
        t = c["tags"]
        if t.get("trees") == "avocado_trees" or "avocado" in (t.get("crop", "") + t.get("trees", "")):
            c["cultivo"], c["cultivo_fuente"] = "palto", "OSM"
        elif "citrus" in (t.get("crop", "") + t.get("trees", "")) or "orange" in t.get("trees", ""):
            c["cultivo"], c["cultivo_fuente"] = "cítrico", "OSM"
        elif t.get("landuse") == "farmland":
            c["cultivo"], c["cultivo_fuente"] = "otro", "supuesto"
        else:
            h = hash01(c["id"] + "cultivo")
            c["cultivo"] = "palto" if h < 0.78 else ("cítrico" if h < 0.92 else "otro")
            c["cultivo_fuente"] = "supuesto"
    return chosen


# ---------------------------------------------------------------- 2. clima (Open-Meteo)
def fetch_clima():
    q = urllib.parse.urlencode(dict(
        latitude=CLIMA_PT[1], longitude=CLIMA_PT[0], start_date=START, end_date=END,
        daily="precipitation_sum,et0_fao_evapotranspiration,temperature_2m_max", timezone="America/Santiago"))
    return json.loads(http("https://archive-api.open-meteo.com/v1/archive?" + q))


def build_clima():
    om = cached_json("open_meteo.json", fetch_clima)
    d = om["daily"]
    t, p, e, tx = d["time"], d["precipitation_sum"], d["et0_fao_evapotranspiration"], d["temperature_2m_max"]
    p = [x if x is not None else 0.0 for x in p]
    e = [x if x is not None else 0.0 for x in e]
    seco = [x < LLUVIA_EFECTIVA_MM for x in p]
    # ventanas secas en toda la serie
    ventanas, i = [], 0
    while i < len(t):
        if seco[i]:
            j = i
            while j + 1 < len(t) and seco[j + 1]:
                j += 1
            n = j - i + 1
            if n >= VENTANA_MIN_DIAS:
                ventanas.append(dict(inicio=t[i], fin=t[j], dias=n))
            i = j + 1
        else:
            i += 1
    mensual = []
    for m in MONTHS:
        idx = [k for k, day in enumerate(t) if day.startswith(m)]
        run = best = 0
        for k in idx:
            run = run + 1 if seco[k] else 0
            best = max(best, run)
        mensual.append(dict(mes=m, lluvia_mm=round(sum(p[k] for k in idx), 1),
                            et0_mm=round(sum(e[k] for k in idx), 1),
                            tmax_media_c=round(sum(tx[k] for k in idx if tx[k] is not None) / max(1, len(idx)), 1),
                            dias_sin_lluvia_max=best))
    anual = {}
    for y in ("2022", "2023", "2024"):
        ms = [x for x in mensual if x["mes"].startswith(y)]
        anual[y] = dict(lluvia_mm=round(sum(x["lluvia_mm"] for x in ms), 1), et0_mm=round(sum(x["et0_mm"] for x in ms), 1))
    return dict(
        fuente="Open-Meteo (ERA5)",
        fuente_url="https://archive-api.open-meteo.com/v1/archive",
        illustrative=False,
        punto=dict(lon=CLIMA_PT[0], lat=CLIMA_PT[1], nombre="Petorca", elevacion_modelo_m=om.get("elevation")),
        periodo=dict(inicio=START, fin=END),
        nota=("Reanalisis ERA5 en grilla (~9-25 km), no una estacion. Pendiente verificar contra estaciones "
              "DMC / DGA / INIA (agrometeorologia.cl) del valle de Petorca."),
        criterio_ventana_seca=f">= {VENTANA_MIN_DIAS} dias consecutivos con precipitacion < {LLUVIA_EFECTIVA_MM} mm (lluvia efectiva)",
        unidades=dict(precipitation_sum="mm", et0_fao_evapotranspiration="mm", temperature_2m_max="°C"),
        diario=dict(fecha=t, precipitation_sum=p, et0_fao_evapotranspiration=e, temperature_2m_max=tx),
        mensual=mensual,
        anual=anual,
        ventanas_secas=ventanas,
    )


# ---------------------------------------------------------------- 3. Sentinel-2 (real, best effort)
def s2_series(predios):
    """Devuelve (series_por_predio, referencia, meta) o None si no se puede."""
    try:
        os.environ.update(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", AWS_NO_SIGN_REQUEST="YES",
                          GDAL_HTTP_MULTIRANGE="YES", GDAL_HTTP_MERGE_CONSECUTIVE_RANGES="YES",
                          CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif", GDAL_HTTP_TIMEOUT="90",
                          GDAL_HTTP_MAX_RETRY="3", GDAL_HTTP_RETRY_DELAY="2", VSI_CACHE="TRUE",
                          GDAL_HTTP_USERAGENT=UA)
        import rasterio
        from rasterio.enums import Resampling
        from rasterio.features import rasterize
        from rasterio.warp import transform_bounds, transform_geom
        from rasterio.windows import Window
        from affine import Affine
        from pystac_client import Client
    except Exception as ex:
        log("  Sentinel-2: dependencias no disponibles:", ex)
        return None

    def stac_items():
        c = Client.open("https://earth-search.aws.element84.com/v1", headers={"User-Agent": UA})
        s = c.search(collections=["sentinel-2-l2a"],
                     bbox=[BBOX["west"], BBOX["south"], BBOX["east"], BBOX["north"]],
                     datetime=f"{START}/{END}", query={"eo:cloud_cover": {"lt": 80}}, limit=200)
        out = []
        for it in s.items():
            if S2_TILE not in it.id:
                continue
            assets = {}
            for k in ("red", "nir", "nir08", "swir16", "scl"):
                a = it.assets[k]
                rb = (a.extra_fields.get("raster:bands") or [{}])[0]
                assets[k] = dict(href=a.href, scale=rb.get("scale", 1e-4), offset=rb.get("offset", 0.0))
            # baseline >= 04.00 suma +1000 al DN; Earth Search lo re-armoniza en algunas escenas
            # (earthsearch:boa_offset_applied=True) aunque raster:bands siga diciendo offset=-0.1
            boa = bool(it.properties.get("earthsearch:boa_offset_applied", False))
            out.append(dict(id=it.id, fecha=it.properties["datetime"][:10], boa_offset_applied=boa,
                            cloud=it.properties.get("eo:cloud_cover", 100), assets=assets))
        return out

    try:
        items = cached_json("stac_items.json", stac_items)
    except Exception as ex:
        log("  Sentinel-2: STAC no disponible:", ex)
        return None
    best = {}
    for it in items:
        m = it["fecha"][:7]
        if m in MONTHS and (m not in best or it["cloud"] < best[m]["cloud"]):
            best[m] = it
    log(f"  Sentinel-2: {len(items)} escenas {S2_TILE}, {len(best)} meses con escena (1 por mes, la menos nubosa)")

    sdir = os.path.join(CACHE, "s2")
    os.makedirs(sdir, exist_ok=True)

    def read_band(href, ub, res_native, resampling):
        with rasterio.open(href) as ds:
            T = ds.transform
            col0 = round((ub[0] - T.c) / T.a); row0 = round((ub[3] - T.f) / T.e)
            ncol = round((ub[2] - ub[0]) / T.a); nrow = round((ub[3] - ub[1]) / -T.e)
            f = int(S2_RES / res_native)
            arr = ds.read(1, window=Window(col0, row0, ncol, nrow), out_shape=(nrow // f, ncol // f),
                          resampling=resampling, boundless=False)
            return arr, ds.crs.to_string()

    def snapped_bounds():
        # bbox en UTM 19S ajustado a multiplos de 40 m respecto del origen de la tesela (comun a 10 y 20 m)
        with rasterio.open(next(iter(best.values()))["assets"]["scl"]["href"]) as ds:
            T, crs = ds.transform, ds.crs.to_string()
        x0, y0, x1, y1 = transform_bounds("EPSG:4326", crs, BBOX["west"], BBOX["south"], BBOX["east"], BBOX["north"])
        x0 = T.c + math.floor((x0 - T.c) / S2_RES) * S2_RES
        x1 = T.c + math.ceil((x1 - T.c) / S2_RES) * S2_RES
        y1 = T.f - math.floor((T.f - y1) / S2_RES) * S2_RES
        y0 = T.f - math.ceil((T.f - y0) / S2_RES) * S2_RES
        return (x0, y0, x1, y1), crs

    try:
        gp = os.path.join(sdir, "grid.json")
        if os.path.exists(gp):
            g = json.load(open(gp)); ub, crs = tuple(g["ub"]), g["crs"]
        else:
            ub, crs = snapped_bounds()
            json.dump(dict(ub=ub, crs=crs), open(gp, "w"))
    except Exception as ex:
        log("  Sentinel-2: no se pudo abrir COG:", ex)
        return None

    def scene(m):
        p = os.path.join(sdir, f"{m}.npz")
        it = best[m]
        if os.path.exists(p) and str(np.load(p)["scene"]) == it["id"]:
            return m, True
        bands = [("red", 10, Resampling.average), ("nir", 10, Resampling.average),
                 ("nir08", 20, Resampling.average), ("swir16", 20, Resampling.average),
                 ("scl", 20, Resampling.nearest)]
        with ThreadPoolExecutor(5) as ex:
            res = list(ex.map(lambda b: read_band(it["assets"][b[0]]["href"], ub, b[1], b[2]), bands))
        arrs = {b[0]: r[0] for b, r in zip(bands, res)}
        sc = {k: (it["assets"][k]["scale"], it["assets"][k]["offset"]) for k in ("red", "nir", "nir08", "swir16")}
        np.savez_compressed(p, scales=json.dumps(sc), scene=it["id"], fecha=it["fecha"], **arrs)
        return m, False

    t0 = time.time()
    todo = [m for m in MONTHS if m in best]
    done = set()
    ex = ThreadPoolExecutor(4)
    futs = {ex.submit(scene, m): m for m in todo}
    pending = set(futs)
    while pending and time.time() - t0 < S2_BUDGET_S:
        fin, pending = wait(pending, timeout=15, return_when=FIRST_COMPLETED)
        for f in fin:
            m = futs[f]
            try:
                f.result(); done.add(m)
                log(f"    S2 {m} ok ({len(done)}/{len(todo)}, {time.time() - t0:.0f}s)")
            except Exception as e2:
                log(f"    S2 {m} fallo: {e2}")
    ex.shutdown(wait=False, cancel_futures=True)
    if len(done) < 0.6 * len(MONTHS):
        log(f"  Sentinel-2: solo {len(done)} meses en el tiempo disponible -> se usan series ilustrativas")
        return None

    # rasterizar predios en la grilla 40 m
    W = int(round((ub[2] - ub[0]) / S2_RES)); H = int(round((ub[3] - ub[1]) / S2_RES))
    tr = Affine(S2_RES, 0, ub[0], 0, -S2_RES, ub[3])
    shapes = [(transform_geom("EPSG:4326", crs, mapping(p["geom"])), i + 1) for i, p in enumerate(predios)]
    labels = rasterize(shapes, out_shape=(H, W), transform=tr, fill=0, all_touched=False, dtype="int32")
    # buffer de 120 m alrededor de predios: excluido de la referencia
    from shapely.geometry import shape as shp
    buf = [(shp(s).buffer(120), 1) for s, _ in shapes]
    near = rasterize(buf, out_shape=(H, W), transform=tr, fill=0, dtype="uint8")
    npx = {p["id"]: int((labels == i + 1).sum()) for i, p in enumerate(predios)}

    series = {p["id"]: [] for p in predios}
    ref = []
    for m in MONTHS:
        f = os.path.join(sdir, f"{m}.npz")
        if m not in done or not os.path.exists(f):
            for p in predios:
                series[p["id"]].append(dict(fecha=m, ndvi=None, ndmi=None, nubosidad_pct=None))
            ref.append(dict(fecha=m, ndvi=None, ndmi=None, ndvi_mad=None, ndmi_mad=None))
            continue
        z = np.load(f)
        sc = json.loads(str(z["scales"]))
        if best[m].get("boa_offset_applied"):
            sc = {k: (v[0], 0.0) for k, v in sc.items()}
        refl = {k: z[k].astype("float32") * sc[k][0] + sc[k][1] for k in ("red", "nir", "nir08", "swir16")}
        scl = z["scl"]
        hh, ww = scl.shape
        lab = labels[:hh, :ww]; nr = near[:hh, :ww]
        nodata = (z["red"] == 0) | (scl == 0)
        cloud = np.isin(scl, [3, 8, 9, 10])
        valid = np.isin(scl, [4, 5, 6, 7, 11]) & ~nodata
        with np.errstate(divide="ignore", invalid="ignore"):
            ndvi = (refl["nir"] - refl["red"]) / (refl["nir"] + refl["red"])
            ndmi = (refl["nir08"] - refl["swir16"]) / (refl["nir08"] + refl["swir16"])
        valid &= np.isfinite(ndvi) & np.isfinite(ndmi)
        # referencia de secano: pixeles validos de vegetacion/suelo lejos de predios OSM y con NDVI bajo-medio
        rmask = valid & (nr == 0) & np.isin(scl, [4, 5]) & (ndvi > 0.05) & (ndvi < 0.5)
        if rmask.sum() > 200:
            rv, rm = ndvi[rmask], ndmi[rmask]
            ref.append(dict(fecha=m, ndvi=round(float(np.median(rv)), 3), ndmi=round(float(np.median(rm)), 3),
                            ndvi_mad=round(float(1.4826 * np.median(np.abs(rv - np.median(rv)))), 4),
                            ndmi_mad=round(float(1.4826 * np.median(np.abs(rm - np.median(rm)))), 4),
                            n_px=int(rmask.sum())))
        else:
            ref.append(dict(fecha=m, ndvi=None, ndmi=None, ndvi_mad=None, ndmi_mad=None, n_px=int(rmask.sum())))
        for i, p in enumerate(predios):
            inside = lab == i + 1
            n = int(inside.sum())
            cl = int((inside & cloud).sum())
            v = inside & valid
            nv = int(v.sum())
            rec = dict(fecha=m, ndvi=None, ndmi=None, nubosidad_pct=round(100 * cl / n, 1) if n else None,
                       escena=str(z["scene"]), n_px_validos=nv)
            if nv >= 3:
                rec["ndvi"] = round(float(np.median(ndvi[v])), 3)
                rec["ndmi"] = round(float(np.median(ndmi[v])), 3)
            series[p["id"]].append(rec)
    meta = dict(escenas={m: best[m]["id"] for m in MONTHS if m in done}, n_px=npx,
                boa_offset_applied={m: best[m].get("boa_offset_applied") for m in MONTHS if m in done},
                meses_con_escena=len(done), tiempo_s=round(time.time() - t0))
    return series, ref, meta


# ---------------------------------------------------------------- 3b. series ilustrativas (fallback)
def illustrative_series(predios, clima):
    rnd = random.Random(26)
    lluvia = {x["mes"]: x["lluvia_mm"] for x in clima["mensual"]}
    ref, prev = [], 0.0
    for m in MONTHS:
        mo = int(m[5:])
        # secano responde a la lluvia acumulada con rezago + estacionalidad invernal
        prev = 0.6 * prev + lluvia[m]
        season = 0.04 * math.cos((mo - 8) / 12 * 2 * math.pi)
        nd = min(0.38, 0.20 + 0.0012 * prev + season + rnd.uniform(-0.01, 0.01))
        ref.append(dict(fecha=m, ndvi=round(nd, 3), ndmi=round(nd - 0.28, 3), ndvi_mad=0.05, ndmi_mad=0.05))
    series = {}
    for p in predios:
        h = hash01(p["id"] + "verde")
        base = 0.48 + 0.25 * h if p["cultivo"] != "otro" else 0.35 + 0.2 * h
        s = []
        for k, m in enumerate(MONTHS):
            mo = int(m[5:])
            nub = max(0.0, rnd.gauss(35 if mo in (5, 6, 7, 8) else 8, 12))
            nd = base + 0.03 * math.sin((mo - 1) / 12 * 2 * math.pi) + rnd.uniform(-0.025, 0.025)
            ok = nub < 70
            s.append(dict(fecha=m, ndvi=round(nd, 3) if ok else None, ndmi=round(nd - 0.35, 3) if ok else None,
                          nubosidad_pct=round(min(100, nub), 1)))
        series[p["id"]] = s
    npx = {p["id"]: int(p["area_ha"] * 1e4 / S2_RES ** 2) for p in predios}
    return series, ref, dict(n_px=npx)


def add_z(series, ref):
    rf = {r["fecha"]: r for r in ref}
    for s in series.values():
        for r in s:
            b = rf.get(r["fecha"], {})
            r["z_verdor"] = (round((r["ndvi"] - b["ndvi"]) / max(b["ndvi_mad"], 0.02), 2)
                             if r.get("ndvi") is not None and b.get("ndvi") is not None else None)
            r["z_humedad"] = (round((r["ndmi"] - b["ndmi"]) / max(b["ndmi_mad"], 0.02), 2)
                              if r.get("ndmi") is not None and b.get("ndmi") is not None else None)


# ---------------------------------------------------------------- 4. scores
def kc(ndvi):
    return min(KC_MAX, max(KC_MIN, KC_A * ndvi + KC_B))


def build_scores(predios, series, ref, clima, meta, real_s2):
    mens = {x["mes"]: x for x in clima["mensual"]}
    secos = [m for m in MONTHS if mens[m]["dias_sin_lluvia_max"] >= 20]
    for p in predios:
        s = series[p["id"]]
        vals = [r["ndvi"] for r in s if r["ndvi"] is not None]
        mean_nd = sum(vals) / len(vals) if vals else 0.3
        # m3 estimado (FAO-56 simplificado) para el ano SCORE_YEAR
        v = 0.0
        for r in s:
            if not r["fecha"].startswith(SCORE_YEAR):
                continue
            nd = r["ndvi"] if r["ndvi"] is not None else mean_nd
            mm = max(0.0, kc(nd) * mens[r["fecha"]]["et0_mm"] - PEF_FACTOR * mens[r["fecha"]]["lluvia_mm"])
            v += mm * 10.0 * p["area_ha"]  # 1 mm sobre 1 ha = 10 m3
        p["m3_mid"] = v
        # confianza
        motivos = []
        npx = meta["n_px"].get(p["id"], 0)
        if npx < 15:
            motivos.append("pocos píxeles")
        yr = [r for r in s if r["fecha"].startswith(SCORE_YEAR)]
        nval = sum(1 for r in yr if r["ndvi"] is not None)
        if nval < 9:
            motivos.append("pocas escenas válidas")
        nubs = [r["nubosidad_pct"] for r in yr if r["nubosidad_pct"] is not None]
        if nubs and sum(nubs) / len(nubs) > 20:
            motivos.append("nubosidad alta")
        if p["centroid"][0] < -70.985:  # extremo poniente: valle angosto, poca superficie de cerro en el bbox
            motivos.append("sin referencia de secano cercana")
        if p["fuente_geom"] == "ilustrativo":
            motivos.append("geometría ilustrativa")
        if p["cultivo_fuente"] == "supuesto" and p["cultivo"] == "otro":
            motivos.append("cultivo no verificado")
        p["confianza_motivos"] = motivos
        p["confianza"] = "alta" if not motivos else ("media" if len(motivos) == 1 else "baja")
        zs = [r["z_verdor"] for r in s if r["fecha"] in secos and r["z_verdor"] is not None]
        hs = [r["z_humedad"] for r in s if r["fecha"] in secos and r["z_humedad"] is not None]
        p["z_verdor_seco"] = round(sum(zs) / len(zs), 2) if zs else 0.0
        p["z_humedad_seco"] = round(sum(hs) / len(hs), 2) if hs else 0.0
        p["prioridad_cruda"] = (0.6 * p["z_verdor_seco"] + 0.4 * p["z_humedad_seco"]) * CONF_W[p["confianza"]] \
            * math.log1p(p["area_ha"])

    # m3_derecho ILUSTRATIVO: se calibra segun el ranking de verdor en ventana seca para que
    # la demo muestre ~5 alta / ~8 media / resto baja-sin alerta. NO es un derecho real.
    order = sorted(predios, key=lambda p: -p["prioridad_cruda"])
    n = len(order)
    n_baja = (n - 13 + 1) // 2
    for rank, p in enumerate(order):
        w = CONF_W[p["confianza"]]
        h = hash01(p["id"] + "der")
        if rank < 5:
            t = 0.66 + (0.92 - 0.66) * (1 - rank / 5) * (0.85 + 0.15 * h)
            t = min(t, w - 0.01)
        elif rank < 13:
            t = 0.34 + 0.22 * (1 - (rank - 5) / 8) * (0.9 + 0.1 * h)
            t = min(t, w - 0.01)
        elif rank < 13 + n_baja:
            t = 0.13 + 0.14 * h
        else:
            t = None
        if t is None:
            der = p["m3_mid"] * (1.05 + 0.35 * h)
        else:
            der = p["m3_mid"] / (1 + 0.5 * t / w)
        p["m3_derecho"] = int(max(500, round(der / 500.0) * 500))
    for p in predios:
        r = CONF_RANGO[p["confianza"]]
        p["m3_estimado_min"] = int(round(p["m3_mid"] * (1 - r), -2))
        p["m3_estimado_max"] = int(round(p["m3_mid"] * (1 + r), -2))
        exceso = (p["m3_mid"] - p["m3_derecho"]) / p["m3_derecho"]
        p["exceso_rel"] = round(exceso, 3)
        p["indice"] = round(min(1.0, max(0.0, exceso) / 0.5) * CONF_W[p["confianza"]], 3)
        p["banda"] = next(b for b, th in BANDAS if p["indice"] >= th)


# ---------------------------------------------------------------- 5. ruta
def osrm(path):
    return json.loads(http("https://router.project-osrm.org/" + path, timeout=60))


def two_opt(D, order):
    best = order[:]
    improved = True
    def cost(o):
        return sum(D[o[i]][o[i + 1]] for i in range(len(o) - 1))
    while improved:
        improved = False
        for i in range(1, len(best) - 2):
            for j in range(i + 1, len(best) - 1):
                cand = best[:i] + best[i:j + 1][::-1] + best[j + 1:]
                if cost(cand) < cost(best) - 1e-9:
                    best, improved = cand, True
    return best


def build_ruta(predios):
    sel = [p for p in sorted(predios, key=lambda p: -p["indice"]) if p["banda"] in ("alta", "media")][:N_RUTA]
    pts = [(PLAZA["lon"], PLAZA["lat"])] + [tuple(p["punto_acceso"]) for p in sel]
    coords = ";".join(f"{lon:.5f},{lat:.5f}" for lon, lat in pts)
    D = Tm = None
    try:
        tb = cached_json(f"osrm_table_{hashlib.md5(coords.encode()).hexdigest()[:10]}.json",
                         lambda: osrm(f"table/v1/driving/{coords}?annotations=distance,duration"))
        if tb.get("code") == "Ok":
            D, Tm = tb["distances"], tb["durations"]
    except Exception as ex:
        log("  OSRM table fallo:", ex)
    matriz = "OSRM"
    if D is None:
        matriz = "haversine"
        D = [[haversine_km(a, b) * 1000 * 1.3 for b in pts] for a in pts]
        Tm = [[d / (40 / 3.6) for d in row] for row in D]
    n = len(pts)
    order, solver = None, None
    try:
        from ortools.constraint_solver import pywrapcp, routing_enums_pb2
        mgr = pywrapcp.RoutingIndexManager(n, 1, 0)
        rt = pywrapcp.RoutingModel(mgr)
        cb = rt.RegisterTransitCallback(lambda i, j: int(D[mgr.IndexToNode(i)][mgr.IndexToNode(j)]))
        rt.SetArcCostEvaluatorOfAllVehicles(cb)
        prm = pywrapcp.DefaultRoutingSearchParameters()
        prm.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
        prm.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
        prm.time_limit.seconds = 3
        solv = rt.SolveWithParameters(prm)
        if solv:
            idx, order = rt.Start(0), []
            while not rt.IsEnd(idx):
                order.append(mgr.IndexToNode(idx)); idx = solv.Value(rt.NextVar(idx))
            order.append(0)
            solver = "OR-Tools"
    except Exception as ex:
        log("  OR-Tools no disponible:", ex)
    if order is None:
        rest = list(range(1, n)); order = [0]
        while rest:
            nxt = min(rest, key=lambda j: D[order[-1]][j]); order.append(nxt); rest.remove(nxt)
        order = two_opt(D, order + [0])
        solver = "2-opt"
    seq = [pts[i] for i in order]
    router, geom, legs = "recta", None, None
    try:
        c2 = ";".join(f"{lon:.5f},{lat:.5f}" for lon, lat in seq)
        r = cached_json(f"osrm_route_{hashlib.md5(c2.encode()).hexdigest()[:10]}.json",
                        lambda: osrm(f"route/v1/driving/{c2}?overview=full&geometries=geojson&steps=false"))
        if r.get("code") == "Ok":
            geom = r["routes"][0]["geometry"]
            legs = [(l["distance"], l["duration"]) for l in r["routes"][0]["legs"]]
            router = "OSRM"
    except Exception as ex:
        log("  OSRM route fallo:", ex)
    if legs is None:
        geom = dict(type="LineString", coordinates=[list(p) for p in seq])
        legs = [(D[order[k]][order[k + 1]], Tm[order[k]][order[k + 1]]) for k in range(len(order) - 1)]
    t = dt.datetime(2025, 1, 1, 8, 30)
    acc_km, paradas = 0.0, []
    for k in range(1, len(order) - 1):
        d, du = legs[k - 1]
        acc_km += d / 1000; t += dt.timedelta(seconds=du)
        p = sel[order[k] - 1]
        paradas.append(dict(orden=k, predio_id=p["id"], banda=p["banda"], indice=p["indice"],
                            lon=round(seq[k][0], 5), lat=round(seq[k][1], 5), llegada=t.strftime("%H:%M"),
                            permanencia_min=PERMANENCIA_MIN, distancia_km_acum=round(acc_km, 1)))
        t += dt.timedelta(minutes=PERMANENCIA_MIN)
    d, du = legs[-1]
    acc_km += d / 1000; t += dt.timedelta(seconds=du)
    total_drive = sum(l[1] for l in legs) / 60
    return dict(
        illustrative=False,
        nota=("Orden y geometria reales (OSRM sobre OpenStreetMap). La seleccion de predios depende del indice, "
              "que usa m3_derecho ilustrativo. Punto de cada parada: punto del predio mas cercano a la plaza "
              "proyectado por OSRM al camino."),
        inicio=PLAZA,
        paradas=paradas,
        regreso=dict(nombre=PLAZA["nombre"], llegada=t.strftime("%H:%M"), distancia_km_acum=round(acc_km, 1)),
        geometry=geom,
        distancia_km=round(acc_km, 1),
        duracion_min=round(total_drive + PERMANENCIA_MIN * len(paradas)),
        duracion_manejo_min=round(total_drive),
        solver=solver, router=router, matriz=matriz, ida_y_vuelta=True,
    )


def write_gpx(ruta, path):
    def esc(s):
        return str(s).replace("&", "&amp;").replace("<", "&lt;")
    L = ['<?xml version="1.0" encoding="UTF-8"?>',
         '<gpx version="1.1" creator="Caudal (demo hackathon)" xmlns="http://www.topografix.com/GPX/1/1">',
         '  <metadata><name>Caudal - ruta de inspeccion Petorca (demo)</name>'
         '<desc>El sistema prioriza, no acusa. Datos parcialmente ilustrativos.</desc></metadata>',
         f'  <wpt lat="{ruta["inicio"]["lat"]}" lon="{ruta["inicio"]["lon"]}"><name>Inicio - {esc(ruta["inicio"]["nombre"])}</name>'
         f'<desc>Salida {ruta["inicio"]["hora"]}</desc></wpt>']
    for p in ruta["paradas"]:
        L.append(f'  <wpt lat="{p["lat"]}" lon="{p["lon"]}"><name>{p["orden"]}. {p["predio_id"]}</name>'
                 f'<desc>Banda {p["banda"]} - llegada {p["llegada"]} - {p["permanencia_min"]} min</desc></wpt>')
    L.append('  <trk><name>Ruta de inspeccion</name><trkseg>')
    for lon, lat in ruta["geometry"]["coordinates"]:
        L.append(f'    <trkpt lat="{lat:.6f}" lon="{lon:.6f}"/>')
    L += ['  </trkseg></trk>', '</gpx>']
    with open(path, "w") as f:
        f.write("\n".join(L) + "\n")


# ---------------------------------------------------------------- README
README = """# Datos demo — Valle de Petorca (Caudal v2)

> **El sistema prioriza, no acusa.** Los predios se identifican solo por ID (P-001…). Nada aquí nombra dueños.

Generado por `scripts/build_petorca_data.py` (re-ejecutable; cachea llamadas externas en `scripts/.cache/petorca/`).

## Qué es real y qué es ilustrativo

| Archivo | Real | Ilustrativo |
|---|---|---|
| `predios.geojson` | Geometría: polígonos OpenStreetMap (`landuse=orchard/farmland`) vía Overpass, `fuente_geom:"OSM"`. Área calculada de la geometría. | `m3_derecho` (**calibrado para la demo**), y por lo tanto `indice` y `banda` (`illustrative_scores: true`). Cultivo marcado `cultivo_fuente:"supuesto"` cuando OSM no lo dice. |
| `clima.json` | Open-Meteo archive (reanálisis ERA5), diario 2022-2024. | — (pendiente contrastar con estaciones DMC / DGA / INIA). |
| `series.json` | {series_real} | {series_ilus} |
| `ruta.json` / `ruta.gpx` | Orden óptimo ({solver}) sobre matriz {matriz}; geometría por camino ({router}). | La selección de predios depende del índice ilustrativo. |

## Método

1. **Ventana seca**: ≥ {vmin} días seguidos con lluvia < {lluv} mm (lluvia efectiva). Meses con racha seca ≥ 20 días se usan para medir verdor anómalo.
2. **Índices**: NDVI = (B08−B04)/(B08+B04); NDMI = (B8A−B11)/(B8A+B11), mediana por predio de píxeles válidos (máscara SCL: se descartan nubes 3/8/9/10). Resolución de lectura {res} m (overviews COG) para mantener liviana la descarga. Reflectancia = DN·0,0001 − 0,1 (sin el −0,1 en escenas que Earth Search ya re-armonizó, `earthsearch:boa_offset_applied`).
3. **Referencia de secano**: mediana mensual de píxeles de vegetación/suelo a >120 m de los predios OSM con 0,05 < NDVI < 0,5 (cerros y matorral). `z_verdor = (NDVI_predio − NDVI_ref) / (1,4826·MAD_ref)`; ídem `z_humedad` con NDMI.
4. **Consumo estimado (FAO-56 simplificado)**, año {year}:
   `V = Σ_mes max(0, Kc(NDVI)·ET0 − Pef) · A`, con `Kc = clamp({a}·NDVI + {b}, {kmin}, {kmax})`, `Pef = {pef}·P`, ET0 y P mensuales de `clima.json`, A en ha (1 mm·ha = 10 m³). Kc lineal simple; para palto NDVI≈0,65 → Kc≈0,91 (rango FAO 0,75–0,95 para palto/cítricos con cobertura).
5. **Rango, no número**: `m3_estimado_min/max = V·(1 ∓ r)`, r = 20 % (confianza alta), 27 % (media), 35 % (baja).
6. **Confianza**: baja con cada motivo (`pocos píxeles` < 15 px de {res} m, `pocas escenas válidas` < 9 meses, `nubosidad alta` > 20 % media, `sin referencia de secano cercana`, `cultivo no verificado`). 0 motivos = alta, 1 = media, ≥2 = baja. Peso w = 1 / 0,85 / 0,65.
7. **Índice de sospecha**: `exceso = (V − m3_derecho)/m3_derecho`; `indice = min(1, max(0, exceso)/0,5) · w`. Bandas: alta ≥ 0,60; media ≥ 0,30; baja ≥ 0,10; sin_alerta < 0,10.
8. **m3_derecho (ILUSTRATIVO)**: no tenemos el catastro de derechos (CPA/DGA) cruzado con predios. Para la demo se calibra a partir del ranking de verdor en ventana seca (`0,6·z_verdor + 0,4·z_humedad`, ponderado por confianza y área) para mostrar ~5 alta / ~8 media / resto baja–sin alerta. **No representa derechos reales.**
9. **Ruta**: plaza de Petorca 08:30, alta + top media (N={nruta}), {perm} min por parada, ida y vuelta. Distancias OSRM (servidor demo público) + TSP OR-Tools; fallback haversine + 2-opt y tramos rectos.

## Resultado de esta corrida

- Predios: {n} ({n_osm} OSM, {n_il} ilustrativos). Bandas: {bandas}.
- Ventanas secas 2022-2024: {nv}.
- Ruta: {km} km, {mins} min totales ({solver} / {router}).
"""


# ---------------------------------------------------------------- main
def main():
    use_s2 = "--no-s2" not in sys.argv
    log("1) Predios (Overpass/OSM)")
    predios = build_predios()
    bb = box(BBOX["west"], BBOX["south"], BBOX["east"], BBOX["north"])
    for p in predios:
        c = p["geom"].representative_point() if not p["geom"].centroid.within(p["geom"]) else p["geom"].centroid
        p["centroid"] = [round(c.x, 5), round(c.y, 5)]
        # punto de acceso para la ruta: vertice del predio mas cercano a la plaza (aprox. entrada desde el camino)
        ext = list(p["geom"].exterior.coords)
        a = min(ext, key=lambda q: haversine_km(q, (PLAZA["lon"], PLAZA["lat"])))
        p["punto_acceso"] = [round(a[0], 5), round(a[1], 5)]
    log(f"   {len(predios)} predios ({sum(p['fuente_geom'] == 'OSM' for p in predios)} OSM)")

    log("2) Clima (Open-Meteo)")
    clima = build_clima()
    with open(os.path.join(OUT, "clima.json"), "w") as f:
        json.dump(clima, f, ensure_ascii=False)
    log(f"   {len(clima['ventanas_secas'])} ventanas secas")

    log("3) Series Sentinel-2")
    res = s2_series(predios) if use_s2 else None
    real_s2 = res is not None
    if real_s2:
        series, ref, meta = res
    else:
        series, ref, meta = illustrative_series(predios, clima)
    add_z(series, ref)

    log("4) Scores")
    build_scores(predios, series, ref, clima, meta, real_s2)

    feats = []
    for p in predios:
        props = dict(
            id=p["id"], area_ha=round(p["area_ha"], 2), cultivo=p["cultivo"], cultivo_fuente=p["cultivo_fuente"],
            fuente_geom=p["fuente_geom"], osm_id=p["osm_id"],
            m3_derecho=p["m3_derecho"], m3_derecho_illustrative=True,
            m3_estimado_min=p["m3_estimado_min"], m3_estimado_max=p["m3_estimado_max"],
            m3_estimado_anio=int(SCORE_YEAR),
            m3_estimado_fuente=("NDVI Sentinel-2 real + ET0/lluvia Open-Meteo" if real_s2
                                else "NDVI ilustrativo + ET0/lluvia Open-Meteo"),
            exceso_rel=p["exceso_rel"], indice=p["indice"], banda=p["banda"],
            confianza=p["confianza"], confianza_motivos=p["confianza_motivos"],
            z_verdor_seco=p["z_verdor_seco"], z_humedad_seco=p["z_humedad_seco"],
            n_px=meta["n_px"].get(p["id"]), centroid=p["centroid"], punto_acceso=p["punto_acceso"],
            ndvi_real=real_s2, illustrative_scores=True,
        )
        feats.append(dict(type="Feature", id=p["id"], properties=props, geometry=mapping(p["geom"])))
    fc = dict(type="FeatureCollection",
              metadata=dict(valle="Petorca, Región de Valparaíso", bbox=BBOX, generado=dt.date.today().isoformat(),
                            principio="El sistema prioriza, no acusa: solo IDs, sin nombres de dueños.",
                            fuente_geom="OpenStreetMap contributors (ODbL) via Overpass API",
                            illustrative_fields=["m3_derecho", "indice", "banda", "exceso_rel"] +
                            ([] if real_s2 else ["m3_estimado_min", "m3_estimado_max", "z_verdor_seco", "z_humedad_seco"]),
                            illustrative_scores=True),
              features=feats)
    # geometria con 5 decimales (~1 m)
    txt = json.dumps(fc, ensure_ascii=False)
    fc2 = json.loads(txt, parse_float=lambda s: round(float(s), 6))
    with open(os.path.join(OUT, "predios.geojson"), "w") as f:
        json.dump(fc2, f, ensure_ascii=False)

    ser = dict(
        illustrative=not real_s2,
        fuente=("Sentinel-2 L2A (Element84 Earth Search STAC, COG AWS), tesela " + S2_TILE if real_s2
                else "ILUSTRATIVO: series sinteticas plausibles (no son observaciones)"),
        resolucion_m=S2_RES if real_s2 else None,
        metodo=("1 escena por mes (la menos nubosa de la tesela), mediana por predio de pixeles validos SCL; "
                "NDVI=(B08-B04)/(B08+B04), NDMI=(B8A-B11)/(B8A+B11)" if real_s2 else
                "Palto/citrico regado verde todo el ano (NDVI~0.5-0.75); secano sigue la lluvia de clima.json"),
        meses=MONTHS,
        escenas=meta.get("escenas"),
        predios=series,
        referencia_secano=dict(
            descripcion=("Mediana de pixeles de vegetacion/suelo a >120 m de predios OSM con 0.05<NDVI<0.5 "
                         "(cerros/matorral); aproximacion" if real_s2 else "ILUSTRATIVO"),
            serie=ref),
        z_definicion="z = (indice_predio - mediana_ref) / max(0.02, 1.4826*MAD_ref)",
    )
    with open(os.path.join(OUT, "series.json"), "w") as f:
        json.dump(ser, f, ensure_ascii=False)

    log("5) Ruta")
    ruta = build_ruta(predios)
    with open(os.path.join(OUT, "ruta.json"), "w") as f:
        json.dump(ruta, f, ensure_ascii=False)
    write_gpx(ruta, os.path.join(OUT, "ruta.gpx"))

    bandas = {b: sum(p["banda"] == b for p in predios) for b, _ in BANDAS}
    readme = README
    for k, v in dict(
        series_real=("NDVI/NDMI Sentinel-2 L2A reales (Earth Search, tesela 19HCE), 1 escena/mes, %d m." % S2_RES
                     if real_s2 else "—"),
        series_ilus=("Referencia de secano es una aproximación por píxeles (no un predio de secano verificado)."
                     if real_s2 else "**Todo** (`illustrative: true`): series sintéticas plausibles."),
        solver=ruta["solver"], matriz=ruta["matriz"], router=ruta["router"], vmin=VENTANA_MIN_DIAS,
        lluv=LLUVIA_EFECTIVA_MM, res=S2_RES, year=SCORE_YEAR, a=KC_A, b=KC_B, kmin=KC_MIN, kmax=KC_MAX,
        pef=PEF_FACTOR, nruta=N_RUTA, perm=PERMANENCIA_MIN, n=len(predios),
        n_osm=sum(p["fuente_geom"] == "OSM" for p in predios),
        n_il=sum(p["fuente_geom"] != "OSM" for p in predios),
        bandas=", ".join(f"{k2} {v2}" for k2, v2 in bandas.items()), nv=len(clima["ventanas_secas"]),
        km=ruta["distancia_km"], mins=ruta["duracion_min"],
    ).items():
        readme = readme.replace("{" + k + "}", str(v))
    with open(os.path.join(OUT, "README.md"), "w") as f:
        f.write(readme)

    # validacion
    log("6) Validacion")
    for fn in ("predios.geojson", "clima.json", "series.json", "ruta.json"):
        with open(os.path.join(OUT, fn)) as f:
            json.load(f)
    g = json.load(open(os.path.join(OUT, "predios.geojson")))
    assert all(shape(ft["geometry"]).is_valid for ft in g["features"])
    assert len(json.load(open(os.path.join(OUT, "series.json")))["predios"]) == len(g["features"])
    log(f"   predios={len(g['features'])} bandas={bandas} real_s2={real_s2}")
    log(f"   ruta {ruta['distancia_km']} km, {ruta['duracion_min']} min ({ruta['solver']}/{ruta['router']}), "
        f"regreso {ruta['regreso']['llegada']}")
    log(f"   ventanas secas={len(clima['ventanas_secas'])}")
    os._exit(0)  # no esperar hilos de descarga abandonados por el time-box


if __name__ == "__main__":
    main()
