#!/usr/bin/env bash
# Avance de la corrida nacional: escenas del plan contra escenas en s2/cache, regiones con base y predicción terminadas,
# últimas ejecuciones de cada job y las últimas líneas del log más reciente.
# Uso: scripts/cloud/chile/progreso.sh [LINEAS_DE_LOG=15]     (CORRIDA=... para otra corrida que la de hoy)
set -euo pipefail
PROYECTO=${PROYECTO:-ph-26-caudal}
# Cuenta de gcloud: la de CUENTA o, si no se pasa, la cuenta activa (no se deja un correo fijo en el repo).
CUENTA=${CUENTA:-$(gcloud config get-value account 2>/dev/null || true)}
: "${CUENTA:?sin cuenta de gcloud: corre 'gcloud auth login' o pasa CUENTA=correo}"
BUCKET=${BUCKET:-ph-26-caudal-chile}
CORRIDA=${CORRIDA:-$(date +%Y%m%d)}
LINEAS=${1:-15}
g() { gcloud --project="$PROYECTO" --account="$CUENTA" "$@"; }
B="gs://$BUCKET"

cuenta() { grep -c . || true; }

echo "== Datos (base)"
echo "regiones con base terminada: $(g storage ls "$B/base/_estado/" 2>/dev/null | cuenta) de 14"
echo "== Satélite"
planeadas=$(g storage cat "$B/plan/partes/*.jsonl" 2>/dev/null | cuenta)
hechas=$(g storage ls "$B/s2/cache/**" 2>/dev/null | grep '_chile_v2.parquet$' | cuenta)
echo "escenas del plan: $planeadas; en caché: $hechas"
echo "== Predicción ($CORRIDA)"
echo "regiones terminadas: $(g storage ls "$B/modelo/$CORRIDA/*/puntaje.parquet" 2>/dev/null | cuenta) de 14"
echo "web/ACTUAL: $(g storage cat "$B/web/ACTUAL" 2>/dev/null || echo 'sin publicar')"
echo "== Ejecuciones"
g run jobs executions list --job=caudal-chile-datos --region=us-west1 --limit=3 2>/dev/null || true
for r in us-west1 us-west2 us-west4 us-central1; do
  g run jobs executions list --job=caudal-chile-satelite --region="$r" --limit=2 2>/dev/null || true
done
g run jobs executions list --job=caudal-chile-prediccion --region=us-west1 --limit=3 2>/dev/null || true
echo "== Último log"
ultimo=$(g storage ls -l "$B/logs/**" 2>/dev/null | grep -v TOTAL | sort -k2 | tail -1 | awk '{print $3}')
if [ -n "${ultimo:-}" ]; then echo "$ultimo"; g storage cat "$ultimo" | tail -n "$LINEAS"; else echo "sin logs todavía"; fi
