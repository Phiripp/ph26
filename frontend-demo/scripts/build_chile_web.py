# /// script
# requires-python = ">=3.11"
# dependencies = ["pandas", "pyarrow"]
# ///
"""Caudal · capa nacional del mapa: los predios en alerta de la corrida nacional, fuera de Z1 y Z2 (docs/spec-chile.md).

El mapa combina dos fuentes sin mezclarlas:

- Z1 y Z2: la exportación validada de siempre (data/zonas/, build_m5_web.py). Las cifras del pitch salen de ahí.
- El resto de Chile: la corrida nacional (`web/<corrida>/RXX/` en el bucket, etapa region de caudal-chile-prediccion).
  Es exploratoria: los umbrales se calibraron en Z1 y Z2, el clima es ERA5-Land sin corrección con estaciones y el
  riego por acciones de canal no está en el registro de derechos (ver "Qué datos ya están disponibles" en el spec).

Este script lee la exportación de cada región, deja fuera los predios de Z1 y Z2 (los de data/processed/puntaje.parquet)
para que no se dupliquen, y escribe en frontend-demo/data/chile/:

  index.json        por región: nombre, bbox, aplicabilidad, conteo por banda (fuera de Z1 y Z2), archivo y estado
                    (`lista` o `pendiente` si la etapa region todavía no la corrió)
  puntos.geojson    un punto por predio en alerta alta o media: id, región, banda, puntaje, confianza y si tiene canal a
                    300 m. Liviano, para la vista nacional
  RXX.geojson       polígonos de la región (los mismos de la exportación, simplificados a 5 m) con lo que muestra la
                    ficha: banda, puntaje, confianza, motivos, rangos de m³, canal y aplicabilidad. Sin rol ni nombres

Uso (desde la raíz del repo; necesita gcloud con acceso al bucket, o una copia local con --origen carpeta):
  uv run frontend-demo/scripts/build_chile_web.py
  uv run frontend-demo/scripts/build_chile_web.py --origen /datos/web/chile-2025-26
"""

import argparse
import json
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parents[2]
WEB = RAIZ / "frontend-demo"
CACHE = WEB / "scripts" / ".cache" / "chile"
CORRIDA = "chile-2025-26"
BUCKET = f"gs://ph-26-caudal-chile/web/{CORRIDA}"
BANDAS = ("alta", "media")
DECIMALES = 5  # ~1 m: la geometría ya viene simplificada a 5 m


def bajar(origen: str, zonas: list[str]) -> Path:
    """Copia del bucket solo lo que se usa (conteo, scores.lite y predios) a la caché local; una carpeta local se usa tal cual."""
    if not origen.startswith("gs://"):
        return Path(origen)
    for z in zonas:
        destino = CACHE / z
        destino.mkdir(parents=True, exist_ok=True)
        r = subprocess.run(["gcloud", "storage", "cp", "-q", *(f"{origen}/{z}/{f}" for f in
                            ("conteo.json", "scores.lite.json", "predios.geojson")), str(destino)],
                           capture_output=True, text=True)
        if r.returncode:  # la región todavía no tiene etapa region: queda pendiente
            shutil.rmtree(destino, ignore_errors=True)
    return CACHE


def redondear(coords):
    if isinstance(coords[0], (int, float)):
        return [round(c, DECIMALES) for c in coords]
    return [redondear(c) for c in coords]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--origen", default=BUCKET, help=f"carpeta web/<corrida> local o en el bucket (por defecto {BUCKET})")
    ap.add_argument("--salida", type=Path, default=WEB / "data" / "chile")
    args = ap.parse_args()

    cfg = json.loads((RAIZ / "data" / "regiones.json").read_text(encoding="utf-8"))
    zonas = cfg["zonas"]
    z12 = set(pd.read_parquet(RAIZ / "data" / "processed" / "puntaje.parquet", columns=["predio_id"])["predio_id"].astype(str))
    base = bajar(args.origen, list(zonas))
    args.salida.mkdir(parents=True, exist_ok=True)

    indice, puntos = [], []
    for z, info in zonas.items():
        fila = {"zona": z, "nombre": info["nombre"], "bbox": info["bbox"], "aplicabilidad": info["aplicabilidad"],
                "exploratorio": True, "estado": "pendiente"}
        carpeta = base / z
        if not (carpeta / "conteo.json").exists():
            indice.append(fila)
            print(f"{z} {info['nombre']}: pendiente (sin etapa region)")
            continue
        scores = json.loads((carpeta / "scores.lite.json").read_text(encoding="utf-8"))["predios"]
        geo = json.loads((carpeta / "predios.geojson").read_text(encoding="utf-8"))
        feats, cuenta = [], {b: 0 for b in BANDAS}
        for f in geo["features"]:
            pid = str(f["properties"]["predio_id"])
            s = scores.get(pid)
            if pid in z12 or not s or s["banda"] not in BANDAS:
                continue
            cuenta[s["banda"]] += 1
            p = f["properties"]
            canal = p.get("dist_canal_m") is not None and p["dist_canal_m"] <= 300
            feats.append({"type": "Feature", "geometry": {**f["geometry"], "coordinates": redondear(f["geometry"]["coordinates"])},
                          "properties": {"id": pid, "zona": z, "comuna": p.get("comuna"), "area_ha": p.get("area_ha"),
                                         "cultivo": p.get("cultivo"), "banda": s["banda"], "puntaje": s["puntaje"],
                                         "confianza": s["confianza"], "motivos": s.get("motivos", []),
                                         "consumo_m3": s.get("consumo_m3"), "exceso_m3": s.get("exceso_m3"),
                                         "derecho_m3": s.get("derecho_m3"), "canal_m": p.get("dist_canal_m"),
                                         "estado_derechos": s.get("estado_derechos"),
                                         "aplicabilidad": s.get("aplicabilidad", info["aplicabilidad"])}})
            lon, lat = p["centroid"]
            puntos.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(lon, DECIMALES), round(lat, DECIMALES)]},
                           "properties": {"id": pid, "z": z, "b": s["banda"], "p": round(s["puntaje"]), "c": s["confianza"][0],
                                          "canal": canal}})
        archivo = f"{z}.geojson"
        (args.salida / archivo).write_text(json.dumps({"type": "FeatureCollection", "features": feats},
                                                      ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        conteo = json.loads((carpeta / "conteo.json").read_text(encoding="utf-8"))
        fila.update(estado="lista", archivo=archivo, predios_region=conteo["predios"], alertas=cuenta,
                    excluidos_z1_z2=sum(1 for pid in scores if pid in z12))
        indice.append(fila)
        print(f"{z} {info['nombre']}: {cuenta['alta']} alta y {cuenta['media']} media fuera de Z1 y Z2 "
              f"({(args.salida / archivo).stat().st_size / 1e6:.1f} MB)")

    (args.salida / "puntos.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": puntos},
                                                           separators=(",", ":")), encoding="utf-8")
    listas = [f for f in indice if f["estado"] == "lista"]
    (args.salida / "index.json").write_text(json.dumps({
        "corrida": CORRIDA, "temporada": cfg["temporada"], "generado": date.today().isoformat(),
        "fuente": "Corrida nacional de Caudal (docs/spec-chile.md). Fuera de Z1 y Z2 es exploratoria: umbrales "
                  "calibrados en Z1 y Z2, clima ERA5-Land sin corrección con estaciones y riego por acciones de canal "
                  "fuera del registro de derechos.",
        "z1_z2": "Los predios de Z1 y Z2 salen de data/zonas/ (exportación validada), no de esta capa.",
        "regiones": indice,
        "totales": {b: sum(f["alertas"][b] for f in listas) for b in BANDAS},
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n{len(listas)} de {len(indice)} regiones listas; {len(puntos)} puntos -> {args.salida}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
