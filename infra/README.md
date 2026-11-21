# Infraestructura (Terraform)

Infraestructura de la corrida nacional de [spec-chile.md](../docs/spec-chile.md) en el proyecto `ph-26-caudal`. Terraform crea solo recursos **nuevos**; no toca el bucket `ph-26-caudal-sentinel2`, el job `caudal-poi` ni el servicio `caudal-web`.

## Qué crea

| Archivo | Recursos |
| --- | --- |
| `apis.tf` | APIs: Cloud Run, Storage, Secret Manager, IAM, Resource Manager y Cloud Quotas (`disable_on_destroy = false`: nunca se deshabilitan) |
| `almacenamiento.tf` | Bucket `ph-26-caudal-chile` (us-west1, acceso uniforme, acceso público prohibido, sin versionado) |
| `iam.tf` | Cuenta `caudal-jobs` con `objectAdmin` sobre el bucket y `secretAccessor` sobre el secreto; `objectViewer` del bucket para la cuenta con la que corre `caudal-web` |
| `secreto.tf` | Secreto `CDS_API_KEY` con una versión provisoria `PENDIENTE` |
| `jobs.tf` | Jobs `caudal-chile-datos`, `caudal-chile-prediccion` y `caudal-chile-satelite` (en 4 regiones) |
| `cuota.tf` | Solicitud de cuota de Cloud Run en us-west1: 200 vCPU y 400 GiB (opcional) |
| `bootstrap.sh` | Bucket del estado remoto `ph-26-caudal-tfstate` |

| Job | Región | Recursos | Timeout | Reintentos | `ETAPA` |
| --- | --- | --- | --- | --- | --- |
| `caudal-chile-datos` | us-west1 | 4 vCPU, 8 GiB | 6 h | 2 | `base` (también `plan`) |
| `caudal-chile-satelite` | us-west1, us-west2, us-west4, us-central1 | 2 vCPU, 4 GiB | 6 h | 2 | `satelite` (`HILOS=10`, `PARTE_BASE` = 0, 10, 20, 30) |
| `caudal-chile-prediccion` | us-west1 | 8 vCPU, 32 GiB | 3 h | 1 | `region` |

Todos usan la imagen pública `mirror.gcr.io/library/python:3.12-slim` (no hay Cloud Build), ejecutan `bash /datos/codigo/arranque.sh`, corren como `caudal-jobs` en gen2 y montan el bucket en `/datos` (caché de metadatos de 600 s). Variables de entorno: `CAUDAL_DATA=/datos`, `CORRIDA`, `ETAPA`, `HILOS` y `PARTE_BASE` (solo satélite), más `CDS_API_KEY` desde Secret Manager. Los jobs pueden crearse antes de que exista `codigo/arranque.sh`; fallan recién al ejecutarlos.

## Uso

Requisitos: `terraform` >= 1.6 y `gcloud` con acceso al proyecto.

```bash
# 1. Una sola vez: bucket del estado (no está en git)
infra/bootstrap.sh

# 2. Credenciales (ADC, o un token de la cuenta del equipo)
gcloud auth application-default login
# alternativa: export GOOGLE_OAUTH_ACCESS_TOKEN=$(gcloud auth print-access-token --account <cuenta>)

# 3. Aplicar
cd infra
terraform init
terraform plan
terraform apply
```

La primera vez, la API de Resource Manager debe estar habilitada para que el proveedor lea el estado de las demás. Si `apply` falla por eso, corre `terraform apply -target='google_project_service.apis["cloudresourcemanager.googleapis.com"]'` y después `terraform apply` completo.

El estado remoto vive en `gs://ph-26-caudal-tfstate` (prefijo `chile`, versionado). No se commitean estados, `.terraform/` ni `*.tfvars`; el único secreto, la clave de CDS, no pasa por Terraform. El `.terraform.lock.hcl` sí se commitea para fijar la versión del proveedor.

### Variables

Ver `variables.tf`; todas tienen valor por defecto salvo que se indique. Las útiles:

| Variable | Para qué |
| --- | --- |
| `corrida` | Valor de `CORRIDA` (por defecto `chile-2025-26`) |
| `regiones_satelite` | Regiones de la etapa satelital y su `PARTE_BASE` |
| `correo_contacto` | Correo que Google exige para pedir cuota. Sin él no se pide. Se pasa con `TF_VAR_correo_contacto=...` para no guardarlo en git |

## Pendientes manuales

**Clave de CDS.** Terraform deja `PENDIENTE` como valor inicial y no vuelve a tocar el secreto. Para cargar la clave real:

```bash
printf '%s' "<uid>:<api-key>" | gcloud secrets versions add CDS_API_KEY --data-file=- --project ph-26-caudal
```

Los jobs leen la versión `latest`, así que no hay que redesplegar.

**Cuota.** Con `correo_contacto`, Terraform registra dos preferencias (`CpuAllocPerProjectRegion` = 200000 milli-vCPU y `MemAllocPerProjectRegion` = 429496729600 bytes en us-west1). Es solo una solicitud: Google la aprueba de forma asíncrona, o no. Estado:

```bash
gcloud beta quotas preferences list --project ph-26-caudal
```

Mientras no se apruebe, rige el límite por defecto de 20 vCPU y 40 GiB por región, que es lo que asume el reparto en 4 regiones.

**Montar el bucket en `caudal-web` (decisión pendiente).** Terraform no modifica el servicio. Los permisos de lectura ya están dados. Para montarlo (esto crea una revisión nueva):

```bash
gcloud run services update caudal-web --region southamerica-west1 --project ph-26-caudal \
  --add-volume name=chile,type=cloud-storage,bucket=ph-26-caudal-chile,readonly=true,mount-options=metadata-cache-ttl-secs=600 \
  --add-volume-mount volume=chile,mount-path=/usr/share/nginx/html/data/chile
```

Montar GCS requiere el entorno gen2 (`--execution-environment gen2`). Además, el `Dockerfile` y la configuración de nginx de `frontend-demo/` tendrán que servir `data/chile/` (por ejemplo, la redirección de `data/chile/actual/*` a `data/chile/web/<corrida>/*` que describe la spec) y no copiar una carpeta `data/chile` propia sobre el punto de montaje. Para revertir: `--remove-volume-mount chile --remove-volume chile`.

## Ejecutar cada etapa

`terraform output comandos_ejecucion` imprime estos comandos. `execute` no cambia los recursos del job, y cada etapa tiene su propio job, así que basta con `--tasks` y `--update-env-vars`.

```bash
P="--project ph-26-caudal"

# Plan y base (job de datos, us-west1)
gcloud run jobs execute caudal-chile-datos --region us-west1 $P --tasks 1  --update-env-vars ETAPA=plan
gcloud run jobs execute caudal-chile-datos --region us-west1 $P --tasks 14 --update-env-vars ETAPA=base

# Satélite: 10 tareas en cada una de las 4 regiones (N = 40 partes)
for r in us-west1 us-west2 us-west4 us-central1; do
  gcloud run jobs execute caudal-chile-satelite --region $r $P --tasks 10 --update-env-vars ETAPA=satelite
done

# Predicción por región (14 regiones)
gcloud run jobs execute caudal-chile-prediccion --region us-west1 $P --tasks 14 --update-env-vars ETAPA=region
```

Con la cuota ampliada se pueden lanzar más tareas, por ejemplo `--tasks 100 --parallelism 100` en `us-west1` (el plan se rehace con el nuevo `N`).

## Destruir

`terraform destroy` borra solo lo creado aquí (el bucket falla si tiene objetos; vaciarlo antes es una decisión explícita). Las APIs quedan habilitadas.
