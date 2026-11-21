# Direcciones anteriores a la división en módulos (todo estaba en la raíz de infra/).
# Con esto Terraform mueve el estado sin destruir ni recrear recursos.
moved {
  from = google_project_service.apis
  to   = module.apis.google_project_service.apis
}

moved {
  from = google_service_account.jobs
  to   = module.identidad.google_service_account.jobs
}

moved {
  from = google_storage_bucket.chile
  to   = module.almacenamiento.google_storage_bucket.chile
}

moved {
  from = google_storage_bucket_iam_member.jobs_escritura
  to   = module.almacenamiento.google_storage_bucket_iam_member.jobs_escritura
}

moved {
  from = google_storage_bucket_iam_member.web_lectura
  to   = module.almacenamiento.google_storage_bucket_iam_member.web_lectura
}

moved {
  from = google_secret_manager_secret.cds_api_key
  to   = module.secretos.google_secret_manager_secret.cds_api_key
}

moved {
  from = google_secret_manager_secret_version.provisoria
  to   = module.secretos.google_secret_manager_secret_version.provisoria
}

moved {
  from = google_secret_manager_secret_iam_member.jobs_cds
  to   = module.secretos.google_secret_manager_secret_iam_member.jobs_cds
}

moved {
  from = google_cloud_run_v2_job.chile
  to   = module.jobs.google_cloud_run_v2_job.chile
}

moved {
  from = google_cloud_quotas_quota_preference.cpu
  to   = module.cuota.google_cloud_quotas_quota_preference.cpu
}

moved {
  from = google_cloud_quotas_quota_preference.memoria
  to   = module.cuota.google_cloud_quotas_quota_preference.memoria
}
