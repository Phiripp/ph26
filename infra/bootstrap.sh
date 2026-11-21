#!/usr/bin/env bash
# Crea el bucket del estado remoto de Terraform (una sola vez; es idempotente).
# Es lo único que Terraform no puede administrar solo (huevo y gallina).
# Uso: infra/bootstrap.sh   (usa la cuenta activa de gcloud o CLOUDSDK_CORE_ACCOUNT)
set -euo pipefail

PROYECTO="${PROYECTO:-ph-26-caudal}"
BUCKET="${BUCKET_ESTADO:-ph-26-caudal-tfstate}"
REGION="${REGION:-us-west1}"

if gcloud storage buckets describe "gs://${BUCKET}" --project "${PROYECTO}" >/dev/null 2>&1; then
  echo "El bucket gs://${BUCKET} ya existe."
else
  gcloud storage buckets create "gs://${BUCKET}" \
    --project "${PROYECTO}" \
    --location "${REGION}" \
    --uniform-bucket-level-access \
    --public-access-prevention
fi

# Versionado: permite recuperar un estado anterior si algo sale mal.
gcloud storage buckets update "gs://${BUCKET}" --project "${PROYECTO}" --versioning
echo "Listo. Ahora: cd infra && terraform init"
