terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.47"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
  }

  backend "s3" {
    bucket       = "nova-toll-tfstate-920534282028"
    key          = "nova-toll/v2/terraform.tfstate"
    region       = "us-east-1"
    use_lockfile = true
  }
}
