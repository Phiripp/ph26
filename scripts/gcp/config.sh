# Configuración compartida de los scripts de scripts/gcp/ (se carga con `source`; no se ejecuta sola).
# Cada valor se puede cambiar con una variable de entorno, p. ej. MACHINE=e2-highcpu-8 HILOS=16 scripts/gcp/...
# us-west1 (Oregón) está cerca del bucket de Earth Search (AWS us-west-2).
# shellcheck shell=bash disable=SC2034  # las variables se usan en los scripts que cargan este archivo
PROJECT=${PROJECT:-ph-26-caudal}
REGION=${REGION:-us-west1}
ZONE=${ZONE:-us-west1-b}
BUCKET=${BUCKET:-gs://ph-26-caudal-sentinel2}
# 8 vCPU: la cuota global de ph-26-caudal es de 12 (CPUS_ALL_REGIONS). highmem (64 GB): con --referencia o
# --elegibles cada hilo lee ventanas de casi un tile completo; e2-highcpu-8 (8 GB) con 24 hilos murió por memoria.
MACHINE=${MACHINE:-e2-highmem-8}
HILOS=${HILOS:-16}  # ~4 GB por hilo; el log de la VM registra la memoria usada cada 2 min
INTENTOS=${INTENTOS:-3}
DISCO_GB=${DISCO_GB:-30}

falla() { echo "ERROR: $*" >&2; exit 1; }

# Cuenta de servicio por defecto de Compute: con ella corre la VM del job.
cuenta_servicio() {
  local num
  num=$(gcloud projects describe "$PROJECT" --format='value(projectNumber)') || falla "no puedo leer el proyecto $PROJECT"
  echo "$num-compute@developer.gserviceaccount.com"
}
