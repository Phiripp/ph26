output "solicitada" {
  description = "true si se pidió cuota (hay correo de contacto)."
  value       = var.correo_contacto != null
}
