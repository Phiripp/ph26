# /// script
# requires-python = ">=3.11"
# dependencies = ["geopandas>=1.0", "pyarrow", "shapely>=2.0", "pandas", "numpy", "scipy"]
# ///
"""Punto de entrada de los Cloud Run Jobs de la corrida nacional (docs/spec-chile.md).

Cada job es una sola definición que corre con una `ETAPA` distinta; la tarea se elige con CLOUD_RUN_TASK_INDEX y
CLOUD_RUN_TASK_COUNT. Todas las etapas son idempotentes: si la salida de la tarea ya está en el bucket, la saltan.

Variables de entorno:
- ETAPA: base | plan | satelite | region | nacional.
- CAUDAL_DATA: el bucket montado (/datos). CORRIDA: nombre de la corrida de predicción (modelo/<corrida>, web/<corrida>).
- HILOS: hilos por tarea (satelite: escenas en paralelo; base: lectura de ERA5-Land). PARTE_BASE: primera parte del
  plan que corre esta región de Cloud Run (satelite). PARTES: N del plan (40). REGIONES: lista separada por comas para
  correr solo algunas regiones (plan, region, nacional).
- CDS_API_KEY: clave de ERA5-Land (Secret Manager); con el valor `PENDIENTE` falla el paso de clima, solo ese.

Etapas:
- base (14 tareas, una por región): extractores de la región, en orden, con `config/regiones.json` como zonas. Cada paso
  deja su salida en base/<tabla>/region=RXX.parquet apenas termina, así un reintento retoma desde el paso que falló.
- plan (1 tarea): scripts/cloud/chile/plan.py.
- satelite (una tarea por parte): scripts/extract/serie_sentinel2.py --parte PARTE_BASE+índice.
- region (14 tareas): scripts/cloud/chile/prediccion.py, serie por región y M1 a M5 más la exportación web.
- nacional (1 tarea): scripts/cloud/chile/prediccion.py, ranking nacional, resumen y comprobación de regresión.

Los logs van también a logs/<etapa>/<ejecución>/tarea-<i>.log, escritos primero en /tmp y copiados al montaje.
"""

import json
import os
import shutil
import subprocess
import sys
import threading
import time
from datetime import date
from pathlib import Path

APP = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(APP / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

DATOS = Path(os.environ.get("CAUDAL_DATA") or "/datos")
TRABAJO = Path(os.environ.get("TRABAJO") or "/tmp/trabajo")
HILOS = os.environ.get("HILOS", "4")
TAREA = int(os.environ.get("CLOUD_RUN_TASK_INDEX", "0"))
TAREAS = int(os.environ.get("CLOUD_RUN_TASK_COUNT", "1"))

# Paso -> (script, argumentos, {salida local relativa a la carpeta de trabajo: destino en el bucket})
# Las salidas son parquet por región. canales va antes del cruce porque este mide la distancia al canal más cercano.
BASE_PASOS = [
    ("predios", "scripts/extract/predios_ciren.py", [],
     {"processed/predio.parquet": "base/predio/region={z}.parquet"}),
    ("secano", "scripts/extract/referencia_secano_conaf.py", [],
     {"processed/referencia_secano.parquet": "base/referencia_secano/region={z}.parquet"}),
    ("cultivos", "scripts/extract/cultivos_ciren.py", [],
     {"processed/predio_cultivo.parquet": "base/cultivo/region={z}.parquet"}),
    ("derechos", "scripts/extract/derechos_dga.py", [],
     {"processed/derecho.parquet": "base/derecho/region={z}.parquet",
      "raw/dga/derecho_titulares.parquet": "base/derecho_titulares/region={z}.parquet"}),
    ("canales", "scripts/extract/canales_ciren.py", [],
     {"raw/ciren_riego/canales.parquet": "base/canal/region={z}.parquet"}),
    ("cruce", "scripts/extract/cruce_derechos_predios.py", [],
     {"processed/derecho_predio.parquet": "base/derecho_predio/region={z}.parquet",
      "processed/predio_derecho.parquet": "base/predio_derecho/region={z}.parquet"}),
    ("cauces", "scripts/extract/cauces_dga.py", [],
     {"processed/cauce.parquet": "base/cauce/region={z}.parquet",
      "processed/predio_cauce.parquet": "base/predio_cauce/region={z}.parquet"}),
    ("restriccion", "scripts/extract/restriccion_dga.py", [],
     {"processed/restriccion.parquet": "base/restriccion/region={z}.parquet",
      "processed/predio_restriccion.parquet": "base/predio_restriccion/region={z}.parquet"}),
    ("fiscalizaciones", "scripts/extract/fiscalizaciones_dga.py", [],
     {"processed/fiscalizacion.parquet": "base/fiscalizacion/region={z}.parquet"}),
    ("clima", "scripts/extract/d2_clima_era5land.py", ["--hilos", HILOS],
     {"processed/clima.parquet": "base/clima/region={z}.parquet",
      "processed/predio_clima.parquet": "base/predio_clima/region={z}.parquet"}),
]


def cargar_config() -> dict:
    """Regiones desde data/regiones.json de la imagen (/app); config/regiones.json del bucket, si se quiere reemplazar."""
    for ruta in (DATOS / "config" / "regiones.json", APP / "data" / "regiones.json"):
        if ruta.exists():
            return json.loads(ruta.read_text(encoding="utf-8"))
    sys.exit("No encuentro data/regiones.json: corre scripts/cloud/chile/regiones.py y vuelve a construir la imagen")


def regiones_elegidas(cfg: dict) -> list[str]:
    todas = list(cfg["zonas"])
    pedidas = [r.strip() for r in os.environ.get("REGIONES", "").split(",") if r.strip()]
    if pedidas:
        desconocidas = set(pedidas) - set(todas)
        if desconocidas:
            sys.exit(f"REGIONES desconocidas: {sorted(desconocidas)}; las válidas son {todas}")
        return [z for z in todas if z in pedidas]
    return todas


def config_de(cfg: dict, zonas: list[str], destino: Path) -> Path:
    """Escribe un archivo de zonas (mismo esquema que data/zonas.json) con solo `zonas`, para CAUDAL_ZONAS."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps({**cfg, "zonas": {z: cfg["zonas"][z] for z in zonas}}, ensure_ascii=False),
                       encoding="utf-8")
    return destino


def correr(script: str, args: list[str], datos: Path, zonas: Path | None = None, extra: dict | None = None) -> None:
    """Corre un script del repo con CAUDAL_DATA y CAUDAL_ZONAS apuntando a la carpeta de trabajo."""
    env = {**os.environ, "CAUDAL_DATA": str(datos), "PYTHONUNBUFFERED": "1", **(extra or {})}
    if zonas:
        env["CAUDAL_ZONAS"] = str(zonas)
    cmd = [sys.executable, str(APP / script), *map(str, args)]
    print(f"$ {' '.join(cmd[1:])}", flush=True)
    t0 = time.time()
    r = subprocess.run(cmd, env=env, cwd=APP)
    print(f"  ({time.time() - t0:.0f} s)", flush=True)
    if r.returncode:
        sys.exit(f"{script} terminó con código {r.returncode}")


def copiar_a_bucket(origen: Path, destino: Path) -> None:
    """Un archivo propio por salida: se copia entero al montaje, sin append ni renombres."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(origen, destino)


def sincronizar_raw(trabajo: Path, zona: str) -> None:
    """Respuestas crudas a base/raw/<zona>/ (no se vuelven a pedir en un reintento)."""
    raiz = trabajo / "raw"
    destino = DATOS / "base" / "raw" / zona
    for f in raiz.rglob("*") if raiz.exists() else []:
        d = destino / f.relative_to(raiz)
        if f.is_file() and not (d.exists() and d.stat().st_size == f.stat().st_size):
            copiar_a_bucket(f, d)


def restaurar_raw(trabajo: Path, zona: str) -> None:
    origen = DATOS / "base" / "raw" / zona
    for f in origen.rglob("*") if origen.exists() else []:
        d = trabajo / "raw" / f.relative_to(origen)
        if f.is_file() and not d.exists():
            d.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(f, d)


def etapa_base(cfg: dict) -> None:
    zonas = regiones_elegidas(cfg)
    if TAREA >= len(zonas):
        print(f"tarea {TAREA}: no hay región {TAREA} (hay {len(zonas)}); nada que hacer")
        return
    zona = zonas[TAREA]
    estado = DATOS / "base" / "_estado" / f"base-{zona}.json"
    if estado.exists():
        print(f"{zona}: base terminada ({estado.name}); nada que hacer")
        return
    trabajo = TRABAJO / zona
    shutil.rmtree(trabajo, ignore_errors=True)
    archivo_zonas = config_de(cfg, [zona], trabajo / f"regiones_{zona}.json")
    restaurar_raw(trabajo, zona)
    print(f"base {zona} ({cfg['zonas'][zona]['nombre']}): trabajo en {trabajo}", flush=True)

    for nombre, script, args, salidas in BASE_PASOS:
        destinos = {rel: DATOS / dest.format(z=zona) for rel, dest in salidas.items()}
        if all(d.exists() for d in destinos.values()):
            print(f"[{nombre}] ya está en el bucket; la restauro en la carpeta de trabajo", flush=True)
            for rel, d in destinos.items():
                (trabajo / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(d, trabajo / rel)
            continue
        print(f"[{nombre}]", flush=True)
        if nombre == "clima":
            clave = os.environ.get("CDS_API_KEY", "").strip()
            if not clave or clave == "PENDIENTE":
                sys.exit("CDS_API_KEY es PENDIENTE: el paso de clima necesita la clave real de ERA5-Land. Guárdala en el "
                         "secreto CDS_API_KEY y relanza la etapa base: los pasos anteriores ya están en el bucket.")
        correr(script, args, trabajo, archivo_zonas)
        sincronizar_raw(trabajo, zona)
        for rel, d in destinos.items():
            copiar_a_bucket(trabajo / rel, d)

    import pandas as pd

    predio = pd.read_parquet(trabajo / "processed" / "predio.parquet", columns=["predio_id", "elegible"])
    resumen = {"zona": zona, "predios": int(len(predio)), "elegibles": int(predio["elegible"].sum()),
               "terminado": date.today().isoformat()}
    estado.parent.mkdir(parents=True, exist_ok=True)
    estado.write_text(json.dumps(resumen), encoding="utf-8")
    print(f"{zona}: base terminada, {resumen}", flush=True)
    shutil.rmtree(trabajo, ignore_errors=True)


def etapa_plan(cfg: dict) -> None:
    zonas = regiones_elegidas(cfg)
    faltan = [z for z in zonas if not (DATOS / "base" / "predio" / f"region={z}.parquet").exists()]
    if faltan:
        sys.exit(f"Faltan los predios base de {faltan}: corre antes la etapa base")
    pendientes = [z for z in zonas if not (DATOS / "base" / "_estado" / f"base-{z}.json").exists()]
    if pendientes:
        print(f"Aviso: base no terminó en {pendientes} (por ejemplo, sin clima); el plan usa los predios que ya están")
    archivo_zonas = config_de(cfg, zonas, TRABAJO / "regiones_plan.json")
    correr("scripts/cloud/chile/plan.py", ["--partes", os.environ.get("PARTES", "40")], DATOS, archivo_zonas)


def etapa_satelite() -> None:
    parte = int(os.environ.get("PARTE_BASE", "0")) + TAREA
    ruta = DATOS / "plan" / "partes" / f"{parte}.jsonl"
    if not ruta.exists():
        sys.exit(f"Falta {ruta}: corre antes la etapa plan (y revisa PARTES)")
    correr("scripts/extract/serie_sentinel2.py", ["--parte", parte, "--hilos", HILOS], DATOS)


def etapa_prediccion(etapa: str, cfg: dict) -> None:
    import prediccion

    corrida = os.environ.get("CORRIDA") or date.today().strftime("%Y%m%d")
    zonas = regiones_elegidas(cfg)
    if etapa == "region":
        if TAREA >= len(zonas):
            print(f"tarea {TAREA}: no hay región {TAREA} (hay {len(zonas)}); nada que hacer")
            return
        prediccion.region(cfg, zonas[TAREA], corrida, DATOS, TRABAJO, correr, config_de)
    else:
        prediccion.nacional(cfg, zonas, corrida, DATOS)


class Registro:
    """Duplica stdout al log de la tarea y lo copia al bucket cada minuto (un solo archivo, se reescribe entero)."""

    def __init__(self, ruta_bucket: Path):
        self.local = Path("/tmp") / f"log-{os.getpid()}.txt"
        self.destino = ruta_bucket
        self.stdout = sys.stdout
        self.f = self.local.open("w", encoding="utf-8")
        self.parar = threading.Event()
        threading.Thread(target=self._copiar_cada_minuto, daemon=True).start()

    def write(self, s):
        self.stdout.write(s)
        self.f.write(s)

    def flush(self):
        self.stdout.flush()
        self.f.flush()

    def _copiar_cada_minuto(self):
        while not self.parar.wait(60):
            self.copiar()

    def copiar(self):
        try:
            self.f.flush()
            self.destino.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(self.local, self.destino)
        except OSError as e:
            self.stdout.write(f"(no pude copiar el log al bucket: {e})\n")

    def cerrar(self):
        self.parar.set()
        self.copiar()


def main() -> int:
    etapa = os.environ.get("ETAPA", "").strip().lower()
    etapas = ("base", "plan", "satelite", "region", "nacional")
    if etapa not in etapas:
        sys.exit(f"ETAPA debe ser una de {etapas}; vale {etapa!r}")
    ejecucion = os.environ.get("CLOUD_RUN_EXECUTION") or time.strftime("local-%Y%m%d-%H%M%S")
    log = Registro(DATOS / "logs" / etapa / ejecucion / f"tarea-{TAREA}.log")
    sys.stdout = sys.stderr = log
    try:
        print(f"etapa {etapa}, tarea {TAREA + 1} de {TAREAS}, ejecución {ejecucion}, datos en {DATOS}", flush=True)
        cfg = cargar_config()
        if etapa == "base":
            etapa_base(cfg)
        elif etapa == "plan":
            if TAREA == 0:
                etapa_plan(cfg)
        elif etapa == "satelite":
            etapa_satelite()
        else:
            etapa_prediccion(etapa, cfg)
        return 0
    except SystemExit as e:
        if isinstance(e.code, str):
            print(e.code, flush=True)  # el motivo también queda en el log del bucket
        raise
    finally:
        sys.stdout, sys.stderr = log.stdout, log.stdout
        log.cerrar()


if __name__ == "__main__":
    sys.exit(main())
