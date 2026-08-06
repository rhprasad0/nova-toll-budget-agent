# Separate keys limit the impact of a compromised data-processing role.  The
# account-root statement delegates administration to account IAM policies; the
# service statements are limited to the AWS service and resource that need it.
resource "aws_kms_key" "raw" {
  description             = "Nova Toll raw feed payloads"
  enable_key_rotation     = true
  deletion_window_in_days = 30
}

resource "aws_kms_alias" "raw" {
  name          = "alias/nova-toll-raw"
  target_key_id = aws_kms_key.raw.key_id
}

resource "aws_kms_key" "tfstate" {
  description             = "Nova Toll Terraform state"
  enable_key_rotation     = true
  deletion_window_in_days = 30
}

resource "aws_kms_alias" "tfstate" {
  name          = "alias/nova-toll-tfstate"
  target_key_id = aws_kms_key.tfstate.key_id
}

# Dedicated key (not the shared default alias/aws/ssm) keeps this token
# independently access-controlled from the VDOT feed tokens and Tailscale
# authkey. Grant decryption only to identities that need this parameter.
resource "aws_kms_key" "cloudflare_token" {
  description             = "Nova Toll Cloudflare API token (SSM SecureString)"
  enable_key_rotation     = true
  deletion_window_in_days = 30
}

resource "aws_kms_alias" "cloudflare_token" {
  name          = "alias/nova-toll-cloudflare-token"
  target_key_id = aws_kms_key.cloudflare_token.key_id
}

data "aws_iam_policy_document" "audit_kms" {
  statement {
    sid       = "EnableAccountIamPolicies"
    effect    = "Allow"
    actions   = ["kms:*"]
    resources = ["*"]
    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"]
    }
  }

  statement {
    sid = "AllowCloudTrailEncryption"
    actions = [
      "kms:GenerateDataKey*",
      "kms:DescribeKey",
    ]
    resources = ["*"]
    principals {
      type        = "Service"
      identifiers = ["cloudtrail.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceArn"
      values   = ["arn:aws:cloudtrail:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:trail/nova-toll-audit"]
    }
  }
}

resource "aws_kms_key" "audit" {
  description             = "Nova Toll CloudTrail audit logs"
  enable_key_rotation     = true
  deletion_window_in_days = 30
  policy                  = data.aws_iam_policy_document.audit_kms.json
}

resource "aws_kms_alias" "audit" {
  name          = "alias/nova-toll-audit"
  target_key_id = aws_kms_key.audit.key_id
}
