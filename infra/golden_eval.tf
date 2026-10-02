# Retained historical evaluation evidence. The holdout reader/reviewer roles
# are retired; keep the bucket and its data protections.
locals {
  golden_bucket = "nova-toll-golden-evidence-903859731897"
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
