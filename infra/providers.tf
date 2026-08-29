provider "aws" {
  # No explicit profile: local runs set AWS_PROFILE=nova-toll in the shell.
  region = "us-east-1"

  default_tags {
    tags = {
      project     = "nova-toll-budget-agent"
      environment = "production"
      shared_with = "development"
    }
  }
}
