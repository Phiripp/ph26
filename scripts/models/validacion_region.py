# /// script
# requires-python = ">=3.11"
# dependencies = ["geopandas>=1.0", "pandas", "pyarrow", "numpy", "scipy", "scikit-learn", "shapely>=2.0", "rasterio",
#                 "pystac-client", "requests"]
# ///
"""Validación del índice de sospecha en una región de la corrida nacional, fuera de Z1 y Z2 (M6 regional).

Pregunta: fuera de las zonas donde se calibró el modelo, ¿la banda alta encuentra más infractores que el azar? Replica
scripts/models/validacion.py (predio del punto, vecindario a 30 m con el ajuste 1 − (1 − p)^n, Wilson, AUC) con las
fiscalizaciones históricas de la región. Mide; no calibra: los umbrales de M3 y el ranking de M5 no se tocan.

Diferencia con validacion.py: no existe el ranking histórico de toda la región, así que el azar no sale del universo
2025-26 sino de una muestra aleatoria de predios elegibles (controles), con las mismas temporadas que los casos y
calculada en la misma corrida de M1 a M5. `--universo` agrega, como contraste, el universo de la corrida nacional.

Entradas, en --datos (por defecto data/raw/<región>/, que no va a git). Cada tabla se busca en
processed/<nombre>.parquet (la carpeta de trabajo de los extractores con CAUDAL_ZONAS de la región) o en
base/<tabla>/region=RXX.parquet (el bucket de la corrida nacional, montado o copiado):
- predio, predio_cultivo, derecho, derecho_predio, predio_derecho, fiscalizacion, referencia_secano.
  No se lee derecho_titulares (nombres).
- data/processed/puntaje.parquet y data/zonas.json del repo: los predios y comunas de Z1 y Z2 (--excluir-z1z2).

Pasos (--paso; "todo" los corre en orden y cada uno salta lo que ya está hecho):
1. casos: expedientes de extracción con etiqueta positivo o negativo y set de validación (D18: predio elegible,
   inspección desde julio de 2020), fuera de Z1 y Z2, con su temporada previa (la última de diciembre a marzo que
   empezó antes de la inspección) y su vecindario a 30 m. Sortea los controles: --controles predios elegibles por
   subzona, cada uno en una temporada sorteada entre las de los casos de su subzona.
2. plan: por temporada, los predios a evaluar y el secano de referencia con centroide a 10 km o menos (el radio de
   M2), los tiles Sentinel-2 que tocan y sus escenas de diciembre a marzo con menos de --nubes-max % de nubes. Deja
   el mismo formato de scripts/cloud/chile/plan.py, una carpeta por temporada: cada caso lee solo su temporada previa.
3. satelite: scripts/extract/serie_sentinel2.py --parte 0 por temporada (celdas de 512, solo las ocupadas) y arma
   serie_predio.parquet y serie_referencia.parquet.
4. clima: lluvia y ET0 diarias de Open-Meteo (reanálisis era5_seamless, sin corrección de estaciones) para las celdas
   de 0,1° de esos predios, de abril de la primera temporada de cada celda a marzo de la última. Es el respaldo de
   ERA5-Land (d2_clima_era5land.py necesita CDS_API_KEY). M1 corre con --umbral-mm 2, como la corrida nacional.
5. modelos: M1 a M5 con los scripts de siempre (umbrales de M7), con los derechos vigentes al 1 de diciembre de cada
   temporada (predio_derecho.parquet).
6. informe: docs/validacion-<región>.md. El bloque entre las marcas `recomendacion` se escribe a mano y se conserva.

Subzonas de R05: `aconcagua_interior` son las provincias de San Felipe de Aconcagua y Los Andes (primera y segunda
sección del río); `resto` es lo demás fuera de Z1 y Z2 (costa, Casablanca, San Antonio, Marga Marga).

Salidas: --datos/validacion/ (casos, plan, caché de escenas, clima y modelos; no va a git) y docs/validacion-<región>.md.

Uso:
  uv run scripts/models/validacion_region.py --region R05 --excluir-z1z2              # todo
  uv run scripts/models/validacion_region.py --region R05 --excluir-z1z2 --paso satelite --temporadas 2021-22
  uv run scripts/models/validacion_region.py --region R05 --excluir-z1z2 --paso informe \\
      --universo ruta/a/modelo/chile-2025-26/region=R05/puntaje.parquet
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

RAIZ = Path(__file__).resolve().parents[2]
for carpeta in ("scripts", "scripts/models", "scripts/cloud/chile"):
    sys.path.insert(0, str(RAIZ / carpeta))
from validacion import NIVELES, ORDEN, auc_ic, wilson  # noqa: E402  (scripts/models/validacion.py)

CRS_METROS = "EPSG:32719"
RADIO_REF_KM = 10.0            # el radio de la referencia de secano de M2 (anomalias.py)
UMBRAL_MM = 2.0                # M1 sin corrección de estaciones, como prediccion.py de la corrida nacional
NDVI_DETECTABLE = 0.30         # como fiscalizaciones_dga.py (D18)
NUBOSIDAD_DETECTABLE = 30
MODELO_CLIMA = "era5_seamless"  # Open-Meteo: ERA5-Land donde existe y ERA5 en el resto; era5_land solo da nulos en el diario
# Tabla de trabajo -> carpeta en base/ del bucket de la corrida nacional (scripts/cloud/chile/prediccion.py)
TABLAS = {"predio": "predio", "predio_cultivo": "cultivo", "derecho": "derecho", "derecho_predio": "derecho_predio",
          "predio_derecho": "predio_derecho", "fiscalizacion": "fiscalizacion", "referencia_secano": "referencia_secano"}
SUBZONAS = {"R05": {"aconcagua_interior": ["CALLE LARGA", "CATEMU", "LLAILLAY", "LOS ANDES", "PANQUEHUE", "PUTAENDO",
                                           "RINCONADA", "SAN ESTEBAN", "SAN FELIPE", "SANTA MARIA"]}}
RESTO = "resto"
NOMBRE_SUBZONA = {"aconcagua_interior": "Aconcagua interior", RESTO: "Resto"}


# --- Entradas -------------------------------------------------------------------------------------------------------


def tabla(datos: Path, nombre: str, region: str) -> Path:
    for ruta in (datos / "processed" / f"{nombre}.parquet", datos / "base" / TABLAS[nombre] / f"region={region}.parquet"):
        if ruta.exists():
            return ruta
    sys.exit(f"Falta la tabla {nombre} de {region} en {datos} (processed/{nombre}.parquet o "
             f"base/{TABLAS[nombre]}/region={region}.parquet): ver el encabezado")


def ids_z1z2() -> set[int]:
    return set(pd.read_parquet(RAIZ / "data" / "processed" / "puntaje.parquet", columns=["predio_id"])["predio_id"])


def subzona(comuna: pd.Series, region: str) -> pd.Series:
    de = {c: s for s, comunas in SUBZONAS.get(region, {}).items() for c in comunas}
    return comuna.map(de).fillna(RESTO)


def temporada_previa(fecha: pd.Series) -> pd.Series:
    """La última temporada seca (diciembre a marzo) que empezó antes de la inspección (fiscalizaciones_dga.py, D18)."""
    anio = fecha.dt.year - (fecha.dt.month < 12).astype(int)
    anio = anio.where(fecha > pd.to_datetime(anio.astype(str) + "-12-01"), anio - 1)
    return anio.astype(str) + "-" + (anio + 1).astype(str).str[2:]


def rango_temporadas(rango: str) -> list[str]:
    a, _, b = rango.partition(":")
    return [f"{y}-{str(y + 1)[2:]}" for y in range(int(a[:4]), int((b or a)[:4]) + 1)]


def ids_de(fila) -> list[int]:
    """Predios de un expediente: su vecindario a 30 m y el predio del punto (serie_sentinel2.ids_validacion)."""
    ids = {int(i) for i in fila["vecindario"]}
    if pd.notna(fila["predio_id"]):
        ids.add(int(fila["predio_id"]))
    return sorted(ids)


# --- Paso 1: casos y controles ------------------------------------------------------------------------------------


def paso_casos(args, val: Path) -> None:
    salida = val / "casos.parquet"
    if salida.exists() and not args.rehacer:
        print(f"casos: {salida} ya existe (--rehacer para sortear de nuevo)")
        return
    f = gpd.read_parquet(tabla(args.datos, "fiscalizacion", args.region))
    predios = pd.read_parquet(tabla(args.datos, "predio", args.region), columns=["predio_id", "comuna", "area_ha", "elegible"])
    fuera = ids_z1z2() if args.excluir_z1z2 else set()
    f["temporada_previa"] = None
    con_fecha = f["fecha_inspeccion"].notna()
    f.loc[con_fecha, "temporada_previa"] = temporada_previa(f.loc[con_fecha, "fecha_inspeccion"])
    base = (f["extraccion"].fillna(False).astype(bool) & f["etiqueta"].isin(["positivo", "negativo"])
            & (f["set_validacion"] != "fuera"))
    print(f"{args.region}: {int(base.sum())} expedientes de extracción con etiqueta y set de validación (D18)")
    c = f[base & ~f["predio_id"].isin(fuera)].copy()
    print(f"  fuera de Z1 y Z2: {len(c)}" if args.excluir_z1z2 else "  sin excluir Z1 y Z2")
    en_rango = c["temporada_previa"].isin(args.temporadas)
    if (~en_rango).any():
        print(f"  fuera de las temporadas pedidas: {int((~en_rango).sum())} "
              f"({c.loc[~en_rango, 'temporada_previa'].value_counts().to_dict()})")
    c = c[en_rango].merge(predios[["predio_id", "comuna"]], on="predio_id", how="left")
    c["subzona"] = subzona(c["comuna"], args.region)
    c["vecindario"] = c.apply(ids_de, axis=1)
    cols = ["expediente", "etiqueta", "decision", "fecha_inspeccion", "temporada_previa", "set_validacion", "predio_id",
            "vecindario", "comuna", "subzona", "geometry"]
    val.mkdir(parents=True, exist_ok=True)
    gpd.GeoDataFrame(c[cols], geometry="geometry", crs=f.crs).to_parquet(salida, index=False)

    elegibles = predios[predios["elegible"]]
    pt = pd.DataFrame([(i, r["temporada_previa"]) for _, r in c.iterrows() for i in r["vecindario"]],
                      columns=["predio_id", "temporada"]).drop_duplicates()
    pt = pt[pt["predio_id"].isin(elegibles["predio_id"])].assign(caso=True)

    # Controles: muestra aleatoria simple de predios elegibles por subzona; la temporada de cada uno se sortea entre las
    # temporadas previas de los casos de su subzona, así el azar tiene la misma mezcla de temporadas que los casos.
    rng = np.random.default_rng(args.semilla)
    universo = elegibles[~elegibles["predio_id"].isin(fuera)].assign(subzona=lambda d: subzona(d["comuna"], args.region))
    controles = []
    for s, u in universo.groupby("subzona"):
        temporadas = c.loc[c["subzona"] == s, "temporada_previa"].to_numpy()
        if len(temporadas) == 0:
            temporadas = c["temporada_previa"].to_numpy()
        n = min(args.controles, len(u))
        ids = rng.choice(np.sort(u["predio_id"].to_numpy()), n, replace=False)
        controles.append(pd.DataFrame({"predio_id": ids, "temporada": rng.choice(temporadas, n), "subzona": s}))
    controles = pd.concat(controles, ignore_index=True)
    controles.to_parquet(val / "controles.parquet", index=False)
    universo.groupby("subzona").size().rename("elegibles").reset_index().to_parquet(val / "universo.parquet", index=False)
    pt = pt.merge(controles[["predio_id", "temporada"]].assign(control=True), on=["predio_id", "temporada"], how="outer")
    pt[["caso", "control"]] = pt[["caso", "control"]].fillna(False).astype(bool)
    pt.to_parquet(val / "predio_temporada.parquet", index=False)

    print("\nExpedientes por temporada previa y etiqueta:")
    print(pd.crosstab(c["temporada_previa"], c["etiqueta"], margins=True).to_string())
    print("\nPor subzona:")
    print(pd.crosstab(c["subzona"], c["etiqueta"], margins=True).to_string())
    print(f"\nPredios a evaluar: {pt['predio_id'].nunique()} ({int(pt['caso'].sum())} predio-temporadas de casos, "
          f"{int(pt['control'].sum())} de controles) -> {val}")


# --- Paso 2: plan Sentinel-2 por temporada --------------------------------------------------------------------------


def paso_plan(args, val: Path) -> None:
    import plan as plan_nacional  # scripts/cloud/chile/plan.py
    from comun.celdas import celdas_ocupadas, grilla_de_item
    from pystac_client import Client

    pt = pd.read_parquet(val / "predio_temporada.parquet")
    pendientes = [t for t in args.temporadas
                  if (pt["temporada"] == t).any() and (args.rehacer or not (val / "s2" / t / "plan" / "escenas.parquet").exists())]
    if not pendientes:
        print("plan: ya está (--rehacer para volver a planificar)")
        return
    predios = gpd.read_parquet(tabla(args.datos, "predio", args.region), columns=["predio_id", "geometry"])
    predios = predios[predios["predio_id"].isin(pt["predio_id"])]
    secano = gpd.read_parquet(tabla(args.datos, "referencia_secano", args.region), columns=["ref_id", "geometry"])
    c_sec = secano.to_crs(CRS_METROS).geometry.centroid
    arbol = cKDTree(np.column_stack([c_sec.x, c_sec.y]))
    c_pre = predios.to_crs(CRS_METROS).geometry.centroid
    xy = dict(zip(predios["predio_id"], zip(c_pre.x, c_pre.y)))

    cfg = json.loads((RAIZ / "data" / "regiones.json").read_text(encoding="utf-8"))["zonas"][args.region]
    catalogo = Client.open(plan_nacional.STAC)
    tiles = plan_nacional.descubrir_tiles({args.region: cfg}, catalogo)
    cajas = {t: plan_nacional.caja_tile_4326(it).iloc[0] for t, it in tiles.items()}

    for t in pendientes:
        ids = pt.loc[pt["temporada"] == t, "predio_id"].unique()
        refs = sorted({j for i in ids for j in arbol.query_ball_point(xy[i], RADIO_REF_KM * 1000)})
        pol = pd.concat([
            predios[predios["predio_id"].isin(ids)].rename(columns={"predio_id": "poligono_id"}).assign(tipo="predio"),
            secano.iloc[refs].rename(columns={"ref_id": "poligono_id"}).assign(tipo="secano"),
        ], ignore_index=True)
        pol = gpd.GeoDataFrame(pol.assign(region=args.region)[["poligono_id", "tipo", "region", "geometry"]], crs="EPSG:4326")
        carpeta = val / "s2" / t / "plan"
        (carpeta / "poligonos_tile").mkdir(parents=True, exist_ok=True)
        (carpeta / "partes").mkdir(parents=True, exist_ok=True)
        a = int(t[:4])
        filas, lineas, costo = [], [], 0
        for tile, item in sorted(tiles.items()):
            g = pol[pol.intersects(cajas[tile])]
            if g.empty:
                continue
            celdas = celdas_ocupadas(g.to_crs(plan_nacional.crs_item(item)).geometry, grilla_de_item(item))
            escenas = plan_nacional.buscar_escenas(catalogo, tile, f"{a}-12-01", f"{a + 1}-03-31", args.nubes_max)
            if not celdas or not escenas:
                continue
            g.to_parquet(carpeta / "poligonos_tile" / f"{tile}.parquet", index=False)
            costo += len(celdas) * len(escenas)
            for it in escenas:
                lineas.append(json.dumps(it.to_dict()))
                filas.append({"escena_id": it.id, "tile": tile, "nubes": it.properties.get("eo:cloud_cover"),
                              "fecha": pd.Timestamp(it.datetime).tz_localize(None).normalize()})
        (carpeta / "partes" / "0.jsonl").write_text("\n".join(lineas) + "\n", encoding="utf-8")
        pd.DataFrame(filas).to_parquet(carpeta / "escenas.parquet", index=False)  # al final: marca de plan terminado
        print(f"plan {t}: {len(ids)} predios, {len(refs)} polígonos de secano, {len(filas)} escenas en "
              f"{len({f['tile'] for f in filas})} tiles, {costo:,} lecturas de celda", flush=True)


# --- Paso 3: lectura satelital y series -----------------------------------------------------------------------------


def paso_satelite(args, val: Path) -> None:
    pt = pd.read_parquet(val / "predio_temporada.parquet")
    incompletas = []
    for t in args.temporadas:
        carpeta = val / "s2" / t
        if not (carpeta / "plan" / "escenas.parquet").exists():
            continue
        r = subprocess.run(["uv", "run", str(RAIZ / "scripts/extract/serie_sentinel2.py"), "--parte", "0", "--hilos",
                            str(args.hilos)], env={**os.environ, "CAUDAL_DATA": str(carpeta), "PYTHONUNBUFFERED": "1"}, cwd=RAIZ)
        if r.returncode:
            incompletas.append(t)
    if incompletas:
        sys.exit(f"satelite: quedaron escenas sin leer en {incompletas}; vuelve a correr el paso (el caché salta lo hecho)")
    armar_series(val, pt, args.region)


def armar_series(val: Path, pt: pd.DataFrame, region: str) -> None:
    """Une los parquet de escena de todas las temporadas: serie de predios y de secano, con el esquema de D1."""
    cols = ["predio_id", "zona", "fecha", "ndvi", "ndwi", "ndmi", "ndvi_std", "nubosidad_pct", "n_pix_validos",
            "n_pix_total", "nubes_escena_pct", "escena_id"]
    partes, faltan = [], 0
    for carpeta in sorted((val / "s2").iterdir()):
        plan = carpeta / "plan" / "escenas.parquet"
        if not plan.exists():
            continue
        for e in pd.read_parquet(plan).itertuples():
            f = carpeta / "s2" / "cache" / e.tile / f"{e.escena_id}_chile_v2.parquet"
            if not f.exists():
                faltan += 1
                continue
            d = pd.read_parquet(f)
            if len(d):
                partes.append(d)
    if faltan:
        print(f"Aviso: faltan {faltan} escenas del plan en el caché (paso satelite incompleto)")
    s = pd.concat(partes, ignore_index=True).rename(columns={"poligono_id": "predio_id"})
    s["fecha"] = pd.to_datetime(s["fecha"])
    s["zona"] = region
    # Un polígono en dos tiles el mismo día: la escena con más píxeles válidos (la regla de siempre).
    s = s.sort_values(["tipo", "predio_id", "fecha", "n_pix_validos"], ascending=[True, True, True, False])
    s = s.drop_duplicates(["tipo", "predio_id", "fecha"])
    (val / "processed").mkdir(parents=True, exist_ok=True)
    serie = s[s["tipo"] == "predio"][cols].reset_index(drop=True)
    ref = s[s["tipo"] == "secano"][cols].reset_index(drop=True)
    serie.to_parquet(val / "processed" / "serie_predio.parquet", index=False)
    ref.to_parquet(val / "processed" / "serie_referencia.parquet", index=False)
    sin_serie = set(pt["predio_id"]) - set(serie["predio_id"])
    print(f"serie: {len(serie)} filas, {serie['predio_id'].nunique()} predios, {serie['escena_id'].nunique()} escenas; "
          f"referencia: {len(ref)} filas, {ref['predio_id'].nunique()} polígonos; predios sin ninguna observación: {len(sin_serie)}")


# --- Paso 4: clima ------------------------------------------------------------------------------------------------


def paso_clima(args, val: Path) -> None:
    from extract.d2_clima_openmeteo import asignar_celdas, pedir_lote

    pt = pd.read_parquet(val / "predio_temporada.parquet")
    predios = gpd.read_parquet(tabla(args.datos, "predio", args.region), columns=["predio_id", "zona", "geometry"])
    asignados = asignar_celdas(predios[predios["predio_id"].isin(pt["predio_id"])])
    pt = pt.merge(asignados[["predio_id", "celda_id"]], on="predio_id")
    anio = pt["temporada"].str[:4].astype(int)
    # Por celda, de abril de su primera temporada a marzo de la última: M4 extrapola el año de abril a marzo y M1
    # necesita días seguidos (una racha seca no debe saltar de una temporada a otra).
    periodo = pt.assign(anio=anio).groupby("celda_id")["anio"].agg(["min", "max"])
    celdas = asignados.drop_duplicates("celda_id").set_index("celda_id")[["zona", "celda_lat", "celda_lon"]].join(periodo)
    celdas["inicio"] = celdas["min"].astype(str) + "-04-01"
    celdas["fin"] = (celdas["max"] + 1).astype(str) + "-03-31"
    crudo = val / "raw" / "clima" / "openmeteo"
    crudo.mkdir(parents=True, exist_ok=True)
    archivo = lambda c, r: crudo / f"{c}_{r['inicio']}_{r['fin']}.json"  # noqa: E731
    pend = celdas[[not archivo(c, r).exists() for c, r in celdas.iterrows()]]
    print(f"clima: {len(celdas)} celdas, {len(pend)} por pedir a Open-Meteo ({MODELO_CLIMA})", flush=True)
    for (inicio, fin), g in pend.groupby(["inicio", "fin"]):
        for i in range(0, len(g), args.lote_clima):
            lote = g.iloc[i : i + args.lote_clima]
            for (c, r), resp in zip(lote.iterrows(), pedir_lote(lote, inicio, fin, MODELO_CLIMA)):
                archivo(c, r).write_text(json.dumps(resp["daily"]))
            time.sleep(1)
    partes = []
    for c, r in celdas.iterrows():
        d = json.loads(archivo(c, r).read_text())
        partes.append(pd.DataFrame({"zona": r["zona"], "punto_id": c, "fuente": "openmeteo", "fecha": pd.to_datetime(d["time"]),
                                    "lluvia_mm": d["precipitation_sum"], "et0_mm": d["et0_fao_evapotranspiration"]}))
    clima = pd.concat(partes, ignore_index=True)
    huecos = clima[["lluvia_mm", "et0_mm"]].isna().sum()
    # Mismo esquema que d2_clima_era5land.py: sin corrección de estaciones, lluvia_corr_mm = lluvia_mm.
    clima = clima.assign(lluvia_corr_mm=clima["lluvia_mm"], estacion_ref_id=pd.NA, lluvia_dato_faltante=clima["lluvia_mm"].isna(),
                         dia_parcial=False, correccion="ninguna")
    clima = clima[["zona", "punto_id", "fuente", "fecha", "lluvia_mm", "lluvia_corr_mm", "et0_mm", "estacion_ref_id",
                   "lluvia_dato_faltante", "dia_parcial", "correccion"]]
    (val / "processed").mkdir(parents=True, exist_ok=True)
    clima.to_parquet(val / "processed" / "clima.parquet", index=False)
    asignados.assign(estacion_id=pd.NA, distancia_estacion_km=np.nan)[
        ["predio_id", "zona", "celda_id", "estacion_id", "distancia_estacion_km"]].to_parquet(
        val / "processed" / "predio_clima.parquet", index=False)
    print(f"clima: {len(clima)} días-celda, {clima['fecha'].min():%Y-%m-%d} a {clima['fecha'].max():%Y-%m-%d}; "
          f"huecos: lluvia {huecos['lluvia_mm']}, ET0 {huecos['et0_mm']}")


# --- Paso 5: M1 a M5 ----------------------------------------------------------------------------------------------


def paso_modelos(args, val: Path) -> None:
    proc = val / "processed"
    for nombre in TABLAS:  # los modelos leen todo de una sola carpeta: enlaces a las tablas base de la región
        destino = proc / f"{nombre}.parquet"
        if destino.is_symlink() or destino.exists():
            destino.unlink()
        destino.symlink_to(tabla(args.datos, nombre, args.region).resolve())
    cfg = json.loads((RAIZ / "data" / "regiones.json").read_text(encoding="utf-8"))
    zonas = val / f"regiones_{args.region}.json"
    zonas.write_text(json.dumps({**cfg, "zonas": {args.region: cfg["zonas"][args.region]}}, ensure_ascii=False), encoding="utf-8")
    env = {**os.environ, "CAUDAL_DATA": str(val), "CAUDAL_ZONAS": str(zonas), "PYTHONUNBUFFERED": "1"}
    p = lambda n: str(proc / n)  # noqa: E731

    def modelo(script: str, *argumentos: str) -> None:
        print(f"\n$ {script} {' '.join(argumentos)}", flush=True)
        if subprocess.run(["uv", "run", str(RAIZ / "scripts/models" / script), *argumentos], env=env, cwd=RAIZ).returncode:
            sys.exit(f"{script} falló")

    # Los mismos pasos y argumentos que la etapa region de la corrida nacional (scripts/cloud/chile/prediccion.py).
    modelo("ventana_seca.py", "--umbral-mm", str(UMBRAL_MM))
    modelo("anomalias.py", "--serie", p("serie_predio.parquet"), "--referencia", p("serie_referencia.parquet"),
           "--referencia-geom", p("referencia_secano.parquet"), "--salida", p("anomalias_predio.parquet"))
    modelo("detector_riego.py", "--anomalias", p("anomalias_predio.parquet"), "--salida", p("senal_riego.parquet"))
    modelo("consumo_fao56.py", "--serie", p("serie_predio.parquet"), "--serie-referencia", p("serie_referencia.parquet"),
           "--salida", p("consumo_predio.parquet"))
    modelo("indice_sospecha.py", "--senal", p("senal_riego.parquet"), "--consumo", p("consumo_predio_temporada.parquet"),
           "--salida", p("puntaje_validacion.parquet"))


# --- Paso 6: métricas e informe -----------------------------------------------------------------------------------

B_AZAR = 2000  # remuestreos para el intervalo del azar y del lift
INICIO_REC, FIN_REC = "<!-- recomendacion:inicio -->", "<!-- recomendacion:fin -->"
DESCUENTOS = {"canal_300m": "canal a 300 m o menos (`canal_300m`)",
              "riego_superficial": "área de riego superficial de CIREN en la mitad del predio o más"}
RIEGO_MIN = 0.5  # fracción del predio dentro de un área de riego superficial o mixta para contarlo como regado por canal


def marcar_detectable(casos: pd.DataFrame, serie: pd.DataFrame) -> pd.DataFrame:
    """ndvi_previo y detectable, con la regla de fiscalizaciones_dga.marcar_detectable (D18): el mayor NDVI mediano de
    la temporada previa entre los predios del vecindario, solo con fechas anteriores a la inspección."""
    s = serie[(serie["n_pix_validos"] > 0) & (serie["nubosidad_pct"] <= NUBOSIDAD_DETECTABLE)]
    ndvi = []
    for r in casos.itertuples():
        a = int(r.temporada_previa[:4])
        v = s[s["predio_id"].isin(r.vecindario) & (s["fecha"] >= pd.Timestamp(a, 12, 1))
              & (s["fecha"] <= pd.Timestamp(a + 1, 3, 31)) & (s["fecha"] < r.fecha_inspeccion)]
        ndvi.append(v.groupby("predio_id")["ndvi"].median().max() if len(v) else np.nan)
    casos = casos.assign(ndvi_previo=np.round(ndvi, 3))
    return casos.assign(detectable=casos["ndvi_previo"] >= NDVI_DETECTABLE)


def fraccion_riego_superficial(args, ids) -> pd.Series | None:
    """Fracción del área de cada predio dentro de un área de riego SUPERFICIAL o MIXTO (areas_riego_ciren.py)."""
    ruta = args.datos / "raw" / "ciren_riego" / "areas_riego.parquet"
    if not ruta.exists():
        return None
    areas = gpd.read_parquet(ruta)
    areas = areas[areas["tipo_agu"].isin(["SUPERFICIAL", "MIXTO"])].to_crs(CRS_METROS)
    union = areas.geometry.make_valid().union_all()
    p = gpd.read_parquet(tabla(args.datos, "predio", args.region), columns=["predio_id", "geometry"])
    p = p[p["predio_id"].isin(ids)].to_crs(CRS_METROS)
    geom = p.geometry.make_valid()
    return pd.Series((geom.intersection(union).area / geom.area).to_numpy(), index=p["predio_id"].to_numpy())


def evaluar(casos: pd.DataFrame, controles: pd.DataFrame, pv: pd.DataFrame, descontar: str | None = None):
    """Banda de cada expediente (predio del punto y vecindario) y de cada control. `descontar` es una columna
    booleana de pv: sus alertas pasan a sin_alerta (casos y controles por igual)."""
    pv = pv.copy()
    if descontar:
        fuera = pv[descontar].fillna(False).astype(bool)
        pv.loc[fuera, "banda"] = "sin_alerta"
        pv.loc[fuera, "puntaje"] = 0.0
    ctl = controles.merge(pv, on=["predio_id", "temporada"], how="inner")
    pvi = pv.set_index(["predio_id", "temporada"])
    filas = []
    for i, r in casos.iterrows():
        g = pv[pv["predio_id"].isin(r["vecindario"]) & (pv["temporada"] == r["temporada_previa"])]
        fila = {"n_predios": len(g)}
        clave = (int(r["predio_id"]), r["temporada_previa"]) if pd.notna(r["predio_id"]) else None
        if clave in pvi.index:
            for c in ("banda", "puntaje", "canal_300m", "riego_superficial", "estado_derechos", "senal_riego"):
                fila[f"{c}_punto"] = pvi.at[clave, c]
        if len(g):
            fila["banda"] = max(g["banda"], key=ORDEN.get)
            fila["puntaje"] = g["puntaje"].max()
            fila["senal_riego"] = bool(g["senal_riego"].fillna(False).any())
        filas.append(pd.Series(fila, name=i))
    f = casos.join(pd.DataFrame(filas))
    f = f[f["n_predios"] > 0].copy()
    f["y"] = f["etiqueta"] == "positivo"
    f["negativo_fuerte"] = f["decision"].str.lower().str.contains("no acoge", na=False)
    return f, ctl


def ic_wilson(k: int, n: int) -> tuple[float, float]:
    """Wilson de validacion.py, acotado a [0, 1] (con k = 0 el límite inferior sale en -0 por redondeo)."""
    lo, hi = wilson(k, n)
    return max(float(lo), 0.0), min(float(hi), 1.0)


def rango(lo: float, hi: float) -> str:
    return "—" if np.isnan(lo) or np.isnan(hi) else f"{lo:.1f}–{hi:.1f}"


def azar_de(pos: pd.DataFrame, ctl: pd.DataFrame, bandas: list[str], punto: bool, rng) -> tuple[float, float, float, np.ndarray]:
    """Azar esperado para un grupo de positivos, con su intervalo por remuestreo de los controles.

    Por expediente: la proporción p de los controles de su subzona en la banda (predio del punto), o 1 − (1 − p)^n con
    los n predios de su vecindario. El azar del grupo es la media. Devuelve también los remuestreos."""
    subs = sorted(pos["subzona"].unique())
    acierto = {s: ctl.loc[ctl["subzona"] == s, "banda"].isin(bandas).to_numpy() for s in subs}
    if any(len(a) == 0 for a in acierto.values()):
        return np.nan, np.nan, np.nan, np.full(B_AZAR, np.nan)
    n = np.ones(len(pos)) if punto else pos["n_predios"].to_numpy(dtype=float)
    idx = pos["subzona"].map({s: k for k, s in enumerate(subs)}).to_numpy()

    def media(p: np.ndarray) -> float:
        return float(np.mean(1 - (1 - p[idx]) ** n))

    base = media(np.array([acierto[s].mean() for s in subs]))
    bs = np.array([media(np.array([rng.choice(acierto[s], len(acierto[s])).mean() for s in subs])) for _ in range(B_AZAR)])
    return base, np.percentile(bs, 2.5), np.percentile(bs, 97.5), bs


def tabla_recall(pos: pd.DataFrame, ctl: pd.DataFrame, rng, punto: bool = True, niveles=None) -> tuple[list[str], dict]:
    """Tabla de validacion.py más el intervalo del azar y un segundo intervalo del lift que cuenta el error del azar
    (remuestreo conjunto de positivos y controles). Devuelve también los números por nivel."""
    banda = "banda_punto" if punto else "banda"
    pos = pos[pos[banda].notna()]
    out = ["| Nivel | Positivos encontrados | Recall (IC 95 %) | Azar (IC 95 %) | Lift (IC 95 % de Wilson) | Lift (IC 95 % con el error del azar) |",
           "| --- | --- | --- | --- | --- | --- |"]
    num = {}
    for nivel, bandas in (niveles or NIVELES).items():
        k, n = int(pos[banda].isin(bandas).sum()), len(pos)
        if n == 0:
            out.append(f"| {nivel} | 0 de 0 | — | — | — | — |")
            continue
        lo, hi = ic_wilson(k, n)
        base, b_lo, b_hi, bs = azar_de(pos, ctl, bandas, punto, rng)
        acierto = pos[banda].isin(bandas).to_numpy()
        rec = np.array([rng.choice(acierto, n).mean() for _ in range(B_AZAR)])
        l_lo = l_hi = np.nan  # con 0 o n aciertos el remuestreo no varía: solo vale el intervalo de Wilson
        if 0 < k < n and np.isfinite(bs).any():
            with np.errstate(divide="ignore", invalid="ignore"):
                l_lo, l_hi = np.nanpercentile(np.where(bs > 0, rec / bs, np.nan), [2.5, 97.5])
        div = base if base and base > 0 else np.nan  # sin controles en la banda no hay lift
        num[nivel] = {"k": k, "n": n, "recall": k / n, "lo": lo, "hi": hi, "azar": base, "azar_lo": b_lo, "azar_hi": b_hi,
                      "lift": k / n / div, "lift_lo": lo / div, "lift_hi": hi / div, "lift_lo_b": l_lo, "lift_hi_b": l_hi}
        x = num[nivel]
        out.append(f"| {nivel} | {k} de {n} | {k / n:.0%} ({lo:.0%}–{hi:.0%}) | {base:.0%} ({b_lo:.0%}–{b_hi:.0%}) | "
                   f"{x['lift']:.1f}× ({rango(x['lift_lo'], x['lift_hi'])}) | {x['lift']:.1f}× ({rango(l_lo, l_hi)}) |")
    return out, num


def miles(n: float) -> str:
    return f"{int(n):,}".replace(",", ".")


def proporcion(k: int, n: int) -> str:
    if n == 0:
        return "—"
    lo, hi = ic_wilson(k, n)
    return f"{k} de {n} ({k / n:.0%}; {lo:.0%}–{hi:.0%})"


def tabla_cruzada(d: pd.DataFrame, filas: str, columnas: str, orden_columnas: list[str], titulo: str) -> list[str]:
    ct = pd.crosstab(d[filas], d[columnas]).reindex(columns=orden_columnas, fill_value=0)
    out = [f"| {titulo} | " + " | ".join(orden_columnas) + " | Total |", "| --- |" + " --- |" * (len(orden_columnas) + 1)]
    for et, row in ct.iterrows():
        out.append(f"| {et} | " + " | ".join(str(int(v)) for v in row) + f" | {int(row.sum())} |")
    out.append("| **Total** | " + " | ".join(str(int(v)) for v in ct.sum()) + f" | {int(ct.to_numpy().sum())} |")
    return out


def recomendacion_guardada(doc: Path) -> list[str]:
    """El bloque de la recomendación se escribe a mano: si el informe ya existe, se conserva tal cual."""
    if doc.exists():
        texto = doc.read_text(encoding="utf-8")
        if INICIO_REC in texto and FIN_REC in texto:
            return texto.split(INICIO_REC)[1].split(FIN_REC)[0].strip("\n").split("\n")
    return ["Pendiente: escribir la recomendación a mano entre estas dos marcas (el script la conserva)."]


def paso_informe(args, val: Path) -> None:
    from scipy.stats import fisher_exact

    rng = np.random.default_rng(args.semilla)
    reg = args.region.lower()
    proc = val / "processed"
    casos = gpd.read_parquet(val / "casos.parquet")
    controles = pd.read_parquet(val / "controles.parquet")
    universo = pd.read_parquet(val / "universo.parquet").set_index("subzona")["elegibles"]
    pv = pd.read_parquet(proc / "puntaje_validacion.parquet")
    serie = pd.read_parquet(proc / "serie_predio.parquet", columns=["predio_id", "fecha", "ndvi", "nubosidad_pct", "n_pix_validos"])
    casos = marcar_detectable(casos, serie)
    riego = fraccion_riego_superficial(args, pv["predio_id"].unique())
    pv["canal_300m"] = pv["canal_300m"].fillna(False).astype(bool)
    pv["riego_superficial"] = (pv["predio_id"].map(riego) >= RIEGO_MIN) if riego is not None else False
    f, ctl = evaluar(casos, controles, pv)
    det, pos = f[f["detectable"]], f[f["y"]]
    pos_d = det[det["y"]]
    subzonas = [s for s in [*SUBZONAS.get(args.region, {}), RESTO] if s in set(f["subzona"]) | set(ctl["subzona"])]
    nombre = lambda s: NOMBRE_SUBZONA.get(s, s)  # noqa: E731
    L: list[str] = []

    # --- Casos
    sec_casos = ["## Casos", "",
                 f"Expedientes de extracción no autorizada con etiqueta positivo o negativo, predio elegible a 50 m o menos, "
                 f"inspección desde julio de 2020 y predio fuera de Z1 y Z2: **{len(casos)}** ({int((casos['etiqueta'] == 'positivo').sum())} "
                 f"positivos y {int((casos['etiqueta'] == 'negativo').sum())} negativos). Con puntaje en su temporada previa: {len(f)} "
                 f"({int(f['y'].sum())} positivos). Detectables por verdor (NDVI previo de 0,30 o más en el vecindario): "
                 f"{len(pos_d)} de {int(f['y'].sum())} positivos y {int((~det['y']).sum())} de {int((~f['y']).sum())} negativos.",
                 "", *tabla_cruzada(casos, "temporada_previa", "etiqueta", ["positivo", "negativo"], "Temporada previa"), "",
                 *tabla_cruzada(casos.assign(s=casos["subzona"].map(nombre)), "s", "etiqueta", ["positivo", "negativo"], "Subzona"), ""]

    # --- Azar
    def cuota(d: pd.DataFrame, bandas: list[str]) -> str:
        return proporcion(int(d["banda"].isin(bandas).sum()), len(d))

    pesos = universo / universo.sum()
    ponderado = {n: sum(pesos[s] * ctl.loc[ctl["subzona"] == s, "banda"].isin(b).mean() for s in pesos.index) for n, b in NIVELES.items()}
    sec_azar = ["## Azar: predios de control", "",
                f"No existe el ranking histórico de toda la región, así que el azar se estima con una muestra aleatoria de "
                f"{len(controles)} predios elegibles fuera de Z1 y Z2 ({args.controles} por subzona, semilla {args.semilla}). Cada control "
                "se evalúa en una temporada sorteada entre las temporadas previas de los casos de su subzona y pasa por la misma "
                "corrida de M1 a M5 que los casos. " + ("Todos tienen puntaje." if len(ctl) == len(controles) else
                f"Con puntaje: {len(ctl)} (el resto no tiene observaciones válidas en su temporada)."),
                "", "| Subzona | Predios elegibles | Controles | En alta (IC 95 %) | En alta o media (IC 95 %) | Con señal de riego |",
                "| --- | --- | --- | --- | --- | --- |"]
    for s in subzonas:
        d = ctl[ctl["subzona"] == s]
        sec_azar.append(f"| {nombre(s)} | {miles(universo.get(s, 0))} | {len(d)} | {cuota(d, NIVELES['alta'])} | "
                        f"{cuota(d, NIVELES['alta o media'])} | {d['senal_riego'].fillna(False).mean():.0%} |")
    sec_azar += [f"| **Región fuera de Z1 y Z2** (ponderado por predios elegibles) | {miles(universo.sum())} | {len(ctl)} | "
                 f"{ponderado['alta']:.0%} | {ponderado['alta o media']:.0%} | — |", "",
                 "Controles en alta por temporada (la última columna pondera las subzonas por sus predios elegibles):", "",
                 "| Temporada | " + " | ".join(nombre(s) for s in subzonas) + " | Región fuera de Z1 y Z2 |",
                 "| --- |" + " --- |" * (len(subzonas) + 1)]
    for t, d in ctl.groupby("temporada"):
        por_sub = {s: d[d["subzona"] == s] for s in subzonas}
        pond = np.nan
        if all(len(x) for x in por_sub.values()):
            pond = sum(pesos.get(s, 0) * x["banda"].isin(NIVELES["alta"]).mean() for s, x in por_sub.items())
        sec_azar.append(f"| {t} | " + " | ".join(cuota(x, NIVELES["alta"]) for x in por_sub.values())
                        + (f" | {pond:.0%} |" if pd.notna(pond) else " | — |"))
    sec_azar.append("")
    alta_universo = None
    if args.universo:
        u = pd.read_parquet(args.universo)
        u = u[~u["predio_id"].isin(ids_z1z2())] if args.excluir_z1z2 else u
        u = u.assign(subzona=subzona(u["comuna"], args.region))
        alta_universo = u["banda"].isin(NIVELES["alta"]).mean()
        sec_azar += [f"Contraste con el universo de la corrida nacional (`{args.universo.name}`, {miles(len(u))} predios, temporada "
                     f"{', '.join(sorted(u['temporada'].unique()))}):", "",
                     "| Subzona | Predios | En alta | En alta o media |", "| --- | --- | --- | --- |"]
        for s in [*subzonas, None]:
            d = u if s is None else u[u["subzona"] == s]
            sec_azar.append(f"| {'**Región fuera de Z1 y Z2**' if s is None else nombre(s)} | {miles(len(d))} | "
                            f"{d['banda'].isin(NIVELES['alta']).mean():.0%} | {d['banda'].isin(NIVELES['alta o media']).mean():.0%} |")
        sec_azar.append("")

    # --- Recall frente al azar
    def bloque(titulo: str, d: pd.DataFrame, punto: bool = True) -> tuple[list[str], dict]:
        col = "banda_punto" if punto else "banda"
        filas, num = tabla_recall(d, ctl, rng, punto)
        return [f"### {titulo} ({int(d[col].notna().sum())})", "", *filas, ""], num

    sec_punto = ["## Recall frente al azar: predio del punto (principal)", "",
                 "Banda del predio que contiene el punto de la inspección, en la temporada previa. Azar: proporción de los "
                 "controles de su subzona en esa banda.", ""]
    b, n_det = bloque("Positivos detectables", pos_d)
    sec_punto += b
    b, n_todos = bloque("Todos los positivos, detectables o no", pos)
    sec_punto += b
    sec_punto += bloque("Positivos detectables del set limpio", pos_d[pos_d["set_validacion"] == "limpio"])[0]
    n_sub = {}
    for s in subzonas:
        b, n_sub[s] = bloque(f"Positivos detectables de {nombre(s)}", pos_d[pos_d["subzona"] == s])
        sec_punto += b
    sec_vec = ["## Recall frente al azar: vecindario (sensibilidad)", "",
               "Mejor banda entre los predios a 30 m o menos del punto. Azar: probabilidad de que al menos uno de los n predios "
               "del vecindario caiga en la banda, 1 − (1 − p)^n, con p de los controles de su subzona.", ""]
    b, n_vec = bloque("Positivos detectables", pos_d, punto=False)
    sec_vec += b
    sec_vec += bloque("Todos los positivos", pos, punto=False)[0]
    for s in subzonas:
        sec_vec += bloque(f"Positivos detectables de {nombre(s)}", pos_d[pos_d["subzona"] == s], punto=False)[0]

    # --- Con y sin canal
    solo_alta = {"alta": NIVELES["alta"]}
    sec_canal = ["## Con y sin el motivo de canal", "",
                 "Qué pasa con la banda alta si se descuentan las alertas con indicio de riego por canal: esas alertas pasan a "
                 "sin_alerta en los casos y en los controles por igual. Predio del punto, positivos detectables.", "",
                 "| Variante | Subzona | Positivos en alta | Recall (IC 95 %) | Azar (IC 95 %) | Lift (IC 95 % de Wilson) | "
                 "Lift (IC 95 % con el error del azar) |",
                 "| --- | --- | --- | --- | --- | --- | --- |"]
    variantes = {None: "Sin descuento", **DESCUENTOS}
    if riego is None:
        variantes.pop("riego_superficial")
    n_var = {}
    for v, texto in variantes.items():
        fv, cv = evaluar(casos, controles, pv, v)
        pv_d = fv[fv["detectable"] & fv["y"]]
        for s in [None, *subzonas]:
            d = pv_d if s is None else pv_d[pv_d["subzona"] == s]
            filas, num = tabla_recall(d, cv, rng, niveles=solo_alta)
            n_var[(v, s)] = num.get("alta")
            celdas = filas[2].split(" | ", 1)[1] if len(filas) > 2 else "— |"
            sec_canal.append(f"| {texto[0].upper() + texto[1:] if v else texto} | {'Todas' if s is None else nombre(s)} | {celdas}")
    sec_canal.append("")

    # --- Prueba del sesgo de canal
    alta = f[f["banda_punto"] == "alta"]
    sec_sesgo = ["## Prueba del sesgo de canal", "",
                 "Si el canal explica las alertas, los fiscalizados en alerta alta con indicio de canal deberían resultar negativos "
                 "más seguido que los demás. Predio del punto en banda alta en la temporada previa (detectables o no).", "",
                 "| Fiscalizados en alta | Expedientes | Negativos | Positivos | Positivos del grupo (IC 95 %) |", "| --- | --- | --- | --- | --- |"]
    sesgo = {}
    for col, texto in DESCUENTOS.items():
        if col == "riego_superficial" and riego is None:
            continue
        marca = alta[f"{col}_punto"].fillna(False).astype(bool)
        tabla2 = []
        for etiqueta, d in ((f"Con {texto}", alta[marca]), (f"Sin {texto.split(' (')[0]}", alta[~marca])):
            k, n = int(d["y"].sum()), len(d)
            tabla2.append([n - k, k])
            sec_sesgo.append(f"| {etiqueta} | {n} | {n - k} | {k} | {proporcion(k, n)} |")
        p = f"p = {fisher_exact(tabla2)[1]:.2f}" if all(sum(x) > 0 for x in tabla2) else "no aplica, un grupo está vacío"
        sesgo[col] = {"con": tabla2[0], "sin": tabla2[1], "p": p}
        sec_sesgo.append(f"| *Fisher exacto, dos colas* | | | | {p} |")
    k, n = int(alta["y"].sum()), len(alta)
    sec_sesgo += [f"| Todos los fiscalizados en alta | {n} | {n - k} | {k} | {proporcion(k, n)} |", "",
                  f"Referencia: entre todos los fiscalizados con puntaje, {proporcion(int(f['y'].sum()), len(f))} son positivos.", ""]
    if riego is not None:
        marca_c = ctl["riego_superficial"].fillna(False).astype(bool)
        sec_sesgo += ["Los mismos indicios entre los controles (para saber cuánto pesa el canal en las alertas al azar):", "",
                      "| Subzona | Controles en alta | Con `canal_300m` | Con área de riego superficial |", "| --- | --- | --- | --- |"]
        for s in subzonas:
            d = ctl[(ctl["subzona"] == s) & (ctl["banda"] == "alta")]
            sec_sesgo.append(f"| {nombre(s)} | {len(d)} | {proporcion(int(d['canal_300m'].sum()), len(d))} | "
                             f"{proporcion(int(d['riego_superficial'].sum()), len(d))} |")
        sec_sesgo += ["", "Controles (todas las bandas) con área de riego superficial: "
                      + "; ".join(f"{nombre(s)} {marca_c[ctl['subzona'] == s].mean():.0%}" for s in subzonas) + ".", ""]

    # --- AUC
    sec_auc = ["## Entre fiscalizados (límite)", "", "| Comparación | Positivos | Negativos | AUC (IC 95 %) |", "| --- | --- | --- | --- |"]
    aucs = {}
    grupos = [("Detectables, todos los negativos", det), ("Detectables, solo \"No acoge\"", det[det["y"] | det["negativo_fuerte"]]),
              ("Todos (detectables o no)", f), *[(f"Detectables de {nombre(s)}", det[det["subzona"] == s]) for s in subzonas]]
    for titulo, d in grupos:
        y, sc = d["y"].to_numpy(), d["puntaje"].to_numpy()
        if 0 < y.sum() < len(y):
            aucs[titulo] = auc_ic(y, sc, rng)
            a, lo, hi = aucs[titulo]
            sec_auc.append(f"| {titulo} | {int(y.sum())} | {int((~y).sum())} | {a:.2f} ({lo:.2f}–{hi:.2f}) |")
    am = det["banda"].isin(NIVELES["alta o media"])
    sec_auc += ["", f"Acierto entre fiscalizados detectables: {det['y'].mean():.0%} en general y "
                f"{det.loc[am, 'y'].mean():.0%} entre los que Caudal pone en alta o media ({int(det.loc[am, 'y'].sum())} de {int(am.sum())}). "
                f"Tienen señal de riego el {det.loc[det['y'], 'senal_riego'].mean():.0%} de los positivos detectables y el "
                f"{det.loc[~det['y'], 'senal_riego'].mean():.0%} de los negativos.", "",
                "Bandas de los fiscalizados detectables (mejor banda del vecindario):", "",
                *tabla_cruzada(det.assign(g=det["subzona"].map(nombre) + ", " + det["etiqueta"]), "g", "banda", list(ORDEN),
                               "Subzona y etiqueta"), ""]

    # --- Señal de riego y derechos: por qué el recall es el que es
    sec_senal = ["## Señal de riego y derechos propios", "",
                 "La banda alta pide dos cosas: señal de riego (M3) y que el consumo no se explique con derechos. Predio del punto "
                 "de cada expediente (detectable o no) y predios de control.", "",
                 "| Grupo | Predios | Con señal de riego | Con derechos propios ubicados | En alta |", "| --- | --- | --- | --- | --- |"]
    senal = {}
    for s in subzonas:
        fs = f[(f["subzona"] == s) & f["banda_punto"].notna()]
        c = ctl[ctl["subzona"] == s]
        fp_, fn_ = fs[fs["y"]], fs[~fs["y"]]
        for et, n, con_senal, derechos, banda in (
                ("positivos", len(fp_), fp_["senal_riego_punto"], fp_["estado_derechos_punto"], fp_["banda_punto"]),
                ("negativos", len(fn_), fn_["senal_riego_punto"], fn_["estado_derechos_punto"], fn_["banda_punto"]),
                ("controles", len(c), c["senal_riego"], c["estado_derechos"], c["banda"])):
            k_s, k_d = int(con_senal.fillna(False).astype(bool).sum()), int((derechos == "con_derechos").sum())
            senal[(s, et)] = {"n": n, "senal": k_s, "derechos": k_d}
            sec_senal.append(f"| {nombre(s)}, {et} | {n} | {proporcion(k_s, n)} | {proporcion(k_d, n)} | "
                             f"{proporcion(int((banda == 'alta').sum()), n)} |")
    sec_senal.append("")

    # --- Por comuna
    sec_comuna = ["## Por comuna", "", "Predio del punto. Los controles por comuna son pocos: la columna sirve para ver el orden de "
                  "magnitud, no para comparar comunas entre sí.", "",
                  "| Comuna | Subzona | Positivos | Positivos en alta | Negativos | Negativos en alta | Controles | Controles en alta |",
                  "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    fp = f[f["banda_punto"].notna()]
    for (s, comuna), d in sorted(fp.groupby(["subzona", "comuna"]), key=lambda x: (subzonas.index(x[0][0]), x[0][1])):
        c = ctl[ctl["comuna"] == comuna]
        en_alta = f"{(c['banda'] == 'alta').mean():.0%}" if len(c) else "—"
        sec_comuna.append(f"| {comuna.title()} | {nombre(s)} | {int(d['y'].sum())} | {int((d['y'] & (d['banda_punto'] == 'alta')).sum())} | "
                          f"{int((~d['y']).sum())} | {int((~d['y'] & (d['banda_punto'] == 'alta')).sum())} | {len(c)} | {en_alta} |")
    sec_comuna.append("")

    # --- Resumen
    a, am_, v = n_det["alta"], n_det["alta o media"], n_vec["alta"]
    t = n_todos["alta"]
    R = ["## Resumen", "",
         f"- **Banda alta, predio del punto.** De los {a['n']} positivos detectables por verdor fuera de Z1 y Z2, el predio del punto de "
         f"la DGA cae en banda alta en {a['k']} ({a['recall']:.0%}; IC 95 % de Wilson {a['lo']:.0%}–{a['hi']:.0%}), contra "
         f"{a['azar']:.0%} al azar ({a['azar_lo']:.0%}–{a['azar_hi']:.0%}): **{a['lift']:.1f} veces** "
         f"(IC 95 % {rango(a['lift_lo'], a['lift_hi'])}; "
         f"{rango(a['lift_lo_b'], a['lift_hi_b'])} contando el error del azar). En alta o media: {am_['k']} ({am_['recall']:.0%}) contra "
         f"{am_['azar']:.0%}, {am_['lift']:.1f} veces ({rango(am_['lift_lo'], am_['lift_hi'])}).",
         f"- **Todos los positivos.** Contando los {t['n'] - a['n']} que el verdor no puede ver, el recall en alta es {t['k']} de {t['n']} "
         f"({t['recall']:.0%}) y el lift {t['lift']:.1f} veces ({rango(t['lift_lo'], t['lift_hi'])})."]
    for s in subzonas:
        x = n_sub[s].get("alta")
        if x:
            R.append(f"- **{nombre(s)}.** {x['k']} de {x['n']} positivos detectables en alta ({x['recall']:.0%}; {x['lo']:.0%}–{x['hi']:.0%}), "
                     f"contra {x['azar']:.0%} al azar ({x['azar_lo']:.0%}–{x['azar_hi']:.0%}): {x['lift']:.1f} veces "
                     f"(IC 95 % {rango(x['lift_lo'], x['lift_hi'])}).")
    R.append(f"- **Por vecindario.** Con la mejor banda de los predios a 30 m: {v['k']} de {v['n']} en alta, contra {v['azar']:.0%} al azar: "
             f"{v['lift']:.1f} veces ({rango(v['lift_lo'], v['lift_hi'])}).")
    sp = {et: (sum(senal[(s, et)]["senal"] for s in subzonas), sum(senal[(s, et)]["derechos"] for s in subzonas),
               sum(senal[(s, et)]["n"] for s in subzonas)) for et in ("positivos", "negativos")}
    R.append(f"- **Por qué.** El predio del punto tiene señal de riego en {sp['positivos'][0]} de {sp['positivos'][2]} positivos y en "
             f"{sp['negativos'][0]} de {sp['negativos'][2]} negativos, y derechos propios ubicados en {sp['positivos'][1]} y "
             f"{sp['negativos'][1]}. Detalle por subzona y comparación con los controles en "
             "[Señal de riego y derechos propios](#señal-de-riego-y-derechos-propios).")
    contraste = (f"el universo de la corrida nacional da {alta_universo:.0%}" if alta_universo is not None else
                 "falta el contraste con el universo de la corrida nacional: `--universo`")
    R.append(f"- **Azar de la región.** Ponderando las subzonas por sus predios elegibles, el {ponderado['alta']:.0%} de los predios "
             f"de control queda en alta en su temporada ({contraste}).")
    for col, texto in DESCUENTOS.items():
        if col in sesgo:
            c, sn = sesgo[col]["con"], sesgo[col]["sin"]
            x = n_var[(col, None)]
            R.append(f"- **Sesgo de canal, {texto.split(' (')[0]}.** De los fiscalizados en alta con el indicio, {c[1]} de {sum(c)} son "
                     f"positivos; sin el indicio, {sn[1]} de {sum(sn)} (Fisher exacto: {sesgo[col]['p']}). Descontando esas alertas, el lift en "
                     + (f"alta queda en {x['lift']:.1f} veces (IC 95 % {rango(x['lift_lo'], x['lift_hi'])}), con {x['k']} de "
                        f"{x['n']} positivos." if x else "alta no se puede calcular."))
    titulo_auc = "Detectables, todos los negativos"
    if titulo_auc in aucs:
        au = aucs[titulo_auc]
        R.append(f"- **Entre fiscalizados.** AUC {au[0]:.2f} (IC 95 % {au[1]:.2f}–{au[2]:.2f}) entre {int(det['y'].sum())} positivos y "
                 f"{int((~det['y']).sum())} negativos detectables.")
    R.append("")

    doc = RAIZ / "docs" / f"validacion-{reg}.md"
    L += [f"# Validación de las alertas en {NOMBRE_REGION.get(args.region, args.region)} fuera de Z1 y Z2", "",
          f"Generado por `scripts/models/validacion_region.py --region {args.region} --excluir-z1z2` (no editar a mano, salvo la "
          "recomendación). Misma metodología que [validacion.md](validacion.md); las diferencias están en [Método](#método-y-límites).",
          "", *R, "## Recomendación", "", INICIO_REC, *recomendacion_guardada(doc), FIN_REC, "",
          *sec_casos, *sec_azar, *sec_punto, *sec_vec, *sec_senal, *sec_canal, *sec_sesgo, *sec_auc, *sec_comuna, *METODO]
    doc.write_text("\n".join(L), encoding="utf-8")

    cols = ["expediente", "etiqueta", "temporada_previa", "subzona", "comuna", "set_validacion", "detectable", "ndvi_previo",
            "n_predios", "banda_punto", "puntaje_punto", "canal_300m_punto", "riego_superficial_punto", "banda", "puntaje"]
    f[cols].to_csv(val / "casos_evaluados.csv", index=False)
    print("\n".join(R))
    print(f"-> {doc}\n-> {val / 'casos_evaluados.csv'} ({len(f)} expedientes)")


NOMBRE_REGION = {"R05": "Valparaíso"}
METODO = [
    "## Método y límites", "",
    "- **Casos y vecindario:** las reglas del set de validación de `scripts/extract/fiscalizaciones_dga.py` (D18), sobre la "
    "planilla de fiscalización de la DGA y la capa de predios de CIREN de la región. Cada expediente se evalúa en su temporada "
    "previa: la última de diciembre a marzo que empezó antes de la inspección.",
    "- **Serie Sentinel-2:** `scripts/extract/serie_sentinel2.py --parte` (celdas de 512, escenas con menos de 40 % de nubes), "
    "solo para los predios de los casos, los controles y todo el secano de referencia a 10 km. Cada predio se lee solo en su "
    "temporada.",
    "- **Clima:** Open-Meteo, reanálisis `era5_seamless`, sin corrección de estaciones, con M1 en `--umbral-mm 2`. La corrida "
    "nacional usa ERA5-Land ARCO con el mismo umbral; aquí no había clave de CDS. Pendiente: repetir el paso de clima con "
    "`d2_clima_era5land.py` y comprobar que las bandas no cambian.",
    "- **M1 a M5:** los scripts y umbrales de la corrida nacional (M7), con los derechos otorgados antes del 1 de diciembre "
    "de cada temporada. No se calibró nada con estos casos: el lift no tiene el sesgo de elección del de Z1 y Z2.",
    "- **Azar:** en `validacion.md` es la proporción del universo 2025-26 en cada banda. Aquí es una muestra de control por "
    "subzona y temporada. Por eso el lift lleva dos intervalos: el de Wilson sobre el recall (comparable con `validacion.md`) "
    "y uno por remuestreo conjunto de positivos y controles, que cuenta el error de la muestra de control. Con 0 positivos "
    "en la banda el remuestreo no varía (—): ahí solo vale el de Wilson. Los controles no se filtran por verdor, igual que el "
    "universo en `validacion.md`.",
    "- **Derechos ajenos:** M5 cuenta con consumo 0 a los predios vecinos sin estimación de M4. En esta corrida solo tienen M4 "
    "los casos y los controles, así que el descuento por derechos ajenos es mayor que en una corrida de todo el universo, para "
    "casos y controles por igual.",
    "- **NDVI de secano de M4:** es la mediana mensual del secano leído (el que está a 10 km de algún predio evaluado), no de "
    "todo el secano de la región.",
    "- **Secano de regiones vecinas:** la corrida nacional usa también el secano de la región vecina a menos de 10 km del borde; "
    "aquí solo se usó el de la región.",
    "- **Subzonas:** Aconcagua interior son las provincias de San Felipe de Aconcagua y Los Andes; el resto es la costa, "
    "Casablanca, San Antonio y Marga Marga.",
    "- **Área de riego superficial:** capa `AREAS DE RIEGO` del estudio FNDR de infraestructura de riego de CIREN "
    "(`scripts/extract/areas_riego_ciren.py`). Un predio cuenta como regado por canal si la mitad o más de su superficie cae "
    "en un área de riego `SUPERFICIAL` o `MIXTO`. El umbral se fijó antes de mirar los resultados.",
    "- **Etiquetas:** un negativo es débil (la DGA no constató infracción ese día) y la DGA fiscaliza por denuncia, no al azar.",
    "- **Muestra chica:** los intervalos son anchos. Sirven para decir si hay señal, no para afinar umbrales.",
    "",
    "## Cómo reproducir", "",
    "```bash",
    "# Tablas base de la región: del bucket (base/<tabla>/region=R05.parquet) o desde las fuentes, con los extractores:",
    "export CAUDAL_DATA=$PWD/data/raw/r05 CAUDAL_ZONAS=$PWD/data/raw/r05/regiones_R05.json   # regiones.json con solo R05",
    "for s in predios_ciren canales_ciren derechos_dga cruce_derechos_predios fiscalizaciones_dga referencia_secano_conaf \\",
    "         cultivos_ciren areas_riego_ciren; do uv run scripts/extract/$s.py; done",
    "unset CAUDAL_DATA CAUDAL_ZONAS",
    "uv run scripts/models/validacion_region.py --region R05 --excluir-z1z2",
    "```",
    "",
]


# --- Entrada ------------------------------------------------------------------------------------------------------

PASOS = {"casos": paso_casos, "plan": paso_plan, "satelite": paso_satelite, "clima": paso_clima, "modelos": paso_modelos,
         "informe": paso_informe}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--region", default="R05", help="código de la región en data/regiones.json")
    ap.add_argument("--excluir-z1z2", action="store_true", help="deja fuera los predios de Z1 y Z2 (data/processed/puntaje.parquet)")
    ap.add_argument("--datos", type=Path, help="carpeta con las tablas de la región (por defecto data/raw/<región>)")
    ap.add_argument("--paso", choices=[*PASOS, "todo"], default="todo")
    ap.add_argument("--temporadas", default="2019-20:2024-25", help="rango de temporadas previas, o una sola")
    ap.add_argument("--controles", type=int, default=300, help="predios de control por subzona")
    ap.add_argument("--semilla", type=int, default=0)
    ap.add_argument("--nubes-max", type=float, default=40, help="nubes de la escena, como la corrida nacional")
    ap.add_argument("--hilos", type=int, default=24, help="escenas en paralelo en el paso satelite")
    ap.add_argument("--lote-clima", type=int, default=5, help="celdas por llamada a Open-Meteo")
    ap.add_argument("--rehacer", action="store_true", help="rehace casos y plan aunque existan")
    ap.add_argument("--universo", type=Path, help="puntaje.parquet de la corrida nacional de la región, como contraste del azar")
    args = ap.parse_args()
    args.datos = (args.datos or RAIZ / "data" / "raw" / args.region.lower()).resolve()
    args.temporadas = rango_temporadas(args.temporadas)
    val = args.datos / "validacion"
    for nombre in PASOS if args.paso == "todo" else [args.paso]:
        print(f"\n=== {nombre} ===", flush=True)
        PASOS[nombre](args, val)
    return 0


if __name__ == "__main__":
    sys.exit(main())
