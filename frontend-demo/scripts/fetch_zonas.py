#!/usr/bin/env python3
"""Fetch EOX Sentinel-2 cloudless imagery + AWS Terrarium DEM for the two spec zones (Z1, Z2).

Writes assets/zonas/{z1,z2}/: sat-{year}.jpg (2018..2024), dem.png, preview.jpg, manifest.json
(same schema as assets/petorca/manifest.json).

Scene bbox rule (data contract): bbox of the zone's 10 validation case points + its
predio_muestra predios, plus a 1.5 km margin, rounded outward to 3 decimals.
- If data/zonas/index.json exists (DATA-TAB), its bbox_escena wins.
- Else data/zonas/bbox.json is reused if present, or computed here and written there,
  so DATA-TAB can copy it into index.json.

Width is capped at 2048 px; when zoom 14 would be wider than 2x the cap, tiles are
fetched at zoom 13 instead (less download, same output resolution after resize).

Usage: python3 scripts/fetch_zonas.py [z1|z2 ...] [--preview] [--force]
Requires Pillow (run with: uv run --with pillow python scripts/fetch_zonas.py).
"""
import io, json, math, os, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
FRONT = os.path.normpath(os.path.join(HERE, ".."))
REPO = os.path.normpath(os.path.join(FRONT, ".."))
UA = {"User-Agent": "caudal-hackathon-mockup"}

YEARS = list(range(2018, 2025))
MAX_W = 2048
DEM_W = 512
DEM_Z = 13
PREVIEW_W = 1000
MARGIN_KM = 1.5
SAT_URL = "https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-{year}_3857/default/g/{z}/{y}/{x}.jpg"
DEM_URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
ZONE_NAMES = {"z1": "Z1 · Petorca", "z2": "Z2 · Aconcagua bajo"}


# ---------- bbox rule ----------
def _walk(c):
    if isinstance(c[0], (int, float)):
        yield c
    else:
        for x in c:
            yield from _walk(x)


def compute_bboxes():
    casos = json.load(open(os.path.join(REPO, "data", "casos_validacion.geojson")))
    muestra = json.load(open(os.path.join(REPO, "data", "processed", "predio_muestra.geojson")))
    pts = {}
    for f in casos["features"]:
        pts.setdefault(f["properties"]["zona"].lower(), []).append(f["geometry"]["coordinates"])
    for f in muestra["features"]:
        pts.setdefault(f["properties"]["zona"].lower(), []).extend(_walk(f["geometry"]["coordinates"]))
    out = {}
    for z, ps in sorted(pts.items()):
        xs = [p[0] for p in ps]; ys = [p[1] for p in ps]
        lat0 = (min(ys) + max(ys)) / 2
        dlat = MARGIN_KM / 111.32
        dlon = MARGIN_KM / (111.32 * math.cos(math.radians(lat0)))
        out[z] = [math.floor((min(xs) - dlon) * 1000) / 1000, math.floor((min(ys) - dlat) * 1000) / 1000,
                  math.ceil((max(xs) + dlon) * 1000) / 1000, math.ceil((max(ys) + dlat) * 1000) / 1000]
    return out


def resolve_bboxes():
    idx = os.path.join(FRONT, "data", "zonas", "index.json")
    if os.path.exists(idx):
        zs = json.load(open(idx))["zonas"]
        print("bbox: from data/zonas/index.json")
        return {z["id"]: z["bbox_escena"] for z in zs}
    bpath = os.path.join(FRONT, "data", "zonas", "bbox.json")
    if os.path.exists(bpath):
        print("bbox: from data/zonas/bbox.json")
        return {k: v for k, v in json.load(open(bpath)).items() if not k.startswith("_")}
    bb = compute_bboxes()
    os.makedirs(os.path.dirname(bpath), exist_ok=True)
    with open(bpath, "w") as fh:
        json.dump({"_regla": "bbox [w,s,e,n] EPSG:4326 de los puntos de casos_validacion + predios de "
                             "predio_muestra de cada zona, margen 1.5 km, redondeado hacia afuera a 3 decimales. "
                             "Escrito por scripts/fetch_zonas.py; DATA-TAB lo copia a index.json bbox_escena.",
                   **bb}, fh, indent=2)
    print("bbox: computed, wrote data/zonas/bbox.json")
    return bb


# ---------- tiles ----------
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


def mosaic(bbox, url_tpl, z, mode, **kw):
    w, s, e, n = bbox
    x0, y0 = lonlat_to_px(w, n, z)
    x1, y1 = lonlat_to_px(e, s, z)
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


def is_blank(img):
    lo, hi = img.convert("L").getextrema()
    return hi - lo < 10


def encode_terrarium(f):
    w, h = f.size
    src = f.load()
    out = Image.new("RGB", (w, h))
    op = out.load()
    for j in range(h):
        for i in range(w):
            v = src[i, j] + 32768
            R = int(v // 256); G = int(v % 256); B = int((v - math.floor(v)) * 256)
            op[i, j] = (max(0, min(255, R)), G, max(0, min(255, B)))
    return out


def build_dem(bbox):
    rgb = mosaic(bbox, DEM_URL, DEM_Z, "RGB")
    w, h = rgb.size
    f = Image.new("F", (w, h))
    fp, rp = f.load(), rgb.load()
    for j in range(h):
        for i in range(w):
            R, G, B = rp[i, j]
            fp[i, j] = R * 256 + G + B / 256 - 32768
    return f


def sat_zoom(bbox):
    x0, _ = lonlat_to_px(bbox[0], bbox[3], 14)
    x1, _ = lonlat_to_px(bbox[2], bbox[1], 14)
    return 14 if (x1 - x0) <= 2 * MAX_W else 13


def save_preview(zid, im, bbox, out):
    """Preview with case points (red rings) and muestra predios (yellow dots) to check coverage."""
    pw = PREVIEW_W
    ph = round(im.size[1] * pw / im.size[0])
    pv = im.resize((pw, ph), Image.LANCZOS)
    d = ImageDraw.Draw(pv)
    w, s, e, n = bbox
    X0, Y0 = lonlat_to_px(w, n, 20); X1, Y1 = lonlat_to_px(e, s, 20)

    def px(lon, lat):
        X, Y = lonlat_to_px(lon, lat, 20)
        return (X - X0) / (X1 - X0) * pw, (Y - Y0) / (Y1 - Y0) * ph

    try:
        muestra = json.load(open(os.path.join(REPO, "data", "processed", "predio_muestra.geojson")))
        for f in muestra["features"]:
            if f["properties"]["zona"].lower() != zid:
                continue
            ring = [px(*p) for p in _walk(f["geometry"]["coordinates"])]
            d.polygon(ring, outline=(255, 220, 0))
        casos = json.load(open(os.path.join(REPO, "data", "casos_validacion.geojson")))
        for f in casos["features"]:
            if f["properties"]["zona"].lower() != zid:
                continue
            x, y = px(*f["geometry"]["coordinates"])
            d.ellipse((x - 7, y - 7, x + 7, y + 7), outline=(255, 40, 40), width=3)
    except Exception as ex:
        print("preview overlay skipped:", ex)
    pv.save(os.path.join(out, "preview.jpg"), quality=80, optimize=True)


def run_zone(zid, bbox, preview_only, force):
    out = os.path.join(FRONT, "assets", "zonas", zid)
    os.makedirs(out, exist_ok=True)
    z = sat_zoom(bbox)
    print(f"[{zid}] bbox {bbox} sat zoom {z}")
    years_to_try = [YEARS[-1]] if preview_only else YEARS
    sats, reused = {}, set()
    for y in years_to_try:
        cached = os.path.join(out, f"sat-{y}.jpg")
        if not force and not preview_only and os.path.exists(cached):
            sats[y] = Image.open(cached).convert("RGB"); reused.add(y)
            print(f"[{zid}] sat {y}: cached {sats[y].size}")
            continue
        try:
            im = mosaic(bbox, SAT_URL, z, "RGB", year=y)
            if is_blank(im):
                print(f"[{zid}] sat {y}: blank, skipped"); continue
            sats[y] = im
            print(f"[{zid}] sat {y}: {im.size}")
        except Exception as e:
            print(f"[{zid}] sat {y} failed: {e}")
    if not sats:
        raise SystemExit(f"[{zid}] no imagery")
    years = sorted(sats)
    save_preview(zid, sats[years[-1]], bbox, out)
    if preview_only:
        return

    W0, H0 = sats[years[-1]].size
    W, H = (MAX_W, round(H0 * MAX_W / W0)) if W0 > MAX_W else (W0, H0)
    for y in years:
        if y in reused and sats[y].size == (W, H):
            continue
        im = sats[y] if sats[y].size == (W, H) else sats[y].resize((W, H), Image.LANCZOS)
        im.save(os.path.join(out, f"sat-{y}.jpg"), quality=85, optimize=True)

    dem_f = build_dem(bbox)
    DH = round(H * DEM_W / W)
    dem_f = dem_f.resize((DEM_W, DH), Image.BILINEAR)
    lo, hi = dem_f.getextrema()
    encode_terrarium(dem_f).save(os.path.join(out, "dem.png"), optimize=True)
    print(f"[{zid}] dem: {DEM_W}x{DH} {lo:.0f}..{hi:.0f} m")

    manifest = {
        "name": ZONE_NAMES.get(zid, zid.upper()),
        "bbox": dict(west=bbox[0], south=bbox[1], east=bbox[2], north=bbox[3]),
        "size": {"w": W, "h": H},
        "years": years,
        "baselineYear": years[0],
        "dem": {"file": "dem.png", "encoding": "terrarium", "w": DEM_W, "h": DH,
                "minM": round(lo, 1), "maxM": round(hi, 1)},
        "water": {},
        "synthetic": False,
        "satZoom": z,
        "notes": "sat-*.jpg son composiciones anuales true-color sin nubes (EOX s2cloudless), "
                 "no escenas individuales; no incluyen banda NIR, por eso no hay capa NDVI real. "
                 "bbox = casos de validación + predios de muestra de la zona + 1.5 km.",
        "attribution": "Sentinel-2 cloudless - https://s2maps.eu by EOX IT Services GmbH "
                       "(contains modified Copernicus Sentinel data). Elevación: AWS Terrain Tiles "
                       "(Mapzen/Terrarium; SRTM, NASA y otros).",
    }
    with open(os.path.join(out, "manifest.json"), "w") as fh:
        json.dump(manifest, fh, indent=2, ensure_ascii=False)
    print(json.dumps({"zona": zid, "years": years, "size": [W, H], "dem": [round(lo, 1), round(hi, 1)]}))


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    bbs = resolve_bboxes()
    for zid in (args or sorted(bbs)):
        run_zone(zid, bbs[zid], "--preview" in sys.argv, "--force" in sys.argv)


if __name__ == "__main__":
    main()
