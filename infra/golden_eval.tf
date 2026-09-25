# This repository imports aggregates only. Private evaluation runs elsewhere.
# No role here can read private cases, call a model, or access a database.
locals {
  golden_bucket = "nova-toll-golden-evidence-903859731897"
  golden_roles = var.environment == "development" ? {
    evaluator = { environment = "golden-evaluation", writes = ["aggregates/reports/*", "aggregates/claims/*", "aggregates/accounting/*"] }
    reviewer  = { environment = "golden-review", writes = ["candidates/private/*"] }
    reader    = { environment = "golden-read", writes = [] }
  } : {}
}

resource "aws_s3_bucket" "golden" {
  count         = var.environment == "development" ? 1 : 0
  bucket        = local.golden_bucket
  force_destroy = false
  lifecycle {
    prevent_destroy = true
    precondition {
      condition     = data.aws_caller_identity.current.account_id == "903859731897"
      error_message = "Golden evidence belongs only in the development account."
    }
  }
}

resource "aws_s3_bucket_versioning" "golden" {
  count  = length(aws_s3_bucket.golden)
  bucket = aws_s3_bucket.golden[0].id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "golden" {
  count  = length(aws_s3_bucket.golden)
  bucket = aws_s3_bucket.golden[0].id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}

resource "aws_s3_bucket_public_access_block" "golden" {
  count                   = length(aws_s3_bucket.golden)
  bucket                  = aws_s3_bucket.golden[0].id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_iam_role" "golden" {
  for_each             = local.golden_roles
  name                 = "nova-toll-golden-${each.key}"
  max_session_duration = 3600
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRoleWithWebIdentity"
      Principal = { Federated = aws_iam_openid_connect_provider.github.arn }
      Condition = { StringEquals = {
        "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
        "token.actions.githubusercontent.com:sub" = "repo:rhprasad0@91573985/nova-toll-budget-agent@1306930324:environment:${each.value.environment}"
        "token.actions.githubusercontent.com:ref" = "refs/heads/main"
      } }
    }]
  })
}

resource "aws_iam_role_policy" "golden" {
  for_each = local.golden_roles
  name     = "fixed-golden-evidence"
  role     = aws_iam_role.golden[each.key].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat([
      { Effect = "Allow", Action = ["s3:GetObject", "s3:GetObjectVersion"], Resource = ["arn:aws:s3:::${local.golden_bucket}/aggregates/*", "arn:aws:s3:::${local.golden_bucket}/candidates/private/*"] },
      { Effect = "Deny", Action = ["s3:DeleteObject", "s3:DeleteObjectVersion", "s3:PutBucketVersioning"], Resource = ["arn:aws:s3:::${local.golden_bucket}", "arn:aws:s3:::${local.golden_bucket}/*"] }
      ], length(each.value.writes) == 0 ? [] : [
      { Effect = "Allow", Action = ["s3:PutObject"], Resource = [for prefix in each.value.writes : "arn:aws:s3:::${local.golden_bucket}/${prefix}"] }
    ])
  })
}

resource "aws_s3_bucket_policy" "golden" {
  count  = length(aws_s3_bucket.golden)
  bucket = aws_s3_bucket.golden[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Deny", Principal = "*", Action = "s3:*"
        Resource  = [aws_s3_bucket.golden[0].arn, "${aws_s3_bucket.golden[0].arn}/*"]
        Condition = { Bool = { "aws:SecureTransport" = "false" } }
      },
      {
        Effect    = "Deny", Principal = "*", Action = "s3:PutObject"
        Resource  = [for prefix in ["reports/*", "claims/*", "approvals/*", "references/*", "aggregates/*"] : "${aws_s3_bucket.golden[0].arn}/${prefix}"]
        Condition = { Null = { "s3:if-none-match" = "true" } }
      },
      {
        Effect    = "Deny", Principal = "*", Action = "s3:PutObject"
        Resource  = "${aws_s3_bucket.golden[0].arn}/*"
        Condition = { Null = { "s3:if-none-match" = "true", "s3:if-match" = "true" } }
      }
    ]
  })
}
