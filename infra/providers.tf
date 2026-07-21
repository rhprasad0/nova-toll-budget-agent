provider "aws" {
  profile = "nova-toll"
  region  = "us-east-1"

  default_tags {
    tags = {
      project = "nova-toll-budget-agent"
    }
  }
}
