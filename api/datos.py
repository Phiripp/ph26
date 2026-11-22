"""Recursos de lectura de Caudal: arma cada recurso del contrato de datos (docs/spec-demo.md) desde data/processed/.

Lo usan las rutas GET de la API (api/main.py) y el respaldo estático (api/respaldo.py): una sola fuente, así la API
y el respaldo no se desalinean. No escribe nada ni define cifras propias: cada valor sale de un Parquet o JSON que
genera un script del repo.

Cómo lee:
- Una base DuckDB en memoria por proceso. Los Parquet tabulares se registran como vistas (no se copian a memoria).
- Tres tablas chicas se calculan una vez al arrancar, con las mismas funciones de los modelos:
  - `fechas`: cada imagen por predio, marcada con detector_riego.en_ventana y marcar_senal (ventana seca, válida, señal).
  - `fisc500`: predios con una fiscalización de la DGA a 500 m o menos desde 2018 (impacto.sin_fiscalizar_500m).
  - `centro`: punto interior de cada predio, para centrar el mapa.
- Las geometrías salen de predio.parquet (capa de CIREN, no está en git), simplificadas a 5 m. Sin ese archivo, el
  resto funciona y las geometrías, los centros y `fiscalizado_500m` quedan sin dato.

Privacidad: ningún recurso devuelve nombres de titulares (no se leen). El rol solo sale si se pide (`rol=True`).
Los casos son los 10 de data/casos_validacion.geojson, todos resueltos por la DGA: un expediente en trámite no se sirve.
"""

import hashlib
import json
import logging
import math
import os
import re
import time
import subprocess
import sys
import threading
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path

import duckdb
import pandas as pd

RAIZ = Path(os.environ.get("CAUDAL_RAIZ") or Path(__file__).resolve().parents[1])
DATA = RAIZ / "data"
PROC = DATA / "processed"
sys.path.insert(0, str(RAIZ / "scripts" / "models"))

from detector_riego import DIAS_MIN, FRAC_MIN, UMBRAL_HUMEDAD, UMBRAL_VERDOR, en_ventana, marcar_senal  # noqa: E402
from explicacion import explicacion, lista_motivos  # noqa: E402

log = logging.getLogger("caudal.datos")
BANDAS = ["alta", "media", "baja", "sin_alerta"]
BANDAS_MAPA = ["alta", "media"]  # las que llevan polígono en el mapa
SIMPLIFICAR_M = 5
CRS_METROS = "EPSG:32719"
MAX_POI = 8
FAMILIAS = ["_elegibles_2025-26", "_validacion"]  # series de M2 y M3; si una fecha está en las dos, vale la primera
COLS_FECHA = ["predio_id", "zona", "fecha", "escena_id", "temporada", "ndvi", "ndmi", "estado", "z_verdor", "z_humedad",
              "ref_ndvi_mediana", "ref_ndmi_mediana"]

_candado = threading.Lock()
_con: duckdb.DuckDBPyConnection | None = None


class NoExiste(LookupError):
    """El predio, la zona o el caso no existe (404)."""


class SinDatos(LookupError):
    """El predio existe, pero no tiene datos para la temporada pedida (422)."""


# ---------------------------------------------------------------- base

def con() -> duckdb.DuckDBPyConnection:
    """Cursor propio de la llamada sobre la base del proceso (las conexiones de DuckDB no se comparten entre hilos)."""
    global _con
    if _con is None:
        with _candado:
            if _con is None:
                _con = _preparar()
    return _con.cursor()


def _preparar() -> duckdb.DuckDBPyConnection:
    c = duckdb.connect(":memory:")
    vistas = {
        "puntaje": "puntaje", "puntaje_validacion": "puntaje_validacion", "cultivo": "predio_cultivo",
        "cauce": "predio_cauce", "derecho": "predio_derecho", "senal": "senal_riego_elegibles_2025-26",
        "senal_validacion": "senal_riego_validacion",
    }
    for vista, archivo in vistas.items():
        c.execute(f"create view {vista} as select * from read_parquet('{PROC / (archivo + '.parquet')}')")
    # Con columnas explícitas: estas dos tablas traen una columna de geometría que aquí no se usa.
    c.execute(f"""create view poi as select poi_id, predio_id, zona, tipo, lon, lat, area_ha, razon, fecha_imagen,
                  n_escenas, confianza from read_parquet('{PROC / 'poi.parquet'}')""")
    c.execute(f"""create view fiscalizacion as select expediente, fecha_inspeccion, tipo_infraccion, resolucion,
                  fecha_resolucion, decision, multa_utm, estado_tramitacion, extraccion, etiqueta, predio_id, zona,
                  vecindario, temporada_previa, ndvi_previo, detectable
                  from read_parquet('{PROC / 'fiscalizacion.parquet'}')""")

    a = pd.concat([pd.read_parquet(PROC / f"anomalias_predio{f}.parquet", columns=COLS_FECHA) for f in FAMILIAS],
                  ignore_index=True).drop_duplicates(["predio_id", "fecha"])
    fechas = marcar_senal(en_ventana(a))[COLS_FECHA + ["dias_sin_lluvia", "en_ventana", "valida", "senal"]]  # noqa: F841
    c.execute("create table fechas as select * from fechas order by predio_id, fecha")

    ids = c.execute("select distinct predio_id from (select predio_id from puntaje union all "
                    "select predio_id from puntaje_validacion)").fetchdf()["predio_id"]
    if (PROC / "predio.parquet").exists():
        from impacto import sin_fiscalizar_500m
        fisc500 = pd.DataFrame({"predio_id": ids[~sin_fiscalizar_500m(ids).to_numpy()]})  # noqa: F841
        g = _geometrias()
        p = g.geometry.representative_point().to_crs("EPSG:4326")
        centro = pd.DataFrame({"predio_id": g.predio_id.to_numpy(), "lon": p.x.round(6).to_numpy(),  # noqa: F841
                               "lat": p.y.round(6).to_numpy(), "rol": g.rol.to_numpy()})
        c.execute("create table fisc500 as select * from fisc500")
        c.execute("create table centro as select * from centro")
    else:
        c.execute("create table fisc500 (predio_id bigint)")
        c.execute("create table centro (predio_id bigint, lon double, lat double, rol varchar)")
    return c


@lru_cache(maxsize=1)
def _geometrias():
    """Polígonos de los predios con puntaje, en metros (EPSG:32719)."""
    import geopandas as gpd
    ids = set(pd.read_parquet(PROC / "puntaje.parquet", columns=["predio_id"]).predio_id) | set(
        pd.read_parquet(PROC / "puntaje_validacion.parquet", columns=["predio_id"]).predio_id)
    g = gpd.read_parquet(PROC / "predio.parquet", columns=["predio_id", "rol", "geometry"])
    return g[g.predio_id.isin(ids)].to_crs(CRS_METROS).reset_index(drop=True)


def con_geometria() -> bool:
    return (PROC / "predio.parquet").exists()


class NoDisponible(LookupError):
    """La corrida nacional no está montada o no tiene regiones (503)."""


def _limpio(v):
    """Valor listo para JSON: NaN y NaT a None, fechas a texto, numpy a Python."""
    if v is None or v is pd.NaT:
        return None
    if isinstance(v, float):
        return None if math.isnan(v) else v
    if isinstance(v, (datetime, pd.Timestamp)):
        return v.isoformat()[:10] if (v.hour, v.minute, v.second) == (0, 0, 0) else v.isoformat(timespec="seconds")
    if isinstance(v, date):
        return v.isoformat()
    if hasattr(v, "item") and not isinstance(v, (list, tuple, dict, str)):
        return _limpio(v.item())
    if isinstance(v, (list, tuple)) or type(v).__name__ == "ndarray":
        return [_limpio(x) for x in v]
    return v


def filas(sql: str, params: list | None = None) -> list[dict]:
    r = con().execute(sql, params or [])
    cols = [d[0] for d in r.description]
    return [{k: _limpio(v) for k, v in zip(cols, f)} for f in r.fetchall()]


def una(sql: str, params: list | None = None) -> dict | None:
    f = filas(sql, params)
    return f[0] if f else None


def red(v, d=None):
    """Redondea para JSON: entero si d es None."""
    if v is None:
        return None
    return int(round(v)) if d is None else round(v, d)


def _json(nombre: Path) -> dict:
    return json.loads(nombre.read_text(encoding="utf-8"))


def zona_id(zona: str) -> str:
    z = str(zona).upper()
    if z not in zonas_def():
        raise NoExiste(f"Zona desconocida: {zona}. Hay: {', '.join(zonas_def())}")
    return z


@lru_cache(maxsize=1)
def zonas_def() -> dict:
    return _json(DATA / "zonas.json")["zonas"]


@lru_cache(maxsize=1)
def temporada_actual() -> str:
    return una("select max(temporada) t from puntaje")["t"]


# ---------------------------------------------------------------- corrida nacional

# Salidas del modelo por región, en el bucket montado (CAUDAL_NACIONAL=/datos/modelo/chile-2025-26): una carpeta
# region=RXX con puntaje.parquet. Se registra una vista con la lista explícita de archivos (no un glob por consulta:
# listar en GCS FUSE es lento) y la lista se vuelve a mirar como mucho cada TTL_NACIONAL segundos, para tomar las
# regiones que terminen de calcularse sin reiniciar.
TTL_NACIONAL = int(os.environ.get("CAUDAL_NACIONAL_TTL", "300"))
_nac: dict = {"raiz": None, "regiones": (), "revisado": 0.0, "conteo": {}, "temporada": None}
_candado_nac = threading.Lock()
RE_REGION = re.compile(r"^R\d{2}$")


def _raiz_nacional() -> Path | None:
    v = os.environ.get("CAUDAL_NACIONAL")
    return Path(v) if v else None


def _regiones_en_disco(raiz: Path) -> tuple[str, ...]:
    try:
        return tuple(sorted(d.name[len("region="):] for d in raiz.glob("region=*")
                            if RE_REGION.match(d.name[len("region="):]) and (d / "puntaje.parquet").exists()))
    except OSError as e:
        log.warning("No se pudo listar %s: %s", raiz, e)
        return ()


def _sin_regiones(raiz: Path):
    raise NoDisponible(f"La corrida nacional no está disponible: {raiz} no existe o no tiene regiones")


def _nacional() -> dict:
    """Estado de la corrida nacional, con la vista `puntaje_nac` registrada. Lanza NoDisponible si no hay datos."""
    raiz = _raiz_nacional()
    if raiz is None:
        raise NoDisponible("La corrida nacional no está configurada (falta CAUDAL_NACIONAL)")
    ahora = time.monotonic()
    if _nac["raiz"] == raiz and ahora - _nac["revisado"] < TTL_NACIONAL:
        return _sin_regiones(raiz) if not _nac["regiones"] else _nac
    with _candado_nac:
        if _nac["raiz"] == raiz and time.monotonic() - _nac["revisado"] < TTL_NACIONAL:
            return _sin_regiones(raiz) if not _nac["regiones"] else _nac
        regiones = _regiones_en_disco(raiz) if raiz.is_dir() else ()
        if not regiones:
            _nac.update(raiz=raiz, regiones=(), revisado=time.monotonic())  # reintenta en el próximo TTL
            return _sin_regiones(raiz)
        if regiones != _nac["regiones"] or _nac["raiz"] != raiz:
            archivos = ", ".join(f"'{raiz / f'region={r}' / 'puntaje.parquet'}'" for r in regiones)
            c = con()
            c.execute(f"create or replace view puntaje_nac as select * from read_parquet([{archivos}], "
                      "union_by_name=true, hive_partitioning=false)")
            conteo = {}
            for f in c.execute("select zona, aplicabilidad, banda, count(*) n from puntaje_nac group by all").fetchall():
                z = conteo.setdefault(f[0], {"aplicabilidad": {}, "bandas": {b: 0 for b in BANDAS}})
                z["aplicabilidad"][f[1]] = z["aplicabilidad"].get(f[1], 0) + f[3]
                z["bandas"][f[2]] = z["bandas"].get(f[2], 0) + f[3]
            _nac.update(conteo=conteo, temporada=c.execute("select max(temporada) from puntaje_nac").fetchone()[0])
            log.info("Corrida nacional: %d regiones (%s)", len(regiones), ", ".join(regiones))
        _nac.update(raiz=raiz, regiones=regiones, revisado=time.monotonic())
        return _nac


def nacional_estado() -> dict:
    """Para /api/health: nunca falla."""
    try:
        n = _nacional()
        return {"disponible": True, "regiones": list(n["regiones"])}
    except Exception as e:  # el servicio sigue sin la corrida nacional
        log.warning("Corrida nacional no disponible: %s", e)
        return {"disponible": False, "regiones": []}


def nacional_firma() -> str:
    """Identifica el conjunto de regiones servido, para el ETag de /api/chile (los datos cambian sin redesplegar)."""
    try:
        return hashlib.sha1(",".join(_nacional()["regiones"]).encode()).hexdigest()[:8]
    except NoDisponible:
        return ""


def chile() -> dict:
    """Regiones disponibles con conteo por banda y por aplicabilidad. Todo es exploratorio fuera de Z1 y Z2."""
    n = _nacional()
    regs = [{"zona": z, "predios": sum(v["bandas"].values()), "bandas": v["bandas"], "aplicabilidad": v["aplicabilidad"],
             "exploratorio": True} for z, v in sorted(n["conteo"].items())]
    return {"corrida": n["raiz"].name, "temporada": n["temporada"], "regiones": regs,
            "predios": sum(r["predios"] for r in regs), "exploratorio": True,
            "nota": "Corrida nacional exploratoria: solo Z1 y Z2 están validadas. Para Z1 y Z2 use /api/zonas y /api/predios.",
            **sello_nacional(n)}


def sello_nacional(n: dict) -> dict:
    return {"calculado": version().get("calculado"), "version_modelo": version().get("commit")}


def ranking_chile(zona: str, banda: str | None = None, limite: int = 200, desde: int = 0) -> dict:
    n = _nacional()
    z = str(zona).upper()
    if z not in n["conteo"]:
        raise NoExiste(f"Región desconocida: {zona}. Hay: {', '.join(sorted(n['conteo']))}")
    donde, params = ["zona = ?"], [z]
    if banda:
        bs = [b.strip() for b in banda.split(",") if b.strip()]
        malas = [b for b in bs if b not in BANDAS]
        if malas:
            raise SinDatos(f"Banda desconocida: {', '.join(malas)}. Hay: {', '.join(BANDAS)}")
        donde.append(f"banda in ({', '.join('?' * len(bs))})")
        params += bs
    w = " where " + " and ".join(donde)
    total = una(f"select count(*) n from puntaje_nac {w}", params)["n"]
    fs = filas(f"""select predio_id, rank_zona, banda, puntaje, confianza, motivos, comuna, area_ha, especie_principal,
                   frac_senal, n_fechas_validas, m3_exceso_min, m3_exceso_central, m3_exceso_max, aplicabilidad
                   from puntaje_nac {w} order by rank_zona limit ? offset ?""", params + [limite, desde])
    return {"zona": z, "corrida": n["raiz"].name, "temporada": n["temporada"], "total": total, "desde": desde,
            "limite": limite, "filtros": {"banda": banda}, "exploratorio": True,
            "predios": [{"predio_id": f["predio_id"], "rank_zona": f["rank_zona"], "banda": f["banda"],
                         "puntaje": red(f["puntaje"], 2), "confianza": f["confianza"],
                         "motivos": lista_motivos(f["motivos"]), "comuna": f["comuna"], "area_ha": red(f["area_ha"], 2),
                         "especie": _titulo(f["especie_principal"]), "frac_senal": red(f["frac_senal"], 3),
                         "n_fechas": f["n_fechas_validas"],
                         "exceso_m3": [red(f["m3_exceso_min"]), red(f["m3_exceso_central"]), red(f["m3_exceso_max"])],
                         "aplicabilidad": f["aplicabilidad"]} for f in fs],
            **sello_nacional(n)}


def predio_chile(predio_id: int, rol: bool = False) -> dict:
    """Fila nacional de puntaje del predio. Sin nombres de titulares; el rol solo con rol=True."""
    n = _nacional()
    f = una("select * from puntaje_nac where predio_id = ? order by temporada desc limit 1", [predio_id])
    if f is None:
        raise NoExiste(f"El predio {predio_id} no está en la corrida nacional")
    en_zonas = una("select 1 x from puntaje where predio_id = ? union all select 1 from puntaje_validacion "
                   "where predio_id = ? limit 1", [predio_id, predio_id]) is not None
    r = {"predio_id": predio_id, "region": f["zona"], "comuna": f["comuna"], "temporada": f["temporada"],
         "aplicabilidad": f["aplicabilidad"], "exploratorio": not en_zonas,
         "puntaje": {"banda": f["banda"], "puntaje": red(f["puntaje"], 2), "confianza": f["confianza"],
                     "motivos": lista_motivos(f["motivos"]), "rank_zona": f["rank_zona"]},
         "senal": {"senal_riego": f["senal_riego"], "frac_senal": red(f["frac_senal"], 3),
                   "n_fechas": f["n_fechas_validas"], "ndvi_mediana": red(f["ndvi_mediana"], 3),
                   "ndmi_mediana": red(f["ndmi_mediana"], 3)},
         "predio": {"area_ha": red(f["area_ha"], 2), "especie": _titulo(f["especie_principal"]),
                    "frac_fruticola": red(f["frac_fruticola"], 3), "predio_grande": f["predio_grande"]},
         "agua": {"consumo_m3": [red(f["m3_consumo_bruto_min"]), red(f["m3_consumo_bruto_central"]),
                                 red(f["m3_consumo_bruto_max"])],
                  "derecho_m3": red(f["m3_derecho_asignado"]),
                  "derecho_ajeno_500m_m3": red(f["m3_derecho_ajeno_disponible_500m"]),
                  "exceso_m3": [red(f["m3_exceso_min"]), red(f["m3_exceso_central"]), red(f["m3_exceso_max"])],
                  "estado_derechos": f["estado_derechos"], "confianza_cruce": f["confianza_cruce"],
                  "confianza_m3": f["confianza_m3"]},
         "contexto": {"canal_300m": f["canal_300m"], "canal_m": red(f["dist_canal_m"]),
                      "fiscalizado_dga": f["fiscalizado_dga"]},
         "corrida": n["raiz"].name, **sello_nacional(n)}
    if not en_zonas:
        r["nota"] = "Predio fuera de Z1 y Z2: resultado exploratorio, sin validar."
    else:
        r["nota"] = "Predio de Z1 o Z2: la ficha completa, con explicación, está en /api/predios/" + str(predio_id)
        r["ficha"] = f"/api/predios/{predio_id}"
    if rol:
        r["predio"]["rol"] = f["rol_id"]
    return r


# ---------------------------------------------------------------- versión

@lru_cache(maxsize=1)
def version() -> dict:
    """Versión de los datos. En la imagen la escribe el despliegue en data/VERSION; en local sale de git."""
    f = DATA / "VERSION"
    if f.exists():
        v = _json(f)
    else:
        def git(*a):
            r = subprocess.run(["git", *a], cwd=RAIZ, capture_output=True, text=True)
            return r.stdout.strip() or None
        v = {"commit": git("rev-parse", "--short", "HEAD"),
             "calculado": git("log", "-1", "--format=%cI", "--", "data/processed/puntaje.parquet")}
    t = temporada_actual()
    v["temporada"] = t
    v["dato_al"] = una("select max(fecha) f from fechas where temporada = ? and valida", [t])["f"]
    v["predios"] = una("select count(*) n from puntaje")["n"]
    return v


def sello() -> dict:
    v = version()
    return {"dato_al": v["dato_al"], "calculado": v.get("calculado"), "version_modelo": v.get("commit")}


# ---------------------------------------------------------------- zonas

def _resumen_ruta(r: dict) -> dict:
    return {"paradas": r["n_visitados"], "km": r["total_km"], "minutos": round(r["total_min"]),
            "hora_inicio": r["hora_inicio"], "hora_termino": r["hora_termino"], "jornada_h": r["jornada_h"],
            "candidatos": r["n_candidatos"],
            "inicio": {k: r["inicio"][k] for k in ("nombre", "lon", "lat")}}


def resumen_zona(zona: str) -> dict:
    z = zona_id(zona)
    n = {f["banda"]: f["n"] for f in filas("select banda, count(*) n from puntaje where zona = ? group by 1", [z])}
    d = zonas_def()[z]
    return {"zona": z, "nombre": d["nombre"], "comunas": d["comunas"], "bbox": d["bbox"],
            "temporada": temporada_actual(), "predios": sum(n.values()),
            "bandas": {b: n.get(b, 0) for b in BANDAS},
            "ruta": _resumen_ruta(ruta(z)), **sello()}


def resumen() -> dict:
    zs = [resumen_zona(z) for z in zonas_def()]
    return {"temporada": temporada_actual(), "predios": sum(z["predios"] for z in zs),
            "bandas": {b: sum(z["bandas"][b] for z in zs) for b in BANDAS}, "zonas": zs, **sello()}


RANKING_SQL = """
select p.predio_id, p.rank_zona, p.banda, p.puntaje, p.confianza, p.motivos, p.comuna, p.area_ha,
       p.especie_principal, p.frac_senal, p.n_fechas_validas,
       p.m3_exceso_min, p.m3_exceso_central, p.m3_exceso_max, p.dist_canal_m, p.canal_300m,
       f.predio_id is not null as fiscalizado_500m, c.lon, c.lat
from puntaje p left join fisc500 f using (predio_id) left join centro c using (predio_id)
"""


def _fila_ranking(f: dict) -> dict:
    return {"predio_id": f["predio_id"], "rank_zona": f["rank_zona"], "banda": f["banda"],
            "puntaje": red(f["puntaje"], 2), "confianza": f["confianza"], "motivos": lista_motivos(f["motivos"]),
            "comuna": f["comuna"], "area_ha": red(f["area_ha"], 2), "especie": _titulo(f["especie_principal"]),
            "frac_senal": red(f["frac_senal"], 3), "n_fechas": f["n_fechas_validas"],
            "exceso_m3": [red(f["m3_exceso_min"]), red(f["m3_exceso_central"]), red(f["m3_exceso_max"])],
            "canal_m": red(f["dist_canal_m"]), "canal_300m": f["canal_300m"],
            "fiscalizado_500m": f["fiscalizado_500m"] if con_geometria() else None,
            "lon": f["lon"], "lat": f["lat"]}


def ranking(zona: str, banda: str | None = None, sin_canal: bool = False, sin_fiscalizar: bool = False,
            limite: int = 200, desde: int = 0) -> dict:
    """Predios de la zona por rank_zona. `banda` acepta varias separadas por coma. Los filtros `sin_canal` (sin canal a
    300 m) y `sin_fiscalizar` (sin fiscalización a 500 m desde 2018) son los del escenario conservador de M9."""
    z = zona_id(zona)
    donde, params = ["p.zona = ?"], [z]
    if banda:
        bs = [b.strip() for b in banda.split(",") if b.strip()]
        malas = [b for b in bs if b not in BANDAS]
        if malas:
            raise SinDatos(f"Banda desconocida: {', '.join(malas)}. Hay: {', '.join(BANDAS)}")
        donde.append(f"p.banda in ({', '.join('?' * len(bs))})")
        params += bs
    if sin_canal:
        donde.append("not coalesce(p.canal_300m, false)")
    if sin_fiscalizar:
        donde.append("f.predio_id is null")
    w = " where " + " and ".join(donde)
    total = una(f"select count(*) n from puntaje p left join fisc500 f using (predio_id) {w}", params)["n"]
    fs = filas(f"{RANKING_SQL} {w} order by p.rank_zona limit ? offset ?", params + [limite, desde])
    return {"zona": z, "temporada": temporada_actual(), "total": total, "desde": desde, "limite": limite,
            "filtros": {"banda": banda, "sin_canal": sin_canal, "sin_fiscalizar": sin_fiscalizar},
            "predios": [_fila_ranking(f) for f in fs], **sello()}


def _titulo(s) -> str | None:
    return str(s).strip().capitalize() if s and str(s).strip() else None


def _nombre(s) -> str | None:
    """Nombre propio en mayúsculas del registro a «Quebrada El Limonal» (las palabras cortas quedan en minúscula)."""
    if not s or not str(s).strip():
        return None
    ws = str(s).split()
    return " ".join(w.capitalize() if (i == 0 or len(w) > 2) else w.lower() for i, w in enumerate(ws))


def _redondear(coords, d=5):
    if isinstance(coords[0], (float, int)):
        return [round(coords[0], d), round(coords[1], d)]
    return [_redondear(c, d) for c in coords]


def _seleccion_mapa(z: str) -> dict[int, str]:
    """Predios con polígono en el mapa de la zona y por qué: banda alta o media, caso, vecindario de la validación
    o parada de la ruta."""
    sel = {f["predio_id"]: "banda" for f in filas(
        f"select predio_id from puntaje where zona = ? and banda in ({', '.join('?' * len(BANDAS_MAPA))})",
        [z] + BANDAS_MAPA)}
    for f in filas("select distinct predio_id from puntaje_validacion where zona = ?", [z]):
        sel.setdefault(f["predio_id"], "vecindario")
    for p in ruta(z)["paradas"]:
        sel.setdefault(int(p["predio_id"]), "ruta")
    for c in casos()["casos"]:
        if c["zona"] == z and c["predio_id"] is not None:
            sel[c["predio_id"]] = "caso"
    return sel


@lru_cache(maxsize=8)
def predios_geojson(zona: str, rol: bool = False) -> dict:
    """GeoJSON de los predios en alerta alta y media de la zona (más casos, vecindarios y paradas de la ruta),
    simplificado a 5 m. El resto de los predios analizados va solo en el ranking y el resumen."""
    z = zona_id(zona)
    if not con_geometria():
        raise SinDatos("Falta data/processed/predio.parquet (capa de CIREN, no está en git): "
                       "uv run scripts/extract/predios_ciren.py")
    sel = _seleccion_mapa(z)
    g = _geometrias()
    g = g[g.predio_id.isin(sel)].copy()
    g["geometry"] = g.geometry.simplify(SIMPLIFICAR_M, preserve_topology=True)
    g = g.to_crs("EPSG:4326")
    t = temporada_actual()
    datos = {f["predio_id"]: f for f in filas(f"{RANKING_SQL} where p.zona = ?", [z])}
    for f in filas("""select v.predio_id, v.banda, v.puntaje, v.confianza, v.motivos, v.comuna, v.area_ha,
                      v.especie_principal, v.frac_senal, v.n_fechas_validas, v.m3_exceso_min, v.m3_exceso_central,
                      v.m3_exceso_max, v.dist_canal_m, v.canal_300m, null as rank_zona,
                      f.predio_id is not null as fiscalizado_500m, c.lon, c.lat
                      from puntaje_validacion v left join fisc500 f using (predio_id) left join centro c using (predio_id)
                      where v.zona = ? and v.temporada = ?""", [z, t]):
        datos.setdefault(f["predio_id"], f)  # predios de la validación que no son elegibles: sin puesto en la zona
    caso_de = {c["predio_id"]: c["expediente"] for c in casos()["casos"] if c["predio_id"] is not None}
    feats = []
    for r in g.sort_values("predio_id").itertuples():
        pid = int(r.predio_id)
        props = {"id": str(pid), **(_fila_ranking(datos[pid]) if pid in datos else {"predio_id": pid}),
                 "zona": z, "caso": caso_de.get(pid), "en_mapa_por": sel[pid]}
        if rol:
            props["rol"] = r.rol
        feats.append({"type": "Feature", "properties": props,
                      "geometry": {"type": r.geometry.geom_type,
                                   "coordinates": _redondear(r.geometry.__geo_interface__["coordinates"])}})
    return {"type": "FeatureCollection", "zona": z, "temporada": t,
            "fuente": "Propiedades Rurales de CIREN (predio.parquet), simplificado a 5 m; puntaje de M5 (puntaje.parquet)",
            **sello(), "features": feats}


@lru_cache(maxsize=4)
def ruta(zona: str) -> dict:
    return _json(PROC / f"ruta_{zona_id(zona).lower()}.json")


def ruta_archivo(zona: str, ext: str) -> Path:
    return PROC / f"ruta_{zona_id(zona).lower()}.{ext}"


# ---------------------------------------------------------------- predio

def _fila_m5(predio_id: int, temporada: str | None) -> tuple[dict, bool]:
    """Fila de M5 del predio y si es del universo de elegibles (con puesto en la zona). Sin temporada: la del ranking
    si el predio es elegible; si no, la última de la validación."""
    for tabla, universo in (("puntaje", True), ("puntaje_validacion", False)):
        f = una(f"select * from {tabla} where predio_id = ? and (? is null or temporada = ?) "
                f"order by temporada desc limit 1", [predio_id, temporada, temporada])
        if f:
            return f, universo
    if una("select 1 from puntaje where predio_id = ? union all select 1 from puntaje_validacion where predio_id = ?",
           [predio_id, predio_id]):
        raise SinDatos(f"El predio {predio_id} no tiene datos en la temporada {temporada}. "
                       f"Tiene: {', '.join(temporadas(predio_id))}")
    raise NoExiste(f"El predio {predio_id} no está entre los predios analizados")


def temporadas(predio_id: int) -> list[str]:
    return [f["temporada"] for f in filas(
        "select distinct temporada from (select predio_id, temporada from puntaje union all "
        "select predio_id, temporada from puntaje_validacion) where predio_id = ? order by 1", [predio_id])]


def _fechas(predio_id: int, temporada: str | None = None) -> list[dict]:
    return filas("select * from fechas where predio_id = ? and (? is null or temporada = ?) order by fecha",
                 [predio_id, temporada, temporada])


def _explicacion(m5: dict, con_fiscalizacion: bool = True) -> dict:
    pid, t = m5["predio_id"], m5["temporada"]
    senal = (una("select n_fechas_senal from senal where predio_id = ? and temporada = ?", [pid, t])
             or una("select n_fechas_senal from senal_validacion where predio_id = ? and temporada = ?", [pid, t]))
    corte = una("select corte from derecho where predio_id = ? and temporada = ?", [pid, t])
    ctx = {"corte_derechos": corte["corte"] if corte else None}
    if con_fiscalizacion and con_geometria():
        ctx["fiscalizado_500m"] = una("select 1 from fisc500 where predio_id = ?", [pid]) is not None
    v = version()
    return explicacion(m5, senal, _fechas(pid, t), ctx, v.get("calculado"), v.get("commit"))


def equivalencias(m3_ano: float | None) -> dict | None:
    """Un volumen anual en personas y latas, con las equivalencias y fuentes de impacto.json (M9)."""
    if not m3_ano or m3_ano <= 0:
        return None
    eq = impacto()["equivalencias"]
    return {"m3_ano": red(m3_ano),
            "personas_ano": {"valor": red(m3_ano / eq["m3_persona_ano"]["valor"]), **_sin_valor(eq["m3_persona_ano"])},
            "latas": {"valor": red(m3_ano / (eq["lata_monster_ml"]["valor"] / 1e6)), **_sin_valor(eq["lata_monster_ml"])}}


def _sin_valor(d: dict) -> dict:
    return {k: v for k, v in d.items() if k != "valor"}


def poi(predio_id: int) -> list[dict]:
    return [{**f, "lon": red(f["lon"], 6), "lat": red(f["lat"], 6), "area_ha": red(f["area_ha"], 2),
             "confianza": red(f["confianza"], 2)}
            for f in filas("select poi_id, tipo, lon, lat, area_ha, razon, fecha_imagen, n_escenas, confianza from poi "
                           "where predio_id = ? order by confianza desc, poi_id limit ?", [predio_id, MAX_POI])]


def contexto(predio_id: int) -> dict:
    """Contexto del predio al elegirlo (M12): cauce, río y canal más cercanos, y fiscalizaciones resueltas en el predio."""
    c = una("select * from cauce where predio_id = ?", [predio_id]) or {}

    def cerca(nombre, dist, **extra):
        if c.get(dist) is None:
            return None
        return {"nombre": _nombre(c.get(nombre)), "dist_m": red(c[dist]), **{k: c.get(v) for k, v in extra.items()}}

    fisc = filas("""select expediente, fecha_inspeccion, decision, multa_utm from fiscalizacion
                    where predio_id = ? and extraccion and etiqueta in ('positivo', 'negativo')
                    order by fecha_inspeccion""", [predio_id])
    return {"cauce": cerca("cauce_nombre", "dist_cauce_m", tipo="cauce_tipo"),
            "rio": cerca("rio_nombre", "dist_rio_m", tipo="rio_tipo"),
            "canal": cerca("canal_nombre", "dist_canal_m", organizacion="canal_organizacion", fuente="canal_fuente"),
            "fiscalizado_500m": (una("select 1 from fisc500 where predio_id = ?", [predio_id]) is not None)
            if con_geometria() else None,
            "fiscalizaciones_resueltas": fisc}


def ficha(predio_id: int, temporada: str | None = None, rol: bool = False) -> dict:
    """Ficha del predio: puntaje, explicación de la alerta, agua, puntos a revisar y contexto."""
    m5, universo = _fila_m5(predio_id, temporada)
    t = m5["temporada"]
    cu = una("select * from cultivo where predio_id = ?", [predio_id]) or {}
    ce = una("select lon, lat, rol from centro where predio_id = ?", [predio_id]) or {}
    n_zona = una("select count(*) n from puntaje where zona = ?", [m5["zona"]])["n"] if universo else None
    caso = next((c["expediente"] for c in casos()["casos"] if c["predio_id"] == predio_id), None)
    predio = {"predio_id": predio_id, "zona": m5["zona"], "comuna": m5["comuna"], "area_ha": red(m5["area_ha"], 2),
              "especie": _titulo(m5["especie_principal"]), "especies": cu.get("especies"),
              "area_fruticola_ha": red(cu.get("area_fruticola_ha"), 2), "frac_fruticola": red(m5["frac_fruticola"], 3),
              "lon": ce.get("lon"), "lat": ce.get("lat")}
    if rol:
        predio["rol"] = ce.get("rol")
    return {
        "predio": predio, "temporada": t, "temporadas": temporadas(predio_id), "caso": caso,
        "puntaje": {"banda": m5["banda"], "puntaje": red(m5["puntaje"], 2), "confianza": m5["confianza"],
                    "motivos": lista_motivos(m5["motivos"]),
                    "rank_zona": m5["rank_zona"] if universo else None, "predios_zona": n_zona},
        "explicacion": _explicacion(m5),
        "agua": {
            "consumo_m3": [red(m5[f"m3_consumo_bruto_{k}"]) for k in ("min", "central", "max")],
            "derecho_m3": red(m5["m3_derecho_asignado"]),
            "derecho_ajeno_500m_m3": red(m5["m3_derecho_ajeno_disponible_500m"]),
            "derecho_entorno_500m_m3": red(m5["m3_anual_derecho_entorno_500m"]),
            "exceso_m3": [red(m5[f"m3_exceso_{k}"]) for k in ("min", "central", "max")],
            "estado_derechos": m5["estado_derechos"],
            "equivalencias": equivalencias(m5["m3_exceso_min"]),
        },
        "poi": poi(predio_id),
        "contexto": contexto(predio_id),
        **sello(),
    }


def serie(predio_id: int, temporada: str | None = None) -> dict:
    """Serie por imagen del predio: verdor (ndvi) y humedad (ndmi) frente al secano de referencia, con las marcas del
    detector de riego. Sin temporada: todas las que tenga (7 en los predios de la validación)."""
    _fila_m5(predio_id, None)  # 404 si el predio no existe
    fs = _fechas(predio_id, temporada)
    if not fs:
        raise SinDatos(f"El predio {predio_id} no tiene imágenes en la temporada {temporada}")
    puntos = [{"fecha": f["fecha"], "temporada": f["temporada"], "escena_id": f["escena_id"], "estado": f["estado"],
               "ndvi": red(f["ndvi"], 3), "ndmi": red(f["ndmi"], 3),
               "ref_ndvi": red(f["ref_ndvi_mediana"], 3), "ref_ndmi": red(f["ref_ndmi_mediana"], 3),
               "dias_sin_lluvia": red(f["dias_sin_lluvia"]), "en_ventana_seca": f["en_ventana"], "valida": f["valida"],
               "senal": f["senal"]} for f in fs]
    return {"predio_id": predio_id, "temporadas": sorted({p["temporada"] for p in puntos}),
            "leyenda": {"ndvi": "verdor del predio", "ndmi": "humedad del predio",
                        "ref_ndvi": "verdor del cerro seco vecino", "ref_ndmi": "humedad del cerro seco vecino",
                        "en_ventana_seca": f"imagen tomada tras {DIAS_MIN} días o más sin lluvia",
                        "valida": "además despejada y con cerro de referencia",
                        "senal": "además más verde y más húmeda que el cerro (señal de riego)"},
            "umbrales": {"z_verdor": UMBRAL_VERDOR, "z_humedad": UMBRAL_HUMEDAD, "dias_sin_lluvia": DIAS_MIN,
                         "fraccion_min": FRAC_MIN, "fuente": "docs/calibracion.md"},
            "fuente": "Sentinel-2 L2A (Earth Search); secano de referencia de CONAF; lluvia de DMC y Open-Meteo",
            "puntos": puntos, **sello()}


# ---------------------------------------------------------------- casos

@lru_cache(maxsize=1)
def casos() -> dict:
    """Los casos resueltos por la DGA que usa la demo (data/casos_validacion.geojson), con lo que Caudal veía antes
    de la inspección: banda previa, primera alerta, años de adelanto (impacto.adelanto) e historial por temporada."""
    from impacto import adelanto
    from validacion import casos as casos_validacion

    curados = _json(DATA / "casos_validacion.geojson")["features"]
    f = casos_validacion()
    f = f[f.expediente.isin([c["properties"]["expediente"] for c in curados])].copy()
    detectable = dict(zip(f.expediente, f.detectable.astype(bool)))
    f["y"], f["detectable"] = True, True  # el adelanto se informa para los 10; `detectable` va aparte
    ad = adelanto(f)
    ad = ad.set_index("expediente") if len(ad) else ad
    fi = {x["expediente"]: x for x in filas("select * from fiscalizacion")}
    utm_clp = impacto()["supuestos"]["utm_clp"]
    out = []
    for c in curados:
        p, (lon, lat) = c["properties"], c["geometry"]["coordinates"][:2]
        x = fi.get(p["expediente"], {})
        r = ad.loc[p["expediente"]] if p["expediente"] in ad.index else None
        alerta = r is not None and isinstance(r.get("primera_alerta"), str)
        pid = x.get("predio_id")
        multa = p.get("multa_utm")
        out.append({
            "expediente": p["expediente"], "papel": p.get("papel"), "zona": p["zona"], "comuna": p["comuna"],
            "predio_id": pid, "lon": round(lon, 6), "lat": round(lat, 6),
            "fecha_inspeccion": p["fecha_inspeccion"], "tipo_infraccion": p.get("tipo_infraccion"),
            "decision": p.get("decision"), "resolucion": p.get("resolucion"), "etiqueta": p.get("etiqueta"),
            "multa_utm": multa, "multa_clp": red(multa * utm_clp) if multa else None,
            "temporada_previa": x.get("temporada_previa"), "detectable": detectable.get(p["expediente"]),
            "banda_previa": r["banda_previa"] if r is not None and isinstance(r["banda_previa"], str) else None,
            "primera_alerta": r["primera_alerta"] if alerta else None,
            "anos_adelanto": red(float(r["anos_adelanto"]), 2) if alerta else None,
            "temporadas_en_alta": int(r["temporadas_en_alta"]) if alerta else 0,
            "censurado": bool(r["censurado"]) if alerta else None,
            "m3_antes_inspeccion": ({"min": red(float(r["m3_exceso_min"])), "central": red(float(r["m3_exceso_central"]))}
                                    if alerta else None),
            "vecindario": [int(v) for v in (x.get("vecindario") or [])],
        })
    out.sort(key=lambda c: (c["zona"], c["fecha_inspeccion"]))
    return {"casos": out,
            "notas": {"censurado": "la serie parte en 2019-20: la primera alerta pudo ser anterior, el adelanto es un mínimo",
                      "multa_clp": f"multa en UTM x {utm_clp} pesos (impacto.json, supuestos.utm_clp)",
                      "primera_alerta": "primera temporada con banda alta, hasta la temporada previa a la inspección"},
            "fuente": "DGA, planilla de fiscalización (fiscalizacion.parquet); puntaje_validacion.parquet (M5)", **sello()}


def caso(expediente: str) -> dict:
    """Un caso con el historial por temporada de su predio y la explicación con los datos previos a la inspección."""
    c = next((c for c in casos()["casos"] if c["expediente"].upper() == expediente.upper()), None)
    if c is None:
        raise NoExiste(f"Caso desconocido: {expediente}. Hay: {', '.join(x['expediente'] for x in casos()['casos'])}")
    c = dict(c)
    pid = c["predio_id"]
    c["historial"] = [{"temporada": f["temporada"], "banda": f["banda"], "puntaje": red(f["puntaje"], 2),
                       "confianza": f["confianza"], "senal_riego": f["senal_riego"], "frac_senal": red(f["frac_senal"], 3),
                       "exceso_m3": [red(f[f"m3_exceso_{k}"]) for k in ("min", "central", "max")],
                       "posterior_a_inspeccion": f["temporada"] > (c["temporada_previa"] or "")}
                      for f in filas("select * from puntaje_validacion where predio_id = ? order by temporada", [pid])]
    previa = una("select * from puntaje_validacion where predio_id = ? and temporada = ?", [pid, c["temporada_previa"]])
    # Antes de la inspección: sin el dato de fiscalización a 500 m, que es la del propio caso
    c["explicacion"] = _explicacion(previa, con_fiscalizacion=False) if previa else None
    return {**c, **sello()}


# ---------------------------------------------------------------- impacto y demo

@lru_cache(maxsize=1)
def impacto() -> dict:
    return _json(PROC / "impacto.json")


def demo() -> dict:
    """Predio y caso que abre el guion de la demo (data/demo.json): configuración, no va en el código del frontend."""
    return _json(DATA / "demo.json")
