output "id_secreto" {
  description = "Nombre del secreto, para referenciarlo desde los jobs."
  value       = google_secret_manager_secret.cds_api_key.secret_id
}
