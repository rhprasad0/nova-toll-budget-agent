# Dedicated immutable storage for saved production release plans. Writer roles
# and their narrowly scoped KMS access are added with the release workflow.
resource "aws_kms_key" "release_plan" {
  description             = "Nova Toll production release plans"
  enable_key_rotation     = true
  deletion_window_in_days = 30
}

resource "aws_kms_alias" "release_plan" {
  name          = "alias/nova-toll-release-plan"
  target_key_id = aws_kms_key.release_plan.key_id
}

resource "aws_s3_bucket" "release_plan" {
  bucket              = "nova-toll-release-plans-920534282028"
  object_lock_enabled = true
}

resource "aws_s3_bucket_versioning" "release_plan" {
  bucket = aws_s3_bucket.release_plan.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_ownership_controls" "release_plan" {
  bucket = aws_s3_bucket.release_plan.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_public_access_block" "release_plan" {
  bucket                  = aws_s3_bucket.release_plan.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "release_plan" {
  bucket = aws_s3_bucket.release_plan.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.release_plan.arn
    }
  }
}

resource "aws_s3_bucket_object_lock_configuration" "release_plan" {
  bucket = aws_s3_bucket.release_plan.id

  rule {
    default_retention {
      mode = "COMPLIANCE"
      days = 2
    }
  }

  depends_on = [aws_s3_bucket_versioning.release_plan]
}

resource "aws_s3_bucket_lifecycle_configuration" "release_plan" {
  bucket = aws_s3_bucket.release_plan.id

  rule {
    id     = "expire-release-plans"
    status = "Enabled"
    filter {}

    expiration {
      days = 3
    }

    # Current-version expiry creates a delete marker; remove its saved version
    # on the next eligible lifecycle pass after the two-day lock has elapsed.
    noncurrent_version_expiration {
      noncurrent_days = 1
    }
  }

  depends_on = [aws_s3_bucket_versioning.release_plan]
}

data "aws_iam_policy_document" "release_plan_bucket" {
  statement {
    sid       = "DenyInsecureTransport"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [aws_s3_bucket.release_plan.arn, "${aws_s3_bucket.release_plan.arn}/*"]

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

  statement {
    sid       = "DenyWritesWithoutKms"
    effect    = "Deny"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.release_plan.arn}/*"]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    condition {
      test     = "StringNotEquals"
      variable = "s3:x-amz-server-side-encryption"
      values   = ["aws:kms"]
    }
  }

  statement {
    sid       = "DenyWritesWithWrongKmsKey"
    effect    = "Deny"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.release_plan.arn}/*"]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    condition {
      test     = "StringNotEquals"
      variable = "s3:x-amz-server-side-encryption-aws-kms-key-id"
      values   = [aws_kms_key.release_plan.arn]
    }
  }
}

resource "aws_s3_bucket_policy" "release_plan" {
  bucket = aws_s3_bucket.release_plan.id
  policy = data.aws_iam_policy_document.release_plan_bucket.json
}
