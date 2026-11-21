#!/usr/bin/env bash
# Preparación de GCP para los jobs de scripts/gcp/ (se corre una vez; repetirlo no rompe nada).
#
# Qué hace:
#   1. Revisa que estén gcloud y uv, y que haya sesión en gcloud (si no, abre gcloud auth login).
#   2. Revisa que el proyecto exista, que tengas acceso y que tenga facturación (sin facturación no se crean VMs).
#   3. Habilita las APIs de Compute Engine y Cloud Storage.
#   4. Crea el bucket privado (acceso uniforme, sin acceso público) en la región de las VMs.
#   5. Da a la cuenta de servicio por defecto de Compute permiso de lectura y escritura en el bucket.
#   6. Revisa la cuota de CPU de la región frente a la máquina configurada.
# No cambia la configuración global de gcloud (proyecto por defecto, etc.): todo va con --project.
#
# Uso (desde la raíz del repo): scripts/gcp/bootstrap.sh
# Después: scripts/gcp/job-serie-sentinel2-deploy.sh
set -euo pipefail
# shellcheck source=scripts/gcp/config.sh
source "$(dirname "$0")/config.sh"

paso() { echo; echo "== $*"; }

paso "1. Herramientas y sesión"
command -v gcloud >/dev/null || falla "falta gcloud (https://cloud.google.com/sdk/docs/install)"
command -v uv >/dev/null || echo "aviso: falta uv (curl -LsSf https://astral.sh/uv/install.sh | sh); el deploy lo usa para revisar predio.parquet"
CUENTA=$(gcloud auth list --filter=status:ACTIVE --format='value(account)' 2>/dev/null | head -1)
if [ -z "$CUENTA" ]; then
  echo "Sin sesión en gcloud: abriendo gcloud auth login"
  gcloud auth login
  CUENTA=$(gcloud auth list --filter=status:ACTIVE --format='value(account)' | head -1)
fi
echo "gcloud $(gcloud version --format='value("Google Cloud SDK")' 2>/dev/null), cuenta activa: $CUENTA"

paso "2. Proyecto $PROJECT"
gcloud projects describe "$PROJECT" --format='value(projectId)' >/dev/null 2>&1 \
  || falla "no existe el proyecto $PROJECT o la cuenta $CUENTA no tiene acceso"
FACT=$(gcloud billing projects describe "$PROJECT" --format='value(billingEnabled)' 2>/dev/null || echo "?")
case "$FACT" in
  True) echo "facturación activa" ;;
  False) falla "el proyecto $PROJECT no tiene facturación: actívala en https://console.cloud.google.com/billing/linkedaccount?project=$PROJECT" ;;
  *) echo "aviso: no pude leer la facturación (falta permiso de billing); si la VM no se crea, revisa que esté activa" ;;
esac

paso "3. APIs"
APIS=(compute.googleapis.com storage.googleapis.com)
habilitadas() { gcloud services list --enabled --project "$PROJECT" --format='value(config.name)'; }
faltan() { local h; h=$(habilitadas); for a in "${APIS[@]}"; do grep -qx "$a" <<<"$h" || echo "$a"; done; }
mapfile -t FALTAN < <(faltan)
if [ ${#FALTAN[@]} -eq 0 ]; then
  echo "ya habilitadas: ${APIS[*]}"
else
  # En un proyecto nuevo, Compute tarda 1 a 5 min en habilitarse y `services enable` espera en silencio:
  # se lanza en segundo plano y se muestra el avance.
  echo "habilitando ${FALTAN[*]} (en un proyecto nuevo tarda unos minutos)"
  gcloud services enable "${FALTAN[@]}" --project "$PROJECT" --async >/dev/null
  for i in $(seq 1 40); do
    mapfile -t FALTAN < <(faltan)
    [ ${#FALTAN[@]} -eq 0 ] && break
    [ "$i" -eq 40 ] && falla "después de 10 min siguen sin habilitarse: ${FALTAN[*]}. Revisa https://console.cloud.google.com/apis/dashboard?project=$PROJECT"
    echo "  esperando ${FALTAN[*]} ($((i * 15)) s)"; sleep "${ESPERA_APIS:-15}"
  done
  echo "habilitadas: ${APIS[*]}"
fi

paso "4. Bucket $BUCKET"
if gcloud storage buckets describe "$BUCKET" --project "$PROJECT" >/dev/null 2>&1; then
  echo "ya existe"
else
  gcloud storage buckets create "$BUCKET" --project "$PROJECT" --location "$REGION" \
    --uniform-bucket-level-access --public-access-prevention
  echo "creado en $REGION"
fi

paso "5. Permiso de la VM sobre el bucket"
SA=$(cuenta_servicio)
for i in 1 2 3 4 5 6; do  # recién habilitado Compute, la cuenta de servicio tarda un poco en existir
  if gcloud storage buckets add-iam-policy-binding "$BUCKET" --member "serviceAccount:$SA" \
       --role roles/storage.objectAdmin --project "$PROJECT" >/dev/null 2>&1; then
    echo "$SA: roles/storage.objectAdmin"
    break
  fi
  [ "$i" -eq 6 ] && falla "no pude dar acceso al bucket a $SA (¿existe la cuenta de servicio por defecto de Compute?)"
  echo "esperando la cuenta de servicio $SA ($i/6)"; sleep 20
done

paso "6. Cuota de CPU (global y en $REGION)"
NCPU=${MACHINE##*-}  # e2-highcpu-16 -> 16
# Manda la más chica de: CPUS_ALL_REGIONS (global del proyecto; 12 en proyectos nuevos), CPUS y E2_CPUS de la región
libres() { awk -F, -v m="$1" '$1 == m {print int($2) - int($3)}'; }
FMT='csv[no-heading](quotas.metric,quotas.limit,quotas.usage)'
Q_GLOBAL=$(gcloud compute project-info describe --project "$PROJECT" --flatten quotas --format="$FMT" | libres CPUS_ALL_REGIONS)
Q_REGION=$(gcloud compute regions describe "$REGION" --project "$PROJECT" --flatten quotas --format="$FMT")
Q_CPUS=$(libres CPUS <<<"$Q_REGION"); Q_E2=$(libres E2_CPUS <<<"$Q_REGION")
echo "vCPU libres: global $Q_GLOBAL, $REGION CPUS $Q_CPUS, $REGION E2_CPUS ${Q_E2:-sin límite propio}"
CUOTA=$(printf '%s\n' "$Q_GLOBAL" "$Q_CPUS" "$Q_E2" | grep -E '^-?[0-9]+$' | sort -n | head -1)
if [ -z "$CUOTA" ]; then
  echo "aviso: no pude leer la cuota de CPU"
elif [[ $NCPU =~ ^[0-9]+$ ]] && [ "$CUOTA" -lt "$NCPU" ]; then
  echo "aviso: quedan $CUOTA vCPU de cuota y $MACHINE usa $NCPU."
  CABE=0; for n in 32 16 8 4 2; do [ "$n" -le "$CUOTA" ] && { CABE=$n; break; }; done  # tamaños de e2-highcpu
  if [ "$CABE" -gt 0 ]; then
    echo "  Usa una máquina más chica (MACHINE=e2-highcpu-$CABE HILOS=$((CABE * 2))) o pide más cuota:"
  else
    echo "  No cabe ni una e2-highcpu-2: pide más cuota:"
  fi
  echo "  https://console.cloud.google.com/iam-admin/quotas?project=$PROJECT"
else
  echo "quedan $CUOTA vCPU libres; $MACHINE usa $NCPU"
fi

paso "Listo"
echo "Siguiente: scripts/gcp/job-serie-sentinel2-deploy.sh prueba -- --referencia --temporadas 2025-26:2025-26 --nubes-max 40 --limite 20"
