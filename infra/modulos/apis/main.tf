# Habilita las APIs del proyecto. Al destruir NO se deshabilitan: otros recursos
# del proyecto (caudal-web, caudal-poi) dependen de ellas.
resource "google_project_service" "apis" {
  for_each = toset(var.servicios)

  service            = each.value
  disable_on_destroy = false
}
