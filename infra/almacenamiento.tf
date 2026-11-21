# Bucket de la corrida nacional: código, datos base, series Sentinel-2 y resultados.
# Se monta como volumen en los jobs (/datos) y, más adelante, en caudal-web.
resource "google_storage_bucket" "chile" {
  name     = var.bucket_chile
  location = var.region

  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"

  versioning {
    enabled = false
  }

  depends_on = [google_project_service.apis]
}
