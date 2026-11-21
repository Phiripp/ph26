# Cloud Run Jobs de la corrida nacional. Todos usan la misma imagen pública y el
# mismo punto de entrada (/datos/codigo/arranque.sh, que instala dependencias y
# descomprime el código del bucket). Cada ejecución cambia ETAPA y --tasks con
# `gcloud run jobs execute` (ver outputs.tf); no hace falta redesplegar.
locals {
  # Parámetros de cada job. La clave es un identificador interno; `nombre` y
  # `region` son los de Cloud Run.
  jobs = merge(
    {
      datos = {
        nombre      = "caudal-chile-datos"
        region      = var.region_principal
        cpu         = 4
        memoria     = "8Gi"
        timeout     = "21600s" # 6 h
        max_retries = 2
        entorno     = { ETAPA = "base" } # también sirve para `plan`
      }
      prediccion = {
        nombre      = "caudal-chile-prediccion"
        region      = var.region_principal
        cpu         = 8
        memoria     = "32Gi"
        timeout     = "10800s" # 3 h
        max_retries = 1
        entorno     = { ETAPA = "region" }
      }
    },
    # La etapa satelital es el mismo job repetido en varias regiones para sumar
    # la cuota de cada una; PARTE_BASE desplaza el índice de las tareas.
    {
      for region, parte_base in var.regiones_satelite : "satelite-${region}" => {
        nombre      = "caudal-chile-satelite"
        region      = region
        cpu         = 2
        memoria     = "4Gi"
        timeout     = "21600s" # 6 h
        max_retries = 2
        entorno = {
          ETAPA      = "satelite"
          HILOS      = tostring(var.hilos_satelite)
          PARTE_BASE = tostring(parte_base)
        }
      }
    },
  )

  nombre_volumen = "datos"
}

resource "google_cloud_run_v2_job" "chile" {
  for_each = local.jobs

  name     = each.value.nombre
  location = each.value.region

  # Entorno de hackathon: los jobs se pueden destruir con `terraform destroy`.
  deletion_protection = false

  template {
    # Se sobrescriben en cada ejecución con --tasks y --parallelism.
    task_count = 1

    template {
      service_account       = var.cuenta_servicio
      timeout               = each.value.timeout
      max_retries           = each.value.max_retries
      execution_environment = "EXECUTION_ENVIRONMENT_GEN2" # requerido para montar GCS

      containers {
        image   = var.imagen
        command = ["bash"]
        args    = ["/datos/codigo/arranque.sh"]

        resources {
          limits = {
            cpu    = tostring(each.value.cpu)
            memory = each.value.memoria
          }
        }

        env {
          name  = "CAUDAL_DATA"
          value = "/datos"
        }
        env {
          name  = "CORRIDA"
          value = var.corrida
        }
        dynamic "env" {
          for_each = each.value.entorno
          content {
            name  = env.key
            value = env.value
          }
        }
        env {
          name = "CDS_API_KEY"
          value_source {
            secret_key_ref {
              secret  = var.secreto_cds
              version = "latest"
            }
          }
        }

        volume_mounts {
          name       = local.nombre_volumen
          mount_path = "/datos"
        }
      }

      volumes {
        name = local.nombre_volumen
        gcs {
          bucket    = var.bucket
          read_only = false
          # Caché de metadatos de gcsfuse: menos llamadas al listar carpetas grandes.
          mount_options = ["metadata-cache-ttl-secs=600"]
        }
      }
    }
  }

  # gcloud y la consola anotan estos campos al ejecutar o editar el job.
  lifecycle {
    ignore_changes = [client, client_version]
  }
}
