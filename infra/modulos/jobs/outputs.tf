output "jobs" {
  description = "Jobs creados, con su nombre y región."
  value = {
    for clave, job in google_cloud_run_v2_job.chile :
    clave => { nombre = job.name, region = job.location }
  }
}
