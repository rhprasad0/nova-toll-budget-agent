"""The chaos lab's dataset bucket, read from root infra/'s development plan."""

from typing import Any

Plan = dict[str, dict[str, Any]]


def test_the_chaos_lab_bucket_is_private_versioned_and_encrypted(
    foundation_development_plan: Plan,
) -> None:
    plan = foundation_development_plan
    assert plan["aws_s3_bucket.chaos_lab[0]"]["bucket"].startswith("chaos-lab-")
    access = plan["aws_s3_bucket_public_access_block.chaos_lab[0]"]
    assert all(
        access[key]
        for key in (
            "block_public_acls",
            "block_public_policy",
            "ignore_public_acls",
            "restrict_public_buckets",
        )
    )
    (versioning,) = plan["aws_s3_bucket_versioning.chaos_lab[0]"][
        "versioning_configuration"
    ]
    assert versioning["status"] == "Enabled"
    (rule,) = plan["aws_s3_bucket_server_side_encryption_configuration.chaos_lab[0]"][
        "rule"
    ]
    assert rule["apply_server_side_encryption_by_default"][0]["sse_algorithm"] == (
        "AES256"
    )
    assert "aws_s3_bucket_policy.chaos_lab[0]" in plan
