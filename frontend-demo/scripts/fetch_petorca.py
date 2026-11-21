#!/usr/bin/env python3
"""Fetch real Sentinel-2 cloudless (EOX) imagery + AWS Terrarium DEM for the Petorca valley.

Demo valley for Caudal v2: Petorca river valley between Petorca town (-32.252, -70.933)
and Chincolco (-32.22, -70.84), Region de Valparaiso. Avocado orchards on dry hillsides.

Writes into ../assets/petorca/: sat-{year}.jpg, dem.png, preview.jpg, manifest.json
(same manifest schema as assets/aculeo/manifest.json, minus per-year water masks, which
are not meaningful here; no "ndvi" key because EOX s2cloudless is a true-colour RGB
composite without the NIR band, so a real NDVI cannot be derived from it).

Usage: python3 scripts/fetch_petorca.py [--preview]
  --preview  only fetch the latest year and write preview.jpg (to check the bbox)
  --force    re-download years whose sat-{year}.jpg already exists (default: reuse them)
Requires Pillow.
"""
import io, json, math, os, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "assets", "petorca")
UA = {"User-Agent": "caudal-hackathon-mockup"}

# ~16 x 11 km: Petorca town (W), valley floor, hillside orchards toward Chincolco (E)
BBOX = dict(west=-71.035, south=-32.288, east=-70.792, north=-32.175)
YEARS = list(range(2018, 2025))
SAT_Z = 14
DEM_Z = 13
MAX_W = 2048
DEM_W = 512
PREVIEW_W = 800
SAT_URL = "https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-{year}_3857/default/g/{z}/{y}/{x}.jpg"
DEM_URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"


def lonlat_to_px(lon, lat, z):
    n = 256 * 2 ** z
    x = (lon + 180) / 360 * n
    s = math.sin(math.radians(lat))
    y = (0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)) * n
    return x, y


def fetch(url, tries=4):
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=45) as r:
                return r.read()
        except Exception:
            if k == tries - 1:
                raise
            time.sleep(2 * (k + 1))


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
    with ThreadPoolExecutor(6) as ex:
        for (tx, ty), im in ex.map(get, tiles):
            canvas.paste(im, ((tx - tx0) * 256, (ty - ty0) * 256))
    ox, oy = tx0 * 256, ty0 * 256
    return canvas.crop((round(x0 - ox), round(y0 - oy), round(x1 - ox), round(y1 - oy)))


def is_blank(img):
    lo, hi = img.convert("L").getextrema()
    return hi - lo < 10


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


def save_preview(im):
    pw = PREVIEW_W
    ph = round(im.size[1] * pw / im.size[0])
    im.resize((pw, ph), Image.LANCZOS).save(os.path.join(OUT, "preview.jpg"), quality=80, optimize=True)


def main():
    os.makedirs(OUT, exist_ok=True)
    preview_only = "--preview" in sys.argv
    years_to_try = [YEARS[-1]] if preview_only else YEARS
    sats = {}
    force = "--force" in sys.argv
    reused = set()
    for y in years_to_try:
        cached = os.path.join(OUT, f"sat-{y}.jpg")
        if not force and not preview_only and os.path.exists(cached):
            sats[y] = Image.open(cached).convert("RGB")
            reused.add(y)
            print(f"sat {y}: cached {sats[y].size}")
            continue
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
        print("No imagery downloaded.")
        sys.exit(1)

    years = sorted(sats)
    save_preview(sats[years[-1]])
    if preview_only:
        print("preview.jpg written")
        return

    W0, H0 = sats[years[0]].size
    if W0 > MAX_W:
        W, H = MAX_W, round(H0 * MAX_W / W0)
    else:
        W, H = W0, H0
    for y in years:
        if y in reused and sats[y].size == (W, H):
            continue  # avoid JPEG re-compression of an existing output
        im = sats[y] if sats[y].size == (W, H) else sats[y].resize((W, H), Image.LANCZOS)
        im.save(os.path.join(OUT, f"sat-{y}.jpg"), quality=85, optimize=True)

    dem_f = build_dem()
    DH = round(H * DEM_W / W)
    dem_f = dem_f.resize((DEM_W, DH), Image.BILINEAR)
    lo, hi = dem_f.getextrema()
    encode_terrarium(dem_f).save(os.path.join(OUT, "dem.png"), optimize=True)
    print(f"dem: {DEM_W}x{DH} {lo:.0f}..{hi:.0f} m")

    manifest = {
        "name": "Valle de Petorca",
        "bbox": BBOX,
        "size": {"w": W, "h": H},
        "years": years,
        "baselineYear": years[0],
        "dem": {"file": "dem.png", "encoding": "terrarium", "w": DEM_W, "h": DH,
                "minM": round(lo, 1), "maxM": round(hi, 1)},
        "water": {},
        "synthetic": False,
        "notes": "sat-*.jpg son composiciones anuales true-color sin nubes (EOX s2cloudless), "
                 "no escenas individuales; no incluyen banda NIR, por eso no hay capa NDVI real. "
                 "baselineYear = primer año disponible (no se calcula agua en este valle).",
        "attribution": "Sentinel-2 cloudless - https://s2maps.eu by EOX IT Services GmbH "
                       "(contains modified Copernicus Sentinel data). Elevación: AWS Terrain Tiles "
                       "(Mapzen/Terrarium; SRTM, NASA y otros).",
    }
    with open(os.path.join(OUT, "manifest.json"), "w") as fh:
        json.dump(manifest, fh, indent=2, ensure_ascii=False)
    print(json.dumps({"years": years, "size": [W, H], "dem": [round(lo, 1), round(hi, 1)]}))


if __name__ == "__main__":
    main()
