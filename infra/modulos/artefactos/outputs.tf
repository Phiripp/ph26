output "url" {
  description = "Prefijo de las imágenes del repositorio (sin nombre de imagen ni etiqueta)."
  value       = "${google_artifact_registry_repository.jobs.location}-docker.pkg.dev/${google_artifact_registry_repository.jobs.project}/${google_artifact_registry_repository.jobs.repository_id}"
}
