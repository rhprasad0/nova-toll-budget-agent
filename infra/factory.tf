# AWS access for the local factory's thin client (v2/plans/FACTORY-SPEC.md, AWS
# credentials). Development only. The machine presents an X.509 certificate to IAM
# Roles Anywhere and gets one-hour credentials for this role; it holds no access key.
locals {
  factory_count = var.environment == "development" ? 1 : 0
  # The one end-entity certificate the CA issues; its key never leaves the thin client.
  factory_certificate_cn  = "factory"
  factory_token_parameter = "/nova-toll/factory/claude-code-oauth-token"
  factory_database_user   = "phoenix_factory"
}

resource "aws_rolesanywhere_trust_anchor" "factory" {
  count   = local.factory_count
  name    = "tollchat-factory"
  enabled = true
  source {
    source_type = "CERTIFICATE_BUNDLE"
    source_data {
      # Public CA certificate; its key stays on Ryan's workstation.
      x509_certificate_data = file("${path.module}/factory-ca.pem")
    }
  }
}

data "aws_iam_policy_document" "factory_assume" {
  count = local.factory_count
  statement {
    actions = ["sts:AssumeRole", "sts:TagSession", "sts:SetSourceIdentity"]
    principals {
      type        = "Service"
      identifiers = ["rolesanywhere.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:PrincipalTag/x509Subject/CN"
      values   = [local.factory_certificate_cn]
    }
    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = [aws_rolesanywhere_trust_anchor.factory[0].arn]
    }
  }
}

resource "aws_iam_role" "factory" {
  count                = local.factory_count
  name                 = "tollchat-factory"
  assume_role_policy   = data.aws_iam_policy_document.factory_assume[0].json
  max_session_duration = 3600
}

# The development measurement bucket's key, which v2/infra owns.
data "aws_kms_alias" "factory_traces" {
  count = local.factory_count
  name  = "alias/tollchat-v2-agent-measurement-dev"
}

data "aws_iam_policy_document" "factory" {
  count = local.factory_count
  statement {
    sid       = "ReadSubscriptionToken"
    actions   = ["ssm:GetParameter"]
    resources = [aws_ssm_parameter.factory_token[0].arn]
  }
  statement {
    sid       = "ArchiveFactoryTraces"
    actions   = ["s3:PutObject"]
    resources = ["${local.development_delivery_measurement_bucket_arn}/factory-traces/*"]
  }
  statement {
    # Decrypt is for multipart uploads; without s3:GetObject it reads nothing.
    sid       = "EncryptFactoryTraces"
    actions   = ["kms:GenerateDataKey", "kms:Decrypt"]
    resources = [data.aws_kms_alias.factory_traces[0].target_key_arn]
    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = ["s3.us-east-1.amazonaws.com"]
    }
    condition {
      # The bucket uses an S3 Bucket Key, so the context is the bucket ARN.
      test     = "StringEquals"
      variable = "kms:EncryptionContext:aws:s3:arn"
      values   = [local.development_delivery_measurement_bucket_arn]
    }
  }
  statement {
    sid       = "ConnectPhoenixDatabase"
    actions   = ["rds-db:connect"]
    resources = ["arn:aws:rds-db:us-east-1:${data.aws_caller_identity.current.account_id}:dbuser:${aws_db_instance.main.resource_id}/${local.factory_database_user}"]
  }
}

resource "aws_iam_role_policy" "factory" {
  count  = local.factory_count
  name   = "tollchat-factory"
  role   = aws_iam_role.factory[0].id
  policy = data.aws_iam_policy_document.factory[0].json
}

resource "aws_rolesanywhere_profile" "factory" {
  count            = local.factory_count
  name             = "tollchat-factory"
  enabled          = true
  role_arns        = [aws_iam_role.factory[0].arn]
  duration_seconds = 3600
}

# Seeded with a placeholder like the parameters in ssm.tf; Ryan sets the value from
# `claude setup-token` with `aws ssm put-parameter --overwrite`, outside Terraform.
resource "aws_ssm_parameter" "factory_token" {
  count = local.factory_count
  name  = local.factory_token_parameter
  type  = "SecureString"
  value = "REPLACE_OUT_OF_BAND"

  lifecycle {
    ignore_changes = [value]
  }
}

output "factory" {
  description = "What the thin client's aws_signing_helper configuration needs; null outside development."
  value = local.factory_count == 1 ? {
    trust_anchor_arn = aws_rolesanywhere_trust_anchor.factory[0].arn
    profile_arn      = aws_rolesanywhere_profile.factory[0].arn
    role_arn         = aws_iam_role.factory[0].arn
    token_parameter  = local.factory_token_parameter
  } : null
}
