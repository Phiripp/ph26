# /// script
# requires-python = ">=3.11"
# dependencies = ["pandas", "pyarrow", "numpy", "geopandas>=1.0", "shapely>=2.0", "matplotlib", "jinja2", "weasyprint",
#                 "rasterio", "pystac-client", "pillow"]
# ///
"""Expediente PDF de un predio: borrador de antecedentes para una denuncia (tarea M13, flujo B).

Arma las 7 secciones de la Guía para la presentación de denuncias por infracciones al Código de Aguas (DGA, jul 2025),
según docs/spec-flujos-poligono.md (B1 a B4):
1-2 denunciante y representante: vacíos. 3 ubicación: pre-llenada (comuna, provincia, cauce y canal cercanos, croquis).
4 hechos: borrador redactado con M3 (señal de riego), M4 (consumo) y D5 (derechos). 5 afectación: vacía, con preguntas
guía (requisito de admisibilidad). 6 adjuntos. 7 declaración y firma: vacía. Luego, cómo presentarla y un anexo técnico
(A1 mapa y POI, A2 series NDVI/NDMI frente al secano, A3 imágenes, A4 consumo y derechos, A5 calidad, A6 fuentes).

Lenguaje (B3): "indicios" y "eventual infracción"; los m³ siempre en rango; nada afirma una infracción.

Entradas (data/processed/): salidas de M2 a M4 (busca el predio en las series _elegibles_2025-26, _validacion y la
muestra, en ese orden), predio_derecho, predio_cauce, poi, predio_cultivo, fiscalizacion, predio_clima, ventana_seca,
dias_sin_lluvia, cauce y la geometría del predio (predio.parquet local o predio_muestra.geojson). La foto base del croquis
es Esri World Imagery Wayback (solo mapa base, con su fecha de captura y atribución); las imágenes del anexo A3 son
Sentinel-2 de Earth Search, con escena y fecha. Sin red, usar --sin-imagenes.

Salida: data/processed/expedientes/<id>/ con expediente.pdf, expediente.html y las figuras, más una fila en
data/processed/expedientes/registro.csv (id, predio_id, rol, temporada, confianza, versión, hash de insumos, ruta, fecha).

Uso:
  uv run scripts/models/expediente.py --rol HIJUELAS:61-6               # caso base FO-0504-95
  uv run scripts/models/expediente.py --predio-id 5301413 --temporada 2021-22
  uv run scripts/models/expediente.py --rol CABILDO:390-80 --sin-imagenes
"""

import argparse
import hashlib
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from jinja2 import Environment, FileSystemLoader, select_autoescape  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from comun.rutas import PROC, RAIZ, mostrar  # noqa: E402
PLANTILLAS = Path(__file__).resolve().parent / "plantillas"
CRS_M = 32719
STAC = "https://earth-search.aws.element84.com/v1"
WAYBACK_CONFIG = "https://s3-us-west-2.amazonaws.com/config.maptiles.arcgis.com/waybackconfig.json"
VERSION = "pre-visita"
FAMILIAS = ["_elegibles_2025-26", "_validacion", ""]  # orden de búsqueda de las series de M2 a M4
PROVINCIA = {"PETORCA": "Petorca", "CABILDO": "Petorca", "LA LIGUA": "Petorca", "PAPUDO": "Petorca", "ZAPALLAR": "Petorca",
             "HIJUELAS": "Quillota", "LA CRUZ": "Quillota", "QUILLOTA": "Quillota", "NOGALES": "Quillota",
             "LA CALERA": "Quillota", "CALERA": "Quillota"}
MOTIVOS = {"pocas_fechas": "pocas imágenes válidas", "sin_clima": "sin dato de clima", "sin_referencia": "sin secano de referencia",
           "nubosidad": "mucha nubosidad", "pocos_pixeles": "predio chico para 20 m", "predio_grande": "predio grande (el promedio diluye)",
           "referencia_provisional": "referencia provisional",
           "sin_derechos_propios_ubicados": "sin derechos propios ubicados", "canal_300m": "canal a 300 m o menos",
           "derechos_ajenos_cubren_exceso": "derechos de otros roles a 500 m cubren el exceso",
           "temporada_incompleta_m4": "consumo con temporada incompleta", "sin_consumo_m4": "sin estimación de consumo",
           "cruce_derechos_media": "cruce de derechos con confianza media", "cruce_derechos_baja": "cruce de derechos con confianza baja",
           "clima_climatologia": "clima completado con climatología"}
BANDA = {"alta": "alta", "media": "media", "baja": "baja", "sin_alerta": "sin alerta"}
TIPO_POI = {"captacion": "Captación (expediente DGA)", "zona_riego": "Zona con verdor y humedad", "posible_tranque": "Posible tranque",
            "pozo_derecho": "Pozo con derecho", "bocatoma": "Bocatoma", "cauce": "Cauce natural", "canal": "Canal"}
ESTADO_DER = {"sin_derechos_cerca": "ninguno a 500 m", "derechos_cerca_de_otro_rol": "solo en otros roles", "con_derechos": "con derechos"}
Z_UMBRAL, DIAS_MIN = 2.0, 10  # los de M3


# ---------- formato chileno ----------
def num(x, dec=0) -> str:
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "s/d"
    s = f"{x:,.{dec}f}"
    return s.replace(",", "_").replace(".", ",").replace("_", ".")


def redondo(x) -> str:
    """m³ a 2 cifras significativas: un rango no merece más precisión."""
    if x is None or np.isnan(x) or x == 0:
        return num(x)
    p = 10 ** max(int(np.floor(np.log10(abs(x)))) - 1, 0)
    return num(round(x / p) * p)


def fecha(d) -> str:
    return pd.Timestamp(d).strftime("%d-%m-%Y")


def titulo(s: str) -> str:
    ws = str(s).split()
    return " ".join(w.capitalize() if (i == 0 or len(w) > 2) else w.lower() for i, w in enumerate(ws))


# ---------- datos ----------
def leer(nombre: str) -> pd.DataFrame:
    return pd.read_parquet(PROC / f"{nombre}.parquet")


def del_predio(base: str, pid: int, clave: str, sufijo_extra: str = "") -> tuple[pd.DataFrame, list[Path]]:
    """Filas del predio en las series de M2 a M4, de la familia más prioritaria que lo tenga para cada clave."""
    partes, usados = [], []
    for fam in FAMILIAS:
        p = PROC / f"{base}{fam}{sufijo_extra}.parquet"
        if not p.exists():
            continue
        d = pd.read_parquet(p)
        d = d[d.predio_id == pid]
        if len(d):
            partes.append(d)
            usados.append(p)
    if not partes:
        return pd.DataFrame(), usados
    return pd.concat(partes, ignore_index=True).drop_duplicates(clave).sort_values(clave).reset_index(drop=True), usados


def puntaje_m5(pid: int, t: str) -> tuple[pd.Series | None, int | None, Path | None]:
    """Fila de M5 del predio en la temporada t. El puesto en la zona solo vale en puntaje.parquet (los 7.911 elegibles);
    en puntaje_validacion el rank es entre los predios de validación y no se muestra."""
    for nombre, con_rank in (("puntaje", True), ("puntaje_validacion", False)):
        f = PROC / f"{nombre}.parquet"
        if not f.exists():
            continue
        d = pd.read_parquet(f)
        x = d[(d.predio_id == pid) & (d.temporada == t)]
        if len(x):
            n = int((d[d.temporada == t].zona == x.zona.iloc[0]).sum()) if con_rank else None
            return x.iloc[0], n, f
    return None, None, None


def predio_geom(pid: int | None, rol: str | None) -> gpd.GeoDataFrame:
    for f in ("predio.parquet", "predio_muestra.geojson"):
        p = PROC / f
        if not p.exists():
            continue
        g = gpd.read_parquet(p) if p.suffix == ".parquet" else gpd.read_file(p)
        if pid is not None:
            g = g[g.predio_id == pid]
        else:
            com, _, r = rol.partition(":")
            g = g[(g.comuna.str.upper() == com.strip().upper()) & (g.rol.astype(str) == r.strip())]
        if len(g):
            return g.iloc[[0]].reset_index(drop=True)
    sys.exit(f"No encontré el predio ({pid or rol}) en predio.parquet ni en predio_muestra.geojson")


def version_de(p: Path) -> str:
    r = subprocess.run(["git", "log", "-1", "--format=%h %ad", "--date=short", "--", str(p)], cwd=RAIZ,
                       capture_output=True, text=True)
    return r.stdout.strip() or f"local sha256 {sha(p)[:10]}"


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def ventanas(pid: int, fechas: pd.Series) -> pd.DataFrame:
    """Para cada fecha: si cae en una ventana seca de M1 de la celda del predio y los días sin lluvia."""
    pc = leer("predio_clima")
    celda = pc.loc[pc.predio_id == pid, "celda_id"]
    out = pd.DataFrame({"fecha": pd.to_datetime(fechas.unique())})
    out["en_ventana"], out["dias_sin_lluvia"] = False, np.nan
    if celda.empty:
        return out
    c = celda.iloc[0]
    v = leer("ventana_seca")
    v = v[v.celda_id == c]
    for _, w in v.iterrows():
        out.loc[(out.fecha >= w.inicio) & (out.fecha <= w.fin), "en_ventana"] = True
    d = leer("dias_sin_lluvia")
    d = d[d.celda_id == c][["fecha", "dias_sin_lluvia"]]
    out = out.drop(columns="dias_sin_lluvia").merge(d, on="fecha", how="left")
    return out


# ---------- figuras ----------
def chip_s2(escena_id: str, bounds, items: dict) -> np.ndarray | None:
    """Recorte en color natural (TCI, 10 m) de la escena, en EPSG:32719. None si no hay red o la escena no está."""
    import rasterio
    from rasterio.windows import from_bounds
    it = items.get(escena_id)
    if it is None or "visual" not in it.assets:
        return None
    try:
        with rasterio.Env(AWS_NO_SIGN_REQUEST="YES", GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR"):
            with rasterio.open(it.assets["visual"].href) as ds:
                if ds.crs.to_epsg() != CRS_M:
                    return None
                return np.moveaxis(ds.read([1, 2, 3], window=from_bounds(*bounds, transform=ds.transform),
                                           boundless=True, fill_value=0), 0, -1)
    except Exception as e:  # sin red o escena rota: el expediente sale igual, sin fondo
        print(f"  aviso: no pude leer la imagen {escena_id}: {e}", file=sys.stderr)
        return None


def _http(url: str, timeout=20) -> bytes:
    from urllib.request import Request, urlopen
    with urlopen(Request(url, headers={"User-Agent": "caudal-expediente"}), timeout=timeout) as r:  # sigue los 301 de Wayback
        return r.read()


def fondo_wayback(bounds, ancho_px=1100) -> tuple[np.ndarray | None, dict]:
    """Foto aérea de Esri World Imagery Wayback (versión más reciente), reproyectada a la grilla UTM 19S de `bounds`.

    Es solo mapa base (decisión del repo: Sentinel-2 para el análisis). Wayback redirige cada tile a la versión en que
    ese sector cambió por última vez; la fecha de captura sale de la capa de metadatos de esa versión."""
    import json
    import math
    from concurrent.futures import ThreadPoolExecutor
    from io import BytesIO

    import rasterio
    from PIL import Image
    from rasterio.transform import Affine, from_bounds
    from rasterio.warp import Resampling, reproject, transform_bounds

    cfg = json.loads(_http(WAYBACK_CONFIG))
    rel, meta = max(cfg.items(), key=lambda kv: kv[1]["itemTitle"])  # "World Imagery (Wayback AAAA-MM-DD)"
    info = {"version": meta["itemTitle"].split("Wayback ")[-1].rstrip(")")}
    lon0, lat0, lon1, lat1 = transform_bounds(CRS_M, 4326, *bounds)
    latc = math.radians((lat0 + lat1) / 2)
    ancho_m = bounds[2] - bounds[0]
    for z in range(min(18, math.ceil(math.log2(ancho_px * 156543.034 * math.cos(latc) / ancho_m))), 13, -1):
        n = 2 ** z
        tx = lambda lon: int((lon + 180) / 360 * n)  # noqa: E731
        ty = lambda lat: int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)  # noqa: E731
        xs, ys = range(tx(lon0), tx(lon1) + 1), range(ty(lat1), ty(lat0) + 1)
        url = meta["itemURL"].replace("{level}", str(z))

        def tile(xy):
            x, y = xy
            try:
                return xy, np.asarray(Image.open(BytesIO(_http(url.replace("{row}", str(y)).replace("{col}", str(x))))).convert("RGB"))
            except Exception:
                return xy, None

        with ThreadPoolExecutor(8) as ex:
            res = dict(ex.map(tile, [(x, y) for y in ys for x in xs]))
        if sum(v is None for v in res.values()) > 0.2 * len(res):  # sin cobertura a este zoom: probar uno menos
            continue
        mos = np.zeros((len(ys) * 256, len(xs) * 256, 3), "uint8")
        for (x, y), im in res.items():
            if im is not None:
                mos[(y - ys[0]) * 256:(y - ys[0] + 1) * 256, (x - xs[0]) * 256:(x - xs[0] + 1) * 256] = im
        r_m, o = 2 * 20037508.342789244 / n / 256, 20037508.342789244
        src_t = Affine(r_m, 0, -o + xs[0] * 256 * r_m, 0, -r_m, o - ys[0] * 256 * r_m)
        alto_px = int(round(ancho_px * (bounds[3] - bounds[1]) / ancho_m))
        dst = np.zeros((3, alto_px, ancho_px), "uint8")
        for b in range(3):
            reproject(mos[..., b], dst[b], src_transform=src_t, src_crs="EPSG:3857",
                      dst_transform=from_bounds(*bounds, ancho_px, alto_px), dst_crs=f"EPSG:{CRS_M}", resampling=Resampling.bilinear)
        try:  # fecha de captura y proveedor en el centro del recuadro (capa de metadatos de la resolución del zoom)
            capa = min(13, max(0, 5 + 18 - z))
            q = (f"{meta['metadataLayerUrl']}/{capa}/query?geometry={(lon0 + lon1) / 2},{(lat0 + lat1) / 2}"
                 "&geometryType=esriGeometryPoint&inSR=4326&spatialRel=esriSpatialRelIntersects"
                 "&outFields=SRC_DATE,SRC_RES,NICE_DESC&returnGeometry=false&f=json")
            a = json.loads(_http(q))["features"][0]["attributes"]
            info.update(captura=pd.to_datetime(str(a["SRC_DATE"]), format="%Y%m%d").strftime("%d-%m-%Y"),
                        proveedor=a.get("NICE_DESC") or "", resolucion=a.get("SRC_RES"))
        except Exception:
            pass
        info["zoom"] = z
        return np.moveaxis(dst, 0, -1), info
    return None, info


def marco(geom, minimo=150.0):
    x0, y0, x1, y1 = geom.bounds
    m = max(minimo, 0.35 * max(x1 - x0, y1 - y0))
    cx, cy, r = (x0 + x1) / 2, (y0 + y1) / 2, max(x1 - x0, y1 - y0) / 2 + m
    return (cx - r, cy - r, cx + r, cy + r)


def dibujar_predio(ax, geom, bounds, fondo, escala=True):
    if fondo is not None:
        ax.imshow(fondo, extent=(bounds[0], bounds[2], bounds[1], bounds[3]))
    else:
        ax.set_facecolor("#f3f4f6")
    for g in getattr(geom, "geoms", [geom]):
        x, y = g.exterior.xy
        ax.plot(x, y, color="#facc15", lw=2.2)
        ax.plot(x, y, color="black", lw=0.6, ls=(0, (2, 2)))
    ax.set_xlim(bounds[0], bounds[2]); ax.set_ylim(bounds[1], bounds[3])
    ax.set_xticks([]); ax.set_yticks([]); ax.set_aspect("equal")
    if escala:
        ancho = bounds[2] - bounds[0]
        largo = 100 if ancho < 900 else 200 if ancho < 1800 else 500
        x0, y0 = bounds[0] + 0.05 * ancho, bounds[1] + 0.05 * ancho
        ax.plot([x0, x0 + largo], [y0, y0], color="white", lw=4, solid_capstyle="butt")
        ax.plot([x0, x0 + largo], [y0, y0], color="black", lw=2, solid_capstyle="butt")
        ax.text(x0 + largo / 2, y0 + 0.025 * ancho, f"{largo} m", ha="center", fontsize=7, color="black",
                bbox=dict(fc="white", ec="none", alpha=0.7, pad=1))
        ax.annotate("N", xy=(bounds[2] - 0.06 * ancho, bounds[3] - 0.05 * ancho), ha="center", fontsize=9, weight="bold",
                    bbox=dict(fc="white", ec="none", alpha=0.7, pad=1))


def fig_croquis(geom, bounds, fondo, poi_m: gpd.GeoDataFrame, cauces: gpd.GeoDataFrame, ruta: Path):
    fig, ax = plt.subplots(figsize=(6.6, 5.2), dpi=170)
    dibujar_predio(ax, geom, bounds, fondo)
    for _, c in cauces.iterrows():
        for g in getattr(c.geometry, "geoms", [c.geometry]):
            x, y = g.xy
            ax.plot(x, y, color="#38bdf8", lw=1.6)
    for _, p in poi_m.iterrows():
        x, y = p.geometry.x, p.geometry.y
        if bounds[0] <= x <= bounds[2] and bounds[1] <= y <= bounds[3]:
            ax.scatter(x, y, s=150, c="white", edgecolors="#b91c1c", linewidths=1.4, zorder=5)
            ax.text(x, y, str(p.n), ha="center", va="center", fontsize=7, weight="bold", color="#b91c1c", zorder=6)
    fig.tight_layout(pad=0.2)
    fig.savefig(ruta, bbox_inches="tight", pad_inches=0.02, pil_kwargs={"quality": 85}); plt.close(fig)  # JPEG: foto aérea


def fig_serie(a: pd.DataFrame, ruta: Path):
    """NDVI y NDMI del predio frente al secano, en posiciones consecutivas (las temporadas quedan pegadas)."""
    a = a.reset_index(drop=True)
    i = np.arange(len(a))
    varias = a.temporada.nunique() > 1
    fig, axs = plt.subplots(2, 1, figsize=(7.2, 4.6), dpi=170, sharex=True)
    for ax, (col, nombre, color) in zip(axs, [("ndvi", "NDVI (verdor)", "#15803d"), ("ndmi", "NDMI (humedad)", "#1d4ed8")]):
        for j in np.flatnonzero(a.en_ventana.to_numpy()):
            ax.axvspan(j - 0.5, j + 0.5, color="#e5e7eb", lw=0)
        med, esc = a[f"ref_{col}_mediana"], a[f"ref_{col}_escala"]
        ax.fill_between(i, med - 2 * esc, med + 2 * esc, color="#a8a29e", alpha=0.35, lw=0, label="secano vecino (mediana ± 2 escalas)")
        ax.plot(i, med, color="#78716c", lw=1)
        ax.plot(i, a[col], color=color, lw=1, alpha=0.7)
        s = a.senal.to_numpy()
        ax.scatter(i[s], a.loc[s, col], s=16, color=color, zorder=3, label="con señal de riego")
        ax.scatter(i[~s], a.loc[~s, col], s=16, facecolors="white", edgecolors=color, zorder=3, label="sin señal")
        ax.set_ylabel(nombre, fontsize=8); ax.tick_params(labelsize=7); ax.grid(axis="y", lw=0.3, color="#d1d5db")
        for k in ("top", "right"):
            ax.spines[k].set_visible(False)
    axs[0].legend(fontsize=6.5, loc="lower left", ncol=3, frameon=False)
    if varias:
        for _, g in a.groupby("temporada"):
            for ax in axs:
                ax.axvline(g.index.min() - 0.5, color="#9ca3af", lw=0.5)
        cen = a.groupby("temporada").apply(lambda g: g.index.to_numpy().mean(), include_groups=False)
        axs[1].set_xticks(cen.to_numpy(), list(cen.index), fontsize=7)
        axs[1].set_xlabel("temporada seca (diciembre a marzo)", fontsize=7)
    else:
        paso = max(1, len(a) // 8)
        axs[1].set_xticks(i[::paso], [pd.Timestamp(f).strftime("%d-%m") for f in a.fecha[::paso]], fontsize=7)
    fig.tight_layout(pad=0.4)
    fig.savefig(ruta); plt.close(fig)


def fig_chip(geom, bounds, fondo, ruta: Path):
    fig, ax = plt.subplots(figsize=(3.4, 3.4), dpi=170)
    dibujar_predio(ax, geom, bounds, fondo, escala=False)
    fig.tight_layout(pad=0.1)
    fig.savefig(ruta); plt.close(fig)


# ---------- texto ----------
def motivos_txt(m) -> str:
    if not isinstance(m, str) or not m:
        return ""
    out = []
    for x in m.split(";"):
        base, _, det = x.partition("(")
        out.append(MOTIVOS.get(base, base.replace("_", " ")) + (f" ({det.rstrip(')')})" if det else ""))
    return "; ".join(out)


def hechos(p, r, a_t, cons, der, cauce, cultivo, fisc, todas, m5=None) -> tuple[list[str], dict]:
    t = r.temporada
    sen = a_t[a_t.senal]
    ref_ndvi = a_t.loc[a_t.estado == "ok", "ref_ndvi_mediana"].median()
    par, corto = [], {}
    if len(sen):
        par.append(f"Entre el {fecha(sen.fecha.min())} y el {fecha(sen.fecha.max())} (temporada seca {t}), {int(r.n_fechas_senal)} de "
                   f"{int(r.n_fechas_validas)} imágenes satelitales Sentinel-2 válidas, tomadas en períodos de al menos {DIAS_MIN} días sin "
                   f"lluvia, muestran el predio más verde y más húmedo que los terrenos de secano vecinos en la misma fecha (NDVI mediano "
                   f"{num(r.ndvi_mediana, 2)}, frente a {num(ref_ndvi, 2)} del secano). Sin lluvia, ese verdor es un indicio de riego.")
        corto["indicio"] = (f"Riego en período seco: señal en {int(r.n_fechas_senal)} de {int(r.n_fechas_validas)} imágenes válidas "
                            f"(temporada {t}, {fecha(sen.fecha.min())} a {fecha(sen.fecha.max())})")
    else:
        par.append(f"En la temporada seca {t}, ninguna de las {int(r.n_fechas_validas)} imágenes satelitales válidas muestra el predio "
                   f"claramente más verde y húmedo que el secano vecino. El análisis satelital no aporta indicios de riego en ese período.")
        corto["indicio"] = f"Sin señal de riego en la temporada {t} ({int(r.n_fechas_validas)} imágenes válidas)"
    if len(todas) > 1:
        con = todas[todas.senal_riego]
        par.append(f"La señal de riego se repite en {len(con)} de las {len(todas)} temporadas secas analizadas"
                   + (f" ({', '.join(con.temporada)})." if len(con) else "."))
    if cultivo is not None and bool(cultivo.get("con_frutales")):
        par.append(f"Según el Catastro Frutícola de CIREN (2025), el predio tiene {num(cultivo.area_fruticola_ha, 1)} ha plantadas, "
                   f"principalmente de {str(cultivo.especie_principal).lower()}.")
    else:
        par.append("El Catastro Frutícola de CIREN (2025) no registra frutales en el predio; el cultivo no está identificado.")
    if cons is not None:
        par.append(f"Con esa vegetación, el consumo de agua del cultivo se estima entre {redondo(cons.m3_temporada_min)} y "
                   f"{redondo(cons.m3_temporada_max)} m³ entre diciembre y marzo (del orden de {redondo(cons.m3_anual_min)} a "
                   f"{redondo(cons.m3_anual_max)} m³ al año), con el método FAO-56 simplificado. Es una estimación en rango, no una medición.")
        corto["consumo"] = (f"{redondo(cons.m3_temporada_min)}–{redondo(cons.m3_temporada_max)} m³ en dic–mar {t} "
                            f"({redondo(cons.m3_anual_min)}–{redondo(cons.m3_anual_max)} m³/año)")
    else:
        corto["consumo"] = "sin estimación para esta temporada"
    if m5 is not None and pd.notna(m5.m3_exceso_max) and m5.m3_exceso_max > 0:
        par.append(f"Sumando las pérdidas propias del riego (eficiencia de 75 % a 90 %), el agua que el predio necesitaría captar se estima "
                   f"entre {redondo(m5.m3_consumo_bruto_min)} y {redondo(m5.m3_consumo_bruto_max)} m³ al año. Descontados los derechos "
                   f"asignados al predio ({redondo(m5.m3_derecho_asignado)} m³/año), quedan entre {redondo(max(m5.m3_exceso_min, 0))} y "
                   f"{redondo(m5.m3_exceso_max)} m³ al año sin un derecho registrado que los respalde.")
    if der is not None:
        al = fecha(der.corte)
        if der.estado_derechos == "sin_derechos_cerca":
            par.append(f"En el registro público de derechos de aprovechamiento de la DGA no se encontraron derechos con punto de captación "
                       f"en el predio, en su rol ni a menos de 500 m (vigentes al {al}).")
            corto["derechos"] = "ninguno en el predio, su rol ni a 500 m"
        elif der.estado_derechos == "derechos_cerca_de_otro_rol":
            par.append(f"No se encontraron derechos de aprovechamiento con punto de captación en el predio ni en su rol (vigentes al {al}); "
                       f"a menos de 500 m hay {redondo(der.m3_anual_derecho_entorno_500m)} m³/año inscritos en otros roles.")
            corto["derechos"] = f"ninguno en el predio ni su rol; {redondo(der.m3_anual_derecho_entorno_500m)} m³/año en otros roles a 500 m"
        else:
            m3 = der.m3_anual_derecho_rol
            supera = cons is not None and cons.m3_anual_min > m3
            par.append(f"El rol tiene {redondo(m3)} m³/año de derechos inscritos (vigentes al {al}). "
                       + ("Incluso el mínimo del consumo estimado supera ese volumen." if supera else
                          "El consumo estimado no lo supera con claridad, así que la señal por sí sola no indica un exceso."))
            corto["derechos"] = f"{redondo(m3)} m³/año en el rol" + (" (menos que el consumo estimado)" if supera else "")
    else:
        corto["derechos"] = "sin cruce de derechos para este predio"
    fuentes = []
    if cauce is not None:
        if pd.notna(cauce.canal_nombre) and pd.notna(cauce.dist_canal_m) and cauce.dist_canal_m <= 300:
            org = f" ({cauce.canal_organizacion})" if pd.notna(cauce.canal_organizacion) else ""
            par.append(f"El predio está a {num(cauce.dist_canal_m)} m del canal {titulo(cauce.canal_nombre)}{org}. Si el riego proviene de "
                       f"acciones de ese canal, no aparecería en el registro de derechos consultado; conviene verificarlo.")
        if pd.notna(cauce.dist_canal_m):
            fuentes.append(f"canal {titulo(cauce.canal_nombre) if pd.notna(cauce.canal_nombre) else 'sin nombre'} a {num(cauce.dist_canal_m)} m")
        if pd.notna(cauce.dist_cauce_m):
            fuentes.append(f"{titulo(cauce.cauce_nombre)} a {num(cauce.dist_cauce_m)} m")
    corto["fuentes"] = "; ".join(fuentes) or "sin datos"
    ant = []
    for _, f in fisc.iterrows():
        multa = f", multa de {num(f.multa_utm, 1)} UTM" if pd.notna(f.multa_utm) and f.multa_utm > 0 else ""
        ant.append(f"{f.expediente} (inspección {fecha(f.fecha_inspeccion) if pd.notna(f.fecha_inspeccion) else 's/f'}: "
                   f"{str(f.decision).lower()}{multa})")
    if ant:
        par.append("La DGA registra fiscalizaciones previas por extracción de aguas en este predio: " + "; ".join(ant) + ".")
    corto["antecedentes"] = "; ".join(ant)
    if len(sen):
        par.append("Por lo anterior, se solicita a la Dirección General de Aguas evaluar si en el predio existe una extracción de aguas "
                   "sin derecho, eventual infracción al Código de Aguas.")
    else:
        par.append("Si usted tiene otros antecedentes de una extracción de aguas en este predio (fechas, observaciones, fotografías), "
                   "descríbalos aquí: el análisis satelital por sí solo no los aporta.")
    return par, corto


# ---------- principal ----------
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--predio-id", type=int, help="mslink CIREN (predio_id)")
    g.add_argument("--rol", help="COMUNA:ROL, p. ej. HIJUELAS:61-6")
    ap.add_argument("--temporada", help="temporada seca del borrador (p. ej. 2025-26); por defecto, la más reciente con datos")
    ap.add_argument("--fondo", choices=["wayback", "sentinel2", "ninguno"], default="wayback",
                    help="foto base del croquis: Esri World Imagery Wayback (por defecto), Sentinel-2 o sin fondo")
    ap.add_argument("--sin-imagenes", action="store_true", help="no bajar imágenes (croquis sin fondo, sin anexo A3)")
    ap.add_argument("--salida", default=str(PROC / "expedientes"))
    args = ap.parse_args()
    t0 = time.time()

    pg = predio_geom(args.predio_id, args.rol)
    pid = int(pg.predio_id.iloc[0])
    pm = pg.to_crs(CRS_M)
    geom = pm.geometry.iloc[0]
    cen = gpd.GeoSeries([geom.centroid], crs=CRS_M)
    cen_ll = cen.to_crs(4326).iloc[0]

    senal, f_senal = del_predio("senal_riego", pid, "temporada")
    anom, f_anom = del_predio("anomalias_predio", pid, "fecha")
    cons_t, f_cons = del_predio("consumo_predio", pid, "temporada", "_temporada")
    if senal.empty or anom.empty:
        sys.exit(f"El predio {pid} no tiene salidas de M2/M3 en ninguna serie ({', '.join(FAMILIAS)}): corre D1 y M2-M3 para él")
    t = args.temporada or senal[senal.n_fechas_validas > 0].temporada.max()
    if t not in set(senal.temporada):
        sys.exit(f"Sin datos de M3 para la temporada {t}; hay: {', '.join(senal.temporada)}")
    r = senal[senal.temporada == t].iloc[0]

    v = ventanas(pid, anom.fecha)
    anom = anom.merge(v, on="fecha", how="left")
    anom["en_ventana"] = anom.en_ventana.fillna(False).astype(bool) & (anom.dias_sin_lluvia >= DIAS_MIN)
    anom["senal"] = anom.en_ventana & (anom.estado == "ok") & (anom.z_verdor >= Z_UMBRAL) & (anom.z_humedad >= Z_UMBRAL)
    a_t = anom[anom.temporada == t]

    der_all = leer("predio_derecho")
    der_all = der_all[der_all.predio_id == pid]
    der = der_all[der_all.temporada == t].iloc[0] if (der_all.temporada == t).any() else None
    pc = leer("predio_cauce")
    cauce = pc[pc.predio_id == pid].iloc[0] if (pc.predio_id == pid).any() else None
    cu = leer("predio_cultivo")
    cultivo = cu[cu.predio_id == pid].iloc[0] if (cu.predio_id == pid).any() else None
    fi = leer("fiscalizacion")
    fisc = fi[(fi.predio_id == pid) & fi.etiqueta.isin(["positivo", "negativo"]) & fi.extraccion.fillna(False).astype(bool)]
    cons = cons_t[cons_t.temporada == t].iloc[0] if (not cons_t.empty and (cons_t.temporada == t).any()) else None
    poi = gpd.read_parquet(PROC / "poi.parquet")
    poi = poi[poi.predio_id == pid].reset_index(drop=True)
    poi["n"] = np.arange(1, len(poi) + 1)

    eid = f"CAU-{pid}-{datetime.now():%Y%m%d%H%M}"
    out = Path(args.salida) / eid
    out.mkdir(parents=True, exist_ok=True)

    # Imágenes: la escena más despejada y reciente de la temporada (croquis) y la primera y última temporadas (antes y después)
    bounds = marco(geom)
    ok = anom[(anom.estado == "ok")].sort_values(["nubosidad_pct", "fecha"], ascending=[True, False])
    escena_croquis = ok[ok.temporada == t].escena_id.iloc[0] if (ok.temporada == t).any() else None
    pares = []
    if anom.temporada.nunique() > 1:
        for tt in (anom.temporada.min(), anom.temporada.max()):
            e = ok[ok.temporada == tt]
            if len(e):
                pares.append((tt, e.iloc[0]))
    items = {}
    if not args.sin_imagenes:
        try:
            from pystac_client import Client
            ids = sorted({x for x in [escena_croquis] + [e.escena_id for _, e in pares] if x})
            items = {i.id: i for i in Client.open(STAC).search(collections=["sentinel-2-l2a"], ids=ids).items()}
        except Exception as e:
            print(f"  aviso: sin acceso a Earth Search ({e}); el expediente sale sin imágenes", file=sys.stderr)
    fondo, fondo_txt = None, None
    if not args.sin_imagenes and args.fondo == "wayback":
        try:
            fondo, wb = fondo_wayback(bounds)
        except Exception as e:
            print(f"  aviso: sin Esri Wayback ({e}); el croquis usa Sentinel-2", file=sys.stderr)
        if fondo is not None:
            cap = f", foto del {wb['captura']}" if wb.get("captura") else ""
            prov = f" ({wb['proveedor']}{', ' + num(wb['resolucion'], 2) + ' m' if wb.get('resolucion') else ''})" if wb.get("proveedor") else ""
            fondo_txt = (f"Esri World Imagery Wayback, versión {wb['version']}{cap}{prov}. "
                         f"Fuentes: Esri{', ' + wb['proveedor'] if wb.get('proveedor') else ''}, Earthstar Geographics y la comunidad de usuarios de GIS.")
    if fondo is None and not args.sin_imagenes and args.fondo != "ninguno" and escena_croquis:
        fondo = chip_s2(escena_croquis, bounds, items)
        if fondo is not None:
            fondo_txt = f"Sentinel-2 color natural, escena {escena_croquis}."

    cauces = gpd.read_parquet(PROC / "cauce.parquet").to_crs(CRS_M)
    caja = gpd.GeoSeries.from_xy([bounds[0], bounds[2]], [bounds[1], bounds[3]], crs=CRS_M).total_bounds
    cauces = cauces.cx[caja[0]:caja[2], caja[1]:caja[3]]
    fig_croquis(geom, bounds, fondo, poi.to_crs(CRS_M), cauces, out / "croquis.jpg")
    fig_serie(anom.sort_values("fecha"), out / "serie.png")
    imagenes = []
    for tt, e in pares:
        ch = chip_s2(e.escena_id, bounds, items)
        if ch is not None:
            nombre = f"imagen_{tt}.png"
            fig_chip(geom, bounds, ch, out / nombre)
            imagenes.append({"src": nombre, "titulo": f"Temporada {tt}: {fecha(e.fecha)}, NDVI {num(e.ndvi, 2)} (escena {e.escena_id})"})

    m5, n_zona, f_m5 = puntaje_m5(pid, t)
    parrafos, corto = hechos(pg.iloc[0], r, a_t, cons, der, cauce, cultivo, fisc, senal, m5)
    if m5 is not None:
        puesto = f" · puesto {int(m5.rank_zona)} de {num(n_zona)} predios de {m5.zona}" if n_zona else ""
        indice = {"banda": BANDA.get(m5.banda, m5.banda), "puntaje": num(m5.puntaje, 0), "puesto": puesto,
                  "confianza": m5.confianza, "motivos_txt": motivos_txt(m5.motivos),
                  "exceso": f"{redondo(max(m5.m3_exceso_min, 0))}–{redondo(m5.m3_exceso_max)} m³/año"
                            if pd.notna(m5.m3_exceso_max) and m5.m3_exceso_max > 0 else "sin exceso estimado"}
    else:
        indice = None

    utm = cen.iloc[0]
    comuna = str(pg.comuna.iloc[0]).upper()
    ctx = {
        "p": {"predio_id": pid, "rol": pg.rol.iloc[0], "comuna_t": titulo(comuna), "provincia": PROVINCIA.get(comuna, "s/d"),
              "area_ha_txt": num(geom.area / 1e4, 1), "sector": "Por completar (no está en las fuentes usadas)",
              "lat_txt": f"{cen_ll.y:.5f}", "lon_txt": f"{cen_ll.x:.5f}", "utm_e": num(utm.x), "utm_n": num(utm.y)},
        "e": {"id": eid, "version": VERSION, "fecha_txt": f"{datetime.now():%d-%m-%Y %H:%M}", "hash": ""},
        "r": {"confianza": r.confianza, "motivos_txt": motivos_txt(r.motivos_confianza), "pix": num(r.pix_mediana),
              "nublado": f"{num(100 * r.frac_nublado)} %",
              "ref_txt": (f"polígonos de matorral y pradera estables de CONAF (D11), hasta 30 por fecha a {num(a_t.ref_dist_km.median(), 1)} km "
                          f"de mediana" if r.referencia == "conaf" else "provisional (no es secano real)")},
        "m5": indice,
        "h": {"hechos": parrafos, "indicio": corto["indicio"], "consumo_corto": corto["consumo"],
              "derechos_corto": corto["derechos"], "fuentes_corto": corto["fuentes"], "antecedentes": corto["antecedentes"]},
        "c": {"cauce_txt": (f"{titulo(cauce.cauce_nombre)} ({str(cauce.cauce_tipo).lower()}), a {num(cauce.dist_cauce_m)} m"
                            + (f"; río más cercano: {titulo(cauce.rio_nombre)}, a {num(cauce.dist_rio_m)} m"
                               if pd.notna(cauce.rio_nombre) and cauce.rio_nombre != cauce.cauce_nombre else "")) if cauce is not None else "s/d",
              "canal_txt": (f"{titulo(cauce.canal_nombre) if pd.notna(cauce.canal_nombre) else 'Sin nombre'}"
                            + (f" ({cauce.canal_organizacion})" if pd.notna(cauce.canal_organizacion) else "")
                            + f", a {num(cauce.dist_canal_m)} m") if cauce is not None and pd.notna(cauce.dist_canal_m) else "s/d"},
        "figs": {"croquis": "croquis.jpg", "serie": "serie.png", "imagenes": imagenes,
                 "croquis_fondo": fondo_txt},
        "poi": [{"n": x.n, "tipo": TIPO_POI.get(x.tipo, x.tipo), "razon": x.razon, "coord": f"{x.lat:.5f}, {x.lon:.5f}",
                 "confianza": num(x.confianza, 2)} for x in poi.itertuples()],
        "temporadas": [{"temporada": x.temporada, "n_validas": int(x.n_fechas_validas), "n_senal": int(x.n_fechas_senal),
                        "frac": f"{num(100 * x.frac_senal)} %" if pd.notna(x.frac_senal) else "s/d", "zv": num(x.z_verdor_mediana, 1),
                        "zh": num(x.z_humedad_mediana, 1), "ndvi": num(x.ndvi_mediana, 2), "confianza": x.confianza}
                       for x in senal.itertuples()],
        "consumo": [], "m": {"supuestos": cons.supuestos.replace(";", "; ") if cons is not None and isinstance(cons.get("supuestos"), str) else ""},
    }
    for x in cons_t.itertuples() if not cons_t.empty else []:
        d = der_all[der_all.temporada == x.temporada]
        d = d.iloc[0] if len(d) else None
        ctx["consumo"].append({
            "temporada": x.temporada,
            "temp": f"{redondo(x.m3_temporada_min)}–{redondo(x.m3_temporada_max)} ({redondo(x.m3_temporada_central)})",
            "anual": f"{redondo(x.m3_anual_min)}–{redondo(x.m3_anual_max)}",
            "der_rol": redondo(d.m3_anual_derecho_rol) if d is not None else "s/d",
            "der_entorno": redondo(d.m3_anual_derecho_entorno_500m) if d is not None else "s/d",
            "estado": ESTADO_DER.get(d.estado_derechos, str(d.estado_derechos)) if d is not None else "s/d"})

    insumos = {"Señal de riego (M3)": f_senal, "Anomalías (M2)": f_anom, "Consumo (M4)": f_cons}
    if f_m5 is not None:
        insumos["Índice de sospecha (M5)"] = [f_m5]
    fijos = [("Derechos por predio (D5)", "DGA, derechos registrados", "predio_derecho"),
             ("Cauce y canal cercanos (D8)", "DGA red de drenajes; CNR y CIREN canales", "predio_cauce"),
             ("Puntos de interés (M10)", "Caudal", "poi"), ("Frutales (D7)", "CIREN Catastro Frutícola 2025", "predio_cultivo"),
             ("Fiscalizaciones (D6)", "DGA, planilla de fiscalización", "fiscalizacion"),
             ("Ventanas secas (M1)", "Open-Meteo y estaciones", "ventana_seca"), ("Cauces (D8)", "DGA red de drenajes", "cauce")]
    fuentes, rutas = [], []
    for dato, ps in insumos.items():  # una fila por dato, con todas las series donde se buscó el predio
        if ps:
            fuentes.append({"dato": dato, "fuente": {"M4": "Sentinel-2 y Open-Meteo", "M5": "M3, M4 y derechos DGA"}.get(dato[-3:-1],
                                                                                                 "Sentinel-2 L2A y secano CONAF (D11)"),
                            "archivo": ", ".join(p.name for p in ps), "version": ", ".join(sorted({version_de(p) for p in ps}))})
            rutas += ps
    for dato, fuente, nombre in fijos:
        p = PROC / f"{nombre}.parquet"
        fuentes.append({"dato": dato, "fuente": fuente, "archivo": p.name, "version": version_de(p)})
        rutas.append(p)
    gp = PROC / "predio.parquet" if (PROC / "predio.parquet").exists() else PROC / "predio_muestra.geojson"
    fuentes.append({"dato": "Polígono del predio (D3)", "fuente": "CIREN Propiedades Rurales", "archivo": gp.name, "version": version_de(gp)})
    rutas.append(gp)
    huella = hashlib.sha256("".join(sha(p) for p in rutas).encode()).hexdigest()[:12]
    ctx["e"]["hash"] = huella
    ctx["fuentes"] = fuentes

    env = Environment(loader=FileSystemLoader(PLANTILLAS), autoescape=select_autoescape(["html", "j2"]))
    html = env.get_template("expediente.html.j2").render(**ctx)
    (out / "expediente.html").write_text(html, encoding="utf-8")
    from weasyprint import HTML
    HTML(string=html, base_url=str(out)).write_pdf(out / "expediente.pdf")

    reg = Path(args.salida) / "registro.csv"
    pdf = (out / "expediente.pdf").resolve()
    ruta_pdf = str(mostrar(pdf))
    fila = pd.DataFrame([{"id": eid, "predio_id": pid, "rol": f"{comuna}:{pg.rol.iloc[0]}", "temporada": t, "confianza": r.confianza,
                          "banda_m5": m5.banda if m5 is not None else "", "puntaje_m5": m5.puntaje if m5 is not None else None,
                          "version": VERSION, "hash_insumos": huella, "ruta_pdf": ruta_pdf,
                          "fecha_creacion": datetime.now().isoformat(timespec="seconds")}])
    if reg.exists():  # se reescribe entero: si cambian las columnas, las filas antiguas quedan vacías en las nuevas
        fila = pd.concat([pd.read_csv(reg), fila], ignore_index=True)
    fila.to_csv(reg, index=False)
    print(f"{eid}: {comuna}:{pg.rol.iloc[0]}, temporada {t}, confianza {r.confianza}, "
          f"M5 {('banda ' + m5.banda + ' ' + num(m5.puntaje)) if m5 is not None else 'sin puntaje'}, {len(poi)} POI, "
          f"{'con' if fondo is not None else 'sin'} imagen -> {out / 'expediente.pdf'} ({time.time() - t0:.1f} s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
