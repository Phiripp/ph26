# Bucket de la corrida nacional: código, datos base, series Sentinel-2 y resultados.
# Se monta como volumen en los jobs (/datos) y, más adelante, en caudal-web.
resource "google_storage_bucket" "chile" {
  name     = var.nombre
  location = var.region

  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"

  versioning {
    enabled = false
  }
}

# Los jobs leen y escriben el bucket.
resource "google_storage_bucket_iam_member" "jobs_escritura" {
  bucket = google_storage_bucket.chile.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${var.cuenta_escritura}"
}

# La web solo lee. No se modifica el servicio caudal-web: solo se le da permiso.
resource "google_storage_bucket_iam_member" "web_lectura" {
  bucket = google_storage_bucket.chile.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${var.cuenta_lectura}"
}
