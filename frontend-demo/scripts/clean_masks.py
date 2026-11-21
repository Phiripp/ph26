#!/usr/bin/env python3
"""Limpia las mascaras de agua de Aculeo y genera campos de distancia con signo (SDF) por año.

Entrada:  assets/aculeo/mask-{year}.png (binarias, ruidosas), basin.png, manifest.json
Salida:   assets/aculeo/water-{year}.png  (SDF 8-bit, 128 = orilla, +2 por pixel hacia adentro del agua,
          clamp a +-64 px a la resolucion de salida, OUT_W px de ancho)
          manifest.json: agrega "waterSdf" y water[year].km2Clean

Limpieza por año: restringe a la cuenca, cierre/apertura morfologica, se queda con el cuerpo principal
(y otros charcos grandes dentro de la cuenca en años secos), rellena hoyos y elimina motas.

Uso: python3 scripts/clean_masks.py   (requiere Pillow, numpy, scipy)
"""
import json
import math
import os

import numpy as np
from PIL import Image
from scipy import ndimage as ndi

HERE = os.path.dirname(os.path.abspath(__file__))
DIR = os.path.join(HERE, "..", "assets", "aculeo")
OUT_W = 512
CLAMP = 64.0  # px at output resolution
SCALE = 2.0   # 8-bit units per px


def disk(r):
    y, x = np.ogrid[-r:r + 1, -r:r + 1]
    return x * x + y * y <= r * r


def clean(mask, basin):
    m = mask & basin
    m = ndi.binary_closing(m, structure=disk(3), iterations=1)
    m = ndi.binary_opening(m, structure=disk(2), iterations=1)
    m = ndi.binary_fill_holes(m)
    lab, n = ndi.label(m)
    if n == 0:
        return m
    sizes = ndi.sum(m, lab, index=np.arange(1, n + 1))
    biggest = sizes.max()
    # main body + any other sizeable pond (relevant in dry years, when the lake splits into puddles)
    keep_min = max(250.0, 0.25 * biggest)
    keep = np.zeros(n + 1, bool)
    keep[1:] = sizes >= keep_min
    m = keep[lab]
    m = ndi.binary_closing(m, structure=disk(2))
    m = ndi.binary_fill_holes(m)
    # smooth outline: blur + re-threshold
    m = ndi.gaussian_filter(m.astype(np.float32), 2.0) > 0.5
    return m


def sdf_image(m, out_w):
    h, w = m.shape
    out_h = round(h * out_w / w)
    # supersampled field at full res, then resampled; distances converted to output px
    k = out_w / w
    if not m.any():  # dry year: no water anywhere
        return Image.fromarray(np.zeros((out_h, out_w), np.uint8))
    inside = ndi.distance_transform_edt(m)
    outside = ndi.distance_transform_edt(~m)
    d = (inside - outside) * k  # >0 in water
    # resample with Pillow (float mode keeps precision)
    img = Image.fromarray(d.astype(np.float32)).resize((out_w, out_h), Image.BILINEAR)
    d = np.asarray(img)
    d = np.clip(d, -CLAMP, CLAMP)
    enc = np.clip(np.round(128.0 + d * SCALE), 0, 255).astype(np.uint8)
    return Image.fromarray(enc)


def main():
    with open(os.path.join(DIR, "manifest.json")) as f:
        man = json.load(f)
    bbox = man["bbox"]
    lat = math.radians((bbox["north"] + bbox["south"]) / 2)
    w_km = (bbox["east"] - bbox["west"]) * 111.32 * math.cos(lat)
    h_km = (bbox["north"] - bbox["south"]) * 110.54

    basin = np.asarray(Image.open(os.path.join(DIR, "basin.png")).convert("L")) > 127
    basin = ndi.binary_dilation(basin, structure=disk(6))

    sdf_map = {}
    for y in man["years"]:
        ys = str(y)
        mf = man.get("water", {}).get(ys, {}).get("maskFile", f"mask-{y}.png")
        raw = np.asarray(Image.open(os.path.join(DIR, mf)).convert("L")) > 127
        m = clean(raw, basin)
        px_km2 = (w_km * h_km) / m.size
        km2 = round(float(m.sum()) * px_km2, 2)
        out = f"water-{y}.png"
        sdf_image(m, OUT_W).save(os.path.join(DIR, out), optimize=True)
        sdf_map[ys] = out
        man.setdefault("water", {}).setdefault(ys, {})["km2Clean"] = km2
        lab, n = ndi.label(m)
        print(f"{y}: raw {raw.sum():7d} px -> clean {m.sum():7d} px, {n} cuerpo(s), {km2} km2 (manifest {man['water'][ys].get('km2')})")

    man["waterSdf"] = sdf_map
    with open(os.path.join(DIR, "manifest.json"), "w") as f:
        json.dump(man, f, indent=2, ensure_ascii=False)
        f.write("\n")


if __name__ == "__main__":
    main()
