# /// script
# requires-python = ">=3.11"
# dependencies = ["pandas", "pyarrow", "geopandas", "shapely", "ortools"]
# ///
"""Ruta de inspección de una jornada con OR-Tools y OSRM (tarea M8).

Problema: "prize-collecting TSP". Un vehículo sale del punto de inicio y vuelve a él. Cada predio es una parada
opcional (disjunction de OR-Tools) con una penalización proporcional a su puntaje si se deja fuera. La jornada
limita el tiempo total: manejo + `min_por_visita` en cada parada + vuelta al inicio.

Reglas:
- Destino de cada predio: su punto representativo (`representative_point`, siempre dentro del polígono). OSRM lo
  lleva al camino más cercano; ese punto es el `acceso` y su distancia al predio es `dist_camino_m`.
- Penalización = puntaje / puntaje_max x 100 x jornada (s). Saltarse el predio de puntaje máximo cuesta más que
  100 jornadas de manejo: el solver primero maximiza el puntaje visitado y después minimiza el tiempo. No garantiza
  que todo predio fuera tenga menos puntaje que todo predio visitado (dos predios medianos cercanos pueden valer más
  que uno alto y lejano), pero sí maximiza la suma de puntajes que cabe en la jornada.
- Tiempos y km entre paradas: matriz `/table` de OSRM (perfil auto). Trazado de la ruta: `/route` de OSRM. Las
  horas de llegada salen de la matriz, que es lo que usó el solver.
- Motivos de los predios fuera: `fuera_de_alcance` (ida + visita + vuelta no caben en la jornada ni solos),
  `sin_ruta` (OSRM no encuentra camino), `tope_de_paradas` (la ruta ya tiene `--max-paradas` predios) y
  `no_cabe_en_jornada` (el resto).
- Tope de paradas (`--max-paradas`, opcional): la ruta visita a lo más esa cantidad de predios, aunque quepan
  más en la jornada. El solver elige cuáles con la misma regla (primero puntaje, después tiempo).
- Puntos de inicio por defecto: plaza de armas de la capital provincial de cada zona (ver INICIOS).

OSRM: servidor público (router.project-osrm.org, datos de OpenStreetMap), decisión D9. Cada respuesta se guarda
en data/raw/osrm/<servicio>_<sha1 de la URL>.json y se reusa: la misma lista de coordenadas no se consulta dos
veces. Se respeta ~1 consulta/s y se reintenta 3 veces ante errores de red. La demo no llama a OSRM: sirve las
rutas ya guardadas en data/processed/.

Entradas:
- data/processed/predio.parquet (predio_id, zona, geometry EPSG:4326).
- --puntajes: CSV o Parquet con predio_id, puntaje (salida de M5). Se toman los `--top` de mayor puntaje de la zona.
- --demo (mientras M5 no exista): positivos limpios de data/processed/fiscalizacion.parquet más los predios de
  data/casos_validacion.geojson, todos con puntaje 1.

Salidas en data/processed/ (prefijo `ruta_<zona>`, o `ruta_ejemplo_<zona>` con --demo):
- <prefijo>.json: resultado de `ruta()`: paradas en orden con hora de llegada, totales y predios fuera.
- <prefijo>.geojson: línea de la ruta, punto de inicio, paradas (visitado=true, con orden) y predios fuera.
- <prefijo>.gpx: GPX 1.1 con waypoints de las paradas, la ruta (rte) en orden y el trazado (trk).

Uso desde el backend:
    from scripts.models.ruta_inspeccion import ruta, a_geojson, a_gpx
    r = ruta(df[["predio_id", "puntaje", "lon", "lat"]], inicio=(-71.2316, -32.4494), hora_inicio="08:30")

Uso: uv run scripts/models/ruta_inspeccion.py --zona Z1 --demo [--jornada-h 8] [--min-visita 30] [--hora 08:30]
         [--max-paradas 5]
     uv run scripts/models/ruta_inspeccion.py --zona Z2 --puntajes data/processed/puntaje.parquet [--top 40]
"""

import argparse
import hashlib
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from xml.sax.saxutils import escape

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from comun.rutas import DATA, PROC  # noqa: E402

CACHE_OSRM = DATA / "raw" / "osrm"
OSRM = "https://router.project-osrm.org"
MAX_TABLA = 100  # límite de puntos por /table en el servidor público

# Plaza de armas de la capital provincial: punto de partida neutro, conocido y con acceso por calle.
INICIOS = {
    "Z1": {"nombre": "Plaza de Armas de La Ligua", "lon": -71.2316, "lat": -32.4494},
    "Z2": {"nombre": "Plaza de Armas de Quillota", "lon": -71.2474, "lat": -32.8800},
}


# --------------------------------------------------------------------------------------------- OSRM

class ErrorOSRM(RuntimeError):
    pass


_ultima_consulta = 0.0


def _coords(puntos) -> str:
    return ";".join(f"{lon:.6f},{lat:.6f}" for lon, lat in puntos)


def osrm_get(servicio: str, puntos, params: str, cache: Path = CACHE_OSRM, reintentos: int = 3) -> dict:
    """GET a OSRM con caché en disco por URL (servicio + coordenadas + parámetros) y ~1 consulta/s."""
    global _ultima_consulta
    url = f"{OSRM}/{servicio}/v1/driving/{_coords(puntos)}?{params}"
    archivo = cache / f"{servicio}_{hashlib.sha1(url.encode()).hexdigest()[:16]}.json"
    if archivo.exists():
        return json.loads(archivo.read_text())
    ultimo_error = None
    for intento in range(reintentos):
        espera = 1.0 - (time.monotonic() - _ultima_consulta)
        if espera > 0:
            time.sleep(espera)
        _ultima_consulta = time.monotonic()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "caudal-hackathon/0.1"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read())
            if data.get("code") != "Ok":
                raise ErrorOSRM(f"OSRM respondió {data.get('code')}: {data.get('message')}")
            cache.mkdir(parents=True, exist_ok=True)
            archivo.write_text(json.dumps({**data, "_url": url}))
            return data
        except urllib.error.HTTPError as e:
            ultimo_error = f"HTTP {e.code}: {e.read()[:200].decode(errors='replace')}"
            if 400 <= e.code < 500 and e.code != 429:
                break  # consulta mal formada: reintentar no sirve
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            ultimo_error = repr(e)
        time.sleep(2 * (intento + 1) * (5 if "429" in str(ultimo_error) else 1))
    raise ErrorOSRM(
        f"No se pudo consultar OSRM {servicio} tras {reintentos} intentos ({ultimo_error}). "
        f"URL: {url[:200]}. Sin red, la demo debe usar las rutas ya guardadas en data/processed/ruta_*."
    )


def osrm_tabla(puntos, **kw) -> dict:
    """Matriz de duraciones (s) y distancias (m) entre todos los puntos [(lon, lat), ...]."""
    if len(puntos) > MAX_TABLA:
        raise ValueError(f"{len(puntos)} puntos: el servidor público de OSRM acepta hasta {MAX_TABLA} por /table")
    return osrm_get("table", puntos, "annotations=duration,distance", **kw)


def osrm_trazado(puntos, **kw) -> dict:
    """Ruta por los puntos en ese orden, con geometría GeoJSON completa."""
    return osrm_get("route", puntos, "overview=full&geometries=geojson", **kw)


# ------------------------------------------------------------------------------------------ solver

def resolver(duracion: list[list[int]], penalizacion: list[int], servicio_s: int, jornada_s: int,
             limite_s: int = 5, max_paradas: int | None = None) -> list[int]:
    """Prize-collecting TSP. Nodo 0 = inicio; devuelve los nodos visitados en orden (sin el 0).

    duracion: matriz (n+1)x(n+1) en segundos; penalizacion[i] se paga si el nodo i (1..n) queda fuera
    (penalizacion[0] se ignora). El tiempo acumulado (manejo + servicio_s por parada) no supera jornada_s.
    max_paradas: si se indica, la ruta visita a lo más esa cantidad de nodos.
    """
    if max_paradas is not None and max_paradas < 1:
        raise ValueError(f"max_paradas debe ser 1 o más (llegó {max_paradas})")
    from ortools.constraint_solver import pywrapcp, routing_enums_pb2

    n = len(duracion)
    manager = pywrapcp.RoutingIndexManager(n, 1, 0)
    routing = pywrapcp.RoutingModel(manager)

    def transito(i, j):
        a, b = manager.IndexToNode(i), manager.IndexToNode(j)
        return duracion[a][b] + (servicio_s if a != 0 else 0)

    cb = routing.RegisterTransitCallback(transito)
    routing.SetArcCostEvaluatorOfAllVehicles(cb)
    routing.AddDimension(cb, 0, jornada_s, True, "tiempo")
    if max_paradas is not None:
        # cada predio visitado suma 1; el inicio no cuenta
        cuenta = routing.RegisterUnaryTransitCallback(lambda i: 0 if manager.IndexToNode(i) == 0 else 1)
        routing.AddDimension(cuenta, 0, int(max_paradas), True, "paradas")
    for nodo in range(1, n):
        routing.AddDisjunction([manager.NodeToIndex(nodo)], int(penalizacion[nodo]))

    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    params.time_limit.FromSeconds(limite_s)
    sol = routing.SolveWithParameters(params)
    if sol is None:
        return []
    orden, i = [], routing.Start(0)
    while not routing.IsEnd(i):
        nodo = manager.IndexToNode(i)
        if nodo != 0:
            orden.append(nodo)
        i = sol.Value(routing.NextVar(i))
    return orden


# -------------------------------------------------------------------------------------------- ruta

def _hora(h) -> datetime:
    """Hora de inicio como datetime; la fecha no se usa (las salidas son HH:MM)."""
    if isinstance(h, datetime):
        return h
    if not hasattr(h, "hour"):  # "HH:MM"
        h = datetime.strptime(str(h), "%H:%M").time()
    return datetime.combine(date(2000, 1, 1), h)


def _nav(lon, lat) -> str:
    return f"https://www.google.com/maps/dir/?api=1&destination={lat:.6f},{lon:.6f}&travelmode=driving"


def ruta(predios: pd.DataFrame, inicio: tuple[float, float], hora_inicio="08:30", jornada_h: float = 8,
         min_por_visita: float = 30, limite_s: int = 5, cache: Path = CACHE_OSRM,
         max_paradas: int | None = None) -> dict:
    """Ruta de inspección de una jornada.

    predios: DataFrame con predio_id, puntaje, lon, lat (punto representativo del predio, EPSG:4326).
    inicio: (lon, lat) de salida y llegada. hora_inicio: "HH:MM", datetime.time o datetime.
    max_paradas: tope de predios visitados (None = los que quepan en la jornada).
    Devuelve un dict serializable a JSON (ver `a_geojson` y `a_gpx` para exportar).
    """
    p = predios.reset_index(drop=True)
    if p["predio_id"].duplicated().any():
        raise ValueError("predio_id repetido")
    t0 = _hora(hora_inicio)
    jornada_s, servicio_s = int(jornada_h * 3600), int(min_por_visita * 60)
    puntos = [tuple(inicio)] + list(zip(p["lon"], p["lat"]))

    tabla = osrm_tabla(puntos, cache=cache)
    inalcanzable = jornada_s + 1
    dur = [[inalcanzable if v is None else round(v) for v in fila] for fila in tabla["durations"]]
    dist = [[0 if v is None else v for v in fila] for fila in tabla["distances"]]
    sin_ruta = {i for i in range(1, len(puntos)) if tabla["durations"][0][i] is None or tabla["durations"][i][0] is None}

    pmax = max(float(p["puntaje"].max()), 1e-9) if len(p) else 1.0
    penal = [0] + [round(max(s, 0) / pmax * 100 * jornada_s) for s in p["puntaje"]]
    orden = resolver(dur, penal, servicio_s, jornada_s, limite_s, max_paradas) if len(p) else []

    dest = tabla["destinations"]
    paradas, t, km, prev = [], 0, 0.0, 0
    for k, nodo in enumerate(orden, 1):
        fila = p.iloc[nodo - 1]
        t += dur[prev][nodo]
        km += dist[prev][nodo] / 1000
        acc_lon, acc_lat = dest[nodo]["location"]
        paradas.append({
            "orden": k, "predio_id": int(fila["predio_id"]), "puntaje": float(fila["puntaje"]),
            "lon": float(fila["lon"]), "lat": float(fila["lat"]), "acceso_lon": acc_lon, "acceso_lat": acc_lat,
            "dist_camino_m": round(dest[nodo]["distance"]), "camino": dest[nodo].get("name") or "",
            "min_desde_anterior": round(dur[prev][nodo] / 60, 1), "km_desde_anterior": round(dist[prev][nodo] / 1000, 1),
            "llegada": (t0 + timedelta(seconds=t)).strftime("%H:%M"),
            "salida": (t0 + timedelta(seconds=t + servicio_s)).strftime("%H:%M"),
            "enlace_navegacion": _nav(acc_lon, acc_lat),
        })
        t += servicio_s
        prev = nodo
    if orden:
        t += dur[prev][0]
        km += dist[prev][0] / 1000

    visitados = set(orden)
    con_tope = max_paradas is not None and len(orden) >= max_paradas
    fuera = []
    for i in range(1, len(puntos)):
        if i in visitados:
            continue
        if i in sin_ruta:
            motivo = "sin_ruta"
        elif dur[0][i] + servicio_s + dur[i][0] > jornada_s:
            motivo = "fuera_de_alcance"
        elif con_tope:
            motivo = "tope_de_paradas"
        else:
            motivo = "no_cabe_en_jornada"
        fila = p.iloc[i - 1]
        fuera.append({"predio_id": int(fila["predio_id"]), "puntaje": float(fila["puntaje"]), "lon": float(fila["lon"]),
                      "lat": float(fila["lat"]), "motivo": motivo,
                      "min_ida": None if i in sin_ruta else round(dur[0][i] / 60, 1)})
    fuera.sort(key=lambda f: -f["puntaje"])

    geometria, km_trazado = None, None
    if orden:
        trazado = osrm_trazado([puntos[0]] + [puntos[n] for n in orden] + [puntos[0]], cache=cache)
        geometria = trazado["routes"][0]["geometry"]
        km_trazado = round(trazado["routes"][0]["distance"] / 1000, 1)

    visita_s = servicio_s * len(orden)
    return {
        "inicio": {"lon": inicio[0], "lat": inicio[1], "acceso_lon": tabla["sources"][0]["location"][0],
                   "acceso_lat": tabla["sources"][0]["location"][1], "camino": tabla["sources"][0].get("name") or ""},
        "hora_inicio": t0.strftime("%H:%M"), "hora_termino": (t0 + timedelta(seconds=t)).strftime("%H:%M"),
        "jornada_h": jornada_h, "min_por_visita": min_por_visita, "max_paradas": max_paradas,
        "total_min": round(t / 60, 1), "manejo_min": round((t - visita_s) / 60, 1), "visita_min": round(visita_s / 60, 1),
        "total_km": round(km, 1), "km_trazado": km_trazado,
        "n_candidatos": len(p), "n_visitados": len(paradas),
        "puntaje_visitado": round(sum(x["puntaje"] for x in paradas), 4),
        "puntaje_candidatos": round(float(p["puntaje"].sum()), 4) if len(p) else 0.0,
        "paradas": paradas, "fuera": fuera, "geometria": geometria,
        "fuente": "OSRM público (router.project-osrm.org, OpenStreetMap, perfil auto); orden con OR-Tools",
    }


# -------------------------------------------------------------------------------------- exportar

def a_geojson(r: dict) -> dict:
    """FeatureCollection: línea de la ruta, inicio, paradas (visitado=true) y predios fuera (visitado=false)."""
    tot = {k: r[k] for k in ("hora_inicio", "hora_termino", "total_min", "manejo_min", "visita_min", "total_km",
                             "n_visitados", "n_candidatos", "puntaje_visitado")}
    feats = []
    if r["geometria"]:
        feats.append({"type": "Feature", "geometry": r["geometria"], "properties": {"tipo": "ruta", **tot}})
    feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [r["inicio"]["lon"], r["inicio"]["lat"]]},
                  "properties": {"tipo": "inicio", "nombre": r["inicio"].get("nombre", "Inicio"), "hora": r["hora_inicio"]}})
    for s in r["paradas"]:
        props = {k: v for k, v in s.items() if k not in ("lon", "lat")}
        feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [s["lon"], s["lat"]]},
                      "properties": {"tipo": "parada", "visitado": True, **props}})
    for f in r["fuera"]:
        props = {k: v for k, v in f.items() if k not in ("lon", "lat")}
        feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [f["lon"], f["lat"]]},
                      "properties": {"tipo": "fuera", "visitado": False, **props}})
    return {"type": "FeatureCollection", "features": feats}


def a_gpx(r: dict, nombre: str = "Ruta de inspección Caudal") -> str:
    """GPX 1.1: un wpt por parada (y el inicio), la ruta en orden (rte) y el trazado de OSRM (trk)."""
    def e(s):
        return escape(str(s))

    ini = r["inicio"]
    nombre_ini = ini.get("nombre", "Inicio")
    resumen = (f"Inicio {r['hora_inicio']}, término {r['hora_termino']}, {r['total_km']} km, "
               f"{r['total_min']} min, {r['n_visitados']} predios")

    def wpt(tag, lon, lat, name, desc, sym):
        return (f'  <{tag} lat="{lat:.6f}" lon="{lon:.6f}"><name>{e(name)}</name><desc>{e(desc)}</desc>'
                f"<sym>{sym}</sym></{tag}>")

    def desc_parada(s):
        return (f"Parada {s['orden']}, llegada {s['llegada']}, salida {s['salida']}. Puntaje {s['puntaje']:g}. "
                f"Acceso por camino a {s['dist_camino_m']} m del punto del predio.")

    lineas = ['<?xml version="1.0" encoding="UTF-8"?>',
              ('<gpx version="1.1" creator="Caudal (scripts/models/ruta_inspeccion.py)" '
               'xmlns="http://www.topografix.com/GPX/1/1" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
               'xsi:schemaLocation="http://www.topografix.com/GPX/1/1 http://www.topografix.com/GPX/1/1/gpx.xsd">'),
              f"  <metadata><name>{e(nombre)}</name><desc>{e(resumen)}</desc></metadata>",
              wpt("wpt", ini["lon"], ini["lat"], nombre_ini, f"Salida {r['hora_inicio']}", "Flag")]
    lineas += [wpt("wpt", s["lon"], s["lat"], f"{s['orden']:02d} predio {s['predio_id']}", desc_parada(s), "Waypoint")
               for s in r["paradas"]]
    lineas.append(f"  <rte><name>{e(nombre)} (paradas)</name>")
    lineas.append(wpt("rtept", ini["lon"], ini["lat"], nombre_ini, "Salida", "Flag"))
    lineas += [wpt("rtept", s["acceso_lon"], s["acceso_lat"], f"{s['orden']:02d} predio {s['predio_id']}",
                   desc_parada(s), "Waypoint") for s in r["paradas"]]
    lineas.append(wpt("rtept", ini["lon"], ini["lat"], nombre_ini, "Llegada", "Flag"))
    lineas.append("  </rte>")
    if r["geometria"]:
        lineas.append(f"  <trk><name>{e(nombre)} (trazado)</name><trkseg>")
        lineas += [f'    <trkpt lat="{lat:.6f}" lon="{lon:.6f}"/>' for lon, lat in r["geometria"]["coordinates"]]
        lineas.append("  </trkseg></trk>")
    lineas.append("</gpx>")
    return "\n".join(lineas) + "\n"


# --------------------------------------------------------------------------------------------- CLI

def predios_con_punto(ids, zona: str):
    """Punto representativo (lon, lat) de los predios de la zona con esos predio_id."""
    import geopandas as gpd

    pr = gpd.read_parquet(PROC / "predio.parquet", columns=["predio_id", "zona", "geometry"])
    pr = pr[pr["predio_id"].isin(list(ids)) & (pr["zona"] == zona)]
    pt = pr.geometry.representative_point()
    return pd.DataFrame({"predio_id": pr["predio_id"].to_numpy(), "lon": pt.x.to_numpy(), "lat": pt.y.to_numpy()})


def puntajes_demo(zona: str) -> pd.DataFrame:
    """Positivos limpios de fiscalización + predios de casos_validacion.geojson, puntaje 1."""
    f = pd.read_parquet(PROC / "fiscalizacion.parquet", columns=["expediente", "predio_id", "zona", "etiqueta", "set_validacion"])
    casos = json.loads((DATA / "casos_validacion.geojson").read_text())
    exp_casos = {ft["properties"]["expediente"] for ft in casos["features"] if ft["properties"]["zona"] == zona}
    sel = f[(f["zona"] == zona) & (((f["etiqueta"] == "positivo") & (f["set_validacion"] == "limpio"))
                                   | f["expediente"].isin(exp_casos))]
    ids = sel["predio_id"].dropna().astype(int).unique()
    return pd.DataFrame({"predio_id": ids, "puntaje": 1.0})


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--zona", required=True, choices=sorted(INICIOS))
    fuente = ap.add_mutually_exclusive_group(required=True)
    fuente.add_argument("--puntajes", type=Path, help="CSV o Parquet con predio_id, puntaje")
    fuente.add_argument("--demo", action="store_true", help="positivos limpios y casos de validación, puntaje 1")
    ap.add_argument("--top", type=int, default=40, help="predios de mayor puntaje que entran como candidatos")
    ap.add_argument("--inicio", help="lon,lat del punto de partida (por defecto, plaza de la capital provincial)")
    ap.add_argument("--hora", default="08:30", help="hora de inicio HH:MM")
    ap.add_argument("--jornada-h", type=float, default=8)
    ap.add_argument("--min-visita", type=float, default=30)
    ap.add_argument("--max-paradas", type=int, help="tope de predios en la ruta (por defecto, los que quepan)")
    ap.add_argument("--limite-s", type=int, default=5, help="segundos de búsqueda de OR-Tools")
    ap.add_argument("--salida", type=Path, help="prefijo de salida (sin extensión)")
    args = ap.parse_args()

    if args.demo:
        sc = puntajes_demo(args.zona)
    else:
        sc = pd.read_csv(args.puntajes) if args.puntajes.suffix == ".csv" else pd.read_parquet(args.puntajes)
        sc = sc[["predio_id", "puntaje"]]
    pts = predios_con_punto(sc["predio_id"], args.zona)
    cand = sc.merge(pts, on="predio_id").sort_values(["puntaje", "predio_id"], ascending=[False, True])
    # Orden estable por predio_id: el mismo conjunto de predios reusa la matriz de OSRM guardada aunque cambien
    # los puntajes.
    cand = cand.head(min(args.top, MAX_TABLA - 1)).sort_values("predio_id")
    if cand.empty:
        print(f"Sin predios de {args.zona} en los puntajes", file=sys.stderr)
        return 1

    ini = dict(INICIOS[args.zona])
    if args.inicio:
        lon, lat = map(float, args.inicio.split(","))
        ini = {"nombre": "Inicio", "lon": lon, "lat": lat}
    try:
        r = ruta(cand, (ini["lon"], ini["lat"]), args.hora, args.jornada_h, args.min_visita, args.limite_s,
                 max_paradas=args.max_paradas)
    except ErrorOSRM as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    r["zona"] = args.zona
    r["inicio"]["nombre"] = ini["nombre"]

    pref = args.salida or PROC / (f"ruta_ejemplo_{args.zona.lower()}" if args.demo else f"ruta_{args.zona.lower()}")
    pref.parent.mkdir(parents=True, exist_ok=True)
    Path(f"{pref}.json").write_text(json.dumps({k: v for k, v in r.items() if k != "geometria"}, ensure_ascii=False, indent=1))
    Path(f"{pref}.geojson").write_text(json.dumps(a_geojson(r), ensure_ascii=False))
    Path(f"{pref}.gpx").write_text(a_gpx(r, f"Ruta de inspección Caudal {args.zona}"))

    print(f"{args.zona}: inicio {ini['nombre']} ({ini['lon']}, {ini['lat']}), acceso por '{r['inicio']['camino']}'")
    print(f"{r['n_visitados']}/{r['n_candidatos']} predios, {r['hora_inicio']}-{r['hora_termino']}, {r['total_min']} min "
          f"({r['manejo_min']} manejo + {r['visita_min']} visita), {r['total_km']} km (trazado {r['km_trazado']} km), "
          f"puntaje {r['puntaje_visitado']}/{r['puntaje_candidatos']}")
    if r["paradas"]:
        cols = ["orden", "predio_id", "puntaje", "llegada", "salida", "min_desde_anterior", "km_desde_anterior", "dist_camino_m", "camino"]
        print(pd.DataFrame(r["paradas"])[cols].to_string(index=False))
    if r["fuera"]:
        print("Fuera:\n" + pd.DataFrame(r["fuera"])[["predio_id", "puntaje", "motivo", "min_ida"]].to_string(index=False))
    print(f"Escrito {pref}.json, .geojson y .gpx")
    return 0


if __name__ == "__main__":
    sys.exit(main())
