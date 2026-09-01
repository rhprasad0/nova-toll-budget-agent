# These controls are attached through local.hardened_buckets in s3.tf. Trivy
# v0.70 cannot follow that for_each map; remove these temporary ignores when
# the scanner recognizes the shared controls. CloudTrail's protected S3 object
# data events provide the audit coverage instead of S3 server access logging.
#trivy:ignore:AVD-AWS-0086:exp:2026-12-01
#trivy:ignore:AVD-AWS-0087:exp:2026-12-01
#trivy:ignore:AVD-AWS-0091:exp:2026-12-01
#trivy:ignore:AVD-AWS-0093:exp:2026-12-01
#trivy:ignore:AVD-AWS-0132:exp:2026-12-01
resource "aws_s3_bucket" "audit" {
  bucket = "nova-toll-audit-${local.account_id}"
}

# Versioning, ownership, public-access block, SSE-KMS and the lifecycle rule
# for this bucket live in s3.tf's local.hardened_buckets -- identical to raw
# and tfstate, so all three are driven from one map there.

data "aws_iam_policy_document" "audit_bucket" {
  statement {
    sid       = "DenyInsecureTransport"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [aws_s3_bucket.audit.arn, "${aws_s3_bucket.audit.arn}/*"]
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
    sid       = "AllowCloudTrailAclCheck"
    effect    = "Allow"
    actions   = ["s3:GetBucketAcl"]
    resources = [aws_s3_bucket.audit.arn]
    principals {
      type        = "Service"
      identifiers = ["cloudtrail.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceArn"
      values   = ["arn:aws:cloudtrail:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:trail/nova-toll-audit"]
    }
  }

  statement {
    sid       = "AllowCloudTrailWrite"
    effect    = "Allow"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.audit.arn}/AWSLogs/${data.aws_caller_identity.current.account_id}/*"]
    principals {
      type        = "Service"
      identifiers = ["cloudtrail.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "s3:x-amz-acl"
      values   = ["bucket-owner-full-control"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceArn"
      values   = ["arn:aws:cloudtrail:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:trail/nova-toll-audit"]
    }
  }
}

resource "aws_s3_bucket_policy" "audit" {
  bucket = aws_s3_bucket.audit.id
  policy = data.aws_iam_policy_document.audit_bucket.json
}

resource "aws_cloudtrail" "audit" {
  name                          = "nova-toll-audit"
  s3_bucket_name                = aws_s3_bucket.audit.id
  kms_key_id                    = aws_kms_key.audit.arn
  enable_logging                = true
  enable_log_file_validation    = true
  is_multi_region_trail         = true
  include_global_service_events = true

  advanced_event_selector {
    name = "Management events"
    field_selector {
      field  = "eventCategory"
      equals = ["Management"]
    }
  }

  advanced_event_selector {
    name = "Protected S3 objects"
    field_selector {
      field  = "eventCategory"
      equals = ["Data"]
    }
    field_selector {
      field  = "resources.type"
      equals = ["AWS::S3::Object"]
    }
    field_selector {
      field       = "resources.ARN"
      starts_with = ["${aws_s3_bucket.raw.arn}/", "${aws_s3_bucket.tfstate.arn}/", "${aws_s3_bucket.agentcore_artifacts.arn}/"]
    }
  }

  depends_on = [aws_s3_bucket_policy.audit]
}
