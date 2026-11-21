# Repositorio Docker de la imagen de los jobs (infra/imagen/). Las imágenes se etiquetan con el commit.
resource "google_artifact_registry_repository" "jobs" {
  repository_id = var.nombre
  location      = var.region
  format        = "DOCKER"
  description   = "Imagen de los Cloud Run Jobs de la corrida nacional de Caudal"

  # Guarda las últimas versiones y borra el resto: cada build agrega una imagen.
  cleanup_policy_dry_run = false
  cleanup_policies {
    id     = "conservar-recientes"
    action = "KEEP"
    most_recent_versions {
      keep_count = var.versiones_a_conservar
    }
  }
  cleanup_policies {
    id     = "borrar-antiguas"
    action = "DELETE"
    condition {
      older_than = "604800s" # 7 días
    }
  }
}

# Cloud Build sube la imagen con esta cuenta (la de Compute por defecto en proyectos nuevos).
resource "google_artifact_registry_repository_iam_member" "build_escritura" {
  repository = google_artifact_registry_repository.jobs.name
  location   = google_artifact_registry_repository.jobs.location
  role       = "roles/artifactregistry.writer"
  member     = "serviceAccount:${var.cuenta_build}"
}

# Los jobs bajan la imagen con su propia cuenta. Las regiones de satélite fuera de us-west1 la bajan igual.
resource "google_artifact_registry_repository_iam_member" "jobs_lectura" {
  repository = google_artifact_registry_repository.jobs.name
  location   = google_artifact_registry_repository.jobs.location
  role       = "roles/artifactregistry.reader"
  member     = "serviceAccount:${var.cuenta_lectura}"
}
