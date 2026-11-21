#!/usr/bin/env python3
"""Caudal · archivos livianos que carga la página, derivados de los JSON completos de data/zonas/.

Los JSON completos (series.json, scores.json) siguen siendo la fuente y no se tocan; la página ya no
los descarga. Este script no usa red: se puede correr cada vez que cambien los datos.

Entrada (por zona, en data/zonas/{z}/):
  predios.geojson, scores.json, series.json, ruta.json, clima.json   +   data/zonas/casos.json, index.json
Salida:
  data/zonas/resumen.json            conteos por banda y ruta de cada zona + la serie del caso demo
                                     (lo único que necesita la portada)
  data/zonas/{z}/scores.lite.json    scores.json sin `historico`, solo los campos que usa la página
  data/zonas/{z}/series/index.json   eje de meses, número de bloques y referencia de secano
  data/zonas/{z}/series/bNN.json     NDVI/NDMI de ~50 predios por bloque, alineados al eje de meses

Un predio cae en el bloque hash(id) % bloques (mismo hash en js/zona-data.js: h = h*31 + código, 32 bits).

Uso:
  python3 scripts/build_zonas_web.py            genera
  python3 scripts/build_zonas_web.py --check    genera y verifica contra los JSON completos
"""
import json
import math
import os
import shutil
import sys
from typing import Any

HERE = os.path.dirname(os.path.abspath(__file__))
ZONAS_DIR = os.path.join(HERE, "..", "data", "zonas")

BANDS = ("alta", "media", "baja", "sin_alerta", "sin_dato")
PREDIOS_POR_BLOQUE = 50
# campos de scores.json que usa la página (js/zona-data.js → loadZona)
SCORE_FIELDS = ("banda", "indice", "m3_estimado_min", "m3_estimado_max", "confianza",
                "confianza_motivos", "ndvi_seca", "ndvi_ref")
SCORE_META = ("provisional", "metodo", "temporada", "periodo_consumo", "generado")
SERIE_FIELDS = ("ndvi", "ndmi")


def log(*parts: object) -> None:
    print("[build_zonas_web]", *parts, file=sys.stderr)


def load(path: str, required: bool = True) -> Any:
    if not os.path.exists(path):
        if required:
            raise FileNotFoundError(f"falta {os.path.relpath(path)}")
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def dump(obj: Any, path: str) -> int:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    return os.path.getsize(path)


def bloque_de(predio_id: str, n_bloques: int) -> int:
    """Mismo hash que js/zona-data.js (serieBlock)."""
    h = 0
    for ch in str(predio_id):
        h = (h * 31 + ord(ch)) & 0xFFFFFFFF
    return h % n_bloques


def filas_min(rows: list[dict] | None) -> list[dict]:
    """[{fecha, ndvi, ndmi}] sin los campos que la página no usa."""
    return [{"fecha": r["fecha"], **{k: r.get(k) for k in SERIE_FIELDS}} for r in rows or [] if r.get("fecha")]


def zona_ids() -> list[str]:
    index = load(os.path.join(ZONAS_DIR, "index.json"))
    return [str(z["id"]).lower() for z in index.get("zonas", [])]


def predio_ids(geo: dict) -> list[str]:
    out = []
    for f in geo.get("features", []):
        p = f.get("properties") or {}
        pid = p.get("id", p.get("predio_id"))
        if pid is not None:
            out.append(str(pid))
    return out


def build_scores_lite(scores: dict) -> dict:
    predios = {pid: {k: s[k] for k in SCORE_FIELDS if k in s} for pid, s in (scores.get("predios") or {}).items()}
    return {**{k: scores[k] for k in SCORE_META if k in scores}, "predios": predios}


def build_series(series: dict, ids: list[str]) -> tuple[dict, dict[int, dict]]:
    """→ (index, {n_bloque: {"predios": {id: {ndvi: [...], ndmi: [...]}}}})"""
    meses = list(series.get("meses") or [])
    src = series.get("predios") or {}
    if not meses:  # eje no declarado: unión de las fechas presentes
        meses = sorted({r["fecha"] for rows in src.values() for r in rows if r.get("fecha")})
    pos = {m: i for i, m in enumerate(meses)}
    todos = sorted(set(ids) | set(src.keys()))
    n_bloques = max(1, math.ceil(len(todos) / PREDIOS_POR_BLOQUE))
    bloques = {b: {"predios": {}} for b in range(n_bloques)}
    for pid in todos:
        cols = {k: [None] * len(meses) for k in SERIE_FIELDS}
        for r in src.get(pid) or []:
            i = pos.get(r.get("fecha"))
            if i is None:
                continue
            for k in SERIE_FIELDS:
                cols[k][i] = r.get(k)
        if any(v is not None for k in SERIE_FIELDS for v in cols[k]):
            bloques[bloque_de(pid, n_bloques)]["predios"][pid] = cols
    ref = series.get("referencia_secano") or {}
    index = {
        "meses": meses,
        "bloques": n_bloques,
        "predios_por_bloque": PREDIOS_POR_BLOQUE,
        "campos": list(SERIE_FIELDS),
        "fuente": series.get("fuente"),
        "referencia_secano": {"descripcion": ref.get("descripcion"), "serie": filas_min(ref.get("serie"))},
    }
    return index, bloques


def build_resumen_zona(ids: list[str], scores: dict, ruta: dict | None) -> dict:
    sc = (scores or {}).get("predios") or {}
    counts = {b: 0 for b in BANDS}
    for pid in ids:
        banda = (sc.get(pid) or {}).get("banda")
        counts[banda if banda in BANDS else "sin_dato"] += 1
    r = None
    if ruta and ruta.get("paradas"):
        r = {
            "paradas": len(ruta["paradas"]),
            "distancia_km": ruta.get("distancia_km"),
            "duracion_min": ruta.get("duracion_min"),
            "inicio": {"nombre": (ruta.get("inicio") or {}).get("nombre")},
        }
    return {"predios": len(ids), "counts": counts, "ruta": r}


def build_demo(casos: list[dict], por_zona: dict[str, dict]) -> dict | None:
    """Serie del caso demo (mismo criterio que js/chart.js → renderChart)."""
    con_predio = [c for c in casos if c.get("predio_id") is not None]
    caso = next((c for c in con_predio if c.get("papel") == "demo_principal"), None) or (con_predio[0] if con_predio else None)
    if not caso:
        return None
    z = str(caso.get("zona", "")).lower()
    src = por_zona.get(z)
    if not src:
        return None
    pid = str(caso["predio_id"])
    feat = next((f for f in src["geo"].get("features", []) if str((f.get("properties") or {}).get("id")) == pid), None)
    ref = (src["series"].get("referencia_secano") or {}).get("serie")
    return {
        "expediente": caso.get("expediente"),
        "zona": z,
        "predio_id": pid,
        "rol": ((feat or {}).get("properties") or {}).get("rol"),
        "series": {
            "predios": {pid: filas_min((src["series"].get("predios") or {}).get(pid))},
            "referencia_secano": {"serie": filas_min(ref)},
        },
        "clima": {"ventanas_secas": (src["clima"] or {}).get("ventanas_secas") or []},
    }


def check_zona(z: str, src: dict, index: dict, bloques: dict[int, dict], lite: dict) -> list[str]:
    """Verifica que lo liviano dice lo mismo que lo completo. Devuelve lista de errores."""
    errs = []
    meses = index["meses"]
    n = index["bloques"]
    for pid, rows in (src["series"].get("predios") or {}).items():
        cols = bloques[bloque_de(pid, n)]["predios"].get(pid)
        con_dato = [r for r in rows if any(r.get(k) is not None for k in SERIE_FIELDS)]
        if not con_dato:
            if cols is not None:
                errs.append(f"{z}/{pid}: sin datos en la fuente pero presente en el bloque")
            continue
        if cols is None:
            errs.append(f"{z}/{pid}: falta en su bloque")
            continue
        for r in rows:
            i = meses.index(r["fecha"])
            for k in SERIE_FIELDS:
                if cols[k][i] != r.get(k):
                    errs.append(f"{z}/{pid} {r['fecha']} {k}: {cols[k][i]} != {r.get(k)}")
    total = sum(len(b["predios"]) for b in bloques.values())
    for pid, s in (src["scores"].get("predios") or {}).items():
        for k in SCORE_FIELDS:
            if lite["predios"].get(pid, {}).get(k) != s.get(k):
                errs.append(f"{z}/{pid} score {k} difiere")
    if "historico" in json.dumps(lite):
        errs.append(f"{z}: scores.lite.json todavía trae historico")
    log(f"check {z}: {total} predios con serie en {n} bloque(s), {len(lite['predios'])} scores")
    return errs


def main(argv: list[str]) -> int:
    check = "--check" in argv
    casos_j = load(os.path.join(ZONAS_DIR, "casos.json"))
    casos = casos_j if isinstance(casos_j, list) else casos_j.get("casos", [])
    por_zona, resumen_zonas, errs = {}, {}, []
    for z in zona_ids():
        zdir = os.path.join(ZONAS_DIR, z)
        src = {
            "geo": load(os.path.join(zdir, "predios.geojson")),
            "scores": load(os.path.join(zdir, "scores.json"), required=False) or {},
            "series": load(os.path.join(zdir, "series.json"), required=False) or {},
            "ruta": load(os.path.join(zdir, "ruta.json"), required=False),
            "clima": load(os.path.join(zdir, "clima.json"), required=False),
        }
        por_zona[z] = src
        ids = predio_ids(src["geo"])
        lite = build_scores_lite(src["scores"])
        kb_lite = dump(lite, os.path.join(zdir, "scores.lite.json")) / 1024
        index, bloques = build_series(src["series"], ids)
        sdir = os.path.join(zdir, "series")
        if os.path.isdir(sdir):
            shutil.rmtree(sdir)  # el número de bloques cambia con el número de predios
        kb_idx = dump(index, os.path.join(sdir, "index.json")) / 1024
        kb_blocks = [dump(b, os.path.join(sdir, f"b{n:02d}.json")) / 1024 for n, b in sorted(bloques.items())]
        resumen_zonas[z] = build_resumen_zona(ids, src["scores"], src["ruta"])
        log(f"{z}: {len(ids)} predios · scores.lite {kb_lite:.0f} KB · series/index {kb_idx:.0f} KB · "
            f"{len(kb_blocks)} bloque(s), el mayor {max(kb_blocks):.0f} KB")
        if check:
            errs += check_zona(z, src, index, bloques, lite)
    resumen = {
        "zonas": resumen_zonas,
        "demo": build_demo(casos, por_zona),
    }
    kb = dump(resumen, os.path.join(ZONAS_DIR, "resumen.json")) / 1024
    log(f"resumen.json {kb:.0f} KB · demo: {(resumen['demo'] or {}).get('expediente')}")
    if errs:
        for e in errs[:20]:
            log("ERROR", e)
        log(f"{len(errs)} diferencia(s) con los JSON completos")
        return 1
    if check:
        log("check OK: lo liviano coincide con los JSON completos")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
