#!/usr/bin/env bash
# Construye la imagen de los jobs con Cloud Build y la sube a Artifact Registry, etiquetada con el commit actual.
# Después hay que apuntar los jobs a esa versión con Terraform (lo imprime al final).
# Uso (desde cualquier carpeta del repo, con el árbol limpio): infra/imagen/construir.sh
set -euo pipefail

PROYECTO="${PROYECTO:-ph-26-caudal}"
REGION="${REGION:-us-west1}"
RAIZ=$(git rev-parse --show-toplevel)
cd "$RAIZ"

# La etiqueta es el commit: la imagen tiene que poder reconstruirse desde git.
if [ -n "$(git status --porcelain -- scripts data frontend-demo/scripts infra/imagen)" ]; then
  echo "Hay cambios sin commitear en lo que va a la imagen; commitéalos antes de construir." >&2
  exit 1
fi
VERSION=$(git rev-parse --short=12 HEAD)

gcloud builds submit "$RAIZ" \
  --project "$PROYECTO" \
  --region "$REGION" \
  --config infra/imagen/cloudbuild.yaml \
  --substitutions "_VERSION=${VERSION}"

echo
echo "Imagen: ${REGION}-docker.pkg.dev/${PROYECTO}/caudal-jobs/pipeline:${VERSION}"
echo "Para usarla en los jobs:"
echo "  cd infra/entornos/prod && terraform apply -var version_imagen=${VERSION}"
