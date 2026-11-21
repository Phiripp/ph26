terraform {
  required_version = ">= 1.6"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 8.12"
    }
  }

  # El estado vive en un bucket creado por infra/bootstrap/estado.sh, no en git.
  backend "gcs" {
    bucket = "ph-26-caudal-tfstate"
    prefix = "chile"
  }
}
