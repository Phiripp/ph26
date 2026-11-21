# Cuenta de servicio de los jobs.
resource "google_service_account" "jobs" {
  account_id   = "caudal-jobs"
  display_name = "Caudal: jobs de la corrida nacional"

  depends_on = [google_project_service.apis]
}

# Los jobs leen y escriben el bucket.
resource "google_storage_bucket_iam_member" "jobs_escritura" {
  bucket = google_storage_bucket.chile.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.jobs.email}"
}

# La web solo lee. No se modifica el servicio caudal-web: solo se le da permiso.
resource "google_storage_bucket_iam_member" "web_lectura" {
  bucket = google_storage_bucket.chile.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${var.cuenta_servicio_web}"
}

# Los jobs leen la clave de CDS (ERA5-Land).
resource "google_secret_manager_secret_iam_member" "jobs_cds" {
  secret_id = google_secret_manager_secret.cds_api_key.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.jobs.email}"
}
