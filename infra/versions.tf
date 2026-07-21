terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
  }

  # State bucket is chicken-and-egg with this same config (see s3.tf for the
  # aws_s3_bucket resource that models it). Bootstrap order:
  #   1. `terraform init -backend=false` + `plan`/`validate` against local
  #      state (works with no bucket, no AWS creds needed for validate).
  #   2. First `apply` (WP4, human-gated) also runs against local state and
  #      creates the bucket via the resource below.
  #   3. Re-run `terraform init` (backend config uncommented/active) to
  #      migrate local state into the now-existing bucket.
  backend "s3" {
    bucket       = "nova-toll-tfstate-920534282028"
    key          = "nova-toll/terraform.tfstate"
    region       = "us-east-1"
    profile      = "nova-toll"
    use_lockfile = true
  }
}
