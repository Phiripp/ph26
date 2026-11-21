# Habilita las APIs necesarias. Al destruir NO se deshabilitan: otros recursos
# del proyecto (caudal-web, caudal-poi) dependen de ellas.
locals {
  apis = [
    "run.googleapis.com",
    "storage.googleapis.com",
    "secretmanager.googleapis.com",
    "iam.googleapis.com",
    "cloudresourcemanager.googleapis.com", # la usa el proveedor para leer el estado de las APIs
    "cloudquotas.googleapis.com",
  ]
}

resource "google_project_service" "apis" {
  for_each = toset(local.apis)

  service            = each.value
  disable_on_destroy = false
}
