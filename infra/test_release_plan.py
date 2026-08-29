from pathlib import Path


def main() -> None:
    config = Path(__file__).with_name("release_plan.tf").read_text()
    start = config.index('resource "aws_s3_bucket_lifecycle_configuration" "release_plan"')
    end = config.index('data "aws_iam_policy_document" "release_plan_bucket"')
    lifecycle = config[start:end]
    assert 'expiration {\n      days = 3\n    }' in lifecycle
    assert 'noncurrent_version_expiration {\n      noncurrent_days = 1\n    }' in lifecycle
    assert "depends_on = [aws_s3_bucket_versioning.release_plan]" in lifecycle


if __name__ == "__main__":
    main()
