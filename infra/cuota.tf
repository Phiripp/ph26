# Solicitud de más cuota de Cloud Run en la región principal (200 vCPU y 400 GiB).
# Es solo una petición: Google la aprueba (o no) de forma asíncrona. Estado:
#   gcloud beta quotas preferences list --project ph-26-caudal
resource "google_cloud_quotas_quota_preference" "cpu" {
  count = var.correo_contacto == null ? 0 : 1

  contact_email = var.correo_contacto
  parent        = "projects/${var.proyecto}"
  name          = "caudal-run-cpu-${var.region}"
  service       = "run.googleapis.com"
  quota_id      = "CpuAllocPerProjectRegion"
  dimensions    = { region = var.region }
  justification = "Corrida nacional de Caudal (hackathon): lectura de Sentinel-2 en paralelo."

  quota_config {
    preferred_value = var.cuota_cpu_milli
  }

  depends_on = [google_project_service.apis]
}

resource "google_cloud_quotas_quota_preference" "memoria" {
  count = var.correo_contacto == null ? 0 : 1

  contact_email = var.correo_contacto
  parent        = "projects/${var.proyecto}"
  name          = "caudal-run-mem-${var.region}"
  service       = "run.googleapis.com"
  quota_id      = "MemAllocPerProjectRegion"
  dimensions    = { region = var.region }
  justification = "Corrida nacional de Caudal (hackathon): lectura de Sentinel-2 en paralelo."

  quota_config {
    preferred_value = var.cuota_memoria_bytes
  }

  depends_on = [google_project_service.apis]
}
