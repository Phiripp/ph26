#!/usr/bin/env python3
"""Cache satellite (EOX Sentinel-2 cloudless 2023) + DEM (AWS Terrarium) tiles over Chile,
and build data/world.geojson (neighbour countries for the black mask in js/map.js).

Usage (from mockups/):
  python3 scripts/cache_tiles.py            # download z3..z9 (falls back to z8 if over budget)
  python3 scripts/cache_tiles.py --dry-run  # only print tile counts per zoom

Outputs:
  tiles/s2/{z}/{x}/{y}.jpg   EOX s2cloudless-2023 (EOX URL is .../{z}/{y}/{x}.jpg; stored XYZ)
  tiles/dem/{z}/{x}/{y}.png  AWS Terrarium elevation
  tiles/index.json           {"s2":{minzoom,maxzoom,count,bytes},"dem":{...},"bounds":[w,s,e,n]}
  data/world.geojson         Natural Earth 1:50m admin-0, South America + neighbours, without Chile

Tile set = tiles intersecting Chile (mainland + Chiloé + Patagonian archipelagos; far islands
west of -77° such as Rapa Nui / Juan Fernández are skipped), buffered ~10 km.
Existing files are skipped, so re-running is cheap and resumes interrupted runs.
Stdlib + Pillow only.
"""
import json
import math
import os
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHILE = os.path.join(ROOT, "data", "chile.geojson")
WORLD = os.path.join(ROOT, "data", "world.geojson")
TILES = os.path.join(ROOT, "tiles")
CACHE = os.environ.get("NE_CACHE") or os.path.join(__import__("tempfile").gettempdir(), "caudal-ne-cache")  # raw Natural Earth downloads

UA = "caudal-hackathon-mockup"
WORKERS = 6
MINZOOM, MAXZOOM = 3, 9
BUDGET_BYTES = 120 * 1024 * 1024
WEST_LIMIT = -77.0       # drop island polygons west of this longitude
BUFFER_KM = 10.0
RASTER_Z = 13            # helper raster resolution (px ~ 3.7 km at 35°S)

SOURCES = {
    "s2": ("https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-2023_3857/default/g/{z}/{y}/{x}.jpg", "jpg"),
    "dem": ("https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png", "png"),
}
NE_50M = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_admin_0_countries.geojson"
NE_10M = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_admin_0_countries.geojson"
WORLD_BBOX = (-95.0, -60.0, -30.0, 15.0)


# ---------------------------------------------------------------- helpers
def http_get(url, retries=4, timeout=30):
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            last = e
        except Exception as e:  # noqa: BLE001
            last = e
        time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"failed {url}: {last}")


def lonlat_to_px(lon, lat, z):
    n = 2 ** z
    x = (lon + 180.0) / 360.0 * n
    lat = max(min(lat, 85.0511), -85.0511)
    r = math.radians(lat)
    y = (1.0 - math.log(math.tan(r) + 1.0 / math.cos(r)) / math.pi) / 2.0 * n
    return x, y


def tile_to_lonlat(x, y, z):
    n = 2 ** z
    lon = x / n * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    return lon, lat


def polys_of(geom):
    if geom["type"] == "Polygon":
        return [geom["coordinates"]]
    if geom["type"] == "MultiPolygon":
        return geom["coordinates"]
    return []


def bbox_of(rings):
    xs = [p[0] for r in rings for p in r]
    ys = [p[1] for r in rings for p in r]
    return min(xs), min(ys), max(xs), max(ys)


def dp(points, tol):
    """Douglas-Peucker simplification (iterative)."""
    if len(points) < 5:
        return points
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        a, b = stack.pop()
        ax, ay = points[a]
        bx, by = points[b]
        dx, dy = bx - ax, by - ay
        L = math.hypot(dx, dy) or 1e-12
        best, idx = -1.0, -1
        for i in range(a + 1, b):
            px, py = points[i]
            d = abs(dy * px - dx * py + bx * ay - by * ax) / L
            if d > best:
                best, idx = d, i
        if best > tol and idx > 0:
            keep[idx] = True
            stack.append((a, idx))
            stack.append((idx, b))
    out = [p for p, k in zip(points, keep) if k]
    return out if len(out) >= 4 else points


# ---------------------------------------------------------------- Chile geometry
def load_ne(url, name):
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, name)
    if not os.path.exists(path):
        print(f"downloading {url}")
        data = http_get(url, timeout=120)
        with open(path, "wb") as f:
            f.write(data)
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def is_chile(props):
    return props.get("ADM0_A3") == "CHL" or props.get("ISO_A3") == "CHL" or props.get("NAME") == "Chile"


def load_chile_polys():
    try:
        with open(CHILE, encoding="utf-8") as f:
            fc = json.load(f)
        polys = [p for feat in fc["features"] for p in polys_of(feat["geometry"])]
        if not polys:
            raise ValueError("empty")
    except Exception as e:  # noqa: BLE001
        print(f"data/chile.geojson missing/broken ({e}); rebuilding from Natural Earth 1:50m")
        ne = load_ne(NE_50M, "ne_50m_admin_0_countries.geojson")
        feat = next(f for f in ne["features"] if is_chile(f["properties"]))
        out = {"type": "FeatureCollection", "features": [{
            "type": "Feature",
            "properties": {"name": "Chile", "source": "Natural Earth 1:50m admin-0 (public domain)"},
            "geometry": feat["geometry"]}]}
        with open(CHILE, "w", encoding="utf-8") as f:
            json.dump(out, f, separators=(",", ":"))
        polys = polys_of(feat["geometry"])
    kept = [p for p in polys if bbox_of(p)[2] > WEST_LIMIT]
    return kept


def chile_mask(polys):
    """Rasterize Chile (buffered) on a crop of the z=RASTER_Z pixel grid (1 px = 1 tile at RASTER_Z)."""
    w, s, e, n = (min(bbox_of(p)[0] for p in polys), min(bbox_of(p)[1] for p in polys),
                  max(bbox_of(p)[2] for p in polys), max(bbox_of(p)[3] for p in polys))
    pad = 0.5
    x0, y0 = lonlat_to_px(w - pad, n + pad, RASTER_Z)
    x1, y1 = lonlat_to_px(e + pad, s - pad, RASTER_Z)
    x0, y0, x1, y1 = int(x0), int(y0), int(math.ceil(x1)), int(math.ceil(y1))
    img = Image.new("L", (x1 - x0, y1 - y0), 0)
    dr = ImageDraw.Draw(img)
    for poly in polys:
        for k, ring in enumerate(poly):
            pts = [lonlat_to_px(lon, lat, RASTER_Z) for lon, lat in ring]
            pts = [(px - x0, py - y0) for px, py in pts]
            if k == 0:
                dr.polygon(pts, fill=255)
            # outline everything (holes too) with a width that covers the buffer
            lat_mid = sum(p[1] for p in ring) / len(ring)
            px_km = 40075.0 * math.cos(math.radians(lat_mid)) / (2 ** RASTER_Z)
            width = max(1, int(round(2 * BUFFER_KM / px_km)) + 1)
            dr.line(pts + [pts[0]], fill=255, width=width, joint="curve")
    return img, (x0, y0), (w, s, e, n)


def tiles_for_zoom(mask, origin, z):
    x0, y0 = origin
    f = 2 ** (RASTER_Z - z)
    px = mask.load()
    W, H = mask.size
    out = set()
    for yy in range(H):
        for xx in range(W):
            if px[xx, yy]:
                out.add(((xx + x0) // f, (yy + y0) // f))
    return sorted(out)


# ---------------------------------------------------------------- downloads
def fetch_tile(kind, z, x, y):
    tmpl, ext = SOURCES[kind]
    path = os.path.join(TILES, kind, str(z), str(x), f"{y}.{ext}")
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return path, os.path.getsize(path), "skip"
    data = http_get(tmpl.format(z=z, x=x, y=y))
    if not data:
        return path, 0, "missing"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".part"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)
    return path, len(data), "ok"


def download_zoom(z, tiles):
    jobs = [(k, z, x, y) for k in SOURCES for (x, y) in tiles]
    stats = {"ok": 0, "skip": 0, "missing": 0, "fail": 0}
    nbytes = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(fetch_tile, *j): j for j in jobs}
        for i, fut in enumerate(as_completed(futs), 1):
            try:
                _, b, st = fut.result()
                stats[st] += 1
                nbytes += b
            except Exception as e:  # noqa: BLE001
                stats["fail"] += 1
                print(f"  ! {futs[fut]}: {e}")
            if i % 200 == 0:
                print(f"  z{z}: {i}/{len(jobs)}")
    print(f"  z{z}: {stats}, {nbytes / 1e6:.1f} MB")
    return stats


def dir_stats(kind, maxzoom):
    count = nbytes = 0
    for z in range(MINZOOM, maxzoom + 1):
        d = os.path.join(TILES, kind, str(z))
        for dp_, _, files in os.walk(d):
            for fn in files:
                if not fn.endswith(".part"):
                    count += 1
                    nbytes += os.path.getsize(os.path.join(dp_, fn))
    return count, nbytes


def list_tiles(kind, maxzoom):
    """Sorted "z/x/y" keys of the cached tiles. The map serves a blank tile for any key not in
    this list instead of requesting it: a 404 inside a terrain tile makes MapLibre fall back to a
    blurry parent tile for the whole terrain tile."""
    keys = []
    for z in range(MINZOOM, maxzoom + 1):
        d = os.path.join(TILES, kind, str(z))
        if not os.path.isdir(d):
            continue
        for xs in os.listdir(d):
            xd = os.path.join(d, xs)
            if not (xs.isdigit() and os.path.isdir(xd)):
                continue
            for fn in os.listdir(xd):
                y = fn.split(".")[0]
                if y.isdigit() and not fn.endswith(".part"):
                    keys.append((z, int(xs), int(y)))
    return [f"{z}/{x}/{y}" for z, x, y in sorted(keys)]


def remove_zoom(z):
    import shutil
    for kind in SOURCES:
        shutil.rmtree(os.path.join(TILES, kind, str(z)), ignore_errors=True)


# ---------------------------------------------------------------- world.geojson
def build_world():
    ne = load_ne(NE_50M, "ne_50m_admin_0_countries.geojson")
    W, S, E, N = WORLD_BBOX
    feats = []
    for f in ne["features"]:
        props = f["properties"]
        if is_chile(props) or not f.get("geometry"):
            continue
        polys = []
        for poly in polys_of(f["geometry"]):
            bw, bs, be, bn = bbox_of(poly[:1])
            if be < W or bw > E or bn < S or bs > N:
                continue
            rings = []
            for ring in poly:
                r = dp([(round(x, 4), round(y, 4)) for x, y in ring], 0.02)
                r = [[round(x, 3), round(y, 3)] for x, y in r]
                if len(r) >= 4:
                    if r[0] != r[-1]:
                        r.append(r[0])
                    rings.append(r)
            if rings:
                polys.append(rings)
        if not polys:
            continue
        name = props.get("NAME") or props.get("ADMIN") or ""
        geom = {"type": "Polygon", "coordinates": polys[0]} if len(polys) == 1 else \
               {"type": "MultiPolygon", "coordinates": polys}
        feats.append({"type": "Feature", "properties": {"name": name}, "geometry": geom})
    feats.sort(key=lambda f: f["properties"]["name"])
    with open(WORLD, "w", encoding="utf-8") as fh:
        json.dump({"type": "FeatureCollection", "features": feats}, fh, separators=(",", ":"))
    print(f"world.geojson: {len(feats)} countries, {os.path.getsize(WORLD) / 1024:.0f} KB "
          f"({', '.join(f['properties']['name'] for f in feats)})")


# ---------------------------------------------------------------- main
def main():
    dry = "--dry-run" in sys.argv
    polys = load_chile_polys()
    mask, origin, bounds = chile_mask(polys)
    plan = {z: tiles_for_zoom(mask, origin, z) for z in range(MINZOOM, MAXZOOM + 1)}
    for z, t in plan.items():
        print(f"z{z}: {len(t)} tiles")
    print(f"total per source: {sum(len(t) for t in plan.values())}")
    if dry:
        return

    if "--skip-world" not in sys.argv:
        build_world()

    maxzoom = MINZOOM - 1
    for z in range(MINZOOM, MAXZOOM + 1):
        if z == MAXZOOM:
            # estimate z9 from average tile size so far; z9 ~ the bulk of the bytes
            c_s2, b_s2 = dir_stats("s2", z - 1)
            c_dem, b_dem = dir_stats("dem", z - 1)
            avg = (b_s2 + b_dem) / max(1, (c_s2 + c_dem) / 2)  # bytes per (s2+dem) pair
            est = b_s2 + b_dem + avg * len(plan[z])
            print(f"estimated total incl. z{z}: {est / 1e6:.1f} MB (budget {BUDGET_BYTES / 1e6:.0f} MB)")
            if est > BUDGET_BYTES:
                print(f"skipping z{z}: over budget")
                break
        print(f"downloading z{z} ({len(plan[z])} tiles x {len(SOURCES)} sources)")
        stats = download_zoom(z, plan[z])
        maxzoom = z
        if stats["fail"]:
            print(f"  warning: {stats['fail']} failures at z{z} (re-run to retry)")

    # if the real total blew the budget, drop the top zoom
    tot = sum(dir_stats(k, maxzoom)[1] for k in SOURCES)
    if tot > BUDGET_BYTES and maxzoom == MAXZOOM:
        print(f"real total {tot / 1e6:.1f} MB over budget; dropping z{maxzoom}")
        remove_zoom(maxzoom)
        maxzoom -= 1

    index = {}
    for kind in SOURCES:
        c, b = dir_stats(kind, maxzoom)
        index[kind] = {"minzoom": MINZOOM, "maxzoom": maxzoom, "count": c, "bytes": b,
                       "tiles": list_tiles(kind, maxzoom)}
    # bounds of the cached tile set (covering tiles at maxzoom)
    xs = [x for x, _ in plan[maxzoom]]
    ys = [y for _, y in plan[maxzoom]]
    w, n = tile_to_lonlat(min(xs), min(ys), maxzoom)
    e, s = tile_to_lonlat(max(xs) + 1, max(ys) + 1, maxzoom)
    index["bounds"] = [round(w, 4), round(s, 4), round(e, 4), round(n, 4)]
    index["chile_bounds"] = [round(v, 4) for v in bounds]
    index["generated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    os.makedirs(TILES, exist_ok=True)
    with open(os.path.join(TILES, "index.json"), "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2)
    print(json.dumps(index, indent=2))


if __name__ == "__main__":
    main()
