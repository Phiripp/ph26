# /// script
# requires-python = ">=3.11"
# dependencies = ["requests"]
# ///
"""Genera data/regiones.json: las regiones de la corrida nacional, con el mismo esquema que data/zonas.json.

Cada región trae sus capas de cada fuente (CIREN predios, CONAF uso de la tierra, Catastro Frutícola, DGA), la
`aplicabilidad` del modelo y la prioridad de la etapa satelital. Las comunas salen de `desccomu` de la capa CIREN y
el bbox de la extensión real de sus predios (`returnExtentOnly`; la extensión de los metadatos de la capa viene
repetida entre Ñuble y Biobío), con 2 km de margen. El archivo va a git y al bucket (config/regiones.json).

Tabla de regiones y campos de CONAF: docs/spec-chile.md. Antofagasta (II) y Magallanes (XII) no tienen capa de
predios CIREN y quedan fuera.

Uso: uv run scripts/cloud/chile/regiones.py [--salida data/regiones.json]
"""

import argparse
import json
import math
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from comun.rutas import DATA, mostrar  # noqa: E402

CIREN = "https://esri.ciren.cl/server/rest/services/IDEMINAGRI"
MARGEN_KM = 2.0
KM_POR_GRADO = 111.32

# (zona, nombre, capa CIREN predios, capa CONAF, capa frutícola, DGA, aplicabilidad, prioridad)
REGIONES = [
    ("R15", "Arica y Parinacota", 0, 1, 55, "XV", "norte_desertico", 3),
    ("R01", "Tarapacá", 1, 2, 56, "I", "norte_desertico", 3),
    ("R03", "Atacama", 2, 3, 57, "III", "norte_desertico", 2),
    ("R04", "Coquimbo", 3, 4, 58, "IV", "mediterraneo_seco", 1),
    ("R05", "Valparaíso", 4, 5, 59, "V", "calibrado", 1),
    ("R13", "Metropolitana", 5, 6, 60, "XIII", "mediterraneo_seco", 1),
    ("R06", "O'Higgins", 6, 7, 61, "VI", "mediterraneo_seco", 1),
    ("R07", "Maule", 7, 16, 62, "VII", "mediterraneo_seco", 1),
    ("R16", "Ñuble", 8, 21, 63, "XVI", "sur_humedo", 2),
    ("R08", "Biobío", 9, 17, 64, "VIII", "sur_humedo", 2),
    ("R09", "Araucanía", 10, 18, 65, "IX", "sur_humedo", 3),
    ("R14", "Los Ríos", 11, 20, 66, "XIV", "sur_humedo", 3),
    ("R10", "Los Lagos", 12, 19, 67, "X", "sur_humedo", 3),
    ("R11", "Aysén", 13, None, 68, "XI", "sur_humedo", 3),
]

# Años de cada capa CONAF, medidos en los metadatos de la capa (`?f=json`): las capas del norte (1 a 3) solo traen
# dos años, las de Coquimbo a O'Higgins llegan a 2019 y las de Maule al sur a 2021. El campo de uso de referencia es
# el último año; "estable" exige el mismo uso en todos los años de la capa.
CONAF_ANIOS = {
    1: ["12", "17"], 2: ["13", "17"], 3: ["15", "17"],
    4: ["01", "13", "16", "17", "19"], 5: ["01", "13", "16", "17", "19"],
    6: ["01", "13", "16", "17", "19"], 7: ["01", "13", "16", "17", "19"],
    **{capa: ["01", "13", "16", "17", "19", "21"] for capa in (16, 17, 18, 19, 20, 21)},
}


def consultar(url: str, params: dict, reintentos: int = 4) -> dict:
    for intento in range(reintentos):
        try:
            r = requests.post(url, data={**params, "f": "json"}, timeout=120)
            r.raise_for_status()
            cuerpo = r.json()
            if "error" in cuerpo:
                raise RuntimeError(cuerpo["error"])
            return cuerpo
        except Exception:  # noqa: BLE001
            if intento == reintentos - 1:
                raise
            time.sleep(3 * 2**intento)
    raise AssertionError("inalcanzable")


def comunas_de_capa(capa: int) -> list[str]:
    url = f"{CIREN}/PROPIEDADES_RURALES/MapServer/{capa}/query"
    r = consultar(url, {"where": "1=1", "outFields": "desccomu", "returnDistinctValues": "true", "returnGeometry": "false"})
    return sorted({f["attributes"]["desccomu"].strip() for f in r["features"] if f["attributes"].get("desccomu")})


def bbox_de_capa(capa: int) -> list[float]:
    url = f"{CIREN}/PROPIEDADES_RURALES/MapServer/{capa}/query"
    ext = consultar(url, {"where": "1=1", "returnExtentOnly": "true", "outSR": 4326})["extent"]
    dlat = MARGEN_KM / KM_POR_GRADO
    dlon = dlat / math.cos(math.radians((ext["ymin"] + ext["ymax"]) / 2))
    return [round(ext["xmin"] - dlon, 4), round(ext["ymin"] - dlat, 4), round(ext["xmax"] + dlon, 4), round(ext["ymax"] + dlat, 4)]


def conaf_de_capa(capa: int | None) -> dict | None:
    if capa is None:
        return None
    anios = CONAF_ANIOS[capa]
    return {"capa": capa, "campo_uso": f"uso_{anios[-1]}", "campos_historia": [f"uso_{a}" for a in anios[:-1]]}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--salida", type=Path, default=DATA / "regiones.json")
    args = ap.parse_args()

    zonas = {}
    for zona, nombre, ciren, conaf, fruticola, dga, aplicabilidad, prioridad in REGIONES:
        zonas[zona] = {
            "nombre": nombre,
            "uso": "Corrida nacional 2025-26",
            "numero": int(zona[1:]),
            "comunas": comunas_de_capa(ciren),
            "bbox": bbox_de_capa(ciren),
            "ciren_predios": ciren,
            "conaf": conaf_de_capa(conaf),
            "fruticola": fruticola,
            "dga": dga,
            "aplicabilidad": aplicabilidad,
            "prioridad": prioridad,
        }
        print(f"{zona} {nombre:<20} {len(zonas[zona]['comunas']):>3} comunas  bbox {zonas[zona]['bbox']}")

    cfg = {
        "_fuente": "Generado por scripts/cloud/chile/regiones.py (tabla de docs/spec-chile.md). No se edita a mano.",
        "crs_bbox": "EPSG:4326",
        "periodo": {"inicio": "2025-03-01", "fin": "2026-03-31"},
        "temporada": {"inicio": "2025-12-01", "fin": "2026-03-31"},
        "zonas": zonas,
    }
    args.salida.parent.mkdir(parents=True, exist_ok=True)
    args.salida.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n{mostrar(args.salida)}: {len(zonas)} regiones")
    return 0


if __name__ == "__main__":
    sys.exit(main())
