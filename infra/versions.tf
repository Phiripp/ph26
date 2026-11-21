terraform {
  required_version = ">= 1.6"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 8.12"
    }
  }

  # El estado vive en un bucket creado por bootstrap.sh, no en git.
  backend "gcs" {
    bucket = "ph-26-caudal-tfstate"
    prefix = "chile"
  }
}

provider "google" {
  project = var.proyecto
  region  = var.region

  # Las APIs de cuotas se cobran contra el proyecto indicado, no contra el de la credencial.
  user_project_override = true
  billing_project       = var.proyecto
}
