# --- shared bucket hardening ------------------------------------------
# raw, audit and tfstate each get the identical five-resource treatment;
# only the KMS key differs, so they're driven from one map rather than
# written out three times. The bucket *policies* genuinely differ per
# bucket, so those stay written out individually below (and in audit.tf).
#
# The site bucket (site.tf) is deliberately not in here: it's a public
# CDN origin with no versioning, no lifecycle rule and AES256 rather than
# SSE-KMS, so folding it in would mean conditionals, not less code.

locals {
  hardened_buckets = {
    raw     = { id = aws_s3_bucket.raw.id, kms_key_arn = aws_kms_key.raw.arn }
    audit   = { id = aws_s3_bucket.audit.id, kms_key_arn = aws_kms_key.audit.arn }
    tfstate = { id = aws_s3_bucket.tfstate.id, kms_key_arn = aws_kms_key.tfstate.arn }
  }
}

resource "aws_s3_bucket_versioning" "hardened" {
  for_each = local.hardened_buckets
  bucket   = each.value.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_ownership_controls" "hardened" {
  for_each = local.hardened_buckets
  bucket   = each.value.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_public_access_block" "hardened" {
  for_each                = local.hardened_buckets
  bucket                  = each.value.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "hardened" {
  for_each = local.hardened_buckets
  bucket   = each.value.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = each.value.kms_key_arn
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "hardened" {
  for_each = local.hardened_buckets
  bucket   = each.value.id

  rule {
    id     = "abort-incomplete-uploads"
    status = "Enabled"
    filter {}
    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

# State migration for the consolidation above -- these keep the existing
# resources in place instead of destroying and recreating them. Safe to
# delete once an apply has run on every workspace that has this state.
moved {
  from = aws_s3_bucket_versioning.raw
  to   = aws_s3_bucket_versioning.hardened["raw"]
}
moved {
  from = aws_s3_bucket_versioning.audit
  to   = aws_s3_bucket_versioning.hardened["audit"]
}
moved {
  from = aws_s3_bucket_versioning.tfstate
  to   = aws_s3_bucket_versioning.hardened["tfstate"]
}
moved {
  from = aws_s3_bucket_ownership_controls.raw
  to   = aws_s3_bucket_ownership_controls.hardened["raw"]
}
moved {
  from = aws_s3_bucket_ownership_controls.audit
  to   = aws_s3_bucket_ownership_controls.hardened["audit"]
}
moved {
  from = aws_s3_bucket_ownership_controls.tfstate
  to   = aws_s3_bucket_ownership_controls.hardened["tfstate"]
}
moved {
  from = aws_s3_bucket_public_access_block.raw
  to   = aws_s3_bucket_public_access_block.hardened["raw"]
}
moved {
  from = aws_s3_bucket_public_access_block.audit
  to   = aws_s3_bucket_public_access_block.hardened["audit"]
}
moved {
  from = aws_s3_bucket_public_access_block.tfstate
  to   = aws_s3_bucket_public_access_block.hardened["tfstate"]
}
moved {
  from = aws_s3_bucket_server_side_encryption_configuration.raw
  to   = aws_s3_bucket_server_side_encryption_configuration.hardened["raw"]
}
moved {
  from = aws_s3_bucket_server_side_encryption_configuration.audit
  to   = aws_s3_bucket_server_side_encryption_configuration.hardened["audit"]
}
moved {
  from = aws_s3_bucket_server_side_encryption_configuration.tfstate
  to   = aws_s3_bucket_server_side_encryption_configuration.hardened["tfstate"]
}
moved {
  from = aws_s3_bucket_lifecycle_configuration.raw
  to   = aws_s3_bucket_lifecycle_configuration.hardened["raw"]
}
moved {
  from = aws_s3_bucket_lifecycle_configuration.audit
  to   = aws_s3_bucket_lifecycle_configuration.hardened["audit"]
}
moved {
  from = aws_s3_bucket_lifecycle_configuration.tfstate
  to   = aws_s3_bucket_lifecycle_configuration.hardened["tfstate"]
}

# --- raw payload bucket -----------------------------------------------

resource "aws_s3_bucket" "raw" {
  bucket = "nova-toll-raw-920534282028"
}

data "aws_iam_policy_document" "raw_bucket" {
  statement {
    sid       = "DenyInsecureTransport"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [aws_s3_bucket.raw.arn, "${aws_s3_bucket.raw.arn}/*"]
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
    sid       = "DenyRawWritesWithoutKms"
    effect    = "Deny"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.raw.arn}/raw/*"]
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
    sid       = "DenyRawWritesWithWrongKmsKey"
    effect    = "Deny"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.raw.arn}/raw/*"]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "StringNotEquals"
      variable = "s3:x-amz-server-side-encryption-aws-kms-key-id"
      values   = [aws_kms_key.raw.arn]
    }
  }

  statement {
    sid       = "DenyUnexpectedRawWriters"
    effect    = "Deny"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.raw.arn}/raw/*"]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "StringNotLike"
      variable = "aws:PrincipalArn"
      values = [
        aws_iam_role.fetcher.arn,
        aws_iam_role.replay.arn,
      ]
    }
  }
}

resource "aws_s3_bucket_policy" "raw" {
  bucket = aws_s3_bucket.raw.id
  policy = data.aws_iam_policy_document.raw_bucket.json

  # Do not activate a policy that requires explicit SSE-KMS until the real
  # fetcher zips and their KMS grants are in place. Placeholder functions are
  # intentionally usable for plans but must never be a production deploy.
  lifecycle {
    precondition {
      condition     = var.fetcher_package_path != ""
      error_message = "Raw-bucket write enforcement requires the real fetcher deployment package."
    }
  }

  depends_on = [
    aws_iam_role_policy.fetcher,
    aws_iam_role_policy.replay,
    aws_lambda_function.fetcher,
  ]
}

# --- terraform state bucket ---------------------------------------------
# See versions.tf for the bootstrap order this resource implies (the
# backend config points here, so the first apply necessarily happens
# against local state, then state is migrated in).

resource "aws_s3_bucket" "tfstate" {
  bucket = "nova-toll-tfstate-920534282028"
}

data "aws_iam_policy_document" "tfstate_bucket" {
  statement {
    sid       = "DenyInsecureTransport"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [aws_s3_bucket.tfstate.arn, "${aws_s3_bucket.tfstate.arn}/*"]
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

resource "aws_s3_bucket_policy" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id
  policy = data.aws_iam_policy_document.tfstate_bucket.json
}
