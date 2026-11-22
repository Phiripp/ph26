# Imagen de los Cloud Run Jobs de la corrida nacional (docs/spec-chile.md).
# Se construye desde la raíz del repo con infra/imagen/construir.sh; .gcloudignore deja subir solo lo que se copia aquí.
FROM mirror.gcr.io/library/python:3.12-slim

# libexpat1: la necesitan las ruedas de rasterio y GDAL. Sin compiladores: todas las dependencias traen ruedas.
RUN apt-get update -qq \
    && apt-get install -y -qq --no-install-recommends libexpat1 \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    MPLBACKEND=Agg \
    CAUDAL_DATA=/datos

# Dependencias fijadas (requirements.txt sale de requirements.in con uv pip compile): capa aparte para reutilizar la
# caché de Docker cuando solo cambia el código.
COPY infra/imagen/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -q uv \
    && uv pip install --system --no-cache -q -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

WORKDIR /app

# Código y datos chicos que leen los jobs. Los datos grandes viven en el bucket montado en /datos.
COPY scripts/ scripts/
COPY frontend-demo/scripts/build_m5_web.py frontend-demo/scripts/build_zonas_web.py frontend-demo/scripts/
COPY frontend-demo/data/zonas/casos.json frontend-demo/data/zonas/
COPY data/zonas.json data/regiones.json data/casos_validacion.geojson data/
COPY data/processed/puntaje.parquet data/processed/

# Cada ejecución elige qué hacer con ETAPA y CLOUD_RUN_TASK_INDEX.
ENTRYPOINT ["python", "/app/scripts/cloud/chile/entrada.py"]
