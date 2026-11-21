# Clave de la API de CDS (ERA5-Land). Terraform solo crea el secreto con un valor
# provisorio; la clave real se agrega a mano y no pasa por el código ni por git:
#   printf '%s' "<uid>:<api-key>" | gcloud secrets versions add CDS_API_KEY --data-file=- --project ph-26-caudal
resource "google_secret_manager_secret" "cds_api_key" {
  secret_id = "CDS_API_KEY"

  replication {
    auto {}
  }

  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_version" "provisoria" {
  secret      = google_secret_manager_secret.cds_api_key.id
  secret_data = "PENDIENTE"

  # Las versiones nuevas (la clave real) se agregan con gcloud; Terraform no las toca.
  lifecycle {
    ignore_changes = [secret_data, enabled]
  }
}
