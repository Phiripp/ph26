# /// script
# requires-python = ">=3.11"
# dependencies = ["geopandas>=1.0", "pandas", "pyarrow", "numpy", "scipy"]
# ///
"""Anomalías de verdor y humedad por predio y fecha frente a la referencia de secano (tarea M2).

z_verdor = (ndvi - mediana_ref) / escala_ref y z_humedad = lo mismo con ndmi, donde la referencia son los
polígonos de secano (matorral y pradera estables de CONAF, D11) más cercanos al predio, en la MISMA fecha
(misma pasada de Sentinel-2: se cancelan la fenología, la atmósfera y el calendario de la temporada).

Entradas (rutas relativas a la raíz del repo):
- --serie: serie de predios de D1 (por defecto data/processed/serie_predio_temporada_2025-26.parquet).
  Sirve igual serie_predio_validacion.parquet o serie_predio_elegibles_2025-26.parquet.
- --referencia: serie de los polígonos de secano de D1 --referencia (por defecto data/processed/serie_referencia.parquet;
  su predio_id es el ref_id) y --referencia-geom: data/processed/referencia_secano.parquet (geometrías y clase).
- Geometrías de los predios: data/processed/predio.parquet (local, no va a git); si no está, predio_muestra.geojson.

Salida: data/processed/anomalias_predio.parquet (o --salida), una fila por (predio_id, fecha):
predio_id, zona, fecha, escena_id, temporada (jul-jun: dic-2025 a mar-2026 = "2025-26"), ndvi, ndmi, nubosidad_pct,
n_pix_validos, n_pix_total, estado, ref_n, ref_dist_km (distancia al más lejano usado), ref_ndvi_mediana,
ref_ndvi_escala, ref_ndmi_mediana, ref_ndmi_escala, z_verdor, z_humedad, referencia ("conaf" o "provisional").

Reglas:
- Una observación (predio o referencia) es válida si tiene índice, nubosidad_pct <= --nubosidad-max (30 %) y al menos
  --min-pix píxeles válidos (10 = 0,4 ha a 20 m). Si un predio cae en dos tiles el mismo día, se usa la escena con más
  píxeles válidos.
- Referencia de cada predio: polígonos de secano con centroide a --radio-km (10 km) o menos del centroide del predio
  (EPSG:32719), ordenados por distancia; en cada fecha se usan los --k (30) más cercanos que tengan observación
  válida ese día. Por qué: 10 km mantiene el mismo valle y régimen de clima (la costa y el interior difieren), y 30
  polígonos dan una mediana y un MAD estables aunque parte de la referencia esté nublada.
- Estadístico robusto: mediana y escala = max(1,4826 * MAD, --escala-min). La escala mínima (0,05 en NDVI y en NDMI)
  evita z enormes cuando la referencia es muy homogénea (pradera seca toda en 0,20): con umbral z = 2, exige al menos
  0,10 de diferencia, por debajo de lo cual una diferencia de NDVI no es evidencia de riego. Mediana y MAD en vez de
  media y desviación: algunos polígonos de matorral arborescente son mucho más verdes que la pradera seca.
- Si ese día hay menos de --min-ref (8) referencias válidas, z queda NaN y estado = "sin_referencia" (M3 baja la
  confianza). Otros estados: "ok" y "nublado" (la observación del predio no es válida).
- Probado con la referencia CONAF real de diciembre de 2019 en Z1 (caché de D1 --referencia, 2.899 polígonos): la
  mediana del secano fue NDVI 0,16 y NDMI -0,19, con 30 referencias a 4 km de mediana (máximo usado 9,8 km). El
  secano de verano es tan homogéneo (MAD ~0,02) que la escala mínima manda en casi todas las fechas: en la práctica
  z = (índice - mediana del secano) / 0,05. Por eso --escala-min es tan importante como el umbral de M3.
- --clases limita las clases de referencia (por defecto todas). Es una perilla para M7: el matorral arborescente
  es siempreverde y sube la mediana de la referencia.

Referencia provisional (--referencia-provisional): mientras no exista serie_referencia.parquet. NO es secano real:
toma como pseudo-secano los predios de la misma --serie cuya mediana de NDVI en la serie es < 0,30 (suelo desnudo,
pradera seca o abandonados), excluye al propio predio de su referencia, y usa toda la zona (radio 60 km, k 15,
min-ref 4) porque la muestra es chica. Es circular y está sesgada hacia abajo (el suelo desnudo es más oscuro que el
matorral): sirve para probar el formato y el código, no para calibrar umbrales. Las filas quedan con
referencia = "provisional".

Uso:
  uv run scripts/models/anomalias.py --referencia-provisional          # muestra, referencia provisional
  uv run scripts/models/anomalias.py --serie data/processed/serie_predio_elegibles_2025-26.parquet \\
      --referencia data/processed/serie_referencia.parquet             # con la referencia real (D1 --referencia)
"""

import argparse
import sys
import warnings
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from comun.rutas import PROC, RAIZ  # noqa: E402

CRS_M = "EPSG:32719"
MAD_A_SIGMA = 1.4826
NDVI_PSEUDO_SECANO = 0.30
PROVISIONAL = {"radio_km": 60.0, "k": 15, "min_ref": 4}
INDICES = {"ndvi": "z_verdor", "ndmi": "z_humedad"}


def ruta(p: str) -> Path:
    q = Path(p)
    return q if q.is_absolute() else RAIZ / q


def temporada(fecha: pd.Series) -> pd.Series:
    """Temporada de julio a junio: diciembre de 2025 a marzo de 2026 -> '2025-26'."""
    y = fecha.dt.year - (fecha.dt.month < 7).astype(int)
    return y.astype(str) + "-" + ((y + 1) % 100).astype(str).str.zfill(2)


def leer_serie(p: Path) -> pd.DataFrame:
    s = pd.read_parquet(p)
    s["fecha"] = pd.to_datetime(s["fecha"]).dt.normalize()
    # Un predio en dos tiles el mismo día: la escena con más píxeles válidos.
    s = s.sort_values("n_pix_validos", ascending=False).drop_duplicates(["predio_id", "fecha"])
    return s.sort_values(["predio_id", "fecha"]).reset_index(drop=True)


def valida(s: pd.DataFrame, args) -> pd.Series:
    return s["ndvi"].notna() & s["ndmi"].notna() & (s["nubosidad_pct"] <= args.nubosidad_max) & (
        s["n_pix_validos"] >= args.min_pix)


def centroides(ids: np.ndarray, geom: gpd.GeoDataFrame, col: str) -> np.ndarray:
    g = geom[geom[col].isin(ids)].to_crs(CRS_M).set_index(col).reindex(ids)
    faltan = g.geometry.isna().sum()
    if faltan:
        print(f"  aviso: {faltan} polígonos sin geometría quedan sin referencia")
    c = g.geometry.centroid
    return np.column_stack([c.x.to_numpy(), c.y.to_numpy()])


def geom_predios() -> gpd.GeoDataFrame:
    if (PROC / "predio.parquet").exists():
        return gpd.read_parquet(PROC / "predio.parquet", columns=["predio_id", "geometry"])
    print("  predio.parquet no está; uso predio_muestra.geojson")
    return gpd.read_file(PROC / "predio_muestra.geojson")[["predio_id", "geometry"]]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--serie", default="data/processed/serie_predio_temporada_2025-26.parquet")
    ap.add_argument("--referencia", default="data/processed/serie_referencia.parquet")
    ap.add_argument("--referencia-geom", default="data/processed/referencia_secano.parquet")
    ap.add_argument("--referencia-provisional", action="store_true",
                    help="pseudo-secano desde la misma serie (solo para probar formato; ver docstring)")
    ap.add_argument("--salida", default="data/processed/anomalias_predio.parquet")
    ap.add_argument("--radio-km", type=float, default=None, help="radio de búsqueda de referencias (10; provisional 60)")
    ap.add_argument("--k", type=int, default=None, help="referencias válidas por fecha (30; provisional 15)")
    ap.add_argument("--min-ref", type=int, default=None, help="mínimo de referencias válidas (8; provisional 4)")
    ap.add_argument("--nubosidad-max", type=float, default=30.0, help="%% máximo de píxeles nublados del polígono")
    ap.add_argument("--min-pix", type=int, default=10, help="píxeles válidos mínimos de una observación")
    ap.add_argument("--escala-min", type=float, default=0.05, help="piso de la escala robusta (NDVI y NDMI)")
    ap.add_argument("--clases", nargs="*", default=None, help="clases de referencia_secano a usar (todas si se omite)")
    args = ap.parse_args()
    prov = args.referencia_provisional
    base = PROVISIONAL if prov else {"radio_km": 10.0, "k": 30, "min_ref": 8}
    for k, v in base.items():
        if getattr(args, k) is None:
            setattr(args, k, v)

    s = leer_serie(ruta(args.serie))
    s["valida"] = valida(s, args)
    print(f"Serie {args.serie}: {s.predio_id.nunique()} predios, {s.fecha.nunique()} fechas, "
          f"{s.valida.mean():.0%} de observaciones válidas")
    gp = geom_predios()

    if prov:
        etiqueta = "provisional"
        med = s[s.valida].groupby("predio_id")["ndvi"].median()
        ref_ids = med[med < NDVI_PSEUDO_SECANO].index
        r = s[s.predio_id.isin(ref_ids)].copy()
        rgeom, rcol = gp, "predio_id"
        print(f"REFERENCIA PROVISIONAL (no es secano real): {len(ref_ids)} predios de la serie con NDVI mediano "
              f"< {NDVI_PSEUDO_SECANO}: {r.groupby('zona').predio_id.nunique().to_dict()}")
    else:
        etiqueta = "conaf"
        p = ruta(args.referencia)
        if not p.exists():
            print(f"No existe {p}. Corre D1 --referencia o usa --referencia-provisional.")
            return 1
        r = leer_serie(p)
        rgeom = gpd.read_parquet(ruta(args.referencia_geom))
        rcol = "ref_id"
        if args.clases:
            r = r[r.predio_id.isin(rgeom.loc[rgeom.clase.isin(args.clases), "ref_id"])]
        print(f"Referencia {args.referencia}: {r.predio_id.nunique()} polígonos, clases {args.clases or 'todas'}")
    r["valida"] = valida(r, args)
    r = r[r.valida]

    # Matrices referencia x fecha (NaN donde no hay observación válida).
    fechas = np.array(sorted(set(s.fecha) | set(r.fecha)), dtype="datetime64[ns]")
    ids_r = np.sort(r.predio_id.unique())
    mat = {}
    for col in INDICES:
        piv = r.pivot(index="predio_id", columns="fecha", values=col).reindex(index=ids_r, columns=fechas)
        mat[col] = piv.to_numpy(dtype=float)
    xy_r = centroides(ids_r, rgeom, rcol)
    ok_r = ~np.isnan(xy_r).any(axis=1)
    arbol = cKDTree(xy_r[ok_r])
    idx_ok = np.flatnonzero(ok_r)

    ids_p = s.predio_id.unique()
    xy_p = dict(zip(ids_p, centroides(ids_p, gp, "predio_id")))
    pos_fecha = {f: i for i, f in enumerate(fechas)}
    out_cols = ["ref_n", "ref_dist_km"] + [f"ref_{c}_{e}" for c in INDICES for e in ("mediana", "escala")]
    res = np.full((len(s), len(out_cols)), np.nan)

    for pid, g in s.groupby("predio_id"):
        xy = xy_p[pid]
        if np.isnan(xy).any():
            continue
        cand = idx_ok[arbol.query_ball_point(xy, args.radio_km * 1000)]
        if prov:
            cand = cand[ids_r[cand] != pid]
        if len(cand) == 0:
            res[g.index, 0] = 0
            continue
        dist = np.hypot(*(xy_r[cand] - xy).T)
        orden = np.argsort(dist)
        cand, dist = cand[orden], dist[orden]
        cols = np.array([pos_fecha[f] for f in g.fecha.to_numpy(dtype="datetime64[ns]")])
        v = {c: mat[c][np.ix_(cand, cols)] for c in INDICES}           # cand x fechas del predio
        hay = ~np.isnan(v["ndvi"]) & ~np.isnan(v["ndmi"])
        usa = hay & (np.cumsum(hay, axis=0) <= args.k)                  # las k más cercanas con dato ese día
        n = usa.sum(axis=0)
        res[g.index, 0] = n
        with np.errstate(all="ignore"), warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)  # fechas sin referencia: nanmedian de puros NaN
            res[g.index, 1] = np.where(n > 0, np.max(np.where(usa, dist[:, None], 0), axis=0) / 1000, np.nan)
            for j, c in enumerate(INDICES):
                x = np.where(usa, v[c], np.nan)
                m = np.nanmedian(x, axis=0)
                mad = np.nanmedian(np.abs(x - m), axis=0)
                res[g.index, 2 + 2 * j] = m
                res[g.index, 3 + 2 * j] = np.maximum(MAD_A_SIGMA * mad, args.escala_min)

    a = pd.concat([s, pd.DataFrame(res, columns=out_cols, index=s.index)], axis=1)
    a["ref_n"] = a["ref_n"].fillna(0).astype(int)
    con_ref = a.ref_n >= args.min_ref
    a["estado"] = np.where(~a.valida, "nublado", np.where(con_ref, "ok", "sin_referencia"))
    for c, z in INDICES.items():
        a[z] = np.where(a.estado == "ok", (a[c] - a[f"ref_{c}_mediana"]) / a[f"ref_{c}_escala"], np.nan)
    a["temporada"] = temporada(a["fecha"])
    a["referencia"] = etiqueta
    cols = ["predio_id", "zona", "fecha", "escena_id", "temporada", "ndvi", "ndmi", "nubosidad_pct", "n_pix_validos",
            "n_pix_total", "estado", *out_cols, "z_verdor", "z_humedad", "referencia"]
    a = a[cols]
    a.to_parquet(ruta(args.salida), index=False)

    print(f"radio {args.radio_km} km, k {args.k}, min-ref {args.min_ref}, escala mínima {args.escala_min}")
    print(f"-> {args.salida}: {len(a)} filas")
    print(a.groupby("zona").estado.value_counts().unstack(fill_value=0).to_string())
    print("\nz por zona (observaciones ok):")
    print(a[a.estado == "ok"].groupby("zona")[["z_verdor", "z_humedad"]].describe(
        percentiles=[.1, .5, .9]).round(2).T.to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
