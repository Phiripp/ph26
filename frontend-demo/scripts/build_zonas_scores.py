#!/usr/bin/env python3
"""Caudal v2 - series Sentinel-2, puntajes provisionales y rutas por zona (rol SERIES).

Escribe, relativo a frontend-demo/:
  data/zonas/{z1,z2}/series.json   NDVI/NDMI mensual por predio (Sentinel-2 L2A real) + referencia de secano CONAF
  data/zonas/{z1,z2}/scores.json   banda provisional (FAO-56 vs derechos reales del rol), por temporada
  data/zonas/{z1,z2}/ruta.json     ruta de inspeccion (OR-Tools + OSRM)
  data/zonas/{z1,z2}/ruta.gpx
  data/zonas/README.md             metodo

Entradas (solo lectura):
  data/zonas/{z}/predios.geojson   (DATA-TAB; si no existe, se arma desde ../data/processed/predio_muestra.geojson)
  data/zonas/bbox.json             bbox de escena por zona
  ../data/processed/predio_derecho.parquet, clima.parquet, dias_sin_lluvia.parquet, predio_clima.parquet,
  referencia_secano.parquet (CONAF)
  NO usa serie_predio (bug D15: offset de Sentinel-2 restado dos veces).

Uso (desde frontend-demo/):
  uv run --with pandas --with pyarrow --with geopandas --with shapely --with numpy --with rasterio \
         --with pystac-client --with ortools python scripts/build_zonas_scores.py [--zonas z1,z2] [--wait-predios 600]

Cachea STAC, escenas (ventanas a 20 m) y OSRM en scripts/.cache/zonas/.
"""
import datetime as dt
import hashlib
import json
import math
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED

import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.geometry import shape, mapping, Point, box
from shapely.ops import unary_union

HERE = os.path.dirname(os.path.abspath(__file__))
FRONT = os.path.dirname(HERE)
REPO = os.path.dirname(FRONT)
PROC = os.path.join(REPO, "data", "processed")
OUT = os.path.join(FRONT, "data", "zonas")
CACHE = os.path.join(HERE, ".cache", "zonas")
UA = "caudal-hackathon-mockup"

ZONAS = {
    "z1": dict(codigo="Z1", nombre="Petorca", plaza=dict(nombre="Plaza de Cabildo", lon=-71.0667, lat=-32.4269, hora="08:30")),
    "z2": dict(codigo="Z2", nombre="Aconcagua bajo", plaza=dict(nombre="Plaza de Hijuelas", lon=-71.1442, lat=-32.7983, hora="08:30")),
}
M_START = (2020, 7)                     # temporada 2020-21 completa (antecedente FO-0504-95, 2021)
TEMPORADA = "2025-26"
TEMPORADAS = ["2020-21", "2021-22", "2022-23", "2023-24", "2024-25", "2025-26"]
S2_RES = 20                             # m (overview 2x de bandas de 10 m; nativo para B8A/B11/SCL)
S2_BUDGET_S = 2400                      # tope por zona
S2_MAX_CLOUD = 70
S2_CANDIDATOS = 3                       # escenas probadas por mes si la primera viene nublada sobre los predios
REF_MARGIN_M = 3000                     # margen de la ventana alrededor de los predios (referencia de secano)
REF_CERCA_M = 3000
REF_MIN_PX = 150
DN_OFFSET_UMBRAL = 800                  # p1 de B04 sobre vegetacion/suelo: armonizado ~250, con +1000 ~1200+
KC_A, KC_B, KC_MIN, KC_MAX = 1.25, 0.10, 0.15, 1.15
PEF_FACTOR = 0.8
VERDE_MIN = 0.30                        # NDVI minimo de un pixel "regado" en meses secos
VERDE_Z = 3.0                           # ... y > ref + 3 MAD
A_RIEGO_MIN_HA = 0.5
ZH_RIEGO = 1.0                          # anomalia de humedad (NDMI) minima del area verde
EXCESO_ESCALA_M3 = 50000                # exceso al que el indice deja de castigarse por tamano
CONF_W = {"alta": 1.0, "media": 0.85, "baja": 0.65}
CONF_RANGO = {"alta": 0.20, "media": 0.27, "baja": 0.35}
N_RUTA = 8
PERMANENCIA_MIN = 20
SECO_DIAS_MES = 20                      # mes "seco": >= 20 dias dentro de una ventana seca (N=10) de la celda


def log(*a):
    print("[scores]", *a, flush=True)


def months_list(end):
    y, m = M_START
    out = []
    while (y, m) <= end:
        out.append(f"{y}-{m:02d}")
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


TODAY = dt.date.today()
MONTHS = months_list((TODAY.year, TODAY.month))


def temporada_meses(t):
    y = int(t[:4])
    anual = [f"{y}-{m:02d}" for m in range(7, 13)] + [f"{y + 1}-{m:02d}" for m in range(1, 7)]
    seca = [f"{y}-12", f"{y + 1}-01", f"{y + 1}-02", f"{y + 1}-03"]
    return anual, seca


def http(url, data=None, timeout=90):
    try:
        req = urllib.request.Request(url, data=data, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.URLError as ex:
        if "SSL" not in str(ex):
            raise
        cmd = ["curl", "-sS", "--fail", "-A", UA, "--max-time", str(timeout), url]
        return subprocess.run(cmd, capture_output=True, check=True).stdout


def cached_json(name, fetcher):
    p = os.path.join(CACHE, name)
    if os.path.exists(p):
        with open(p) as f:
            return json.load(f)
    d = fetcher()
    with open(p, "w") as f:
        json.dump(d, f)
    return d


def haversine_km(a, b):
    lon1, lat1, lon2, lat2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(h))


def r3(x):
    return None if x is None or (isinstance(x, float) and not math.isfinite(x)) else round(float(x), 3)


# ---------------------------------------------------------------- predios
def load_predios(z, wait_s):
    p = os.path.join(OUT, z, "predios.geojson")
    t0 = time.time()
    while not os.path.exists(p) and time.time() - t0 < wait_s:
        log(f"  esperando {p} (DATA-TAB)...")
        time.sleep(20)
    if os.path.exists(p):
        fc = json.load(open(p))
        src = "predios.geojson (DATA-TAB)"
        feats = fc["features"]
    else:
        src = "predio_muestra.geojson (fallback)"
        m = json.load(open(os.path.join(REPO, "data", "processed", "predio_muestra.geojson")))
        feats = []
        for f in m["features"]:
            pr = f["properties"]
            if pr["zona"].lower() != z:
                continue
            props = dict(id=str(pr["predio_id"]), predio_id=pr["predio_id"], rol=pr["rol"], comuna=pr["comuna"],
                         zona=z, area_ha=pr["area_ha"],
                         caso=pr["caso_cercano"] if pr.get("dist_caso_m", 1e9) <= 30 else None)
            feats.append(dict(type="Feature", properties=props, geometry=f["geometry"]))
    out = []
    for f in feats:
        pr = dict(f["properties"])
        pr["id"] = str(pr.get("id") or pr["predio_id"])
        g = shape(f["geometry"])
        if not g.is_valid:
            g = g.buffer(0)
        out.append(dict(id=pr["id"], props=pr, geom=g))
    log(f"  {len(out)} predios desde {src}")
    return out, src


def derechos_por_temporada(ids):
    d = pd.read_parquet(os.path.join(PROC, "predio_derecho.parquet"),
                        columns=["predio_id", "temporada", "m3_anual_derecho_rol", "estado_derechos", "confianza_cruce",
                                 "m3_anual_derecho_entorno_500m"])
    d = d[d.predio_id.isin([int(i) for i in ids])]
    out = {}
    for r in d.itertuples():
        out.setdefault(str(r.predio_id), {})[r.temporada] = dict(
            m3=float(r.m3_anual_derecho_rol or 0), estado=r.estado_derechos, conf=r.confianza_cruce,
            entorno=float(r.m3_anual_derecho_entorno_500m or 0))
    return out


# ---------------------------------------------------------------- clima (equipo)
def clima_por_celda(celdas):
    c = pd.read_parquet(os.path.join(PROC, "clima.parquet"))
    c = c[(c.fuente == "openmeteo") & c.punto_id.isin(celdas)].copy()
    c["lluvia"] = c.lluvia_corr_mm.fillna(c.lluvia_mm)
    c["mes"] = c.fecha.dt.strftime("%Y-%m")
    g = c.groupby(["punto_id", "mes"]).agg(lluvia=("lluvia", "sum"), et0=("et0_mm", "sum"), n=("fecha", "count")).reset_index()
    ds = pd.read_parquet(os.path.join(PROC, "dias_sin_lluvia.parquet"))
    ds = ds[ds.celda_id.isin(celdas)].copy()
    ds["mes"] = ds.fecha.dt.strftime("%Y-%m")
    v = ds.groupby(["celda_id", "mes"]).en_ventana.sum().reset_index()
    out = {}
    for r in g.itertuples():
        out.setdefault(r.punto_id, {})[r.mes] = dict(lluvia=float(r.lluvia), et0=float(r.et0), n=int(r.n))
    for r in v.itertuples():
        out.setdefault(r.celda_id, {}).setdefault(r.mes, {})["dias_ventana"] = int(r.en_ventana)
    return out


def celda_de_predios(predios):
    pc = pd.read_parquet(os.path.join(PROC, "predio_clima.parquet"))
    m = dict(zip(pc.predio_id.astype(str), pc.celda_id))
    out = {}
    for p in predios:
        out[p["id"]] = p["props"].get("celda_clima") or m.get(p["id"])
    return out


# ---------------------------------------------------------------- Sentinel-2
def s2_env():
    os.environ.update(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", AWS_NO_SIGN_REQUEST="YES",
                      GDAL_HTTP_MULTIRANGE="YES", GDAL_HTTP_MERGE_CONSECUTIVE_RANGES="YES",
                      CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif", GDAL_HTTP_TIMEOUT="90",
                      GDAL_HTTP_MAX_RETRY="4", GDAL_HTTP_RETRY_DELAY="2", VSI_CACHE="TRUE",
                      GDAL_HTTP_USERAGENT=UA, GDAL_HTTP_VERSION="2")


def stac_items(z, bbox):
    from pystac_client import Client

    def fetch():
        c = Client.open("https://earth-search.aws.element84.com/v1", headers={"User-Agent": UA})
        s = c.search(collections=["sentinel-2-l2a"], bbox=bbox,
                     datetime=f"{MONTHS[0]}-01/{TODAY.isoformat()}",
                     query={"eo:cloud_cover": {"lt": S2_MAX_CLOUD}}, limit=100)
        out = []
        for it in s.items():
            p = it.properties
            tile = f"{p['mgrs:utm_zone']}{p['mgrs:latitude_band']}{p['mgrs:grid_square']}"
            out.append(dict(id=it.id, tile=tile, fecha=p["datetime"][:10], cloud=p.get("eo:cloud_cover", 100),
                            baseline=p.get("s2:processing_baseline"),
                            boa_offset_applied=p.get("earthsearch:boa_offset_applied"),
                            hrefs={k: it.assets[k].href for k in ("red", "nir", "nir08", "swir16", "scl")}))
        return out
    return cached_json(f"stac_{z}_{MONTHS[0]}_{MONTHS[-1]}.json", fetch)


def tile_grid(href):
    import rasterio
    with rasterio.open(href) as ds:
        T = ds.transform
        return dict(x0=T.c, y0=T.f, crs=ds.crs.to_string(), w=ds.width * T.a, h=ds.height * -T.e)


def assign_tiles(predios, tiles_grid):
    """Asigna cada predio a la tesela que lo contiene entero (margen 200 m); preferencia por la que tiene mas predios."""
    from rasterio.warp import transform_geom
    cand = {}
    for p in predios:
        ok = []
        for t, g in tiles_grid.items():
            gg = shape(transform_geom("EPSG:4326", g["crs"], mapping(p["geom"])))
            x0, y0, x1, y1 = gg.bounds
            if x0 > g["x0"] + 200 and x1 < g["x0"] + g["w"] - 200 and y1 < g["y0"] - 200 and y0 > g["y0"] - g["h"] + 200:
                ok.append(t)
        cand[p["id"]] = ok
    count = {t: sum(t in v for v in cand.values()) for t in tiles_grid}
    asig = {}
    for p in predios:
        ok = cand[p["id"]]
        asig[p["id"]] = max(ok, key=lambda t: count[t]) if ok else None
    return asig


def window_for(predios_t, g):
    """Ventana (en CRS de la tesela) alrededor de los predios + margen, ajustada a la grilla de 20 m de la tesela."""
    from rasterio.warp import transform_geom
    geoms = [shape(transform_geom("EPSG:4326", g["crs"], mapping(p["geom"]))) for p in predios_t]
    x0, y0, x1, y1 = unary_union(geoms).bounds
    x0 -= REF_MARGIN_M; y0 -= REF_MARGIN_M; x1 += REF_MARGIN_M; y1 += REF_MARGIN_M
    X0, Y1 = g["x0"], g["y0"]
    x0 = max(X0, X0 + math.floor((x0 - X0) / S2_RES) * S2_RES)
    x1 = min(X0 + g["w"], X0 + math.ceil((x1 - X0) / S2_RES) * S2_RES)
    y1 = min(Y1, Y1 - math.floor((Y1 - y1) / S2_RES) * S2_RES)
    y0 = max(Y1 - g["h"], Y1 - math.ceil((Y1 - y0) / S2_RES) * S2_RES)
    return (x0, y0, x1, y1)


def read_band(href, ub, res_native, resampling):
    import rasterio
    from rasterio.windows import Window
    with rasterio.open(href) as ds:
        T = ds.transform
        col0 = round((ub[0] - T.c) / T.a); row0 = round((ub[3] - T.f) / T.e)
        ncol = round((ub[2] - ub[0]) / T.a); nrow = round((ub[3] - ub[1]) / -T.e)
        f = int(S2_RES / res_native)
        return ds.read(1, window=Window(col0, row0, ncol, nrow), out_shape=(nrow // f, ncol // f),
                       resampling=resampling, boundless=False)


def s2_zone(z, predios, bbox):
    s2_env()
    import rasterio  # noqa
    from rasterio.enums import Resampling
    from rasterio.features import rasterize
    from rasterio.warp import transform_geom
    from affine import Affine

    items = stac_items(z, bbox)
    by_tile = {}
    for it in items:
        by_tile.setdefault(it["tile"], []).append(it)
    log(f"  STAC: {len(items)} escenas, teselas {[(t, len(v)) for t, v in by_tile.items()]}")
    sdir = os.path.join(CACHE, "s2", z)
    os.makedirs(sdir, exist_ok=True)
    grids = cached_json(f"grids_{z}.json", lambda: {t: tile_grid(v[0]["hrefs"]["scl"]) for t, v in by_tile.items()})
    asig = assign_tiles(predios, grids)
    sin = [k for k, v in asig.items() if v is None]
    if sin:
        log(f"  {len(sin)} predios no caben enteros en una tesela; se asigna la de su centroide")
        for p in predios:
            if asig[p["id"]] is None:
                c = p["geom"].centroid
                for t, g in grids.items():
                    from rasterio.warp import transform as tr_
                    xs, ys = tr_("EPSG:4326", g["crs"], [c.x], [c.y])
                    if g["x0"] < xs[0] < g["x0"] + g["w"] and g["y0"] - g["h"] < ys[0] < g["y0"]:
                        asig[p["id"]] = t
                        break
    tiles = sorted({t for t in asig.values() if t})
    log(f"  teselas usadas: {{{', '.join(f'{t}: {sum(v == t for v in asig.values())}' for t in tiles)}}}")

    # CONAF referencia de secano
    ref = gpd.read_parquet(os.path.join(PROC, "referencia_secano.parquet"))
    ref = ref[ref.zona == ZONAS[z]["codigo"]]

    ctx = {}
    for t in tiles:
        g = grids[t]
        pt = [p for p in predios if asig[p["id"]] == t]
        ub = window_for(pt, g)
        W = int(round((ub[2] - ub[0]) / S2_RES)); H = int(round((ub[3] - ub[1]) / S2_RES))
        tr = Affine(S2_RES, 0, ub[0], 0, -S2_RES, ub[3])
        shapes = [(transform_geom("EPSG:4326", g["crs"], mapping(p["geom"])), i + 1) for i, p in enumerate(pt)]
        labels = rasterize(shapes, out_shape=(H, W), transform=tr, fill=0, all_touched=False, dtype="int32")
        # predios chicos: si no queda ningun pixel con centro adentro, all_touched
        for i, p in enumerate(pt):
            if not (labels == i + 1).any():
                m = rasterize([(shapes[i][0], 1)], out_shape=(H, W), transform=tr, fill=0, all_touched=True, dtype="uint8")
                labels[(m == 1) & (labels == 0)] = i + 1
        # referencia CONAF dentro de la ventana, sin un buffer de 60 m alrededor de los predios
        wb = box(*ub)
        rg = ref.to_crs(g["crs"])
        rg = rg[rg.intersects(wb)]
        refmask = np.zeros((H, W), dtype=bool)
        if len(rg):
            refmask = rasterize([(geom, 1) for geom in rg.geometry], out_shape=(H, W), transform=tr, fill=0,
                                dtype="uint8").astype(bool)
            near = rasterize([(shape(s).buffer(60), 1) for s, _ in shapes], out_shape=(H, W), transform=tr, fill=0,
                             dtype="uint8").astype(bool)
            refmask &= ~near
        # referencia cercana por predio: ha de CONAF a <= 3 km
        cerca = {}
        sidx = rg.sindex if len(rg) else None
        for p, (s, _) in zip(pt, shapes):
            gg = shape(s)
            if sidx is None:
                cerca[p["id"]] = 0.0
                continue
            bz = gg.buffer(REF_CERCA_M)
            idx = list(sidx.query(bz))
            cerca[p["id"]] = round(float(rg.geometry.iloc[idx].intersection(bz).area.sum() / 1e4), 1) if idx else 0.0
        ctx[t] = dict(ub=ub, W=W, H=H, predios=pt, labels=labels, refmask=refmask, cerca=cerca,
                      ref_px=int(refmask.sum()), conaf_n=len(rg))
        log(f"  {t}: ventana {W}x{H} px a {S2_RES} m, {len(pt)} predios, CONAF {len(rg)} poligonos / {int(refmask.sum())} px")

    # candidatos por (tesela, mes): menos nubosa de la tesela primero; mismo dia -> mayor baseline
    cands = {}
    for t in tiles:
        per = {}
        for it in by_tile[t]:
            per.setdefault(it["fecha"][:7], {})
            k = it["fecha"]
            prev = per[it["fecha"][:7]].get(k)
            if prev is None or (it["baseline"] or "") > (prev["baseline"] or ""):
                per[it["fecha"][:7]][k] = it
        for m, d in per.items():
            if m in MONTHS:
                cands[(t, m)] = sorted(d.values(), key=lambda i: i["cloud"])[:S2_CANDIDATOS]

    def scene(t, m):
        p = os.path.join(sdir, f"{t}_{m}.npz")
        if os.path.exists(p):
            return "cache"
        c = ctx[t]
        sel, best_frac = None, -1
        inside = c["labels"] > 0
        for it in cands[(t, m)]:
            try:
                scl = read_band(it["hrefs"]["scl"], c["ub"], 20, Resampling.nearest)
            except Exception as e3:
                log(f"    S2 {t} {m}: {it['id']} no disponible ({str(e3)[:80]}), se prueba otra")
                continue
            hh, ww = min(scl.shape[0], c["H"]), min(scl.shape[1], c["W"])
            ins = inside[:hh, :ww]
            frac = float(np.isin(scl[:hh, :ww][ins], [4, 5, 6, 7, 11]).mean()) if ins.any() else 0.0
            if frac > best_frac:
                sel, best_frac, sel_scl = it, frac, scl
            if frac >= 0.85:
                break
        if sel is None or best_frac < 0.2:
            np.savez_compressed(p, vacio=True, frac=best_frac)
            return "vacio"
        bands = [("red", 10, Resampling.average), ("nir", 10, Resampling.average),
                 ("nir08", 20, Resampling.average), ("swir16", 20, Resampling.average)]
        with ThreadPoolExecutor(4) as bx:
            res = list(bx.map(lambda b: read_band(sel["hrefs"][b[0]], c["ub"], b[1], b[2]), bands))
        arrs = {b[0]: a for b, a in zip(bands, res)}
        np.savez_compressed(p, vacio=False, scene=sel["id"], fecha=sel["fecha"], baseline=str(sel["baseline"]),
                            boa=str(sel["boa_offset_applied"]), frac=best_frac, scl=sel_scl, **arrs)
        return "ok"

    t0 = time.time()
    todo = sorted(cands)
    ex = ThreadPoolExecutor(12)
    futs = {ex.submit(scene, t, m): (t, m) for t, m in todo}
    pending = set(futs)
    done = 0
    while pending and time.time() - t0 < S2_BUDGET_S:
        fin, pending = wait(pending, timeout=20, return_when=FIRST_COMPLETED)
        for f in fin:
            done += 1
            try:
                r = f.result()
                if r != "cache" or done % 20 == 0:
                    log(f"    S2 {futs[f]} {r} ({done}/{len(todo)}, {time.time() - t0:.0f}s)")
            except Exception as e2:
                log(f"    S2 {futs[f]} fallo: {str(e2)[:160]}")
    if pending:
        log(f"  time-box: quedan {len(pending)} escenas sin bajar (se re-intentan en la proxima corrida)")
    ex.shutdown(wait=False, cancel_futures=True)

    # ------------------------------------------------ extraer series
    series = {p["id"]: [] for p in predios}
    ref_series = {t: [] for t in tiles}
    escenas = {}
    offsets = {}
    for m in MONTHS:
        for t in tiles:
            c = ctx[t]
            f = os.path.join(sdir, f"{t}_{m}.npz")
            ok = os.path.exists(f)
            zf = np.load(f) if ok else None
            if not ok or bool(zf["vacio"]):
                for p in c["predios"]:
                    series[p["id"]].append(dict(fecha=m, ndvi=None, ndmi=None, nubosidad_pct=None))
                ref_series[t].append(dict(fecha=m, ndvi=None, ndmi=None, ndvi_mad=None, ndmi_mad=None, n_px=0))
                continue
            scl = zf["scl"]
            hh = min(scl.shape[0], zf["red"].shape[0], zf["nir08"].shape[0], c["H"])
            ww = min(scl.shape[1], zf["red"].shape[1], zf["nir08"].shape[1], c["W"])
            scl = scl[:hh, :ww]
            dn = {k: zf[k][:hh, :ww].astype("float32") for k in ("red", "nir", "nir08", "swir16")}
            nodata = (dn["red"] == 0) | (scl == 0)
            # offset BOA: se decide con los datos (el flag earthsearch:boa_offset_applied no es confiable,
            # ej. S2C_19HBE_20241108_1 viene False y ya esta armonizado)
            vs = (np.isin(scl, [4, 5])) & ~nodata
            p1 = float(np.percentile(dn["red"][vs], 1)) if vs.sum() > 200 else None
            if p1 is not None:
                off = 1000.0 if p1 > DN_OFFSET_UMBRAL else 0.0
            else:
                off = 1000.0 if (str(zf["baseline"]) >= "04.00" and str(zf["boa"]) != "True") else 0.0
            offsets[f"{t}_{m}"] = dict(scene=str(zf["scene"]), p1_red=r3(p1), dn_offset=off,
                                       flag_boa=str(zf["boa"]), baseline=str(zf["baseline"]))
            refl = {k: (v - off) / 1e4 for k, v in dn.items()}
            cloud = np.isin(scl, [3, 8, 9, 10])
            valid = np.isin(scl, [4, 5, 6, 7, 11]) & ~nodata
            with np.errstate(divide="ignore", invalid="ignore"):
                ndvi = (refl["nir"] - refl["red"]) / (refl["nir"] + refl["red"])
                ndmi = (refl["nir08"] - refl["swir16"]) / (refl["nir08"] + refl["swir16"])
            valid &= np.isfinite(ndvi) & np.isfinite(ndmi) & (refl["red"] > -0.05) & (refl["nir"] > 0)
            escenas.setdefault(m, {})[t] = str(zf["scene"])
            rm = valid & c["refmask"][:hh, :ww] & np.isin(scl, [4, 5])
            if rm.sum() >= REF_MIN_PX:
                rv, rn = ndvi[rm], ndmi[rm]
                rmed, rnm = float(np.median(rv)), float(np.median(rn))
                rmad = float(1.4826 * np.median(np.abs(rv - rmed)))
                rnmad = float(1.4826 * np.median(np.abs(rn - rnm)))
                ref_series[t].append(dict(fecha=m, ndvi=r3(rmed), ndmi=r3(rnm), ndvi_mad=round(rmad, 4),
                                          ndmi_mad=round(rnmad, 4), n_px=int(rm.sum()), escena=str(zf["scene"])))
            else:
                rmed = rnm = rmad = rnmad = None
                ref_series[t].append(dict(fecha=m, ndvi=None, ndmi=None, ndvi_mad=None, ndmi_mad=None, n_px=int(rm.sum())))
            lab = c["labels"][:hh, :ww]
            thr = max(VERDE_MIN, (rmed + VERDE_Z * max(rmad, 0.02)) if rmed is not None else VERDE_MIN)
            for i, p in enumerate(c["predios"]):
                ins = lab == i + 1
                n = int(ins.sum())
                v = ins & valid
                nv = int(v.sum())
                rec = dict(fecha=m, ndvi=None, ndmi=None,
                           nubosidad_pct=round(100 * int((ins & cloud).sum()) / n, 1) if n else None,
                           escena=str(zf["scene"]), n_px_validos=nv)
                if nv >= 3 and nv >= 0.3 * n:
                    nd, nm = ndvi[v], ndmi[v]
                    rec["ndvi"] = r3(np.median(nd))
                    rec["ndmi"] = r3(np.median(nm))
                    gmask = nd > thr
                    rec["frac_verde"] = round(float(gmask.mean()), 3)
                    if gmask.sum() >= 2:
                        rec["ndvi_verde"] = r3(np.median(nd[gmask]))
                        rec["ndmi_verde"] = r3(np.median(nm[gmask]))
                series[p["id"]].append(rec)
    npx = {p["id"]: int((ctx[asig[p["id"]]]["labels"] == ctx[asig[p["id"]]]["predios"].index(p) + 1).sum())
           for p in predios if asig[p["id"]]}
    cerca = {k: v for t in tiles for k, v in ctx[t]["cerca"].items()}
    meta = dict(escenas=escenas, tiles=tiles, asig=asig, npx=npx, ref_cerca_ha=cerca, offsets=offsets,
                ref_px={t: ctx[t]["ref_px"] for t in tiles}, n_pend=len(pending),
                conaf_n={t: ctx[t]["conaf_n"] for t in tiles})
    return series, ref_series, meta


def add_z(series, ref_series, asig):
    for pid, s in series.items():
        t = asig.get(pid)
        rf = {r["fecha"]: r for r in ref_series.get(t, [])}
        for r in s:
            b = rf.get(r["fecha"], {})
            ok = b.get("ndvi") is not None
            r["z_verdor"] = round((r["ndvi"] - b["ndvi"]) / max(b["ndvi_mad"], 0.02), 2) if ok and r.get("ndvi") is not None else None
            r["z_humedad"] = round((r["ndmi"] - b["ndmi"]) / max(b["ndmi_mad"], 0.02), 2) if ok and r.get("ndmi") is not None else None
            if ok and r.get("ndmi_verde") is not None:
                r["z_humedad_verde"] = round((r["ndmi_verde"] - b["ndmi"]) / max(b["ndmi_mad"], 0.02), 2)


# ---------------------------------------------------------------- puntajes
def d_rol(der):
    return float(der.get("m3") or 0)


def kc(nd):
    return min(KC_MAX, max(KC_MIN, KC_A * nd + KC_B))


def interp(vals):
    """Rellena None por interpolacion lineal (extremos: valor mas cercano)."""
    idx = [i for i, v in enumerate(vals) if v is not None]
    if not idx:
        return None
    out = list(vals)
    for i in range(len(vals)):
        if out[i] is None:
            lo = max([j for j in idx if j < i], default=None)
            hi = min([j for j in idx if j > i], default=None)
            if lo is None:
                out[i] = vals[hi]
            elif hi is None:
                out[i] = vals[lo]
            else:
                out[i] = vals[lo] + (vals[hi] - vals[lo]) * (i - lo) / (hi - lo)
    return out


def score_temporada(p, s, clima_c, der, temporada, meta):
    anual, seca = temporada_meses(temporada)
    rec = {r["fecha"]: r for r in s}
    if anual[-1] > MONTHS[-1] and temporada != TEMPORADA:
        return None
    # meses secos de la temporada segun la celda (>= 20 dias en ventana seca N=10); si ninguno, dic-mar
    secos = [m for m in seca if (clima_c.get(m, {}).get("dias_ventana") or 0) >= SECO_DIAS_MES] or seca
    obs = [rec[m] for m in secos if m in rec and rec[m].get("ndvi") is not None]
    n_anual_val = sum(1 for m in anual if rec.get(m, {}).get("ndvi") is not None)
    if not obs:
        return dict(banda="sin_dato", indice=None, m3_estimado_min=None, m3_estimado_max=None, confianza="baja",
                    confianza_motivos=["sin escenas válidas en la ventana seca"], meses_secos=secos,
                    n_escenas_validas=n_anual_val)
    area = float(p["props"].get("area_ha") or p["geom"].area)
    frac_verde = float(np.median([o.get("frac_verde", 0.0) for o in obs]))
    a_riego = area * frac_verde
    zv = float(np.mean([o["z_verdor"] for o in obs if o.get("z_verdor") is not None] or [0]))
    zh = float(np.mean([o["z_humedad"] for o in obs if o.get("z_humedad") is not None] or [0]))
    zhv = [o["z_humedad_verde"] for o in obs if o.get("z_humedad_verde") is not None]
    zhv = float(np.mean(zhv)) if zhv else None
    riego = a_riego >= A_RIEGO_MIN_HA and zhv is not None and zhv >= ZH_RIEGO
    # FAO-56 simplificado sobre el area regada estimada, 12 meses jul-jun
    ndv = interp([rec.get(m, {}).get("ndvi_verde") for m in anual])
    v = 0.0
    for k, m in enumerate(anual):
        cm = clima_c.get(m)
        if cm is None or ndv is None:
            continue
        mm = max(0.0, kc(ndv[k]) * cm["et0"] - PEF_FACTOR * cm["lluvia"])
        v += mm * 10.0 * a_riego
    # confianza
    motivos = []
    if meta["npx"].get(p["id"], 0) < 25:
        motivos.append("pocos píxeles")
    if len(obs) < max(2, len(secos) - 1) or n_anual_val < 8:
        motivos.append("pocas escenas válidas")
    nubs = [rec.get(m, {}).get("nubosidad_pct") for m in anual]
    nubs = [x for x in nubs if x is not None]
    if nubs and sum(nubs) / len(nubs) > 20:
        motivos.append("nubosidad alta")
    if meta["ref_cerca_ha"].get(p["id"], 0) < 20:
        motivos.append("sin referencia de secano cercana")
    if area > 150:
        motivos.append("predio muy grande (señal diluida)")
    if p["props"].get("geom_aprox"):
        motivos.append("geometría aproximada")
    if der.get("estado") == "con_derechos" and der.get("conf") == "baja":
        motivos.append("cruce de derechos con confianza baja")
    dc = p["props"].get("dist_canal_m")
    if p["props"].get("zona") == "z2" and dc is not None and dc <= 300 and d_rol(der) <= 0:
        # en Z2 el Aconcagua si trae agua por canal (acciones de comunidades, no inscritas por rol)
        motivos.append("posible agua de canal no registrada en el rol")
    conf = "alta" if not motivos else ("media" if len(motivos) == 1 else "baja")
    w = CONF_W[conf]
    r = CONF_RANGO[conf]
    d = der.get("m3", 0.0)
    exceso = v - d
    if not riego:
        banda, indice = "sin_alerta", 0.0
    else:
        frac = max(0.0, exceso) / v if v > 0 else 0.0
        s_ = min(1.0, math.sqrt(max(0.0, exceso) / EXCESO_ESCALA_M3))
        indice = w * frac * s_
        banda = "alta" if indice >= 0.6 else ("media" if indice >= 0.3 else "baja")
        if banda == "alta" and conf == "baja":
            banda = "media"   # alta exige confianza media o alta
    return dict(
        banda=banda, indice=round(indice, 3), riego_ventana_seca=bool(riego),
        m3_estimado_min=int(round(v * (1 - r), -2)), m3_estimado_max=int(round(v * (1 + r), -2)),
        m3_derecho_rol=int(round(d)), estado_derechos=der.get("estado"),
        exceso_min=int(round(v * (1 - r) - d, -2)), exceso_max=int(round(v * (1 + r) - d, -2)),
        area_riego_ha=round(a_riego, 2), frac_verde=round(frac_verde, 3),
        z_verdor_seco=round(zv, 2), z_humedad_seco=round(zh, 2), z_humedad_verde=r3(zhv) if zhv is not None else None,
        ndvi_seca=r3(np.mean([o["ndvi"] for o in obs])),
        confianza=conf, confianza_motivos=motivos, meses_secos=secos, n_escenas_validas=n_anual_val,
    )


# ---------------------------------------------------------------- ruta
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


def build_ruta(z, predios, scores):
    plaza = ZONAS[z]["plaza"]
    elig = [p for p in predios if scores[p["id"]]["banda"] in ("alta", "media")]
    sel = sorted(elig, key=lambda p: -scores[p["id"]]["indice"])[:N_RUTA]
    if not sel:
        return None
    for p in sel:
        g = p["geom"]
        ext = list((g.exterior if g.geom_type == "Polygon" else max(g.geoms, key=lambda q: q.area).exterior).coords)
        a = min(ext, key=lambda q: haversine_km(q, (plaza["lon"], plaza["lat"])))
        p["punto_acceso"] = [round(a[0], 5), round(a[1], 5)]
    pts = [(plaza["lon"], plaza["lat"])] + [tuple(p["punto_acceso"]) for p in sel]
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
    geom["coordinates"] = [[round(x, 6), round(y, 6)] for x, y in geom["coordinates"]]
    t = dt.datetime(2026, 1, 1, 8, 30)
    acc_km, paradas = 0.0, []
    for k in range(1, len(order) - 1):
        d, du = legs[k - 1]
        acc_km += d / 1000; t += dt.timedelta(seconds=du)
        p = sel[order[k] - 1]
        sc = scores[p["id"]]
        paradas.append(dict(orden=k, predio_id=p["id"], rol=p["props"].get("rol"), comuna=p["props"].get("comuna"),
                            caso=p["props"].get("caso"), banda=sc["banda"], indice=sc["indice"],
                            lon=round(seq[k][0], 5), lat=round(seq[k][1], 5), llegada=t.strftime("%H:%M"),
                            permanencia_min=PERMANENCIA_MIN, distancia_km_acum=round(acc_km, 1)))
        t += dt.timedelta(minutes=PERMANENCIA_MIN)
    d, du = legs[-1]
    acc_km += d / 1000; t += dt.timedelta(seconds=du)
    total_drive = sum(l[1] for l in legs) / 60
    return dict(
        illustrative=False, provisional=True, temporada=TEMPORADA,
        nota=("Orden y geometria reales (OSRM sobre OpenStreetMap). Seleccion: predios en banda alta y media "
              f"(maximo {N_RUTA}) por indice provisional de la temporada {TEMPORADA}. Punto de cada parada: vertice del "
              "predio mas cercano a la plaza, proyectado por OSRM al camino."),
        inicio=plaza, paradas=paradas,
        regreso=dict(nombre=plaza["nombre"], llegada=t.strftime("%H:%M"), distancia_km_acum=round(acc_km, 1)),
        geometry=geom, distancia_km=round(acc_km, 1),
        duracion_min=round(total_drive + PERMANENCIA_MIN * len(paradas)), duracion_manejo_min=round(total_drive),
        solver=solver, router=router, matriz=matriz, ida_y_vuelta=True,
    )


def write_gpx(z, ruta, path):
    def esc(s):
        return str(s).replace("&", "&amp;").replace("<", "&lt;")
    L = ['<?xml version="1.0" encoding="UTF-8"?>',
         '<gpx version="1.1" creator="Caudal (demo hackathon)" xmlns="http://www.topografix.com/GPX/1/1">',
         f'  <metadata><name>Caudal - ruta de inspeccion {ZONAS[z]["codigo"]} {esc(ZONAS[z]["nombre"])}</name>'
         '<desc>El sistema prioriza, no acusa. Bandas provisionales.</desc></metadata>',
         f'  <wpt lat="{ruta["inicio"]["lat"]}" lon="{ruta["inicio"]["lon"]}"><name>Inicio - {esc(ruta["inicio"]["nombre"])}</name>'
         f'<desc>Salida {ruta["inicio"]["hora"]}</desc></wpt>']
    for p in ruta["paradas"]:
        L.append(f'  <wpt lat="{p["lat"]}" lon="{p["lon"]}"><name>{p["orden"]}. Predio {p["predio_id"]} (rol {esc(p["rol"])})</name>'
                 f'<desc>Banda {p["banda"]} (provisional) - llegada {p["llegada"]} - {p["permanencia_min"]} min</desc></wpt>')
    L.append('  <trk><name>Ruta de inspeccion</name><trkseg>')
    for lon, lat in ruta["geometry"]["coordinates"]:
        L.append(f'    <trkpt lat="{lat:.6f}" lon="{lon:.6f}"/>')
    L += ['  </trkseg></trk>', '</gpx>']
    with open(path, "w") as f:
        f.write("\n".join(L) + "\n")


# ---------------------------------------------------------------- casos: senal antes de la inspeccion
def resumen_casos(z, predios, historico, series):
    p = os.path.join(OUT, "casos.json")
    casos = json.load(open(p)) if os.path.exists(p) else []
    out = {}
    for p_ in predios:
        exp = p_["props"].get("caso")
        if not exp:
            continue
        c = next((c for c in casos if c.get("expediente") == exp), {})
        fi = c.get("fecha_inspeccion")
        h = historico.get(p_["id"], {})
        prev = []
        for t in TEMPORADAS:
            if t not in h or h[t] is None:
                continue
            _, seca = temporada_meses(t)
            if fi and seca[0] + "-01" < fi:   # la ventana seca empieza antes de la inspeccion
                prev.append(t)
        alta_prev = [t for t in prev if h[t]["banda"] == "alta"]
        riego_prev = [t for t in prev if h[t].get("riego_ventana_seca")]
        out[exp] = dict(predio_id=p_["id"], fecha_inspeccion=fi,
                        temporadas_previas=prev, temporadas_alta_previas=alta_prev,
                        temporadas_riego_previas=riego_prev,
                        primera_alta=alta_prev[0] if alta_prev else None,
                        temporada_inspeccion=prev[-1] if prev else None,
                        banda_temporada_inspeccion=h[prev[-1]]["banda"] if prev else None)
    return out


# ---------------------------------------------------------------- README
README = """# Datos por zona — series, puntajes y rutas (Caudal v2)

> **El sistema prioriza, no acusa.** Predios por ID CIREN y rol; sin nombres. Las bandas son **provisionales**
> hasta el modelo M5 del equipo. Los 10 casos son expedientes **resueltos** por la DGA (sancionados).

Generado por `scripts/build_zonas_scores.py` (series, scores, ruta) y `scripts/build_zonas_data.py` (predios,
clima, casos, fiscalizaciones). Ambos son re-ejecutables; las llamadas externas se cachean en `scripts/.cache/zonas/`.

## Qué es real y qué es provisional

| Archivo | Real | Provisional |
|---|---|---|
| `{z}/predios.geojson` | Polígonos CIREN 2022, rol, derechos DGA del rol (temporada 2025-26), especie (Catastro Frutícola 2025) | — |
| `{z}/clima.json` | Lluvia Open-Meteo corregida con estaciones DMC, ET0, ventanas secas N=10 (equipo) | — |
| `{z}/series.json` | NDVI/NDMI Sentinel-2 L2A (Earth Search), 1 escena por mes y tesela, mediana por predio | Referencia de secano = píxeles CONAF (matorral/pradera estable) en la ventana |
| `{z}/scores.json` | Consumo FAO-56 con NDVI real, ET0/lluvia reales, derechos reales del rol | Umbrales, Kc(NDVI), pesos de confianza, bandas (`provisional: true`) |
| `{z}/ruta.json`, `ruta.gpx` | Orden óptimo ({solver}) y geometría por camino ({router}) | La selección depende de las bandas provisionales |

## Método

1. **Escenas**: Sentinel-2 L2A, Element84 Earth Search (COG en AWS). Por tesela MGRS y mes, se prueban hasta
   {ncand} escenas en orden de nubosidad de la tesela y se elige la con más píxeles despejados (SCL 4/5/6/7/11)
   sobre los predios. Lectura a {res} m (overview 2x de B04/B08, nativo B8A/B11/SCL), en una ventana alrededor de
   los predios + {margen} km. Meses: {m0} a {m1}. Teselas: {tiles}.
2. **Offset BOA (corregido)**: desde la baseline 04.00 los DN traen +1000. Earth Search ya los re-armonizó en
   parte de las escenas, pero `earthsearch:boa_offset_applied` no es confiable (p. ej. `S2C_19HBE_20241108_1`
   dice `False` y ya está armonizada). Se decide **con los datos**: si el percentil 1 de B04 sobre vegetación/suelo
   (SCL 4/5) es > {umbral} DN, se resta 1000; si no, no. Reflectancia = (DN − offset)/10000. Se resta **una sola vez**
   (el bug D15 del `serie_predio` del equipo la restaba dos veces). Validación en la tabla de abajo.
3. **Índices**: NDVI = (B08−B04)/(B08+B04); NDMI = (B8A−B11)/(B8A+B11); mediana por predio de píxeles válidos SCL
   (nubes 3/8/9/10 descartadas; `nubosidad_pct` = % del predio con nube). Se exige ≥ 30 % del predio válido.
4. **Referencia de secano**: polígonos CONAF del equipo (`referencia_secano.parquet`, matorral y pradera estable,
   sin huertos) dentro de la ventana, a > 60 m de los predios. Mediana y MAD mensual por tesela.
   `z = (índice_predio − mediana_ref) / max(0,02; 1,4826·MAD)`.
5. **Área regada en seca**: píxeles del predio con NDVI > max({vmin}; ref + {vz}·MAD) en los meses secos.
   `area_riego_ha = área × mediana(frac_verde)`. Evita que un cerro de 900 ha "consuma" como huerto.
6. **Ventana seca**: mes seco = ≥ {seco} días dentro de una ventana seca (N=10 días sin lluvia efectiva) de la celda
   de clima del predio (`dias_sin_lluvia.parquet` del equipo). Se miran dic–mar de cada temporada.
7. **Riego probable en ventana seca**: `area_riego_ha ≥ {amin}` y anomalía de humedad del área verde
   (`z_humedad_verde`, NDMI) ≥ {zh} en los meses secos (verdor y humedad sobre la referencia a la vez).
8. **Consumo (FAO-56 simplificado)**, temporada jul–jun:
   `V = Σ_mes max(0, Kc(NDVI_verde)·ET0 − {pef}·P) · area_riego`, `Kc = clamp({a}·NDVI + {b}, {kmin}, {kmax})`,
   ET0 y P (lluvia corregida) mensuales de la celda del predio. 1 mm·ha = 10 m³. Meses sin escena: interpolación.
9. **Rango, no número**: `m3_estimado_min/max = V·(1 ∓ r)`, r = 20 / 27 / 35 % según confianza alta / media / baja.
10. **Confianza**: baja un nivel por motivo (`pocos píxeles` < 25 px, `pocas escenas válidas`, `nubosidad alta`
    > 20 %, `sin referencia de secano cercana` < 20 ha CONAF a 3 km, `predio muy grande` > 150 ha,
    `geometría aproximada`, `cruce de derechos con confianza baja` solo si el rol tiene derechos, y en Z2
    `posible agua de canal no registrada en el rol` si el rol no tiene derechos y hay canal a ≤ 300 m: en el
    Aconcagua el canal sí trae agua por acciones de comunidades que no se inscriben por rol). Los derechos del
    entorno **no** bajan la confianza (riesgo del caso FD-0501-181 en el spec). Peso w = 1 / 0,85 / 0,65.
11. **Índice y banda** (`m3_derecho_rol` real de la temporada, `predio_derecho.parquet`):
    sin riego en ventana seca → `sin_alerta`; con riego, `exceso = V − derecho`,
    `indice = w · max(0, exceso)/V · min(1, √(exceso/{esc}))`; alta ≥ 0,60, media ≥ 0,30, si no `baja`
    (riego dentro de los derechos = prioridad baja, como dice el spec). `alta` exige confianza media o alta (si no,
    queda en `media`). `sin_dato` si no hay escenas en la seca.
12. **Histórico**: lo mismo para cada temporada {t0}…{t1} con los derechos vigentes a esa temporada
    (`scores.json → predios[id].historico`). `scores.json → casos` resume, para cada caso, las temporadas cuya ventana
    seca empezó antes de la inspección y en cuáles el predio ya estaba en banda alta.
13. **Ruta**: sale de la plaza de la comuna principal (Z1 Cabildo, Z2 Hijuelas) a las 08:30, visita alta + media
    (máx. {nruta}) por índice, {perm} min por parada, ida y vuelta. Matriz OSRM (servidor demo público) + TSP OR-Tools.

## Resultado de esta corrida ({fecha})

{resultado}

## Validación del offset (escenas con flag y percentil 1 de B04)

{offsets}
"""


# ---------------------------------------------------------------- main
def main():
    args = sys.argv[1:]
    zonas = ["z1", "z2"]
    wait_s = 600
    if "--zonas" in args:
        zonas = args[args.index("--zonas") + 1].split(",")
    if "--wait-predios" in args:
        wait_s = int(args[args.index("--wait-predios") + 1])
    os.makedirs(CACHE, exist_ok=True)
    bboxes = json.load(open(os.path.join(OUT, "bbox.json")))
    resultado, off_rows, run_meta = [], [], {}
    for z in zonas:
        log(f"=== {z} {ZONAS[z]['nombre']}")
        predios, src = load_predios(z, wait_s)
        ids = [p["id"] for p in predios]
        der = derechos_por_temporada(ids)
        celdas = celda_de_predios(predios)
        clima = clima_por_celda(sorted({c for c in celdas.values() if c}))
        log("  Sentinel-2")
        series, ref_series, meta = s2_zone(z, predios, bboxes[z])
        add_z(series, ref_series, meta["asig"])

        scores, historico = {}, {}
        for p in predios:
            cl = clima.get(celdas.get(p["id"]), {})
            h = {}
            for t in TEMPORADAS:
                dd = der.get(p["id"], {}).get(t)
                if dd is None:
                    dd = dict(m3=float(p["props"].get("m3_derecho_rol") or 0), estado=p["props"].get("estado_derechos"),
                              conf=p["props"].get("confianza_cruce"))
                h[t] = score_temporada(p, series[p["id"]], cl, dd, t, meta)
            historico[p["id"]] = h
            cur = dict(h[TEMPORADA] or dict(banda="sin_dato", indice=None, confianza="baja",
                                            confianza_motivos=["sin escenas"]))
            t = meta["asig"].get(p["id"])
            _, seca = temporada_meses(TEMPORADA)
            refv = [r["ndvi"] for r in ref_series.get(t, []) if r["fecha"] in seca and r.get("ndvi") is not None]
            cur["ndvi_ref"] = r3(np.mean(refv)) if refv else None
            cur["tesela"] = t
            cur["historico"] = {k: ({kk: vv for kk, vv in v.items() if kk not in ("meses_secos",)} if v else None)
                                for k, v in h.items() if k != TEMPORADA}
            scores[p["id"]] = cur
        counts = {b: sum(1 for s in scores.values() if s["banda"] == b) for b in ("alta", "media", "baja", "sin_alerta", "sin_dato")}
        casos = resumen_casos(z, predios, historico, series)
        zdir = os.path.join(OUT, z)
        os.makedirs(zdir, exist_ok=True)
        with open(os.path.join(zdir, "scores.json"), "w") as f:
            json.dump(dict(
                provisional=True,
                metodo=("FAO-56 simplificado (Kc lineal en NDVI del area verde, ET0 y lluvia corregida del equipo) sobre el "
                        "area regada en meses secos, contra m3_anual_derecho_rol real de la temporada; banda solo si hay "
                        "riego probable en ventana seca. Provisional hasta M5. Ver data/zonas/README.md"),
                temporada=TEMPORADA, periodo_consumo="2025-07 a 2026-06", generado=TODAY.isoformat(),
                umbrales=dict(alta=0.6, media=0.3, a_riego_min_ha=A_RIEGO_MIN_HA, z_humedad_verde_min=ZH_RIEGO,
                              exceso_escala_m3=EXCESO_ESCALA_M3),
                counts=counts, casos=casos, predios=scores), f, ensure_ascii=False)

        ref_main = max(meta["tiles"], key=lambda t: sum(v == t for v in meta["asig"].values()))
        ser = dict(
            illustrative=False,
            fuente="Sentinel-2 L2A (Element84 Earth Search STAC, COG AWS), teselas " + ", ".join(meta["tiles"]),
            resolucion_m=S2_RES,
            metodo=("1 escena por mes y tesela (la mas despejada sobre los predios entre las 3 menos nubosas), mediana por "
                    "predio de pixeles validos SCL; NDVI=(B08-B04)/(B08+B04), NDMI=(B8A-B11)/(B8A+B11); offset BOA "
                    "decidido por escena con los datos (una sola vez)"),
            meses=MONTHS, escenas=meta["escenas"],
            predios=series, predio_tesela=meta["asig"],
            referencia_secano=dict(
                descripcion=("Mediana mensual de pixeles dentro de poligonos CONAF de matorral/pradera estable (equipo, "
                             "referencia_secano.parquet) en la ventana de la tesela, a >60 m de los predios"),
                tesela=ref_main, serie=ref_series[ref_main],
                por_tesela=ref_series),
            z_definicion="z = (indice_predio - mediana_ref) / max(0.02, 1.4826*MAD_ref); ref de la tesela del predio",
            campos=dict(frac_verde="fraccion del predio con NDVI > max(0.30, ref+3MAD)",
                        ndvi_verde="mediana NDVI de esos pixeles", ndmi_verde="idem NDMI",
                        z_humedad_verde="anomalia NDMI del area verde"),
        )
        txt = json.dumps(ser, ensure_ascii=False, separators=(",", ":"))
        with open(os.path.join(zdir, "series.json"), "w") as f:
            f.write(txt)

        log("  Ruta")
        ruta = build_ruta(z, predios, scores)
        if ruta:
            with open(os.path.join(zdir, "ruta.json"), "w") as f:
                json.dump(ruta, f, ensure_ascii=False)
            write_gpx(z, ruta, os.path.join(zdir, "ruta.gpx"))
        n_meses = sum(1 for m in MONTHS if m in meta["escenas"])
        resultado.append(
            f"- **{ZONAS[z]['codigo']} {ZONAS[z]['nombre']}**: {len(predios)} predios ({src}); teselas {', '.join(meta['tiles'])}; "
            f"{n_meses}/{len(MONTHS)} meses con escena; bandas {TEMPORADA}: "
            + ", ".join(f"{k} {v}" for k, v in counts.items())
            + (f"; ruta {ruta['distancia_km']} km, {ruta['duracion_min']} min, {len(ruta['paradas'])} paradas "
               f"({ruta['solver']}/{ruta['router']})" if ruta else "; sin ruta (no hay alta/media)")
            + (f"; {meta['n_pend']} escenas pendientes por time-box" if meta["n_pend"] else ""))
        for exp, c in casos.items():
            resultado.append(f"  - Caso {exp} (predio {c['predio_id']}, inspección {c['fecha_inspeccion']}): banda en la "
                             f"temporada previa {c['temporada_inspeccion']} = {c['banda_temporada_inspeccion']}; "
                             f"temporadas en alta antes de la inspección: {', '.join(c['temporadas_alta_previas']) or 'ninguna'}")
        seen = set()
        for k, o in sorted(meta["offsets"].items()):
            key = (o["baseline"] >= "04.00", o["flag_boa"], o["dn_offset"])
            if key in seen:
                continue
            seen.add(key)
            off_rows.append(f"| {o['scene']} | {o['baseline']} | {o['flag_boa']} | {o['p1_red']} | {int(o['dn_offset'])} |")
        run_meta[z] = dict(counts=counts, casos=casos)
        log(f"  {z}: bandas {counts}")
        for exp, c in casos.items():
            log(f"    {exp}: {c['temporada_inspeccion']} -> {c['banda_temporada_inspeccion']}; alta previas {c['temporadas_alta_previas']}")

    ruta_any = None
    for z in ("z1", "z2"):
        p = os.path.join(OUT, z, "ruta.json")
        if os.path.exists(p):
            ruta_any = json.load(open(p))
            break
    readme = README
    for k, v in dict(
        solver=(ruta_any or {}).get("solver", "OR-Tools"), router=(ruta_any or {}).get("router", "OSRM"),
        ncand=S2_CANDIDATOS, res=S2_RES, margen=REF_MARGIN_M / 1000, m0=MONTHS[0], m1=MONTHS[-1],
        tiles="Z1 19HBE + 19HCE, Z2 19HBD + 19HCD", umbral=DN_OFFSET_UMBRAL, vmin=VERDE_MIN, vz=VERDE_Z,
        seco=SECO_DIAS_MES, amin=A_RIEGO_MIN_HA, zh=ZH_RIEGO, pef=PEF_FACTOR, a=KC_A, b=KC_B, kmin=KC_MIN, kmax=KC_MAX,
        esc=EXCESO_ESCALA_M3, t0=TEMPORADAS[0], t1=TEMPORADAS[-1], nruta=N_RUTA, perm=PERMANENCIA_MIN,
        fecha=TODAY.isoformat(), resultado="\n".join(resultado),
        offsets="| Escena | Baseline | boa_offset_applied | p1 B04 (DN) | Offset restado |\n|---|---|---|---|---|\n" + "\n".join(off_rows),
    ).items():
        readme = readme.replace("{" + k + "}", str(v))
    if zonas == ["z1", "z2"]:
        with open(os.path.join(OUT, "README.md"), "w") as f:
            f.write(readme)
    log("listo")
    os._exit(0)


if __name__ == "__main__":
    main()
