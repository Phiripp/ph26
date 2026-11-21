#!/usr/bin/env bash
# Corre scripts/extract/serie_sentinel2.py (D1) en una VM de Compute Engine y deja la serie en un bucket de GCS.
#
# Antes, una vez: scripts/gcp/bootstrap.sh (APIs, bucket, permisos y cuota). Este script verifica que esté hecho.
#
# Qué hace:
#   1. Revisa que exista el bucket (si no, pide correr bootstrap.sh).
#   2. Empaqueta el script y sus entradas locales (zonas.json, referencia_secano.parquet, predio_muestra.geojson,
#      fiscalizacion.parquet y, si existe, predio.parquet) y los sube a gs://<bucket>/runs/<run>/input.tar.gz.
#      predio.parquet no está en git: se sube desde tu copia local.
#   3. Crea la VM. Al arrancar instala uv, baja las entradas y el caché compartido (gs://<bucket>/cache), sube HILOS,
#      corre el script (reintenta el comando completo si termina INCOMPLETO), sube la serie, el log y el caché, y
#      se apaga sola. Apagada no cobra CPU (solo el disco, centavos); bórrala al terminar.
#
# Uso (desde la raíz del repo, con `gcloud auth login` hecho):
#   scripts/gcp/job-serie-sentinel2-deploy.sh                                  # referencia de secano 2025-26
#   scripts/gcp/job-serie-sentinel2-deploy.sh referencia -- --referencia --temporadas 2019-20:2025-26 --nubes-max 40
#   scripts/gcp/job-serie-sentinel2-deploy.sh elegibles-2025-26 -- --elegibles --temporadas 2025-26:2025-26 --nubes-max 40
#   scripts/gcp/job-serie-sentinel2-deploy.sh prueba -- --referencia --temporadas 2025-26:2025-26 --nubes-max 40 --limite 20
# Las series en git usan --nubes-max 40 (ver data/README.md); sin él, el script toma 70 y salen más escenas.
#
# El primer argumento es el nombre de la corrida (minúsculas, números y guiones): nombra la VM (job-s2-<run>),
# la carpeta gs://<bucket>/runs/<run>/ y la salida serie_<run>.parquet. Lo que va después de -- se pasa tal cual
# a serie_sentinel2.py; no pongas --salida, la fija este script.
#
# Proyecto, región, bucket, máquina e hilos: scripts/gcp/config.sh (cada uno se cambia con una variable de entorno).
# La cuota global del proyecto es de 12 vCPU: una VM de 8 a la vez. Borra la VM anterior antes de lanzar otra.
set -euo pipefail
# shellcheck source=scripts/gcp/config.sh
source "$(dirname "$0")/config.sh"

RUN=${1:-referencia-2025-26}
[ $# -gt 0 ] && shift
[ "${1:-}" = "--" ] && shift
ARGS=${*:-"--referencia --temporadas 2025-26:2025-26 --nubes-max 40"}

VM="job-s2-$RUN"
DEST="$BUCKET/runs/$RUN"

[[ $RUN =~ ^[a-z0-9]([a-z0-9-]*[a-z0-9])?$ ]] || falla "el nombre de la corrida '$RUN' solo admite minúsculas, números y guiones"
[ ${#VM} -le 63 ] || falla "nombre de corrida demasiado largo (la VM '$VM' supera 63 caracteres)"
[[ " $ARGS " == *" --salida"* ]] && falla "no pases --salida: la salida es serie_$RUN.parquet en $DEST/"
command -v gcloud >/dev/null || falla "falta gcloud (https://cloud.google.com/sdk/docs/install)"
[ -n "$(gcloud auth list --filter=status:ACTIVE --format='value(account)' 2>/dev/null)" ] || falla "no hay sesión: corre gcloud auth login"

RAIZ=$(git rev-parse --show-toplevel 2>/dev/null) || falla "corre el script dentro del repo"
cd "$RAIZ"

# Entradas: las que lee serie_sentinel2.py según el modo. predio.parquet es local (no va a git).
ENTRADAS=(scripts/extract/serie_sentinel2.py data/zonas.json data/processed/referencia_secano.parquet
          data/processed/predio_muestra.geojson data/processed/fiscalizacion.parquet)
for f in "${ENTRADAS[@]}"; do [ -f "$f" ] || falla "falta $f"; done
if [[ " $ARGS " =~ \ --(elegibles|validacion|todos|predios)\  ]]; then
  [ -f data/processed/predio.parquet ] || falla "este modo necesita data/processed/predio.parquet (local, no está en git)"
  uv run -q --with pyarrow python -c "
import pyarrow.parquet as pq, sys
c = pq.read_schema('data/processed/predio.parquet').names
sys.exit(0 if 'elegible' in c else 'predio.parquet no tiene la columna elegible: regenéralo con predios_ciren.py')" \
    || falla "predio.parquet desactualizado"
fi
[ -f data/processed/predio.parquet ] && ENTRADAS+=(data/processed/predio.parquet)
if [[ " $ARGS " =~ \ --predios\ ([^ ]+) ]]; then
  [ -f "${BASH_REMATCH[1]}" ] || falla "no existe el archivo de --predios ${BASH_REMATCH[1]}"
  ENTRADAS+=("${BASH_REMATCH[1]}")
fi

echo "Proyecto $PROJECT, VM $VM ($MACHINE, $ZONE), $HILOS hilos"
echo "Corrida '$RUN': serie_sentinel2.py $ARGS"
echo "Salida: $DEST/serie_$RUN.parquet"

gcloud storage buckets describe "$BUCKET" --project "$PROJECT" >/dev/null 2>&1 \
  || falla "no existe el bucket $BUCKET: corre primero scripts/gcp/bootstrap.sh"
SA=$(cuenta_servicio)  # con ella corre la VM; bootstrap.sh le dio acceso al bucket

if gcloud compute instances describe "$VM" --zone "$ZONE" --project "$PROJECT" >/dev/null 2>&1; then
  falla "ya existe la VM $VM. Bórrala (gcloud compute instances delete $VM --zone $ZONE --project $PROJECT) o usa otro nombre de corrida"
fi

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
tar czf "$TMP/input.tar.gz" "${ENTRADAS[@]}"
gcloud storage cp "$TMP/input.tar.gz" "$DEST/input.tar.gz" --project "$PROJECT"
gcloud storage rm "$DEST/DONE" --project "$PROJECT" >/dev/null 2>&1 || true
printf '%s' "$ARGS" > "$TMP/args.txt"

cat > "$TMP/startup.sh" <<'STARTUP'
#!/bin/bash
# Corre en la VM como root en cada arranque. Si la corrida ya terminó, solo apaga.
set -uo pipefail
export HOME=/root PATH=/usr/local/bin:$PATH
md() { curl -sf -H "Metadata-Flavor: Google" "http://metadata.google.internal/computeMetadata/v1/instance/attributes/$1"; }
BUCKET=$(md job-bucket); RUN=$(md job-run); ARGS=$(md job-args); HILOS=$(md job-hilos); INTENTOS=$(md job-intentos)
W=/opt/job; LOG=$W/job.log; DEST="$BUCKET/runs/$RUN"; SALIDA=data/processed/serie_$RUN.parquet
mkdir -p "$W"; cd "$W" || exit 1
if [ -f "$W/DONE" ]; then shutdown -h now; exit 0; fi
exec > >(tee -a "$LOG") 2>&1
echo "[$(date -Is)] inicio: run=$RUN hilos=$HILOS args=$ARGS"


# Log al bucket cada 2 minutos, con la memoria usada (rc=137 al terminar = el sistema mató el proceso por memoria)
( while true; do
    free -m | awk -v t="$(date -Is)" '/^Mem:/ {print "[" t "] memoria usada " $3 " de " $2 " MB"}'
    gcloud storage cp -q "$LOG" "$DEST/job.log" || true; sleep 120
  done ) &

fin() {  # deja la marca DONE (local y en el bucket), sube el log y apaga: una VM apagada no cobra CPU
  echo "[$(date -Is)] fin: rc=$1"
  echo "$1" > "$W/DONE"
  gcloud storage cp "$LOG" "$DEST/job.log"
  echo "$1" | gcloud storage cp - "$DEST/DONE"
  shutdown -h now
  exit "$1"
}

if ! gcloud storage cp "$DEST/input.tar.gz" . || ! tar xzf input.tar.gz; then
  echo "no pude bajar o abrir las entradas"; fin 2
fi
mkdir -p data/raw/s2
# Caché compartido entre corridas: los nombres llevan escena, modo y versión (_v2), así que no se mezclan
gcloud storage rsync -r "$BUCKET/cache" data/raw/s2 || true
sed -i "s/^HILOS = .*/HILOS = $HILOS/" scripts/extract/serie_sentinel2.py
curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin INSTALLER_NO_MODIFY_PATH=1 sh
command -v uv >/dev/null || { echo "no se instaló uv"; fin 2; }

rc=1
for i in $(seq 1 "$INTENTOS"); do
  # shellcheck disable=SC2086  # ARGS se separa en palabras a propósito
  uv run scripts/extract/serie_sentinel2.py $ARGS --salida "$SALIDA"
  rc=$?
  gcloud storage rsync -r data/raw/s2 "$BUCKET/cache" || true
  [ "$rc" -eq 0 ] && break
  echo "[$(date -Is)] intento $i/$INTENTOS terminó con rc=$rc; el siguiente lee el caché y pide solo lo que falta"
  sleep 60
done

[ -f "$SALIDA" ] && gcloud storage cp "$SALIDA" "$DEST/"
fin "$rc"
STARTUP

gcloud compute instances create "$VM" --project "$PROJECT" --zone "$ZONE" --machine-type "$MACHINE" \
  --image-family debian-12 --image-project debian-cloud --boot-disk-size "${DISCO_GB}GB" --boot-disk-type pd-balanced \
  --service-account "$SA" --scopes cloud-platform \
  --metadata "job-bucket=$BUCKET,job-run=$RUN,job-hilos=$HILOS,job-intentos=$INTENTOS" \
  --metadata-from-file "startup-script=$TMP/startup.sh,job-args=$TMP/args.txt"

cat <<EOF

VM $VM creada. La corrida parte sola en ~1 minuto y la VM se apaga al terminar.

Seguir el avance (el log se sube cada 2 min):
  gcloud storage cat $DEST/job.log | tail -20
  gcloud compute ssh $VM --zone $ZONE --project $PROJECT -- sudo tail -f /opt/job/job.log

Terminó cuando existe $DEST/DONE (0 = completa; 1 = INCOMPLETO después de $INTENTOS intentos; 2 = falló el arranque; 137 = sin memoria):
  gcloud storage cat $DEST/DONE

Bajar la serie:
  gcloud storage cp $DEST/serie_$RUN.parquet data/processed/

Borrar la VM al terminar (el caché y la serie quedan en el bucket):
  gcloud compute instances delete $VM --zone $ZONE --project $PROJECT --quiet
EOF
