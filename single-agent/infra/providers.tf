provider "aws" {
  # No explicit profile: local runs set AWS_PROFILE=nova-toll in the shell;
  # CI relies on aws-actions/configure-aws-credentials's env-var creds from
  # an assumed OIDC role. A hardcoded profile here would make Terraform look
  # up that named profile regardless of ambient credentials, which fails in
  # CI where no "nova-toll" profile exists.
  region = "us-east-1"

  default_tags {
    tags = {
      project = "nova-toll-budget-agent"
    }
  }
}

provider "cloudflare" {
  # Reads CLOUDFLARE_API_TOKEN from the environment -- no variable needed.
}
