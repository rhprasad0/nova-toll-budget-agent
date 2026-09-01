"""Focused, dependency-free contract checks for release-plan storage."""

from pathlib import Path


ROOT = Path(__file__).resolve().parent
RELEASE_PLAN = (ROOT / "release_plan.tf").read_text()
AUDIT = (ROOT / "audit.tf").read_text()
WORKFLOW = (ROOT.parent / ".github/workflows/terraform.yml").read_text()


def block(source: str, header: str | int) -> str:
    if isinstance(header, str):
        assert header in source, f"missing {header!r}"
        start = source.index(header)
    else:
        start = header
    depth = 0
    for index in range(start, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
    raise AssertionError(f"unclosed {header}")


def require(source: str, *needles: str) -> None:
    for needle in needles:
        assert needle in source, f"missing {needle!r}"


def statement(policy: str, sid: str) -> str:
    sid_start = policy.index(f'sid       = "{sid}"')
    return block(policy, policy.rfind("statement {", 0, sid_start))


def main() -> None:
    require(
        block(RELEASE_PLAN, 'resource "aws_kms_key" "release_plan"'),
        "enable_key_rotation     = true",
        "deletion_window_in_days = 30",
    )
    require(
        block(RELEASE_PLAN, 'resource "aws_kms_alias" "release_plan"'),
        'name          = "alias/nova-toll-release-plan"',
        "target_key_id = aws_kms_key.release_plan.key_id",
    )
    require(
        block(RELEASE_PLAN, 'resource "aws_s3_bucket" "release_plan"'),
        'bucket              = "nova-toll-release-plans-920534282028"',
        "object_lock_enabled = true",
    )
    require(
        block(RELEASE_PLAN, 'resource "aws_s3_bucket_versioning" "release_plan"'),
        "bucket = aws_s3_bucket.release_plan.id",
        'status = "Enabled"',
    )
    require(
        block(RELEASE_PLAN, 'resource "aws_s3_bucket_ownership_controls" "release_plan"'),
        "bucket = aws_s3_bucket.release_plan.id",
        'object_ownership = "BucketOwnerEnforced"',
    )
    require(
        block(RELEASE_PLAN, 'resource "aws_s3_bucket_public_access_block" "release_plan"'),
        "bucket                  = aws_s3_bucket.release_plan.id",
        "block_public_acls       = true",
        "block_public_policy     = true",
        "ignore_public_acls      = true",
        "restrict_public_buckets = true",
    )
    require(
        block(RELEASE_PLAN, 'resource "aws_s3_bucket_server_side_encryption_configuration" "release_plan"'),
        "bucket = aws_s3_bucket.release_plan.id",
        'sse_algorithm     = "aws:kms"',
        "kms_master_key_id = aws_kms_key.release_plan.arn",
    )
    for resource, settings in (
        ('resource "aws_s3_bucket_object_lock_configuration" "release_plan"', ('mode = "COMPLIANCE"', "days = 2")),
        ('resource "aws_s3_bucket_lifecycle_configuration" "release_plan"', ('status = "Enabled"', "days = 3", "noncurrent_days = 1")),
    ):
        resource_block = block(RELEASE_PLAN, resource)
        require(
            resource_block,
            "bucket = aws_s3_bucket.release_plan.id",
            *settings,
            "depends_on = [aws_s3_bucket_versioning.release_plan]",
        )

    policy = block(RELEASE_PLAN, 'data "aws_iam_policy_document" "release_plan_bucket"')
    require(
        statement(policy, "DenyInsecureTransport"),
        'effect    = "Deny"',
        'actions   = ["s3:*"]',
        "aws_s3_bucket.release_plan.arn",
        '"${aws_s3_bucket.release_plan.arn}/*"',
        'type        = "*"',
        'identifiers = ["*"]',
        'test     = "Bool"',
        'variable = "aws:SecureTransport"',
        'values   = ["false"]',
    )
    for sid, variable, value in (
        ("DenyWritesWithoutKms", "s3:x-amz-server-side-encryption", '"aws:kms"'),
        ("DenyWritesWithWrongKmsKey", "s3:x-amz-server-side-encryption-aws-kms-key-id", "aws_kms_key.release_plan.arn"),
        ("DenyNonConditionalWrites", "s3:if-none-match", '"*"'),
    ):
        require(statement(policy, sid), 'effect    = "Deny"', 'actions   = ["s3:PutObject"]', '"${aws_s3_bucket.release_plan.arn}/*"', 'type        = "*"', 'identifiers = ["*"]', 'test     = "StringNotEquals"', f'variable = "{variable}"', f"values   = [{value}]")
    assert 'effect    = "Allow"' not in policy
    assert "s3:PutObjectRetention" not in policy
    assert "s3:DeleteObject" not in policy
    assert "checksum" not in policy.lower()
    require(
        block(RELEASE_PLAN, 'resource "aws_s3_bucket_policy" "release_plan"'),
        "bucket = aws_s3_bucket.release_plan.id",
        "policy = data.aws_iam_policy_document.release_plan_bucket.json",
    )
    require(RELEASE_PLAN, "ChecksumAlgorithm=SHA256", "HeadObject", "stored checksum", "KMS metadata", "default retention")
    require(AUDIT, 'starts_with = ["${aws_s3_bucket.raw.arn}/", "${aws_s3_bucket.tfstate.arn}/", "${aws_s3_bucket.agentcore_artifacts.arn}/", "${aws_s3_bucket.release_plan.arn}/"]')
    require(WORKFLOW, "- run: python3 infra/test_release_plan.py")


if __name__ == "__main__":
    main()
