# /// script
# requires-python = ">=3.11"
# dependencies = ["geopandas>=1.0", "pandas", "pyarrow", "numpy", "shapely>=2.0", "scikit-learn"]
# ///
"""Caudal · exporta M5 (y M3, M8, M9, M10) al frontend estático (docs/spec-demo.md, "Datos: exportación de M5").

Lee data/processed/ y escribe los archivos que la
página ya carga (js/zona-data.js), con los mismos nombres:

  data/zonas/resumen.json            por zona: total de predios analizados, conteo por banda, resumen de la ruta;
                                     global: total (7.911), bloque `impacto` (= data/processed/impacto.json) y la
                                     serie del caso demo de la portada
  data/zonas/impacto.json            data/processed/impacto.json + bloque `pitch` (cifras de F6, con su fuente)
  data/zonas/casos.json              los 10 casos + primera_alerta, anos_adelanto, m3_antes_inspeccion (impacto.adelanto)
  data/zonas/index.json              n_predios = predios exportados por zona
  data/zonas/{z}/predios.geojson     polígonos (simplificados a 5 m) de los predios exportados
  data/zonas/{z}/scores.lite.json    campos de puntaje.parquet por predio (tabla del spec)
  data/zonas/{z}/series/             index.json + bNN.json: por predio y fecha ndvi, ndmi, ref_ndvi, ref_ndmi,
                                     en_ventana_seca, senal (formato indexado: cada predio trae `i`, posiciones en
                                     el eje `fechas`; mismo hash de bloque que js/zona-data.js)
  data/zonas/{z}/historial.json      predios de los casos: banda, puntaje y exceso por temporada (puntaje_validacion)
  data/zonas/{z}/poi.json            hasta 8 POI por predio exportado (poi.parquet)
  data/zonas/{z}/ruta.json, ruta.gpx, ruta.geojson   copia de data/processed/ruta_z*.* (formato de M8 sin cambios)

Qué predios se exportan por zona: banda alta y media de 2025-26, los predios de los 10 casos y de sus vecindarios
de validación (puntaje_validacion.parquet), y las paradas de la ruta. El resto va solo como conteo.

Necesita data/processed/predio.parquet (no va a git): `uv run scripts/extract/predios_ciren.py` desde la raíz.

Modo región (corrida nacional, docs/spec-chile.md): `--region R05 --salida <web/corrida/R05>` exporta lo mismo para
una región, desde la carpeta de trabajo de la etapa region (CAUDAL_DATA): puntaje.parquet, predio.parquet,
predio_cultivo.parquet y anomalias_predio.parquet de esa región. Solo van las bandas alta y media (el resto queda en
el conteo de resumen.json): scores.lite.json (con `aplicabilidad`), predios.geojson y series/. No toca data/zonas.

Uso (desde la raíz del repo o desde frontend-demo/):
  uv run frontend-demo/scripts/build_m5_web.py
  uv run frontend-demo/scripts/build_m5_web.py --region R05 --salida /datos/web/20261121/R05
  python3 frontend-demo/scripts/build_zonas_web.py --check     verifica lo exportado
"""

import argparse
import json
import math
import shutil
import sys
from datetime import date
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
WEB = HERE.parent
ZONAS = WEB / "data" / "zonas"
RAIZ = WEB.parent
sys.path.insert(0, str(RAIZ / "scripts"))
sys.path.insert(0, str(RAIZ / "scripts" / "models"))
sys.path.insert(0, str(HERE))

from comun.rutas import PROC  # noqa: E402  (CAUDAL_DATA; sin la variable, data/processed del repo)

from build_zonas_web import PREDIOS_POR_BLOQUE, bloque_de  # noqa: E402  (mismo hash que js/zona-data.js)

TEMPORADA = "2025-26"
SIMPLIFICAR_M = 5
CRS_METROS = "EPSG:32719"
MAX_POI = 8
# Umbrales de señal por fecha: los de M3 calibrados en M7 (scripts/models/detector_riego.py, valores por defecto)
UMBRAL_VERDOR, UMBRAL_HUMEDAD, DIAS_SECOS_MIN = 2.5, 1.5, 10
# F6 (docs/spec-demo.md): todas las cifras y equivalencias salen de data/processed/impacto.json (M9:
# lift_alta_sin_calibrar, equivalencias, torres_costanera_ano, capacidad). Aquí solo se elige el predio
# del pitch: data/demo.json → "candidato". El identificador no va en el código.


def candidato_pitch() -> int:
    for f in (RAIZ / "data" / "demo.json", WEB / "data" / "demo.json"):
        try:
            d = json.loads(Path(f).read_text())
            v = d.get("candidato") or (d.get("candidato_predio") if isinstance(d, dict) else None)
            if isinstance(v, dict):
                v = v.get("predio_id")
            if v:
                return int(v)
        except (OSError, ValueError, AttributeError):
            pass
    sys.exit("falta el candidato del pitch: data/demo.json → \"candidato\"")

HOY = date.today().isoformat()


def log(*a: object) -> None:
    print("[build_m5_web]", *a, file=sys.stderr)


def dump(obj, path: Path, indent=None) -> float:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=None if indent else (",", ":"), indent=indent, default=_json)
    return path.stat().st_size / 1024


def _json(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return None if np.isnan(o) else float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, (pd.Timestamp, date)):
        return o.isoformat()[:10]
    raise TypeError(type(o))


def num(v, d=None):
    """float/int limpio para JSON (NaN -> None); d decimales, o entero si d es None."""
    if v is None or (isinstance(v, float) and math.isnan(v)) or pd.isna(v):
        return None
    return int(round(float(v))) if d is None else round(float(v), d)


def titulo(s) -> str | None:
    if s is None or pd.isna(s) or not str(s).strip():
        return None
    return str(s).strip().capitalize()


# ---------------------------------------------------------------- entradas

def leer() -> dict:
    if not (PROC / "predio.parquet").exists():
        sys.exit("falta data/processed/predio.parquet: corre `uv run scripts/extract/predios_ciren.py` en la raíz")
    u = pd.read_parquet(PROC / "puntaje.parquet")
    pv = pd.read_parquet(PROC / "puntaje_validacion.parquet")
    casos = json.loads((ZONAS / "casos.json").read_text(encoding="utf-8"))
    index = json.loads((ZONAS / "index.json").read_text(encoding="utf-8"))
    rutas = {z: json.loads((PROC / f"ruta_{z}.json").read_text(encoding="utf-8")) for z in ("z1", "z2")}
    return {"u": u, "pv": pv, "casos": casos, "index": index, "rutas": rutas,
            "impacto": json.loads((PROC / "impacto.json").read_text(encoding="utf-8"))}


def seleccion(d: dict) -> dict[str, dict[int, str]]:
    """{z: {predio_id: motivo}}: alta/media, casos, vecindarios de validación, paradas de la ruta."""
    u, pv = d["u"], d["pv"]
    out: dict[str, dict[int, str]] = {}
    for z in ("z1", "z2"):
        sel: dict[int, str] = {}
        for pid in u.loc[(u.zona == z.upper()) & u.banda.isin(["alta", "media"]), "predio_id"]:
            sel[int(pid)] = "banda"
        for pid in pv.loc[pv.zona == z.upper(), "predio_id"].unique():
            sel.setdefault(int(pid), "vecindario")
        for p in d["rutas"][z]["paradas"]:
            sel.setdefault(int(p["predio_id"]), "ruta")
        for c in d["casos"]:
            if str(c.get("zona", "")).lower() == z and c.get("predio_id") is not None:
                sel[int(c["predio_id"])] = "caso"
        out[z] = sel
    return out


# ---------------------------------------------------------------- predios.geojson

def geometrias(ids: set[int]) -> gpd.GeoDataFrame:
    g = gpd.read_parquet(PROC / "predio.parquet", columns=["predio_id", "zona", "comuna", "rol", "area_ha", "geometry"])
    g = g[g.predio_id.isin(ids)].copy()
    m = g.to_crs(CRS_METROS)
    cent = m.geometry.representative_point().to_crs("EPSG:4326")
    m["geometry"] = m.geometry.simplify(SIMPLIFICAR_M, preserve_topology=True)
    g = m.to_crs("EPSG:4326")
    g["cx"], g["cy"] = cent.x.values, cent.y.values
    return g


def redondear(coords, d=6):
    if isinstance(coords[0], (float, int)):
        return [round(coords[0], d), round(coords[1], d)]
    return [redondear(c, d) for c in coords]


def predios_geojson(z: str, sel: dict[int, str], geo: gpd.GeoDataFrame, u: pd.DataFrame, cult: pd.DataFrame,
                    casos_z: dict[int, str]) -> dict:
    s = u.set_index("predio_id")
    cu = cult.set_index("predio_id")
    feats = []
    for r in geo[geo.predio_id.isin(sel)].itertuples():
        pid = int(r.predio_id)
        a = s.loc[pid] if pid in s.index else None
        c = cu.loc[pid] if pid in cu.index else None
        esp = titulo(c["especie_principal"]) if c is not None else None
        props = {
            # el rol solo va en los predios con un caso sancionado por la DGA (dato público); el resto, por ID
            "id": str(pid), "predio_id": pid, "rol": r.rol if pid in casos_z else None, "comuna": r.comuna, "zona": z,
            "area_ha": num(r.area_ha, 2),
            "cultivo": esp or "sin catastro",
            "especies": (c["especies"] if c is not None and isinstance(c["especies"], str) else None),
            "area_fruticola_ha": num(c["area_fruticola_ha"], 2) if c is not None else None,
            "frac_fruticola": num(c["frac_fruticola"], 3) if c is not None else None,
            "m3_derecho_rol": num(a["m3_derecho_asignado"]) if a is not None else None,
            "m3_derecho_entorno_500m": num(a["m3_anual_derecho_entorno_500m"]) if a is not None else None,
            "estado_derechos": a["estado_derechos"] if a is not None else None,
            "confianza_cruce": a["confianza_cruce"] if a is not None and isinstance(a["confianza_cruce"], str) else None,
            "pozo_compartido_500m": bool(a["pozo_compartido_500m"]) if a is not None else None,
            "dist_canal_m": num(a["dist_canal_m"]) if a is not None else None,
            "caso": casos_z.get(pid),
            "exportado_por": sel[pid],
            "centroid": [round(r.cx, 6), round(r.cy, 6)],
        }
        feats.append({"type": "Feature", "properties": props,
                      "geometry": {"type": r.geometry.geom_type,
                                   "coordinates": redondear(r.geometry.__geo_interface__["coordinates"], 5)}})
    feats.sort(key=lambda f: f["properties"]["predio_id"])
    return {"type": "FeatureCollection", "fuente": "CIREN (predio.parquet), simplificado a 5 m; "
            "especie: Catastro Frutícola CIREN 2025 (predio_cultivo.parquet); derechos: puntaje.parquet (M5)",
            "features": feats}


# ---------------------------------------------------------------- scores.lite.json

def lista_motivos(m) -> list[str]:
    return [t for t in str(m or "").split(";") if t.strip()]


def scores_lite(z: str, sel: dict[int, str], u: pd.DataFrame, pv: pd.DataFrame, fisc: set[int]) -> dict:
    s = u[u.predio_id.isin(sel)]
    falta = set(sel) - set(s.predio_id)
    if falta:  # no elegibles en 2025-26: su fila 2025-26 de la validación, sin puesto
        s = pd.concat([s, pv[pv.predio_id.isin(falta) & (pv.temporada == TEMPORADA)].assign(rank_zona=np.nan)])
    predios = {}
    for r in s.itertuples():
        pid = int(r.predio_id)
        predios[str(pid)] = {
            "rank": num(r.rank_zona), "banda": r.banda, "puntaje": num(r.puntaje, 2), "confianza": r.confianza,
            "motivos": lista_motivos(r.motivos),
            "frac_senal": num(r.frac_senal, 3), "n_fechas": num(r.n_fechas_validas),
            "consumo_m3": [num(r.m3_consumo_bruto_min), num(r.m3_consumo_bruto_central), num(r.m3_consumo_bruto_max)],
            "derecho_m3": num(r.m3_derecho_asignado), "derecho_ajeno_m3": num(r.m3_derecho_ajeno_disponible_500m),
            "exceso_m3": [num(r.m3_exceso_min), num(r.m3_exceso_central), num(r.m3_exceso_max)],
            "estado_derechos": r.estado_derechos, "canal_m": num(r.dist_canal_m),
            "fiscalizado_500m": pid in fisc,
        }
    return {
        "provisional": False, "temporada": TEMPORADA, "generado": HOY,
        "metodo": "Índice de sospecha M5 (scripts/models/indice_sospecha.py): señal de riego en ventana seca (M3), "
                  "consumo FAO-56 (M4) y derechos asignados; exceso = consumo bruto − derecho, en rango.",
        "fuente": "data/processed/puntaje.parquet; fiscalizado_500m como impacto.py (sin_fiscalizar_500m)",
        "predios": predios,
    }


# ---------------------------------------------------------------- series

def anomalias(ids_val: set[int], ids_eleg: set[int]) -> pd.DataFrame:
    cols = ["predio_id", "zona", "fecha", "temporada", "ndvi", "ndmi", "estado", "z_verdor", "z_humedad",
            "ref_ndvi_mediana", "ref_ndmi_mediana"]
    av = pd.read_parquet(PROC / "anomalias_predio_validacion.parquet", columns=cols)
    ae = pd.read_parquet(PROC / "anomalias_predio_elegibles_2025-26.parquet", columns=cols)
    a = pd.concat([av[av.predio_id.isin(ids_val)], ae[ae.predio_id.isin(ids_eleg - ids_val)]], ignore_index=True)
    return con_senal(a)


def con_senal(a: pd.DataFrame) -> pd.DataFrame:
    """Agrega ventana seca y señal por fecha (umbrales de M3) a las anomalías de M2."""
    from detector_riego import en_ventana
    a = en_ventana(a)
    a["en_ventana_seca"] = a.ventana_id.notna() & (a.dias_sin_lluvia >= DIAS_SECOS_MIN)
    a["senal"] = (a.en_ventana_seca & (a.estado == "ok") & (a.z_verdor >= UMBRAL_VERDOR)
                  & (a.z_humedad >= UMBRAL_HUMEDAD))
    a["fecha_s"] = a.fecha.dt.strftime("%Y-%m-%d")
    return a.sort_values(["predio_id", "fecha"])


def r3(v):
    return None if v is None or pd.isna(v) else round(float(v), 3)


def series_zona(a: pd.DataFrame, ids: list[int], fuente_val: set[int]) -> tuple[dict, dict[int, dict]]:
    a = a[a.predio_id.isin(ids)]
    fechas = sorted(a.fecha_s.unique())
    pos = {f: i for i, f in enumerate(fechas)}
    n_bloques = max(1, math.ceil(len(ids) / PREDIOS_POR_BLOQUE))
    bloques = {b: {"predios": {}} for b in range(n_bloques)}
    for pid, g in a.groupby("predio_id"):
        bloques[bloque_de(str(pid), n_bloques)]["predios"][str(pid)] = {
            "i": [pos[f] for f in g.fecha_s],
            "ndvi": [r3(v) for v in g.ndvi], "ndmi": [r3(v) for v in g.ndmi],
            "ref_ndvi": [r3(v) for v in g.ref_ndvi_mediana], "ref_ndmi": [r3(v) for v in g.ref_ndmi_mediana],
            "en_ventana_seca": [int(v) for v in g.en_ventana_seca], "senal": [int(v) for v in g.senal],
        }
    # línea de secano de la zona (compatibilidad con chart.js): mediana mensual de la referencia de cada predio
    m = a.assign(mes=a.fecha.dt.strftime("%Y-%m")).groupby("mes")[["ref_ndvi_mediana", "ref_ndmi_mediana"]].median()
    index = {
        "formato": "indexado",
        "fechas": fechas, "meses": fechas,
        "bloques": n_bloques, "predios_por_bloque": PREDIOS_POR_BLOQUE,
        "campos": ["ndvi", "ndmi", "ref_ndvi", "ref_ndmi", "en_ventana_seca", "senal"],
        "fuente": "Sentinel-2 L2A, anomalías M2: anomalias_predio_elegibles_2025-26.parquet (temporada 2025-26) y "
                  "anomalias_predio_validacion.parquet (2019-20 a 2025-26) para los predios de los casos y sus vecindarios",
        "senal": f"en ventana seca (≥ {DIAS_SECOS_MIN} días sin lluvia), despejada, z_verdor ≥ {UMBRAL_VERDOR} y "
                 f"z_humedad ≥ {UMBRAL_HUMEDAD} (M3, umbrales de M7)",
        "predios_7_temporadas": sorted(str(p) for p in fuente_val if p in set(ids)),
        "referencia_secano": {
            "descripcion": "Mediana mensual, entre los predios exportados de la zona, de la referencia de secano de "
                           "cada predio (30 polígonos CONAF más cercanos, M2). La referencia propia de cada predio "
                           "va en ref_ndvi / ref_ndmi.",
            "serie": [{"fecha": mes, "ndvi": r3(x.ref_ndvi_mediana), "ndmi": r3(x.ref_ndmi_mediana)}
                      for mes, x in m.iterrows()],
        },
    }
    return index, bloques


# ---------------------------------------------------------------- historial, POI, casos, impacto

def historial(pv: pd.DataFrame, ids: list[int]) -> dict:
    out = {}
    for pid, g in pv[pv.predio_id.isin(ids)].sort_values("temporada").groupby("predio_id"):
        out[str(pid)] = [{"temporada": r.temporada, "banda": r.banda, "puntaje": num(r.puntaje, 2),
                          "confianza": r.confianza, "m3_exceso_min": num(r.m3_exceso_min),
                          "m3_exceso_central": num(r.m3_exceso_central), "m3_exceso_max": num(r.m3_exceso_max)}
                         for r in g.itertuples()]
    return {"fuente": "data/processed/puntaje_validacion.parquet (M5 por temporada, 2019-20 a 2025-26)",
            "predios": out}


def poi_zona(poi: pd.DataFrame, ids: set[int]) -> dict:
    p = poi[poi.predio_id.isin(ids)].sort_values(["predio_id", "confianza"], ascending=[True, False])
    out = {}
    for pid, g in p.groupby("predio_id"):
        out[str(pid)] = [{"tipo": r.tipo, "lon": round(r.lon, 6), "lat": round(r.lat, 6), "razon": r.razon,
                          "confianza": num(r.confianza, 2)} for r in g.head(MAX_POI).itertuples()]
    return {"fuente": "data/processed/poi.parquet (M10)", "predios": out}


def casos_enriquecidos(casos: list[dict]) -> list[dict]:
    from validacion import casos as casos_validacion
    from impacto import adelanto
    f = casos_validacion()
    exp = [c["expediente"] for c in casos]
    g = f[f.expediente.isin(exp)].copy()
    det = dict(zip(g.expediente, g.detectable.fillna(False).astype(bool)))
    # misma regla de impacto.adelanto() para los 10 casos (todos positivos con predio); `detectable` se informa aparte
    g["y"], g["detectable"] = True, True
    ad = adelanto(g).set_index("expediente")
    out = []
    for c in casos:
        c = {k: v for k, v in c.items() if k not in ("primera_alerta", "anos_adelanto", "m3_antes_inspeccion",
                                                       "temporadas_en_alta", "censurado", "banda_previa", "detectable")}
        r = ad.loc[c["expediente"]] if c["expediente"] in ad.index else None
        alerta = r is not None and isinstance(r.get("primera_alerta"), str)
        c |= {
            "detectable": det.get(c["expediente"]),
            "banda_previa": (r["banda_previa"] if r is not None and isinstance(r["banda_previa"], str) else None),
            "primera_alerta": r["primera_alerta"] if alerta else None,
            "anos_adelanto": num(r["anos_adelanto"], 2) if alerta else None,
            "temporadas_en_alta": num(r["temporadas_en_alta"]) if alerta else 0,
            "censurado": bool(r["censurado"]) if alerta else None,
            "m3_antes_inspeccion": ({"min": num(r["m3_exceso_min"]), "central": num(r["m3_exceso_central"])}
                                    if alerta else None),
        }
        out.append(c)
    return out


def inspecciones_por_ano() -> float:
    """Igual que impacto.py (acierto + main): fiscalizaciones por extracción en Z1 y Z2, promedio 2020–2025."""
    fis = pd.read_parquet(PROC / "fiscalizacion.parquet")
    fis = fis[fis["extraccion"].fillna(False).astype(bool) & fis["zona"].isin(["Z1", "Z2"])]
    insp = fis.groupby(pd.to_datetime(fis["fecha_inspeccion"]).dt.year).size()
    return float(insp[insp.index.isin(range(2020, 2026))].mean())


def impacto_web(imp: dict, u: pd.DataFrame) -> dict:
    """Bloque "pitch" con las cifras de F6 leídas de impacto.json (M9). No define números propios."""
    cid = candidato_pitch()
    cand = u[u.predio_id == cid].iloc[0]
    exceso_min = float(cand.m3_exceso_min)
    eq = imp["equivalencias"]
    m3_persona = float(eq["m3_persona_ano"]["valor"])
    m3_lata = float(eq["lata_monster_ml"]["valor"]) / 1e6
    m3_torre = float(eq["torre_costanera_m3"]["valor"])
    lift = imp["lift_alta_sin_calibrar"]
    torres = imp["torres_costanera_ano"]
    cap = imp["capacidad"]
    esc = imp["escenarios"]
    return imp | {"pitch": {
        "generado": HOY,
        "lift": {"valor": num(lift["valor"], 2), "ic_bajo": num(lift["ic_bajo"], 2), "ic_alto": num(lift["ic_alto"], 2),
                 "positivos": lift.get("positivos"), "de": lift.get("de"),
                 "fuente": "impacto.json lift_alta_sin_calibrar (umbrales fijados antes de mirar; docs/validacion.md)",
                 "nota": "No se usa lift_alta: se midió con los mismos casos que calibraron los umbrales"},
        "predio": {
            "predio_id": cid, "zona": cand.zona,
            "m3_exceso_min": num(exceso_min), "m3_exceso_central": num(cand.m3_exceso_central),
            "m3_exceso_max": num(cand.m3_exceso_max),
            "m3_persona_ano": m3_persona, "personas": num(exceso_min / m3_persona),
            "m3_lata": m3_lata, "latas": num(exceso_min / m3_lata),
            "persona": eq["m3_persona_ano"], "lata": eq["lata_monster_ml"],
            "fuente": "puntaje.parquet m3_exceso_min del predio ÷ impacto.json equivalencias",
        },
        "candidatos": {"n": imp["candidatos"], "por_zona": imp["candidatos_por_zona"],
                       "fuente": "impacto.json candidatos: banda alta 2025-26 sin fiscalización de la DGA a 500 m "
                                 "desde 2018"},
        "torres": {
            "m3_torre": m3_torre, "torre": eq["torre_costanera_m3"],
            "m3_ano_conservador": num(esc["conservador"]["m3_ano"]), "m3_ano_central": num(esc["central"]["m3_ano"]),
            "valor_min": round(float(torres["conservador"]), 2), "valor_max": round(float(torres["central"]), 2),
            "min": round(float(torres["conservador"])), "max": math.floor(float(torres["central"])),
            "redondeo": "mínimo al entero más cercano y máximo hacia abajo (4,7 → 5; 20,7 → 20)",
            "fuente": "impacto.json torres_costanera_ano (conservador y central)",
        },
        "capacidad": {
            "candidatos_hasta_100ha": cap["candidatos_hasta_100ha"],
            "fiscalizaciones_ano": round(float(cap["fiscalizaciones_por_ano"]), 1),
            "anos_valor": round(float(cap["anos"]), 2), "anos": round(float(cap["anos"])),
            "fuente": "impacto.json capacidad",
        },
        "pie": (f"{esc['conservador']['m3_ano'] / 1e6:.1f} a {esc['central']['m3_ano'] / 1e6:.1f} millones de m³ al año"
                .replace(".", ",") + f" · torre estimada en {m3_torre:,.0f} m³".replace(",", ".")),
    }}


def fiscalizados_500m(ids: pd.Series) -> set[int]:
    from impacto import sin_fiscalizar_500m
    sin = sin_fiscalizar_500m(ids).to_numpy()
    return set(int(x) for x in ids[~sin])


# ---------------------------------------------------------------- resumen de ruta y demo

def resumen_ruta(r: dict) -> dict:
    return {
        "paradas": r["n_visitados"], "distancia_km": r["total_km"], "duracion_min": round(r["total_min"]),
        "hora_inicio": r["hora_inicio"], "hora_termino": r["hora_termino"], "jornada_h": r["jornada_h"],
        "n_candidatos": r["n_candidatos"],
        "inicio": {"nombre": r["inicio"]["nombre"], "lon": r["inicio"]["lon"], "lat": r["inicio"]["lat"]},
    }


def demo_resumen(casos: list[dict], z_data: dict) -> dict | None:
    """Serie del caso demo de la portada (mismo criterio que js/chart.js → renderChart)."""
    con = [c for c in casos if c.get("predio_id") is not None]
    caso = next((c for c in con if c.get("papel") == "demo_principal"), None) or (con[0] if con else None)
    if not caso:
        return None
    z = str(caso["zona"]).lower()
    pid = str(caso["predio_id"])
    idx, bloques = z_data[z]["series"]
    cols = next((b["predios"][pid] for b in bloques.values() if pid in b["predios"]), None)
    rows = []
    if cols:
        for k, i in enumerate(cols["i"]):
            rows.append({"fecha": idx["fechas"][i], **{c: cols[c][k] for c in idx["campos"]}})
    return {"expediente": caso["expediente"], "zona": z, "predio_id": pid, "rol": caso.get("rol"),
            "series": {"predios": {pid: rows}, "referencia_secano": {"serie": idx["referencia_secano"]["serie"]}},
            "clima": {"ventanas_secas": (json.loads((ZONAS / z / "clima.json").read_text(encoding="utf-8"))
                                         .get("ventanas_secas") or []) if (ZONAS / z / "clima.json").exists() else []}}


# ---------------------------------------------------------------- modo región (corrida nacional)

def main_region(zona: str, salida: Path) -> int:
    u = pd.read_parquet(PROC / "puntaje.parquet")
    u = u[(u.zona == zona) & (u.temporada == TEMPORADA)]
    sel = {int(p): "banda" for p in u.loc[u.banda.isin(["alta", "media"]), "predio_id"]}
    counts = {b: int((u.banda == b).sum()) for b in ("alta", "media", "baja", "sin_alerta")}
    log(f"{zona}: {len(sel)} predios de banda alta o media de {len(u)}")
    ids = sorted(sel)
    geo = geometrias(set(sel))
    cult = pd.read_parquet(PROC / "predio_cultivo.parquet")
    fisc = set(int(p) for p in u.loc[u.fiscalizado_dga, "predio_id"])

    pg = predios_geojson(zona, sel, geo, u, cult, {})
    aplic = u.set_index("predio_id")["aplicabilidad"]
    for f in pg["features"]:
        f["properties"]["aplicabilidad"] = aplic.get(f["properties"]["predio_id"])
    pg["fuente"] = "CIREN (predio.parquet), simplificado a 5 m; derechos y exceso: puntaje.parquet (M5), corrida nacional"
    sl = scores_lite(zona, sel, u, pd.DataFrame(columns=u.columns), fisc)
    sl["metodo"] += f" Región {zona}: percentil y ranking por región."
    sl["fuente"] = "modelo/<corrida>/region=" + zona + "/puntaje.parquet"
    for pid, p in sl["predios"].items():
        p["aplicabilidad"] = aplic.get(int(pid))
    an = pd.read_parquet(PROC / "anomalias_predio.parquet", columns=[
        "predio_id", "zona", "fecha", "temporada", "ndvi", "ndmi", "estado", "z_verdor", "z_humedad",
        "ref_ndvi_mediana", "ref_ndmi_mediana"])
    a = con_senal(an[an.predio_id.isin(sel)])
    index, bloques = series_zona(a, ids, set())
    index["fuente"] = "Sentinel-2 L2A, anomalías M2 de la región (anomalias_predio.parquet), temporada 2025-26"
    index["predios_7_temporadas"] = []

    kb = {"predios": dump(pg, salida / "predios.geojson"), "scores": dump(sl, salida / "scores.lite.json")}
    if (salida / "series").is_dir():
        shutil.rmtree(salida / "series")
    kb["series_index"] = dump(index, salida / "series" / "index.json")
    kb["series_bloques"] = sum(dump(b, salida / "series" / f"b{n:02d}.json") for n, b in sorted(bloques.items()))
    dump({"zona": zona, "temporada": TEMPORADA, "generado": HOY, "predios": len(u), "exportados": len(sel),
          "counts": counts, "aplicabilidad": u["aplicabilidad"].iloc[0] if len(u) else None},
         salida / "conteo.json")
    log(f"{zona}: " + " · ".join(f"{k} {v:.0f} KB" for k, v in kb.items()) + f" · {len(bloques)} bloques")
    return 0


# ---------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--region", help="modo región (corrida nacional): código de la región, p. ej. R05")
    ap.add_argument("--salida", type=Path, help="carpeta de salida del modo región (web/<corrida>/<región>)")
    args = ap.parse_args()
    if args.region:
        if not args.salida:
            sys.exit("--region necesita --salida")
        return main_region(args.region, args.salida)
    d = leer()
    u, pv = d["u"], d["pv"]
    sel = seleccion(d)
    todos = set().union(*[set(s) for s in sel.values()])
    log("predios exportados:", {z: len(s) for z, s in sel.items()})

    geo = geometrias(todos)
    sin_geo = todos - set(geo.predio_id)
    if sin_geo:
        log("AVISO sin geometría:", sorted(sin_geo)[:10])
    cult = pd.read_parquet(PROC / "predio_cultivo.parquet")
    poi = pd.read_parquet(PROC / "poi.parquet", columns=["predio_id", "tipo", "lon", "lat", "razon", "confianza"])
    fisc = fiscalizados_500m(pd.Series(sorted(todos)))
    ids_val = set(int(x) for x in pv.predio_id.unique())
    a = anomalias(ids_val & todos, todos)

    casos = casos_enriquecidos(d["casos"])
    z_data = {}
    resumen_z = {}
    for z, s in sel.items():
        zd = ZONAS / z
        casos_z = {int(c["predio_id"]): c["expediente"] for c in casos
                   if str(c["zona"]).lower() == z and c.get("predio_id") is not None}
        kb = {}
        kb["predios"] = dump(predios_geojson(z, s, geo, u, cult, casos_z), zd / "predios.geojson")
        kb["scores"] = dump(scores_lite(z, s, u, pv, fisc), zd / "scores.lite.json")
        ids = sorted(s)
        index, bloques = series_zona(a, ids, ids_val)
        z_data[z] = {"series": (index, bloques)}
        if (zd / "series").is_dir():
            shutil.rmtree(zd / "series")
        kb["series_index"] = dump(index, zd / "series" / "index.json")
        kb["series_bloques"] = sum(dump(b, zd / "series" / f"b{n:02d}.json") for n, b in sorted(bloques.items()))
        # historial: predios de los casos y su vecindario de la fiscalización (fiscalizacion.parquet `vecindario`)
        fis = pd.read_parquet(PROC / "fiscalizacion.parquet", columns=["expediente", "vecindario"])
        vec = {int(p) for v in fis[fis.expediente.isin(casos_z.values())].vecindario for p in (v if v is not None else [])}
        kb["historial"] = dump(historial(pv, sorted(set(casos_z) | vec)), zd / "historial.json")
        kb["poi"] = dump(poi_zona(poi, set(s)), zd / "poi.json")
        for ext in ("json", "gpx", "geojson"):
            shutil.copyfile(PROC / f"ruta_{z}.{ext}", zd / f"ruta.{ext}")
        for viejo in ("scores.json", "series.json"):  # archivos de una exportación anterior, ya sin uso
            (zd / viejo).unlink(missing_ok=True)
        uz = u[u.zona == z.upper()]
        counts = {b: int((uz.banda == b).sum()) for b in ("alta", "media", "baja", "sin_alerta")} | {"sin_dato": 0}
        resumen_z[z] = {"predios": len(uz), "exportados": len(s), "counts": counts,
                        "ruta": resumen_ruta(d["rutas"][z])}
        log(f"{z}: {len(s)} predios exportados de {len(uz)} · " + " · ".join(f"{k} {v:.0f} KB" for k, v in kb.items())
            + f" · {len(bloques)} bloques")

    imp = impacto_web(d["impacto"], u)
    dump(imp, ZONAS / "impacto.json", indent=2)
    dump(casos, ZONAS / "casos.json", indent=1)
    resumen = {
        "temporada": TEMPORADA, "generado": HOY, "provisional": False,
        "total": int(len(u)), "zonas": resumen_z, "impacto": d["impacto"],
        "demo": demo_resumen(casos, z_data),
    }
    dump(resumen, ZONAS / "resumen.json")
    idx = d["index"]
    for zi in idx.get("zonas", []):
        zi["n_predios"] = resumen_z[str(zi["id"]).lower()]["exportados"]
        zi["n_predios_analizados"] = resumen_z[str(zi["id"]).lower()]["predios"]
    idx["generado_por"] = "frontend-demo/scripts/build_m5_web.py (antes build_zonas_data.py)"
    dump(idx, ZONAS / "index.json")
    p = imp["pitch"]
    log(f"resumen: total {resumen['total']} · impacto pitch: lift {p['lift']['valor']} · predio {p['predio']['personas']} "
        f"personas / {p['predio']['latas']} latas · {p['candidatos']['n']} candidatos · torres "
        f"{p['torres']['valor_min']}–{p['torres']['valor_max']} · {p['capacidad']['anos_valor']} años")
    for c in casos:
        log(f"caso {c['expediente']}: primera_alerta {c['primera_alerta']} · {c['anos_adelanto']} años · "
            f"m3 {c['m3_antes_inspeccion']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
