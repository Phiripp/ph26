output "bucket_chile" {
  description = "Bucket de la corrida nacional (se monta en /datos en los jobs)."
  value       = google_storage_bucket.chile.name
}

output "cuenta_servicio_jobs" {
  description = "Cuenta de servicio con la que corren los jobs."
  value       = google_service_account.jobs.email
}

output "jobs" {
  description = "Jobs creados, con su nombre y región."
  value = {
    for clave, job in google_cloud_run_v2_job.chile :
    clave => { nombre = job.name, region = job.location }
  }
}

output "comandos_ejecucion" {
  description = "Comandos de ejemplo para lanzar cada etapa (ver infra/README.md)."
  value = {
    base       = "gcloud run jobs execute caudal-chile-datos --region ${var.region} --project ${var.proyecto} --tasks 14 --update-env-vars ETAPA=base"
    plan       = "gcloud run jobs execute caudal-chile-datos --region ${var.region} --project ${var.proyecto} --tasks 1 --update-env-vars ETAPA=plan"
    satelite   = [for region in keys(var.regiones_satelite) : "gcloud run jobs execute caudal-chile-satelite --region ${region} --project ${var.proyecto} --tasks 10 --update-env-vars ETAPA=satelite"]
    prediccion = "gcloud run jobs execute caudal-chile-prediccion --region ${var.region} --project ${var.proyecto} --tasks 14 --update-env-vars ETAPA=region"
  }
}
