# Cuenta de servicio con la que corren los jobs.
resource "google_service_account" "jobs" {
  account_id   = var.id_cuenta
  display_name = var.nombre_visible
}
