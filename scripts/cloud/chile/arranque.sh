#!/usr/bin/env bash
# Arranque de los Cloud Run Jobs de la corrida nacional: `bash /datos/codigo/arranque.sh` en la imagen pública de Python.
# Instala las dependencias con uv, descomprime el código del bucket montado (lo sube subir_codigo.sh) y entrega el control
# a entrada.py, que elige qué hacer según ETAPA y CLOUD_RUN_TASK_INDEX. Mismo patrón que scripts/cloud/poi/ejecutar.sh.
set -euo pipefail
APP=/app
DATOS=${CAUDAL_DATA:-/datos}

apt-get update -qq
apt-get install -y -qq --no-install-recommends libexpat1 >/dev/null
pip install -q --no-cache-dir uv
# Unión de los encabezados PEP 723 de los scripts que corren en los jobs (extract, models, cloud/chile, build_m5_web).
uv pip install --system -q 'geopandas>=1.0' pyarrow 'shapely>=2.0' rasterio pystac-client numpy pandas scipy \
  scikit-learn requests pyproj python-calamine truststore xarray zarr dask fsspec aiohttp

mkdir -p "$APP"
tar xzf "$DATOS/codigo/app.tgz" -C "$APP"
cd "$APP"
export MPLBACKEND=Agg
exec python "$APP/scripts/cloud/chile/entrada.py"
