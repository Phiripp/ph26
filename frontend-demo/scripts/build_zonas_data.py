"""
build_zonas_data.py — datos tabulares de las zonas Z1/Z2 para el frontend (rol DATA-TAB).

Lee SOLO datos del equipo (../data, solo lectura) y escribe, relativo a frontend-demo/:
  data/zonas/index.json                zonas (Z1 Petorca, Z2 Aconcagua bajo) con bbox_escena
  data/zonas/{z1,z2}/predios.geojson   predios muestra + predio de cada caso, con derechos DGA reales
  data/zonas/{z1,z2}/clima.json        lluvia corregida + ET0 (Open-Meteo corregido con DMC) y ventanas secas N=10
  data/zonas/casos.json                los 10 casos de validación (resueltos, sancionados por la DGA)
  data/zonas/fiscalizaciones.geojson   expedientes DGA de extracción de aguas en Z1/Z2 (sin nombres)
  assets/casos/<expediente>/*.png      imágenes antes/después del equipo (3 casos)

No usa serie_predio (bug D15). No incluye nombres de titulares.

Correr desde frontend-demo/:
  uv run --with pandas --with pyarrow --with geopandas --with shapely python scripts/build_zonas_data.py
"""
import json
import math
import os
import shutil

import geopandas as gpd
import pandas as pd
from shapely.geometry import mapping

HERE = os.path.dirname(os.path.abspath(__file__))
FRONT = os.path.dirname(HERE)
REPO = os.path.dirname(FRONT)
DATA = os.path.join(REPO, "data")
PROC = os.path.join(DATA, "processed")
OUT = os.path.join(FRONT, "data", "zonas")
ASSETS_CASOS = os.path.join(FRONT, "assets", "casos")

TEMPORADA = "2025-26"
CLIMA_INICIO = "2020-01-01"
MARGEN_M = 1500.0
ZONA_IDS = {"Z1": "z1", "Z2": "z2"}


def log(*a):
    print("[build_zonas]", *a, flush=True)


def nn(x):
    """NaN/NA -> None, numpy -> python."""
    if x is None:
        return None
    try:
        if pd.isna(x):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(x, "item"):
        x = x.item()
    if isinstance(x, float):
        return round(x, 3)
    return x


def iso(x):
    if x is None or (not isinstance(x, str) and pd.isna(x)):
        return None
    return pd.Timestamp(x).strftime("%Y-%m-%d")


def dump(obj, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    log("escrito", os.path.relpath(path, FRONT), f"{os.path.getsize(path) / 1024:.0f} KB")


def round_geom(geom, nd=6):
    g = mapping(geom)

    def r(c):
        if isinstance(c, (list, tuple)) and c and isinstance(c[0], (int, float)):
            return [round(c[0], nd), round(c[1], nd)]
        return [r(x) for x in c]

    return {"type": g["type"], "coordinates": r(g["coordinates"])}


def bbox_rule(muestra, casos):
    """bbox de casos + predios muestra por zona, margen 1.5 km, redondeo hacia afuera a 3 decimales."""
    res = {}
    for z, zid in ZONA_IDS.items():
        pts = list(muestra[muestra.zona == z].total_bounds.reshape(2, 2)) + \
            list(casos[casos.zona == z].total_bounds.reshape(2, 2))
        w = min(p[0] for p in pts); s = min(p[1] for p in pts)
        e = max(p[0] for p in pts); n = max(p[1] for p in pts)
        lat = (s + n) / 2
        dlat = MARGEN_M / 111320.0
        dlon = MARGEN_M / (111320.0 * math.cos(math.radians(lat)))
        res[zid] = [math.floor((w - dlon) * 1000) / 1000, math.floor((s - dlat) * 1000) / 1000,
                    math.ceil((e + dlon) * 1000) / 1000, math.ceil((n + dlat) * 1000) / 1000]
    return res


def main():
    zonas_cfg = json.load(open(os.path.join(DATA, "zonas.json"), encoding="utf-8"))["zonas"]
    casos = gpd.read_file(os.path.join(DATA, "casos_validacion.geojson"))
    muestra = gpd.read_file(os.path.join(PROC, "predio_muestra.geojson"))
    pdr = pd.read_parquet(os.path.join(PROC, "predio_derecho.parquet"))
    pdr = pdr[pdr.temporada == TEMPORADA].set_index("predio_id")
    cult = pd.read_parquet(os.path.join(PROC, "predio_cultivo.parquet")).set_index("predio_id")
    pclima = pd.read_parquet(os.path.join(PROC, "predio_clima.parquet")).set_index("predio_id")
    fisc = gpd.read_parquet(os.path.join(PROC, "fiscalizacion.parquet"))
    img_manifest = {c["expediente"]: c for c in json.load(
        open(os.path.join(PROC, "imagenes", "manifest.json"), encoding="utf-8"))}

    # ---------------------------------------------------------------- caso -> predio
    m_u = muestra.to_crs(32719)
    c_u = casos.to_crs(32719)
    caso_predio, approx = {}, []
    for i, r in c_u.iterrows():
        exp = r.expediente
        fr = fisc[(fisc.expediente == exp) & fisc.predio_id.notna()]
        d = m_u.distance(r.geometry)
        j = d.idxmin()
        pid = int(fr.predio_id.iloc[0]) if len(fr) else int(muestra.loc[j, "predio_id"])
        if (muestra.predio_id == pid).any():
            caso_predio[exp] = dict(predio_id=pid, dist_m=round(float(d[j]), 1), geom_aprox=False)
        else:
            # sin geometría en la muestra: buffer ~150 m alrededor del punto del caso
            approx.append(exp)
            caso_predio[exp] = dict(predio_id=pid, dist_m=None, geom_aprox=True)
    if approx:
        log("casos con geometría aproximada:", approx)

    # ---------------------------------------------------------------- bbox_escena
    bbox_path = os.path.join(OUT, "bbox.json")
    if os.path.exists(bbox_path):
        bb = json.load(open(bbox_path, encoding="utf-8"))
        bboxes = {z: bb[z] for z in ("z1", "z2")}
        log("bbox_escena desde data/zonas/bbox.json (IMAGERY)")
    else:
        bboxes = bbox_rule(muestra, casos)
        log("bbox_escena calculado con la regla (no había bbox.json)")

    # ---------------------------------------------------------------- predios por zona
    clima = pd.read_parquet(os.path.join(PROC, "clima.parquet"))
    vseca = pd.read_parquet(os.path.join(PROC, "ventana_seca.parquet"))
    index = {"generado_por": "frontend-demo/scripts/build_zonas_data.py", "temporada": TEMPORADA, "zonas": []}
    counts = {}
    case_feat_props = {}

    for z, zid in ZONA_IDS.items():
        cfg = zonas_cfg[z]
        zcasos = casos[casos.zona == z]
        sub = muestra[muestra.zona == z].copy()
        case_pids = {caso_predio[e]["predio_id"]: e for e in zcasos.expediente}
        feats = []
        centroids = sub.to_crs(32719).centroid.to_crs(4326)
        for (idx, r), cen in zip(sub.iterrows(), centroids):
            pid = int(r.predio_id)
            d = pdr.loc[pid] if pid in pdr.index else None
            c = cult.loc[pid] if pid in cult.index else None
            cultivo = "sin catastro"
            if c is not None and bool(c.con_frutales) and isinstance(c.especie_principal, str):
                cultivo = c.especie_principal.capitalize()
            caso = case_pids.get(pid)
            props = dict(
                id=str(pid), predio_id=pid, rol=r.rol, comuna=r.comuna, zona=zid,
                area_ha=nn(r.area_ha), cultivo=cultivo,
                especies=(c.especies if c is not None and isinstance(c.especies, str) else None),
                area_fruticola_ha=(nn(c.area_fruticola_ha) if c is not None else None),
                m3_derecho_rol=(nn(round(d.m3_anual_derecho_rol)) if d is not None else None),
                m3_derecho_entorno_500m=(nn(round(d.m3_anual_derecho_entorno_500m)) if d is not None else None),
                n_derechos_rol=(nn(d.n_derechos_rol) if d is not None else None),
                estado_derechos=(d.estado_derechos if d is not None else None),
                confianza_cruce=(d.confianza_cruce if d is not None else None),
                pozo_compartido_500m=(nn(d.pozo_compartido_500m) if d is not None else None),
                dist_canal_m=(nn(d.dist_canal_m) if d is not None else None),
                celda_clima=(pclima.loc[pid, "celda_id"] if pid in pclima.index else None),
                caso=caso, caso_cercano=r.caso_cercano, dist_caso_m=nn(r.dist_caso_m),
                geom_aprox=False,
                centroid=[round(cen.x, 6), round(cen.y, 6)],
            )
            feats.append({"type": "Feature", "properties": props, "geometry": round_geom(r.geometry)})
            if caso:
                case_feat_props[caso] = props
        # casos sin predio en la muestra -> buffer aproximado
        for exp in zcasos.expediente:
            if exp in case_feat_props:
                continue
            pt = c_u[c_u.expediente == exp].geometry.iloc[0]
            poly = gpd.GeoSeries([pt.buffer(150)], crs=32719).to_crs(4326).iloc[0]
            pid = caso_predio[exp]["predio_id"]
            d = pdr.loc[pid] if pid in pdr.index else None
            cen = casos[casos.expediente == exp].geometry.iloc[0]
            props = dict(id=str(pid), predio_id=pid, rol=(d.rol_id.split(":")[1] if d is not None else None),
                         comuna=casos[casos.expediente == exp].comuna.iloc[0], zona=zid,
                         area_ha=(nn(d.area_ha) if d is not None else None), cultivo="sin catastro",
                         m3_derecho_rol=(nn(round(d.m3_anual_derecho_rol)) if d is not None else None),
                         m3_derecho_entorno_500m=(nn(round(d.m3_anual_derecho_entorno_500m)) if d is not None else None),
                         estado_derechos=(d.estado_derechos if d is not None else None),
                         confianza_cruce=(d.confianza_cruce if d is not None else None),
                         dist_canal_m=(nn(d.dist_canal_m) if d is not None else None),
                         caso=exp, geom_aprox=True, centroid=[round(cen.x, 6), round(cen.y, 6)])
            feats.append({"type": "Feature", "properties": props, "geometry": round_geom(poly)})
            case_feat_props[exp] = props

        fc = {"type": "FeatureCollection",
              "fuente": ("Predios CIREN 2022 (muestra del equipo, 50 por zona alrededor de los casos); derechos DGA "
                         f"cruzados por rol, temporada {TEMPORADA} (predio_derecho.parquet); especie: Catastro "
                         "Frutícola CIREN 2025. Sin nombres de titulares."),
              "features": feats}
        dump(fc, os.path.join(OUT, zid, "predios.geojson"))
        counts[zid] = dict(predios=len(feats), casos=len(zcasos),
                           con_derechos=sum(1 for f in feats if f["properties"]["estado_derechos"] == "con_derechos"))

        # ------------------------------------------------------------ clima de la celda principal
        celdas = pd.Series([f["properties"].get("celda_clima") for f in feats]).dropna()
        celda = celdas.value_counts().idxmax()
        om = clima[(clima.punto_id == celda) & (clima.fuente == "openmeteo")].sort_values("fecha")
        om = om[om.fecha >= CLIMA_INICIO]
        lluvia = om.lluvia_corr_mm.where(om.lluvia_corr_mm.notna(), om.lluvia_mm).fillna(0.0)
        fechas = om.fecha.dt.strftime("%Y-%m-%d").tolist()
        p = [round(float(x), 2) for x in lluvia]
        e = [round(float(x), 2) if pd.notna(x) else 0.0 for x in om.et0_mm]
        seco = [x < 1.0 for x in p]
        meses = sorted(set(f[:7] for f in fechas))
        mensual = []
        for mes in meses:
            ix = [k for k, f in enumerate(fechas) if f.startswith(mes)]
            run = best = 0
            for k in ix:
                run = run + 1 if seco[k] else 0
                best = max(best, run)
            mensual.append(dict(mes=mes, lluvia_mm=round(sum(p[k] for k in ix), 1),
                                et0_mm=round(sum(e[k] for k in ix), 1), tmax_media_c=None,
                                dias_sin_lluvia_max=best))
        anual = {}
        for y in sorted(set(m[:4] for m in meses)):
            ms = [x for x in mensual if x["mes"].startswith(y)]
            anual[y] = dict(lluvia_mm=round(sum(x["lluvia_mm"] for x in ms), 1),
                            et0_mm=round(sum(x["et0_mm"] for x in ms), 1), meses=len(ms))
        vs = vseca[(vseca.celda_id == celda) & (vseca.fin >= CLIMA_INICIO)].sort_values("inicio")
        ventanas = [dict(inicio=iso(v.inicio), fin=iso(v.fin), dias=int(v.dias), et0_mm=nn(v.et0_mm),
                         lluvia_max_mm=nn(v.lluvia_max_mm), abierta=bool(v.abierta)) for v in vs.itertuples()]
        _, _, lat, lon = celda.split("_")
        lat = -float(lat[1:]); lon = -float(lon[1:])
        clima_json = dict(
            fuente="Open-Meteo corregido con estaciones DMC (lluvia_corr_mm) + ET0 Open-Meteo",
            fuente_url="https://archive-api.open-meteo.com/v1/archive",
            illustrative=False,
            celda_id=celda,
            estacion_ref_id=nn(om.estacion_ref_id.dropna().iloc[0]) if om.estacion_ref_id.notna().any() else None,
            punto=dict(lon=lon, lat=lat, nombre=f"{cfg['nombre']} (celda {celda})", elevacion_modelo_m=None),
            periodo=dict(inicio=fechas[0], fin=fechas[-1]),
            nota=("Lluvia diaria de la celda de Open-Meteo con más predios de la zona, corregida mes a mes con la "
                  "estación DMC más cercana (data/processed/clima.parquet, tarea D2). Ventanas secas del equipo "
                  "(ventana_seca.parquet). Sin temperatura."),
            criterio_ventana_seca=">= 10 dias consecutivos sin lluvia efectiva (ventana_seca.parquet, N=10)",
            unidades=dict(precipitation_sum="mm", et0_fao_evapotranspiration="mm", temperature_2m_max="°C"),
            diario=dict(fecha=fechas, precipitation_sum=p, et0_fao_evapotranspiration=e,
                        temperature_2m_max=[None] * len(fechas)),
            mensual=mensual,
            anual=anual,
            ventanas_secas=ventanas,
        )
        dump(clima_json, os.path.join(OUT, zid, "clima.json"))
        counts[zid].update(celda=celda, ventanas=len(ventanas), clima_dias=len(fechas))

        # ------------------------------------------------------------ index
        bb = bboxes[zid]
        orden_papel = {"demo_principal": 0, "antecedente_satelital": 1}
        zc_sorted = sorted(zcasos.itertuples(), key=lambda c: (orden_papel.get(c.papel, 2), iso(c.fecha_inspeccion)))
        index["zonas"].append(dict(
            id=zid, codigo=z, nombre=cfg["nombre"], uso=cfg.get("uso"), comunas=cfg["comunas"],
            bbox_zona=cfg["bbox"], bbox_escena=bb,
            centro=[round((bb[0] + bb[2]) / 2, 5), round((bb[1] + bb[3]) / 2, 5)],
            base=f"assets/zonas/{zid}/", data=f"data/zonas/{zid}/",
            casos=[c.expediente for c in zc_sorted],
            n_predios=len(feats),
        ))

    dump(index, os.path.join(OUT, "index.json"))

    # ---------------------------------------------------------------- casos.json + imágenes
    if os.path.isdir(ASSETS_CASOS):
        shutil.rmtree(ASSETS_CASOS)
    out_casos = []
    for r in casos.itertuples():
        cp = caso_predio[r.expediente]
        props = case_feat_props[r.expediente]
        imgs = []
        man = img_manifest.get(r.expediente)
        if man:
            dst = os.path.join(ASSETS_CASOS, r.expediente)
            os.makedirs(dst, exist_ok=True)
            for im in man["imagenes"]:
                entry = dict(etiqueta=im["etiqueta"], fecha=im["fecha"], escena_id=im.get("escena_id"),
                             nubes_recorte_pct=im.get("nubes_recorte_pct"), esquinas=im["esquinas"])
                for k, rel in im["archivos"].items():
                    shutil.copy2(os.path.join(PROC, "imagenes", rel), os.path.join(dst, os.path.basename(rel)))
                    entry[k] = f"assets/casos/{r.expediente}/{os.path.basename(rel)}"
                imgs.append(entry)
        out_casos.append(dict(
            expediente=r.expediente, papel=r.papel, zona=ZONA_IDS[r.zona], comuna=r.comuna,
            predio_id=cp["predio_id"], id=str(cp["predio_id"]), rol=props.get("rol"), area_ha=props.get("area_ha"),
            dist_punto_predio_m=cp["dist_m"], geom_aprox=cp["geom_aprox"],
            fecha_inspeccion=iso(r.fecha_inspeccion), decision=r.decision, resolucion=r.resolucion,
            multa_utm=nn(r.multa_utm), etiqueta=r.etiqueta, tipo_infraccion=r.tipo_infraccion,
            estado_derechos=props.get("estado_derechos"), m3_derecho_rol=props.get("m3_derecho_rol"),
            m3_derecho_entorno_500m=props.get("m3_derecho_entorno_500m"), cultivo=props.get("cultivo"),
            lon=round(r.geometry.x, 6), lat=round(r.geometry.y, 6),
            imagenes=imgs,
        ))
    orden = {"demo_principal": 0, "antecedente_satelital": 1}
    out_casos.sort(key=lambda c: (c["zona"], orden.get(c["papel"], 2), c["fecha_inspeccion"]))
    dump(out_casos, os.path.join(OUT, "casos.json"))

    # ---------------------------------------------------------------- fiscalizaciones
    fx = fisc[(fisc.extraccion == True) & fisc.zona.isin(["Z1", "Z2"]) & fisc.geometry.notna()  # noqa: E712
              & ~fisc.geometry.is_empty].copy()
    case_set = set(casos.expediente)
    ffeats = []
    for r in fx.itertuples():
        ffeats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [
            round(r.geometry.x, 5), round(r.geometry.y, 5)]}, "properties": dict(
            expediente=r.expediente, zona=ZONA_IDS[r.zona], comuna=r.comuna_declarada,
            fecha_inspeccion=iso(r.fecha_inspeccion), etiqueta=r.etiqueta,
            decision=nn(r.decision), multa_utm=nn(r.multa_utm),
            predio_id=nn(r.predio_id), es_caso=r.expediente in case_set)})
    dump({"type": "FeatureCollection",
          "fuente": "Planilla de fiscalización DGA (fiscalizacion.parquet, tarea D6), solo extracción de aguas. Sin nombres.",
          "features": ffeats}, os.path.join(OUT, "fiscalizaciones.geojson"))
    et = pd.Series([f["properties"]["etiqueta"] for f in ffeats]).value_counts().to_dict()

    log("conteos", json.dumps(counts, ensure_ascii=False))
    log("fiscalizaciones", len(ffeats), et)
    log("casos", len(out_casos), "con imágenes:", [c["expediente"] for c in out_casos if c["imagenes"]])
    log("geometría aproximada:", approx or "ninguna")


if __name__ == "__main__":
    main()
