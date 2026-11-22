#!/usr/bin/env bash
# Construye la imagen de caudal-api con los datos de data/processed/ y la despliega en Cloud Run.
#
# Qué hace:
#   1. Arma un contexto mínimo: api/, scripts/models/, scripts/comun/ y los datos que lee la API (los Parquet menos las series crudas,
#      las rutas, impacto.json, zonas.json, demo.json, los casos). predio.parquet no está en git: sale del disco local.
#   2. Escribe data/VERSION (commit y fecha de cálculo de puntaje.parquet): es la versión que muestra /api/health.
#   3. Construye la imagen: con Docker en local si está, y si no con Cloud Build (CONSTRUIR=cloud lo fuerza). Al
#      construir se generan los expedientes de la demo (data/demo.json), con red.
#   4. Sube la imagen a Artifact Registry y despliega el servicio con los parámetros de docs/spec-demo.md.
#
# Uso (desde cualquier carpeta del repo, con `gcloud auth login` hecho):
#   scripts/cloud/api/desplegar.sh                       construye, sube y despliega
#   SOLO_IMAGEN=1 scripts/cloud/api/desplegar.sh         solo construye la imagen local `caudal-api`, para probar:
#       docker run --rm -p 8080:8080 caudal-api          y luego  curl localhost:8080/api/health
#   ORIGENES=https://caudal-web-xxxx.run.app scripts/cloud/api/desplegar.sh    fija el origen de CORS a mano
#   REGION=us-central1 CONSTRUIR=cloud scripts/cloud/api/desplegar.sh          otra región, construyendo con Cloud Build
#
# Corrida nacional: el servicio monta el bucket privado BUCKET (solo lectura, GCS FUSE, requiere gen2) en /datos y
# lee CAUDAL_NACIONAL=/datos/modelo/$CORRIDA para servir /api/chile. La cuenta de servicio de Cloud Run necesita
# roles/storage.objectViewer en el bucket. Si el montaje falta, el resto de la API responde igual y /api/chile da 503.
#   BUCKET=otro-bucket CORRIDA=chile-2025-26 scripts/cloud/api/desplegar.sh    cambia el bucket o la corrida
#
# Para actualizar los datos se corre de nuevo: cada despliegue es una revisión, y se vuelve atrás con
#   gcloud run services update-traffic caudal-api --region southamerica-west1 --to-revisions=REVISION=100
set -euo pipefail
PROYECTO=${PROYECTO:-ph-26-caudal}
REGION=${REGION:-southamerica-west1}
SERVICIO=${SERVICIO:-caudal-api}
WEB=${WEB:-caudal-web}
BUCKET=${BUCKET:-ph-26-caudal-chile}
CORRIDA=${CORRIDA:-chile-2025-26}
REPO=${REPO:-caudal}
RAIZ=$(cd "$(dirname "$0")/../../.." && pwd)
cd "$RAIZ"

falla() { echo "ERROR: $*" >&2; exit 1; }
[ -f data/processed/predio.parquet ] || falla "falta data/processed/predio.parquet (no está en git): uv run scripts/extract/predios_ciren.py"
[ -z "$(git status --porcelain -- api scripts/models scripts/comun data)" ] || echo "AVISO: hay cambios sin commit en api/, scripts/models/ o data/: la versión dirá $(git rev-parse --short HEAD) igual" >&2

COMMIT=$(git rev-parse --short HEAD)
CTX=$(mktemp -d)
trap 'rm -rf "$CTX"' EXIT
mkdir -p "$CTX/scripts" "$CTX/data/processed"
cp -R api "$CTX/api"
cp -R scripts/models "$CTX/scripts/models"
cp -R scripts/comun "$CTX/scripts/comun"  # los modelos importan comun.rutas
find "$CTX" -name __pycache__ -type d -prune -exec rm -rf {} +
cp data/zonas.json data/demo.json data/casos_validacion.geojson "$CTX/data/"
for f in data/processed/*.parquet data/processed/ruta_z?.* data/processed/impacto.json data/processed/calibracion_grilla.csv \
         data/processed/predio_muestra.geojson; do
  case "$(basename "$f")" in serie_*|referencia_secano.parquet) continue ;; esac  # series crudas: la API no las lee
  cp "$f" "$CTX/data/processed/"
done
cat > "$CTX/data/VERSION" <<JSON
{"commit": "$COMMIT", "calculado": "$(git log -1 --format=%cI -- data/processed/puntaje.parquet)", "imagen": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"}
JSON
echo "Contexto: $(du -sh "$CTX" | cut -f1) · versión $COMMIT"

if [ -n "${SOLO_IMAGEN:-}" ]; then
  docker build -t caudal-api -f "$CTX/api/Dockerfile" "$CTX"
  echo "Imagen local lista: docker run --rm -p 8080:8080 caudal-api"
  exit 0
fi

command -v gcloud >/dev/null || falla "falta gcloud (https://cloud.google.com/sdk/docs/install)"
IMAGEN="$REGION-docker.pkg.dev/$PROYECTO/$REPO/$SERVICIO:$COMMIT"
gcloud artifacts repositories describe "$REPO" --project "$PROYECTO" --location "$REGION" >/dev/null 2>&1 \
  || gcloud artifacts repositories create "$REPO" --project "$PROYECTO" --location "$REGION" --repository-format docker \
       --description "Imágenes de Caudal"
CONSTRUIR=${CONSTRUIR:-$(command -v docker >/dev/null && docker info >/dev/null 2>&1 && echo local || echo cloud)}
if [ "$CONSTRUIR" = local ]; then
  gcloud auth configure-docker "$REGION-docker.pkg.dev" --quiet
  docker build --platform linux/amd64 -t "$IMAGEN" -f "$CTX/api/Dockerfile" "$CTX"
  docker push "$IMAGEN"
else
  # Cloud Build pide el Dockerfile en la raíz del contexto. Sube el contexto mínimo de arriba, no el repo.
  cp "$CTX/api/Dockerfile" "$CTX/Dockerfile"
  gcloud builds submit "$CTX" --project "$PROYECTO" --region "$REGION" --tag "$IMAGEN" --timeout 1200s
fi

# CORS: solo la página. Si caudal-web ya está desplegado, se toma su URL; si no, se pasa con ORIGENES=...
ORIGENES=${ORIGENES:-$(gcloud run services describe "$WEB" --project "$PROYECTO" --region "$REGION" --format 'value(status.url)' 2>/dev/null || true)}
[ -n "$ORIGENES" ] || echo "AVISO: sin ORIGENES y sin $WEB desplegado: la página no podrá llamar a la API hasta fijar CAUDAL_ORIGENES" >&2

gcloud run deploy "$SERVICIO" --project "$PROYECTO" --region "$REGION" --image "$IMAGEN" --allow-unauthenticated \
  --cpu 2 --memory 2Gi --concurrency 20 --timeout 300 --min-instances 1 --max-instances 2 \
  --execution-environment gen2 \
  --add-volume "name=datos,type=cloud-storage,bucket=$BUCKET,readonly=true" --add-volume-mount "volume=datos,mount-path=/datos" \
  --set-env-vars "^;^CAUDAL_ORIGENES=$ORIGENES;CAUDAL_NACIONAL=/datos/modelo/$CORRIDA"
URL=$(gcloud run services describe "$SERVICIO" --project "$PROYECTO" --region "$REGION" --format 'value(status.url)')
echo "Desplegado: $URL"
curl -fsS "$URL/api/health" && echo
