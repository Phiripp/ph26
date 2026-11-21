"""Job `caudal-chile-prediccion`: etapa `region` (serie por región y M1 a M5) y etapa `nacional` (docs/spec-chile.md).

Lo llama entrada.py. Las salidas van a modelo/<corrida>/region=RXX/ y web/<corrida>/RXX/ (región) y a
modelo/<corrida>/puntaje_chile.parquet, web/<corrida>/{index,resumen}.json y web/ACTUAL (nacional).
"""

import json
import os
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

APP = Path(__file__).resolve().parents[3]
BUFFER_KM = 10
GRADOS_POR_KM = 1 / 111.32
FALTANTES_MAX = 0.02      # fracción de escenas del plan que pueden faltar en el caché
ESPERA_MAX_S = 30 * 60    # espera máxima del control de completitud
BANDAS = ["alta", "media", "baja", "sin_alerta"]
ORDEN_APLICABILIDAD = {"calibrado": 0, "mediterraneo_seco": 1, "norte_desertico": 2, "sur_humedo": 3}
# Comprobación de regresión contra Z1 y Z2 (docs/spec-chile.md)
COINCIDENCIA_MIN = 0.90
UMBRAL_MM_SIN_CORRECCION = 2.0  # la grilla ERA5-Land sobreestima la lluvia cerca de 2 veces y no hay corrección DMC

COLUMNAS_SERIE = ["predio_id", "zona", "fecha", "ndvi", "ndwi", "ndmi", "ndvi_std", "nubosidad_pct", "n_pix_validos",
                  "n_pix_total", "nubes_escena_pct", "escena_id"]
# Salidas por región: archivo de trabajo (processed/) -> nombre en modelo/<corrida>/region=RXX/. puntaje va al final:
# su existencia es la marca de región terminada.
SALIDAS_MODELO = {"serie_predio.parquet": "serie.parquet", "serie_referencia.parquet": "serie_referencia.parquet",
                  "anomalias_predio.parquet": "anomalias.parquet", "senal_riego.parquet": "senal_riego.parquet",
                  "consumo_predio.parquet": "consumo_predio.parquet",
                  "consumo_predio_temporada.parquet": "consumo_predio_temporada.parquet",
                  "predio_derecho.parquet": "predio_derecho.parquet", "puntaje.parquet": "puntaje.parquet"}


# --- Completitud y serie ----------------------------------------------------------------------------------------------


def faltantes(datos: Path, zona: str) -> pd.DataFrame:
    """Escenas del plan en los tiles de la región que no tienen parquet en s2/cache."""
    tiles = json.loads((datos / "plan" / "regiones_tiles.json").read_text())[zona]
    esc = pd.read_parquet(datos / "plan" / "escenas.parquet")
    esc = esc[esc["tile"].isin(tiles)]
    hechas = set()
    for t in tiles:
        carpeta = datos / "s2" / "cache" / t
        if carpeta.exists():
            hechas |= {n.removesuffix("_chile_v2.parquet") for n in os.listdir(carpeta)}
    return esc[~esc["escena_id"].isin(hechas)].assign(total=len(esc))


def esperar_completitud(datos: Path, zona: str) -> None:
    """Más del 2 % de escenas sin procesar: espera hasta 30 minutos y falla con la lista (relanzar satelite)."""
    t0 = time.time()
    while True:
        f = faltantes(datos, zona)
        total = int(f["total"].iloc[0]) if len(f) else 1
        frac = len(f) / max(total, 1)
        if frac <= FALTANTES_MAX:
            print(f"{zona}: completitud ok, faltan {len(f)} escenas ({frac:.1%})", flush=True)
            return
        if time.time() - t0 > ESPERA_MAX_S:
            sys.exit(f"{zona}: faltan {len(f)} de {total} escenas ({frac:.1%}). Relanza la etapa satelite con las mismas "
                     f"partes (el caché salta lo hecho). Primeras faltantes: {f['escena_id'].head(20).tolist()}")
        print(f"{zona}: faltan {len(f)} escenas ({frac:.1%}); espero 60 s", flush=True)
        time.sleep(60)


def secano_con_buffer(datos: Path, bounds: tuple, zonas: list[str]) -> gpd.GeoDataFrame:
    """Referencia de secano de todas las regiones dentro de la caja de la región más el buffer de 10 km."""
    dlat = BUFFER_KM * GRADOS_POR_KM * 1.2
    dlon = dlat / np.cos(np.radians((bounds[1] + bounds[3]) / 2))
    partes = []
    for z in zonas:
        ruta = datos / "base" / "referencia_secano" / f"region={z}.parquet"
        if ruta.exists():
            g = gpd.read_parquet(ruta)
            if len(g):
                partes.append(g.cx[bounds[0] - dlon : bounds[2] + dlon, bounds[1] - dlat : bounds[3] + dlat])
    partes = [p for p in partes if len(p)]
    if not partes:
        return gpd.GeoDataFrame({"ref_id": [], "zona": [], "comuna": [], "clase": [], "uso_cod": [], "area_ha": [],
                                 "estable": [], "recortado_fruta": []}, geometry=[], crs="EPSG:4326")
    return gpd.GeoDataFrame(pd.concat(partes, ignore_index=True), crs="EPSG:4326").drop_duplicates("ref_id")


def armar_serie(datos: Path, zona: str, ids_predio: np.ndarray, ids_ref: np.ndarray, hilos: int) -> tuple:
    """Paso 4 del spec: serie y serie_referencia de la región desde los parquet de escena de sus tiles."""
    tiles = json.loads((datos / "plan" / "regiones_tiles.json").read_text())[zona]
    esc = pd.read_parquet(datos / "plan" / "escenas.parquet")
    archivos = [datos / "s2" / "cache" / r.tile / f"{r.escena_id}_chile_v2.parquet"
                for r in esc[esc["tile"].isin(tiles)].itertuples()]
    print(f"{zona}: leyendo {len(archivos)} parquet de escena de {len(tiles)} tiles", flush=True)

    def leer(f: Path) -> pd.DataFrame | None:
        if not f.exists():
            return None  # faltante tolerado por el control de completitud
        d = pd.read_parquet(f)
        return d[((d["tipo"] == "predio") & d["poligono_id"].isin(ids_predio))
                 | ((d["tipo"] == "secano") & d["poligono_id"].isin(ids_ref))]

    with ThreadPoolExecutor(hilos) as ex:
        partes = [d for d in ex.map(leer, archivos) if d is not None and len(d)]
    s = pd.concat(partes, ignore_index=True) if partes else pd.DataFrame(columns=["poligono_id", "tipo", *COLUMNAS_SERIE])
    s = s.rename(columns={"poligono_id": "predio_id"}).assign(zona=zona)
    s["fecha"] = pd.to_datetime(s["fecha"])
    # Un predio en dos tiles el mismo día: la escena con más píxeles válidos (la regla actual).
    s = s.sort_values(["tipo", "predio_id", "fecha", "n_pix_validos"], ascending=[True, True, True, False])
    s = s.drop_duplicates(["tipo", "predio_id", "fecha"])
    serie = s[s["tipo"] == "predio"][COLUMNAS_SERIE].reset_index(drop=True)
    ref = s[s["tipo"] == "secano"][COLUMNAS_SERIE].reset_index(drop=True)
    print(f"{zona}: serie {len(serie)} filas ({serie['predio_id'].nunique()} predios), "
          f"referencia {len(ref)} filas ({ref['predio_id'].nunique()} polígonos)", flush=True)
    return serie, ref


# --- Carpeta de trabajo -------------------------------------------------------------------------------------------


def armar_trabajo(cfg: dict, zona: str, datos: Path, trabajo: Path) -> tuple[Path, np.ndarray, np.ndarray]:
    """Copia a `trabajo/processed` lo que los modelos leen, con el esquema de data/processed/ de Z1 y Z2."""
    proc = trabajo / "processed"
    proc.mkdir(parents=True, exist_ok=True)
    base = datos / "base"
    for tabla, destino in (("predio", "predio"), ("cultivo", "predio_cultivo"), ("derecho_predio", "derecho_predio"),
                           ("predio_derecho", "predio_derecho"), ("fiscalizacion", "fiscalizacion"),
                           ("clima", "clima"), ("predio_clima", "predio_clima")):
        origen = base / tabla / f"region={zona}.parquet"
        if not origen.exists():
            sys.exit(f"Falta {origen}: la etapa base de {zona} no terminó")
        shutil.copyfile(origen, proc / f"{destino}.parquet")

    predios = gpd.read_parquet(proc / "predio.parquet", columns=["predio_id", "elegible", "geometry"])
    elegibles = predios[predios["elegible"]]
    bounds = tuple(elegibles.total_bounds)

    # Derechos de la región y los de regiones vecinas dentro de la caja con buffer (derechos ajenos a 500 m de M5).
    dlat = BUFFER_KM * GRADOS_POR_KM
    dlon = dlat / np.cos(np.radians((bounds[1] + bounds[3]) / 2))
    derechos = []
    for z in cfg["zonas"]:
        ruta = base / "derecho" / f"region={z}.parquet"
        if ruta.exists():
            g = gpd.read_parquet(ruta)
            if z != zona:
                g = g.cx[bounds[0] - dlon : bounds[2] + dlon, bounds[1] - dlat : bounds[3] + dlat]
            derechos.append(g)
    pd.concat(derechos, ignore_index=True).drop_duplicates("derecho_id").pipe(
        lambda d: gpd.GeoDataFrame(d, crs="EPSG:4326")).to_parquet(proc / "derecho.parquet", index=False)

    ref = secano_con_buffer(datos, bounds, list(cfg["zonas"]))
    ref.to_parquet(proc / "referencia_secano.parquet", index=False)
    print(f"{zona}: {len(elegibles)} predios elegibles, {len(ref)} polígonos de secano con buffer", flush=True)
    return proc, elegibles["predio_id"].to_numpy(), ref["ref_id"].to_numpy()


# --- Etapa region -----------------------------------------------------------------------------------------------


def region(cfg: dict, zona: str, corrida: str, datos: Path, raiz_trabajo: Path, correr, config_de) -> None:
    modelo = datos / "modelo" / corrida / f"region={zona}"
    web = datos / "web" / corrida / zona
    if (modelo / "puntaje.parquet").exists() and (web / "scores.lite.json").exists():
        print(f"{zona}: ya terminada en la corrida {corrida}; nada que hacer")
        return
    trabajo = raiz_trabajo / f"{zona}-prediccion"
    shutil.rmtree(trabajo, ignore_errors=True)
    hilos = int(os.environ.get("HILOS", "8"))
    esperar_completitud(datos, zona)

    proc, ids_predio, ids_ref = armar_trabajo(cfg, zona, datos, trabajo)
    serie, serie_ref = armar_serie(datos, zona, ids_predio, ids_ref, hilos)
    if serie.empty:
        sys.exit(f"{zona}: la serie quedó vacía; revisa s2/cache y plan/poligonos_tile")
    serie.to_parquet(proc / "serie_predio.parquet", index=False)
    serie_ref.to_parquet(proc / "serie_referencia.parquet", index=False)
    zonas_json = config_de(cfg, [zona], trabajo / f"regiones_{zona}.json")

    def modelo_(script: str, *args: str) -> None:
        correr(f"scripts/models/{script}", list(args), trabajo, zonas_json)

    p = lambda n: str(proc / n)  # noqa: E731
    modelo_("ventana_seca.py", "--umbral-mm", str(UMBRAL_MM_SIN_CORRECCION))                      # M1
    modelo_("anomalias.py", "--serie", p("serie_predio.parquet"), "--referencia", p("serie_referencia.parquet"),
            "--referencia-geom", p("referencia_secano.parquet"), "--salida", p("anomalias_predio.parquet"))  # M2
    modelo_("detector_riego.py", "--anomalias", p("anomalias_predio.parquet"), "--salida", p("senal_riego.parquet"))  # M3
    modelo_("consumo_fao56.py", "--serie", p("serie_predio.parquet"), "--serie-referencia", p("serie_referencia.parquet"),
            "--salida", p("consumo_predio.parquet"))                                               # M4
    modelo_("indice_sospecha.py", "--senal", p("senal_riego.parquet"), "--consumo", p("consumo_predio_temporada.parquet"),
            "--salida", p("puntaje.parquet"))                                                      # M5

    for local, nombre in SALIDAS_MODELO.items():  # puntaje al final
        (modelo).mkdir(parents=True, exist_ok=True)
        shutil.copyfile(proc / local, modelo / nombre)

    salida_web = trabajo / "web" / zona
    correr("frontend-demo/scripts/build_m5_web.py", ["--region", zona, "--salida", salida_web], trabajo, zonas_json)
    web.mkdir(parents=True, exist_ok=True)
    for f in sorted(salida_web.rglob("*")):
        if f.is_file():
            destino = web / f.relative_to(salida_web)
            destino.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(f, destino)
    print(f"{zona}: terminada -> {modelo} y {web}", flush=True)
    shutil.rmtree(trabajo, ignore_errors=True)


# --- Etapa nacional ---------------------------------------------------------------------------------------------


def regresion(chile: pd.DataFrame) -> dict:
    """Los predios de Z1 y Z2 de la corrida nacional contra data/processed/puntaje.parquet (docs/spec-chile.md)."""
    ref_f = APP / "data" / "processed" / "puntaje.parquet"
    casos_f = APP / "frontend-demo" / "data" / "zonas" / "casos.json"
    if not ref_f.exists():
        return {"aprobada": False, "motivo": f"no está {ref_f}"}
    ref = pd.read_parquet(ref_f, columns=["predio_id", "temporada", "banda"])
    ref = ref[ref["temporada"] == "2025-26"].set_index("predio_id")["banda"]
    nac = chile[chile["temporada"] == "2025-26"].set_index("predio_id")["banda"]
    comunes = ref.index.intersection(nac.index)
    if len(comunes) == 0:
        return {"aprobada": False, "motivo": "ningún predio de Z1 y Z2 en la corrida nacional (¿está R05?)"}
    coincide = float((ref.loc[comunes] == nac.loc[comunes]).mean())
    casos = [int(c["predio_id"]) for c in json.loads(casos_f.read_text(encoding="utf-8")) if c.get("predio_id")]
    casos = [c for c in casos if c in comunes]
    casos_ok = sum(ref.loc[c] == nac.loc[c] for c in casos)
    aprobada = coincide >= COINCIDENCIA_MIN and casos_ok == len(casos) and len(casos) > 0
    return {"aprobada": bool(aprobada), "predios_comunes": int(len(comunes)), "coincidencia_banda": round(coincide, 4),
            "casos_con_puntaje": len(casos), "casos_misma_banda": int(casos_ok),
            "criterio": f"coincidencia >= {COINCIDENCIA_MIN:.0%} y los casos de validación con la misma banda",
            "cruce": pd.crosstab(ref.loc[comunes].rename("z1z2"), nac.loc[comunes].rename("nacional")).to_dict()}


def nacional(cfg: dict, zonas: list[str], corrida: str, datos: Path) -> None:
    modelo = datos / "modelo" / corrida
    web = datos / "web" / corrida
    faltan = [z for z in zonas if not (modelo / f"region={z}" / "puntaje.parquet").exists()]
    if faltan:
        sys.exit(f"Faltan las regiones {faltan} en la corrida {corrida}: corre antes la etapa region")
    partes = []
    for z in zonas:
        d = pd.read_parquet(modelo / f"region={z}" / "puntaje.parquet")
        d["region"] = z
        partes.append(d)
    chile = pd.concat(partes, ignore_index=True)
    # Un predio repetido entre capas de CIREN (98 mslink en dos regiones): queda el de la primera región.
    antes = len(chile)
    chile = chile.drop_duplicates(["predio_id", "temporada"], keep="first")
    print(f"{antes - len(chile)} predios repetidos entre regiones descartados", flush=True)
    chile["_ob"] = chile["banda"].map({b: i for i, b in enumerate(BANDAS)})
    chile["_oa"] = chile["aplicabilidad"].map(ORDEN_APLICABILIDAD).fillna(len(ORDEN_APLICABILIDAD))
    chile = chile.sort_values(["temporada", "_ob", "_oa", "puntaje", "predio_id"],
                              ascending=[True, True, True, False, True])
    chile["rank_nacional"] = chile.groupby("temporada").cumcount() + 1
    chile = chile.drop(columns=["_ob", "_oa"])
    chile.to_parquet(modelo / "puntaje_chile.parquet", index=False)

    actual = chile[chile["temporada"] == "2025-26"]
    resumen = {"corrida": corrida, "temporada": "2025-26", "regiones": {}}
    for z in zonas:
        r = actual[actual["region"] == z]
        alta = r[r["banda"] == "alta"]
        resumen["regiones"][z] = {
            "nombre": cfg["zonas"][z]["nombre"], "aplicabilidad": cfg["zonas"][z]["aplicabilidad"],
            "predios_elegibles": int(len(r)),
            "counts": {b: int((r["banda"] == b).sum()) for b in BANDAS},
            "m3_exceso_central_alta": int(alta["m3_exceso_central"].sum()),
        }
    resumen["total"] = {"predios_elegibles": int(len(actual)),
                        "alta": int((actual["banda"] == "alta").sum()),
                        "m3_exceso_central_alta": int(actual.loc[actual["banda"] == "alta", "m3_exceso_central"].sum())}
    index = {"corrida": corrida, "regiones": [
        {"id": z, "nombre": cfg["zonas"][z]["nombre"], "bbox": cfg["zonas"][z]["bbox"],
         "aplicabilidad": cfg["zonas"][z]["aplicabilidad"]} for z in zonas]}
    web.mkdir(parents=True, exist_ok=True)
    (web / "resumen.json").write_text(json.dumps(resumen, ensure_ascii=False), encoding="utf-8")
    (web / "index.json").write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(resumen["total"]), flush=True)

    comprobacion = regresion(chile)
    (web / "regresion.json").write_text(json.dumps(comprobacion, ensure_ascii=False, indent=1), encoding="utf-8")
    print("comprobación de regresión:", {k: v for k, v in comprobacion.items() if k != "cruce"}, flush=True)
    if not comprobacion["aprobada"]:
        sys.exit(f"La comprobación de regresión no pasó: no se publica web/ACTUAL (detalle en {web / 'regresion.json'})")
    (datos / "web").mkdir(parents=True, exist_ok=True)
    (datos / "web" / "ACTUAL").write_text(corrida, encoding="utf-8")
    print(f"web/ACTUAL -> {corrida}", flush=True)
