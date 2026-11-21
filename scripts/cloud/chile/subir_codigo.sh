#!/usr/bin/env bash
# Empaqueta el código de la corrida nacional y lo sube al bucket (codigo/app.tgz, codigo/arranque.sh y
# config/regiones.json). Los jobs lo bajan al arrancar (arranque.sh); no hay Cloud Build ni imagen propia.
# Uso: scripts/cloud/chile/subir_codigo.sh [--regenerar]   (--regenerar vuelve a armar data/regiones.json desde CIREN)
set -euo pipefail
PROYECTO=${PROYECTO:-ph-26-caudal}
CUENTA=${CUENTA:-gacuna.latam.challenge@gmail.com}
BUCKET=${BUCKET:-ph-26-caudal-chile}
RAIZ=$(cd "$(dirname "$0")/../../.." && pwd)
g() { gcloud --project="$PROYECTO" --account="$CUENTA" "$@"; }

[ "${1:-}" = "--regenerar" ] && uv run "$RAIZ/scripts/cloud/chile/regiones.py"

# Contenido: scripts/, la exportación web (build_m5_web.py y lo que importa), las zonas y regiones, y lo que usa la
# comprobación de regresión (puntaje de Z1 y Z2 y los 10 casos de validación).
CTX=$(mktemp -d)
trap 'rm -rf "$CTX"' EXIT
mkdir -p "$CTX/frontend-demo/scripts" "$CTX/frontend-demo/data/zonas" "$CTX/data/processed"
cp -r "$RAIZ/scripts" "$CTX/"
find "$CTX/scripts" -name __pycache__ -type d -prune -exec rm -rf {} +
rm -rf "$CTX/scripts/pruebas_datos"
cp "$RAIZ"/frontend-demo/scripts/{build_m5_web,build_zonas_web}.py "$CTX/frontend-demo/scripts/"
cp "$RAIZ/frontend-demo/data/zonas/casos.json" "$CTX/frontend-demo/data/zonas/"
cp "$RAIZ"/data/{zonas.json,regiones.json,casos_validacion.geojson} "$CTX/data/"
cp "$RAIZ/data/processed/puntaje.parquet" "$CTX/data/processed/"
tar czf "$CTX/app.tgz" -C "$CTX" scripts frontend-demo data

g storage cp "$CTX/app.tgz" "$RAIZ/scripts/cloud/chile/arranque.sh" "gs://$BUCKET/codigo/"
g storage cp "$RAIZ/data/regiones.json" "gs://$BUCKET/config/regiones.json"
echo "subido: gs://$BUCKET/codigo/{app.tgz,arranque.sh} y gs://$BUCKET/config/regiones.json"
