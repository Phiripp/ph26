variable "nombre" {
  description = "Nombre del repositorio de Artifact Registry."
  type        = string
}

variable "region" {
  description = "Ubicación del repositorio."
  type        = string
}

variable "cuenta_build" {
  description = "Cuenta de servicio con la que corre Cloud Build (roles/artifactregistry.writer)."
  type        = string
}

variable "cuenta_lectura" {
  description = "Cuenta de servicio de los jobs (roles/artifactregistry.reader)."
  type        = string
}

variable "versiones_a_conservar" {
  description = "Imágenes recientes que nunca se borran, aunque tengan más de 7 días."
  type        = number
  default     = 10
}
