#!/usr/bin/env bash
# Crea o actualiza el Cloud Run Job `caudal-poi` y lo lanza. Resultados en gs://BUCKET/poi/CORRIDA/.
# Uso: scripts/cloud/poi/ejecutar.sh [TAREAS=20] [LIMITE=0] [CORRIDA=fecha]   (LIMITE>0: prueba con los primeros N predios)
set -euo pipefail
PROYECTO=${PROYECTO:-ph-26-caudal}
# Cuenta de gcloud: la de CUENTA o, si no se pasa, la cuenta activa (no se deja un correo fijo en el repo).
CUENTA=${CUENTA:-$(gcloud config get-value account 2>/dev/null || true)}
: "${CUENTA:?sin cuenta de gcloud: corre 'gcloud auth login' o pasa CUENTA=correo}"
REGION=${REGION:-us-west1}          # misma región que el bucket y cerca de Earth Search (AWS Oregón)
BUCKET=${BUCKET:-ph-26-caudal-sentinel2}
IMAGEN=${IMAGEN:-mirror.gcr.io/library/python:3.12-slim}
TAREAS=${1:-20}
LIMITE=${2:-0}
CORRIDA=${3:-$(date +%Y%m%d-%H%M)}
WORKERS=${WORKERS:-20}              # predios en paralelo por tarea (procesos); cada predio usa unos 5 s de CPU
# Cuota regional de Cloud Run en este proyecto: 20 vCPU y 40 GiB en total -> 5 tareas de 4 vCPU y 8 GiB a la vez.
PARALELO=${PARALELO:-5}
CPU=${CPU:-4}; MEMORIA=${MEMORIA:-8Gi}
g() { gcloud --project="$PROYECTO" --account="$CUENTA" "$@"; }

ARRANQUE="apt-get update -qq && apt-get install -y -qq --no-install-recommends libexpat1 >/dev/null \
&& pip install -q --no-cache-dir 'geopandas>=1.0' pyarrow 'shapely>=2.0' rasterio pystac-client numpy pandas scipy requests matplotlib google-cloud-storage \
&& python -c \"from google.cloud import storage; storage.Client().bucket('$BUCKET').blob('poi/codigo/app.tgz').download_to_filename('/tmp/app.tgz')\" \
&& mkdir -p /app && tar xzf /tmp/app.tgz -C /app && cd /app && MPLBACKEND=Agg exec python scripts/extract/poi_predio.py \"\$@\""
ARGS="^|^-c|$ARRANQUE|poi|--elegibles|--workers=$WORKERS|--silencio|--salida-gcs=gs://$BUCKET/poi/$CORRIDA"
[ "$LIMITE" -gt 0 ] && ARGS="$ARGS|--limit=$LIMITE"
COMUN=(--image="$IMAGEN" --region="$REGION" --tasks="$TAREAS" --parallelism="$PARALELO" --cpu="$CPU" --memory="$MEMORIA"
       --task-timeout=6h --max-retries=1 --command=bash --args="$ARGS")
if g run jobs describe caudal-poi --region="$REGION" >/dev/null 2>&1; then g run jobs update caudal-poi "${COMUN[@]}"
else g run jobs create caudal-poi "${COMUN[@]}"; fi
g run jobs execute caudal-poi --region="$REGION" --async
echo "resultados: gs://$BUCKET/poi/$CORRIDA/"
