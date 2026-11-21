# Infraestructura de la corrida nacional de Caudal (docs/spec-chile.md).
# Cada módulo tiene una sola responsabilidad; aquí solo se componen.

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

module "apis" {
  source    = "../../modulos/apis"
  servicios = local.apis
}

module "identidad" {
  source         = "../../modulos/identidad"
  id_cuenta      = "caudal-jobs"
  nombre_visible = "Caudal: jobs de la corrida nacional"

  depends_on = [module.apis]
}

module "almacenamiento" {
  source           = "../../modulos/almacenamiento"
  nombre           = var.bucket_chile
  region           = var.region
  cuenta_escritura = module.identidad.email
  cuenta_lectura   = var.cuenta_servicio_web

  depends_on = [module.apis]
}

module "secretos" {
  source         = "../../modulos/secretos"
  id_secreto     = "CDS_API_KEY"
  cuenta_lectura = module.identidad.email

  depends_on = [module.apis]
}

module "jobs" {
  source            = "../../modulos/jobs"
  region_principal  = var.region
  regiones_satelite = var.regiones_satelite
  hilos_satelite    = var.hilos_satelite
  imagen            = var.imagen
  corrida           = var.corrida
  cuenta_servicio   = module.identidad.email
  bucket            = module.almacenamiento.nombre
  secreto_cds       = module.secretos.id_secreto

  # Los jobs necesitan los permisos antes de existir: si no, la primera ejecución falla.
  depends_on = [module.almacenamiento, module.secretos]
}

module "cuota" {
  source              = "../../modulos/cuota"
  proyecto            = var.proyecto
  region              = var.region
  correo_contacto     = var.correo_contacto
  cuota_cpu_milli     = var.cuota_cpu_milli
  cuota_memoria_bytes = var.cuota_memoria_bytes

  depends_on = [module.apis]
}
