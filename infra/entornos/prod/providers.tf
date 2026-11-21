provider "google" {
  project = var.proyecto
  region  = var.region

  # Las APIs de cuotas se cobran contra el proyecto indicado, no contra el de la credencial.
  user_project_override = true
  billing_project       = var.proyecto
}
