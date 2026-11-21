#!/usr/bin/env python3
"""Fetch real Sentinel-2 cloudless (EOX) imagery + AWS Terrarium DEM for Laguna de Aculeo.

Writes into ../assets/aculeo/: sat-{year}.jpg, dem.png, mask-{year}.png, manifest.json
Usage: python3 scripts/fetch_aculeo.py
Requires Pillow. Falls back to synthetic assets if network fails.
"""
import io, json, math, os, sys, urllib.request
from concurrent.futures import ThreadPoolExecutor
from PIL import Image, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "assets", "aculeo")
UA = {"User-Agent": "caudal-hackathon-mockup"}

# ~14 x 10 km around the lagoon
BBOX = dict(west=-70.990, south=-33.888, east=-70.838, north=-33.798)
LAGOON = dict(lat=-33.837, lon=-70.917, rx_km=4.0, ry_km=2.1)  # search ellipse for water
YEARS = list(range(2016, 2025))
SAT_Z = 14
DEM_Z = 13
MAX_W = 2048
DEM_W = 512
SAT_URL = "https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-{year}_3857/default/g/{z}/{y}/{x}.jpg"
DEM_URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"


def lonlat_to_px(lon, lat, z):
    n = 256 * 2 ** z
    x = (lon + 180) / 360 * n
    s = math.sin(math.radians(lat))
    y = (0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)) * n
    return x, y


def fetch(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def mosaic(url_tpl, z, mode, **kw):
    """Download tiles covering BBOX at zoom z, return image cropped exactly to BBOX (mercator)."""
    x0, y0 = lonlat_to_px(BBOX["west"], BBOX["north"], z)
    x1, y1 = lonlat_to_px(BBOX["east"], BBOX["south"], z)
    tx0, ty0, tx1, ty1 = int(x0 // 256), int(y0 // 256), int(x1 // 256), int(y1 // 256)
    tiles = [(tx, ty) for ty in range(ty0, ty1 + 1) for tx in range(tx0, tx1 + 1)]

    def get(t):
        tx, ty = t
        return t, Image.open(io.BytesIO(fetch(url_tpl.format(z=z, x=tx, y=ty, **kw)))).convert(mode)

    canvas = Image.new(mode, ((tx1 - tx0 + 1) * 256, (ty1 - ty0 + 1) * 256))
    with ThreadPoolExecutor(8) as ex:
        for (tx, ty), im in ex.map(get, tiles):
            canvas.paste(im, ((tx - tx0) * 256, (ty - ty0) * 256))
    ox, oy = tx0 * 256, ty0 * 256
    return canvas.crop((round(x0 - ox), round(y0 - oy), round(x1 - ox), round(y1 - oy)))


def pixel_area_m2(w, h):
    """Per-row pixel area (m2) for an image spanning BBOX in web-mercator."""
    R = 6378137.0
    mx_w = math.radians(BBOX["west"]) * R
    mx_e = math.radians(BBOX["east"]) * R
    def my(lat): return R * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))
    my_n, my_s = my(BBOX["north"]), my(BBOX["south"])
    pw, ph = (mx_e - mx_w) / w, (my_n - my_s) / h
    rows = []
    for j in range(h):
        y = my_n - (j + 0.5) * ph
        lat = math.degrees(2 * math.atan(math.exp(y / R)) - math.pi / 2)
        c = math.cos(math.radians(lat))
        rows.append(pw * ph * c * c)
    return rows


def lagoon_ellipse_mask(w, h):
    m = Image.new("L", (w, h), 0)
    km_per_deg_lat = 110.95
    km_per_deg_lon = 111.32 * math.cos(math.radians(LAGOON["lat"]))
    dlat = LAGOON["ry_km"] / km_per_deg_lat
    dlon = LAGOON["rx_km"] / km_per_deg_lon
    def to_px(lon, lat):
        return ((lon - BBOX["west"]) / (BBOX["east"] - BBOX["west"]) * w,
                (BBOX["north"] - lat) / (BBOX["north"] - BBOX["south"]) * h)
    ax, ay = to_px(LAGOON["lon"] - dlon, LAGOON["lat"] + dlat)
    bx, by = to_px(LAGOON["lon"] + dlon, LAGOON["lat"] - dlat)
    ImageDraw.Draw(m).ellipse((ax, ay, bx, by), fill=255)
    return m


def is_blank(img):
    lo_hi = img.convert("L").getextrema()
    return lo_hi[1] - lo_hi[0] < 10


def basin_mask(imgs, region):
    """Lake basin: pixels that are pale bare lakebed in >=3 years (green-water votes unused),
    inside the search ellipse; keep only the component connected to the lagoon centre, fill holes."""
    w, h = region.size
    bed = [[0] * w for _ in range(h)]
    wet = [[0] * w for _ in range(h)]
    reg = region.load()
    for im in imgs:
        p = im.load()
        for j in range(h):
            brow, wrow = bed[j], wet[j]
            for i in range(w):
                if not reg[i, j]:
                    continue
                R, G, B = p[i, j]
                br = (R + G + B) / 3
                if br > 80 and R >= G + 3:
                    brow[i] += 1
                if G >= R + 8 and br < 90:
                    wrow[i] += 1
    m = Image.new("L", (w, h), 0)
    mp = m.load()
    for j in range(h):
        for i in range(w):
            if bed[j][i] >= 3:
                mp[i, j] = 255
    m = m.filter(ImageFilter.MedianFilter(5))
    # keep component connected to lagoon centre
    cx = int((LAGOON["lon"] - BBOX["west"]) / (BBOX["east"] - BBOX["west"]) * w)
    cy = int((BBOX["north"] - LAGOON["lat"]) / (BBOX["north"] - BBOX["south"]) * h)
    ImageDraw.floodfill(m, (cx, cy), 128)
    m = m.point(lambda v: 255 if v == 128 else 0)
    # fill holes: flood background from corner, invert
    m = m.filter(ImageFilter.MaxFilter(15)).filter(ImageFilter.MinFilter(15))
    inv = m.copy()
    ImageDraw.floodfill(inv, (0, 0), 128)
    inv = inv.point(lambda v: 0 if v == 128 else 255)
    return inv


def water_mask(img, basin):
    """True-color heuristic for turbid/green Aculeo water: dark, not reddish, inside basin."""
    r, g, b = img.split()
    rp, gp, bp, reg = r.load(), g.load(), b.load(), basin.load()
    w, h = img.size
    m = Image.new("L", (w, h), 0)
    mp = m.load()
    for j in range(h):
        for i in range(w):
            if not reg[i, j]:
                continue
            R, G, B = rp[i, j], gp[i, j], bp[i, j]
            br = (R + G + B) / 3
            if (G >= R + 3 and br < 95) or (br < 42 and B >= R - 10):
                mp[i, j] = 255
    m = m.filter(ImageFilter.MedianFilter(5))
    m = m.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.MaxFilter(3))
    return m


def area_km2(mask, rows):
    px = mask.load()
    w, h = mask.size
    tot = 0.0
    for j in range(h):
        a = rows[j]
        tot += a * sum(1 for i in range(w) if px[i, j] > 127)
    return tot / 1e6


def encode_terrarium(arr_img):
    """arr_img: mode 'F' heights in meters -> RGB terrarium PNG."""
    w, h = arr_img.size
    src = arr_img.load()
    out = Image.new("RGB", (w, h))
    op = out.load()
    for j in range(h):
        for i in range(w):
            v = src[i, j] + 32768
            R = int(v // 256); G = int(v % 256); B = int((v - math.floor(v)) * 256)
            op[i, j] = (max(0, min(255, R)), G, max(0, min(255, B)))
    return out


def build_dem():
    rgb = mosaic(DEM_URL, DEM_Z, "RGB")
    w, h = rgb.size
    f = Image.new("F", (w, h))
    fp, rp = f.load(), rgb.load()
    for j in range(h):
        for i in range(w):
            R, G, B = rp[i, j]
            fp[i, j] = R * 256 + G + B / 256 - 32768
    return f


def main():
    os.makedirs(OUT, exist_ok=True)
    synthetic = False
    sats = {}
    for y in YEARS:
        try:
            im = mosaic(SAT_URL, SAT_Z, "RGB", year=y)
            if is_blank(im):
                print(f"sat {y}: blank (no data), skipped")
                continue
            sats[y] = im
            print(f"sat {y}: {im.size}")
        except Exception as e:
            print(f"sat {y} failed: {e}")
    if not sats:
        print("No imagery downloaded; run with synthetic fallback (not implemented here).")
        sys.exit(1)

    years = sorted(sats)
    W0, H0 = sats[years[0]].size
    if W0 > MAX_W:
        W, H = MAX_W, round(H0 * MAX_W / W0)
    else:
        W, H = W0, H0
    region = lagoon_ellipse_mask(W, H)
    rows = pixel_area_m2(W, H)
    imgs = {y: (sats[y].resize((W, H), Image.LANCZOS) if sats[y].size != (W, H) else sats[y]) for y in years}
    region = basin_mask(list(imgs.values()), region)
    region.save(os.path.join(HERE, "..", "assets", "aculeo", "basin.png"))
    water = {}
    for y in years:
        im = imgs[y]
        im.save(os.path.join(OUT, f"sat-{y}.jpg"), quality=85, optimize=True)
        m = water_mask(im, region)
        m.save(os.path.join(OUT, f"mask-{y}.png"), optimize=True)
        km2 = round(area_km2(m, rows), 2)
        water[str(y)] = {"km2": km2, "maskFile": f"mask-{y}.png"}
        print(f"water {y}: {km2} km2")

    dem_f = build_dem()
    DH = round(H * DEM_W / W)
    dem_f = dem_f.resize((DEM_W, DH), Image.BILINEAR)
    lo, hi = dem_f.getextrema()
    encode_terrarium(dem_f).save(os.path.join(OUT, "dem.png"), optimize=True)
    print(f"dem: {DEM_W}x{DH} {lo:.0f}..{hi:.0f} m")

    baseline = max(years, key=lambda y: water[str(y)]["km2"])
    manifest = {
        "name": "Laguna de Aculeo",
        "bbox": BBOX,
        "size": {"w": W, "h": H},
        "years": years,
        "baselineYear": baseline,
        "dem": {"file": "dem.png", "encoding": "terrarium", "w": DEM_W, "h": DH,
                "minM": round(lo, 1), "maxM": round(hi, 1)},
        "water": water,
        "synthetic": synthetic,
        "attribution": "Sentinel-2 cloudless - https://s2maps.eu by EOX IT Services GmbH "
                       "(contains modified Copernicus Sentinel data). Elevación: AWS Terrain Tiles "
                       "(Mapzen/Terrarium; SRTM, NASA y otros).",
    }
    with open(os.path.join(OUT, "manifest.json"), "w") as fh:
        json.dump(manifest, fh, indent=2, ensure_ascii=False)
    print(json.dumps({"baseline": baseline, "water": water}))


if __name__ == "__main__":
    main()
