provider "aws" {
  profile = "nova-toll"
  region  = "us-east-1"

  default_tags {
    tags = {
      project = "nova-toll-budget-agent"
    }
  }
}

provider "cloudflare" {
  # Reads CLOUDFLARE_API_TOKEN from the environment -- no variable needed.
}
