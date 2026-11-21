#!/usr/bin/env python3
"""Build data/chile.geojson (Chile boundary for the satellite mask in js/map.js).

Source: Natural Earth admin-0 countries 1:10m (public domain), via
https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_admin_0_countries.geojson

Usage:
  python3 -I scripts/build_chile_geojson.py path/to/ne_10m_admin_0_countries.geojson data/chile.geojson

Keeps mainland + islands (Rapa Nui, Juan Fernández, Patagonian archipelagos), drops
specks smaller than MIN_AREA_KM2, simplifies with Douglas-Peucker (TOL degrees) and rounds
coordinates to 4 decimals so the file stays well under 400 KB.
"""
import json
import math
import sys

TOL = 0.006          # ~600 m
MIN_AREA_KM2 = 6.0
ROUND = 4


def ring_area_km2(ring):
    # planar shoelace on an equirectangular projection scaled at the ring's latitude
    if len(ring) < 4:
        return 0.0
    lat0 = math.radians(sum(p[1] for p in ring) / len(ring))
    kx = 111.32 * math.cos(lat0)
    ky = 110.57
    a = 0.0
    for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
        a += (x1 * kx) * (y2 * ky) - (x2 * kx) * (y1 * ky)
    return abs(a) / 2


def dp(points, tol):
    if len(points) < 3:
        return points
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        i, j = stack.pop()
        ax, ay = points[i]
        bx, by = points[j]
        dx, dy = bx - ax, by - ay
        L = math.hypot(dx, dy) or 1e-12
        best, idx = -1.0, -1
        for k in range(i + 1, j):
            px, py = points[k]
            d = abs(dy * px - dx * py + bx * ay - by * ax) / L
            if d > best:
                best, idx = d, k
        if best > tol and idx > 0:
            keep[idx] = True
            stack.append((i, idx))
            stack.append((idx, j))
    return [p for p, k in zip(points, keep) if k]


def simplify_ring(ring):
    # closed ring: first == last, so split it in two open chains before Douglas-Peucker
    mid = len(ring) // 2
    s = dp(ring[: mid + 1], TOL)[:-1] + dp(ring[mid:], TOL)
    s =[[round(x, ROUND), round(y, ROUND)] for x, y in s]
    out = []
    for p in s:
        if not out or out[-1] != p:
            out.append(p)
    if out[0] != out[-1]:
        out.append(out[0])
    return out if len(out) >= 4 else None


def main(src, dst):
    with open(src, encoding="utf-8") as f:
        fc = json.load(f)
    chile = None
    for ft in fc["features"]:
        p = ft["properties"]
        if p.get("ADM0_A3") == "CHL" or p.get("ISO_A3") == "CHL":
            chile = ft
            break
    if not chile:
        sys.exit("Chile not found")
    g = chile["geometry"]
    polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
    out = []
    for poly in polys:
        if ring_area_km2(poly[0]) < MIN_AREA_KM2:
            continue
        outer = simplify_ring(poly[0])
        if not outer:
            continue
        holes = [h for h in (simplify_ring(r) for r in poly[1:] if ring_area_km2(r) >= MIN_AREA_KM2) if h]
        out.append([outer] + holes)
    feat = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {"name": "Chile", "source": "Natural Earth 1:10m admin-0 (public domain)"},
            "geometry": {"type": "MultiPolygon", "coordinates": out},
        }],
    }
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(feat, f, separators=(",", ":"))
    n = sum(len(r) for p in out for r in p)
    print(f"{len(out)} polygons, {n} vertices -> {dst}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
