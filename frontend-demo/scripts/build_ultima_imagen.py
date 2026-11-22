# /// script
# requires-python = ">=3.11"
# dependencies = ["duckdb"]
# ///
"""Caudal · fecha de la imagen satelital más reciente, para la portada (js/datos-portada.js).

Lee data/processed/serie_predio.parquet (serie Sentinel-2 de la muestra de predios, D1) y escribe
frontend-demo/data/zonas/ultima_imagen.json con:

  valida          la escena más reciente con dato en al menos un predio (fecha, escena, predios con dato)
  ultima_pasada   la escena más reciente, tenga dato o no (fecha, escena, nubosidad media sobre los predios)
  muestra_predios cuántos predios tiene la muestra

El ranking no usa estas imágenes: se calcula con la temporada de riego cerrada (ver `dato_al` en /api/health).

Uso (desde la raíz del repo): uv run frontend-demo/scripts/build_ultima_imagen.py
"""

import json
import sys
from datetime import date
from pathlib import Path

import duckdb

RAIZ = Path(__file__).resolve().parents[2]
SERIE = RAIZ / "data" / "processed" / "serie_predio.parquet"
SALIDA = RAIZ / "frontend-demo" / "data" / "zonas" / "ultima_imagen.json"

POR_ESCENA = """
    select cast(fecha as date) as fecha,
           any_value(escena_id) as escena,
           count(*) as predios,
           count(ndvi) as con_dato,
           round(avg(nubosidad_pct), 1) as nubosidad_pct
    from read_parquet(?)
    group by 1
    order by 1 desc
"""


def escenas(serie: Path) -> list[dict]:
    cur = duckdb.execute(POR_ESCENA, [str(serie)])
    columnas = [c[0] for c in cur.description]
    return [dict(zip(columnas, fila)) for fila in cur.fetchall()]


def resumen(filas: list[dict], muestra: int) -> dict:
    if not filas:
        raise ValueError("la serie no tiene imágenes")
    validas = [f for f in filas if f["con_dato"] > 0]
    if not validas:
        raise ValueError("ninguna imagen de la serie tiene dato válido")
    ultima, valida = filas[0], validas[0]
    return {
        "valida": {"fecha": valida["fecha"].isoformat(), "escena": valida["escena"],
                   "predios_con_dato": valida["con_dato"], "predios": valida["predios"]},
        "ultima_pasada": {"fecha": ultima["fecha"].isoformat(), "escena": ultima["escena"],
                          "predios_con_dato": ultima["con_dato"], "nubosidad_pct": ultima["nubosidad_pct"]},
        "muestra_predios": muestra,
        "fuente": "Sentinel-2 L2A (Copernicus), muestra de predios de data/processed/serie_predio.parquet",
        "generado": date.today().isoformat(),
    }


def main() -> int:
    if not SERIE.exists():
        print(f"ERROR: falta {SERIE.relative_to(RAIZ)}", file=sys.stderr)
        return 1
    try:
        muestra = duckdb.execute("select count(distinct predio_id) from read_parquet(?)", [str(SERIE)]).fetchall()[0][0]
        datos = resumen(escenas(SERIE), muestra)
    except (duckdb.Error, ValueError) as err:
        print(f"ERROR: no se pudo leer la serie: {err}", file=sys.stderr)
        return 1
    SALIDA.write_text(json.dumps(datos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{SALIDA.relative_to(RAIZ)}: última imagen con dato {datos['valida']['fecha']}, "
          f"última pasada {datos['ultima_pasada']['fecha']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
