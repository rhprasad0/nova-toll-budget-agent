provider "aws" {
  region = "us-east-1"
  allowed_account_ids = [
    jsondecode(file("${path.module}/../../infra/account-contract.json")).accounts[var.environment].id,
  ]

  default_tags {
    tags = {
      project     = "nova-toll-budget-agent"
      version     = "v2"
      environment = var.environment
    }
  }
}

provider "cloudflare" {}
