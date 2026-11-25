#!/usr/bin/env bash
# Sube el código y los datos mínimos del POI (tarea M10) a GCS. El Cloud Run Job arranca con una imagen pública de
# Python, instala las dependencias y baja este paquete (no usa Cloud Build ni Artifact Registry).
# Uso: scripts/cloud/poi/desplegar.sh && scripts/cloud/poi/ejecutar.sh [TAREAS] [LIMITE] [CORRIDA]
set -euo pipefail
PROYECTO=${PROYECTO:-ph-26-caudal}
# Cuenta de gcloud: la de CUENTA o, si no se pasa, la cuenta activa (no se deja un correo fijo en el repo).
CUENTA=${CUENTA:-$(gcloud config get-value account 2>/dev/null || true)}
: "${CUENTA:?sin cuenta de gcloud: corre 'gcloud auth login' o pasa CUENTA=correo}"
BUCKET=${BUCKET:-ph-26-caudal-sentinel2}
RAIZ=$(cd "$(dirname "$0")/../../.." && pwd)

# Contexto mínimo: solo lo que lee poi_predio.py (predio.parquet no está en git: sale del disco local).
CTX=$(mktemp -d)
mkdir -p "$CTX/scripts/extract" "$CTX/data/processed"
cp "$RAIZ"/scripts/extract/{poi_predio,serie_sentinel2}.py "$CTX/scripts/extract/"
cp "$RAIZ"/data/{zonas.json,casos_validacion.geojson} "$CTX/data/"
cp "$RAIZ"/data/processed/{predio.parquet,predio_muestra.geojson,derecho.parquet,cauce.parquet,senal_riego.parquet} "$CTX/data/processed/"
tar czf "$CTX/app.tgz" -C "$CTX" scripts data
gcloud --project="$PROYECTO" --account="$CUENTA" storage cp "$CTX/app.tgz" "gs://$BUCKET/poi/codigo/app.tgz"
rm -rf "$CTX"
