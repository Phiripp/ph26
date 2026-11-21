variable "proyecto" {
  description = "ID del proyecto de GCP."
  type        = string
}

variable "region" {
  description = "Región en la que se pide la cuota."
  type        = string
}

variable "correo_contacto" {
  description = "Correo de contacto que exige Google para pedir cuota. Si es null no se pide."
  type        = string
  default     = null
}

variable "cuota_cpu_milli" {
  description = "Cuota de CPU de Cloud Run pedida, en milli-vCPU."
  type        = number
}

variable "cuota_memoria_bytes" {
  description = "Cuota de memoria de Cloud Run pedida, en bytes."
  type        = number
}
