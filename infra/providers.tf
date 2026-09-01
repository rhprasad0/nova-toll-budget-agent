provider "aws" {
  # Credentials are selected out-of-band by the deployment shell.
  region = "us-east-1"
  allowed_account_ids = [
    jsondecode(file("${path.module}/account-contract.json")).accounts[var.environment].id,
  ]

  default_tags {
    tags = {
      project     = "nova-toll-budget-agent"
      environment = "shared"
      shared_with = "development"
    }
  }
}
