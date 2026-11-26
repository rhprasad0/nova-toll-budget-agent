resource "aws_s3_bucket" "chaos_lab" {
  count  = local.factory_count
  bucket = "chaos-lab-${local.account_id}"
}

resource "aws_s3_bucket_ownership_controls" "chaos_lab" {
  count  = local.factory_count
  bucket = aws_s3_bucket.chaos_lab[0].id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_public_access_block" "chaos_lab" {
  count                   = local.factory_count
  bucket                  = aws_s3_bucket.chaos_lab[0].id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "chaos_lab" {
  count  = local.factory_count
  bucket = aws_s3_bucket.chaos_lab[0].id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_versioning" "chaos_lab" {
  count  = local.factory_count
  bucket = aws_s3_bucket.chaos_lab[0].id
  versioning_configuration { status = "Enabled" }
}

data "aws_iam_policy_document" "chaos_lab" {
  count = local.factory_count
  statement {
    sid       = "DenyInsecureTransport"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [aws_s3_bucket.chaos_lab[0].arn, "${aws_s3_bucket.chaos_lab[0].arn}/*"]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "chaos_lab" {
  count  = local.factory_count
  bucket = aws_s3_bucket.chaos_lab[0].id
  policy = data.aws_iam_policy_document.chaos_lab[0].json
}
