variable "nombre" {
  description = "Nombre del bucket."
  type        = string
}

variable "region" {
  description = "Ubicación del bucket."
  type        = string
}

variable "cuenta_escritura" {
  description = "Cuenta de servicio con lectura y escritura (roles/storage.objectAdmin): la de los jobs."
  type        = string
}

variable "cuenta_lectura" {
  description = "Cuenta de servicio con solo lectura (roles/storage.objectViewer): la de caudal-web."
  type        = string
}
