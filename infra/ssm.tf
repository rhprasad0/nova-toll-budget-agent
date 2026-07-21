# Parameters exist so IAM/env-var wiring has something real to point at.
# `value` is a required argument on create, so it's seeded with a placeholder
# and then ignored — the real token is set out-of-band via
# `aws ssm put-parameter --overwrite`, so it never appears in Terraform state.
resource "aws_ssm_parameter" "i95_token" {
  name  = var.i95_token_param_name
  type  = "SecureString"
  value = "REPLACE_OUT_OF_BAND"

  lifecycle {
    ignore_changes = [value]
  }
}

resource "aws_ssm_parameter" "i66_token" {
  name  = var.i66_token_param_name
  type  = "SecureString"
  value = "REPLACE_OUT_OF_BAND"

  lifecycle {
    ignore_changes = [value]
  }
}
