variable "id_secreto" {
  description = "Nombre del secreto en Secret Manager."
  type        = string
}

variable "valor_provisorio" {
  description = "Valor inicial del secreto, hasta que se cargue la clave real con gcloud."
  type        = string
  default     = "PENDIENTE"
}

variable "cuenta_lectura" {
  description = "Cuenta de servicio que puede leer el secreto (roles/secretmanager.secretAccessor)."
  type        = string
}
