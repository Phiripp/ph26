#!/usr/bin/env python3
"""Caudal · verificación de los archivos livianos que carga la página (data/zonas/).

Los archivos los genera ahora scripts/build_m5_web.py desde data/processed/ (M5, docs/spec-demo.md). Este script
no usa red ni dependencias: revisa que lo exportado sea coherente con lo que espera js/zona-data.js. También
define el hash de bloque de las series, que comparten build_m5_web.py y js/zona-data.js.

  data/zonas/resumen.json            total (7.911), conteos por banda y ruta de cada zona, bloque impacto, demo
  data/zonas/impacto.json            impacto.json de M9 + bloque `pitch` (F6)
  data/zonas/casos.json              10 casos con primera_alerta, anos_adelanto, m3_antes_inspeccion
  data/zonas/{z}/predios.geojson     polígonos de los predios exportados (alta, media, casos, vecindarios, ruta)
  data/zonas/{z}/scores.lite.json    campos de puntaje.parquet por predio
  data/zonas/{z}/series/index.json   eje `fechas`, número de bloques, referencia de secano de la zona
  data/zonas/{z}/series/bNN.json     por predio: `i` (posiciones en `fechas`) y una lista por campo
  data/zonas/{z}/historial.json      bandas por temporada de los predios de los casos
  data/zonas/{z}/poi.json            hasta 8 POI por predio
  data/zonas/{z}/ruta.json, ruta.gpx, ruta.geojson   ruta de M8

Un predio cae en el bloque hash(id) % bloques (mismo hash en js/zona-data.js: h = h*31 + código, 32 bits).

Uso:
  uv run scripts/build_m5_web.py                genera (desde frontend-demo/ o con la ruta completa)
  python3 scripts/build_zonas_web.py --check    verifica; sale con 1 si encuentra diferencias
"""
import json
import os
import sys
from typing import Any

HERE = os.path.dirname(os.path.abspath(__file__))
ZONAS_DIR = os.path.join(HERE, "..", "data", "zonas")

BANDS = ("alta", "media", "baja", "sin_alerta", "sin_dato")
PREDIOS_POR_BLOQUE = 50
SCORE_FIELDS = ("rank", "banda", "puntaje", "confianza", "motivos", "frac_senal", "n_fechas", "consumo_m3",
                "derecho_m3", "derecho_ajeno_m3", "exceso_m3", "estado_derechos", "canal_m", "fiscalizado_500m")
CASO_FIELDS = ("primera_alerta", "anos_adelanto", "m3_antes_inspeccion")
PITCH_FIELDS = ("lift", "predio", "candidatos", "torres", "capacidad")
TOTAL_PREDIOS = 7911  # elegibles 2025-26 de puntaje.parquet (spec-demo.md, F1)


def log(*parts: object) -> None:
    print("[build_zonas_web]", *parts, file=sys.stderr)


def load(path: str, required: bool = True) -> Any:
    if not os.path.exists(path):
        if required:
            raise FileNotFoundError(f"falta {os.path.relpath(path)}")
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def bloque_de(predio_id: str, n_bloques: int) -> int:
    """Mismo hash que js/zona-data.js (serieBlock)."""
    h = 0
    for ch in str(predio_id):
        h = (h * 31 + ord(ch)) & 0xFFFFFFFF
    return h % n_bloques


def zona_ids() -> list[str]:
    index = load(os.path.join(ZONAS_DIR, "index.json"))
    return [str(z["id"]).lower() for z in index.get("zonas", [])]


def check_zona(z: str, resumen_z: dict, casos: list[dict]) -> list[str]:
    errs: list[str] = []
    zdir = os.path.join(ZONAS_DIR, z)
    geo = load(os.path.join(zdir, "predios.geojson"))
    lite = load(os.path.join(zdir, "scores.lite.json"))
    ids = [str((f.get("properties") or {}).get("id")) for f in geo.get("features", [])]
    sids = set(lite.get("predios", {}))
    if len(set(ids)) != len(ids):
        errs.append(f"{z}: ids repetidos en predios.geojson")
    if set(ids) != sids:
        errs.append(f"{z}: predios.geojson y scores.lite.json no tienen los mismos predios "
                    f"({len(set(ids) - sids)} sin score, {len(sids - set(ids))} sin polígono)")
    if lite.get("provisional") is not False:
        errs.append(f"{z}: scores.lite.json sin provisional:false")
    pred = lite.get("predios", {})
    for pid, s in pred.items():
        falta = [k for k in SCORE_FIELDS if k not in s]
        if falta:
            errs.append(f"{z}/{pid}: faltan campos {falta}")
            break
        if s["banda"] not in BANDS:
            errs.append(f"{z}/{pid}: banda {s['banda']!r}")
        for k in ("consumo_m3", "exceso_m3"):
            v = s[k]
            if not (isinstance(v, list) and len(v) == 3):
                errs.append(f"{z}/{pid}: {k} no es [min, central, max]")
            elif None not in v and not v[0] <= v[1] <= v[2]:
                errs.append(f"{z}/{pid}: {k} desordenado {v}")
    ranks = sorted(s["rank"] for s in pred.values() if s.get("rank") is not None)
    if len(set(ranks)) != len(ranks):
        errs.append(f"{z}: rank repetido")
    # todos los alta y media de la zona están exportados
    c = resumen_z.get("counts", {})
    for b in ("alta", "media"):
        n = sum(1 for s in pred.values() if s["banda"] == b)
        if n != c.get(b):
            errs.append(f"{z}: {n} predios {b} exportados, resumen dice {c.get(b)}")
    if sum(c.values()) != resumen_z.get("predios"):
        errs.append(f"{z}: los conteos por banda no suman el total de la zona")

    # series por bloque
    sdir = os.path.join(zdir, "series")
    index = load(os.path.join(sdir, "index.json"))
    fechas, n = index.get("fechas") or index.get("meses"), index["bloques"]
    if fechas != sorted(fechas):
        errs.append(f"{z}: eje de fechas desordenado")
    campos = index.get("campos", [])
    con_serie = 0
    for b in range(n):
        blk = load(os.path.join(sdir, f"b{b:02d}.json"))
        for pid, cols in blk.get("predios", {}).items():
            con_serie += 1
            if bloque_de(pid, n) != b:
                errs.append(f"{z}/{pid}: en el bloque {b}, debería estar en {bloque_de(pid, n)}")
            if pid not in sids:
                errs.append(f"{z}/{pid}: serie de un predio no exportado")
            idx = cols.get("i")
            if idx is not None:
                if any(not 0 <= i < len(fechas) for i in idx) or idx != sorted(set(idx)):
                    errs.append(f"{z}/{pid}: índices fuera del eje o repetidos")
                if any(len(cols.get(k, [])) != len(idx) for k in campos):
                    errs.append(f"{z}/{pid}: columnas de distinto largo")
    if os.path.exists(os.path.join(sdir, f"b{n:02d}.json")):
        errs.append(f"{z}: sobran bloques (index dice {n})")

    # historial, POI, ruta, casos
    hist = load(os.path.join(zdir, "historial.json")).get("predios", {})
    for cz in casos:
        if str(cz.get("zona", "")).lower() != z or cz.get("predio_id") is None:
            continue
        pid = str(cz["predio_id"])
        if pid not in sids:
            errs.append(f"{z}: el predio {pid} del caso {cz['expediente']} no está exportado")
        if len(hist.get(pid, [])) != 7:
            errs.append(f"{z}: historial de {pid} ({cz['expediente']}) con {len(hist.get(pid, []))} temporadas")
    poi = load(os.path.join(zdir, "poi.json")).get("predios", {})
    if set(poi) - sids:
        errs.append(f"{z}: POI de predios no exportados")
    if any(len(v) > 8 for v in poi.values()):
        errs.append(f"{z}: más de 8 POI en un predio")
    ruta = load(os.path.join(zdir, "ruta.json"))
    for p in ruta.get("paradas", []):
        if str(p["predio_id"]) not in sids:
            errs.append(f"{z}: parada {p['predio_id']} no exportada")
    for f in ("ruta.gpx", "ruta.geojson"):
        if not os.path.exists(os.path.join(zdir, f)):
            errs.append(f"{z}: falta {f}")
    r = resumen_z.get("ruta") or {}
    if r.get("paradas") != len(ruta.get("paradas", [])):
        errs.append(f"{z}: resumen.ruta.paradas no coincide con ruta.json")
    for viejo in ("scores.json", "series.json"):
        if os.path.exists(os.path.join(zdir, viejo)):
            errs.append(f"{z}: queda {viejo} provisional")
    log(f"check {z}: {len(ids)} predios ({c.get('alta')} alta, {c.get('media')} media de {resumen_z.get('predios')}) · "
        f"{con_serie} con serie en {n} bloques ({len(fechas)} fechas) · {len(hist)} con historial · "
        f"{len(poi)} con POI · ruta {len(ruta.get('paradas', []))} paradas")
    return errs


def main(argv: list[str]) -> int:
    check = "--check" in argv
    if not check:
        log("los archivos se generan con `uv run scripts/build_m5_web.py`; este script solo verifica (--check)")
    errs: list[str] = []
    resumen = load(os.path.join(ZONAS_DIR, "resumen.json"))
    casos = load(os.path.join(ZONAS_DIR, "casos.json"))
    casos = casos if isinstance(casos, list) else casos.get("casos", [])
    impacto = load(os.path.join(ZONAS_DIR, "impacto.json"))
    zonas = resumen.get("zonas", {})
    total = sum(z.get("predios", 0) for z in zonas.values())
    if resumen.get("total") != TOTAL_PREDIOS or total != TOTAL_PREDIOS:
        errs.append(f"resumen: total {resumen.get('total')} / suma de zonas {total}, se esperaba {TOTAL_PREDIOS}")
    for z in zona_ids():
        errs += check_zona(z, zonas.get(z, {}), casos)
    for cz in casos:
        if any(k not in cz for k in CASO_FIELDS):
            errs.append(f"casos.json: {cz.get('expediente')} sin {CASO_FIELDS}")
        if cz.get("primera_alerta") and not (cz.get("anos_adelanto") or 0) > 0:
            errs.append(f"casos.json: {cz.get('expediente')} con alerta y sin adelanto")
    pitch = impacto.get("pitch") or {}
    if any(k not in pitch for k in PITCH_FIELDS):
        errs.append(f"impacto.json: bloque pitch incompleto ({sorted(pitch)})")
    if (resumen.get("impacto") or {}).get("candidatos") != impacto.get("candidatos"):
        errs.append("resumen.impacto e impacto.json no coinciden")
    for root, _, files in os.walk(ZONAS_DIR):
        for f in files:
            if f.endswith((".json", ".geojson")):
                with open(os.path.join(root, f), encoding="utf-8") as fh:
                    if '"provisional":true' in fh.read().replace(" ", ""):
                        errs.append(f"{os.path.relpath(os.path.join(root, f), ZONAS_DIR)}: provisional:true")
    log(f"resumen: {resumen.get('total')} predios analizados · candidatos {impacto.get('candidatos')} · "
        f"casos con alerta previa: {sum(1 for c in casos if c.get('primera_alerta'))} de {len(casos)}")
    if errs:
        for e in errs[:30]:
            log("ERROR", e)
        log(f"{len(errs)} problema(s)")
        return 1
    log("check OK" if check else "OK")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
