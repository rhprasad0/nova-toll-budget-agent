from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_reviewed_packages_publish_atomically_and_rollback_verifies_them() -> None:
    workflow = (ROOT / ".github" / "workflows" / "terraform.yml").read_text()
    rollback = (ROOT / "docs" / "runbooks" / "rollback.md").read_text()
    agentcore = (ROOT / "infra" / "agentcore.tf").read_text()
    audit = (ROOT / "infra" / "audit.tf").read_text()

    for artifact in (
        "agentcore.zip",
        "chat-proxy.zip",
        "fetcher.zip",
        "loader.zip",
    ):
        assert artifact in workflow
        assert artifact in rollback

    apply = workflow.index("terraform apply -auto-approve")
    stage = workflow.index("name: Stage reviewed packages")
    publish = workflow.index("name: Publish reviewed release")
    latest = workflow.index("reviewed/latest")
    assert stage < apply < publish < latest
    assert "SHA256SUMS" in workflow
    assert 'REVIEWED_RELEASE="${GITHUB_SHA}/' in workflow
    assert "GITHUB_STEP_SUMMARY" in workflow
    assert "--checksum-algorithm SHA256" in workflow
    assert "--checksum-mode ENABLED" in workflow
    assert "sha256sum --check SHA256SUMS" in workflow

    assert "rebuild the corresponding Git commit" not in rollback
    assert "s3://$artifact_bucket/reviewed/latest" not in rollback
    assert "prior successful Terraform workflow run" in rollback
    assert "${reviewed_release#*/}" in rollback
    assert "sha256sum SHA256SUMS" in rollback
    assert "sha256sum --check SHA256SUMS" in rollback
    assert "trap fail_closed EXIT" in rollback
    bounded = rollback.index("Validate with bounded private concurrency")
    smoke = rollback.index("scripts/smoke_agentcore_canonical.py")
    restore = rollback.index("Restore approved proxy concurrency")
    assert bounded < smoke < restore
    config = rollback.index("https://preview.tollchat.ai/api/config")
    assert rollback.index("--reserved-concurrent-executions 1") < config < smoke
    assert "--write-out '%{http_code}'" in rollback
    assert '" = 200' in rollback
    assert restore < rollback.index(
        '--reserved-concurrent-executions "$baseline_concurrency"'
    )

    lifecycle = agentcore.split(
        'resource "aws_s3_bucket_lifecycle_configuration" "agentcore_artifacts"'
    )[1].split('data "aws_iam_policy_document" "agentcore_artifacts"')[0]
    assert 'prefix = "runtime/"' in lifecycle
    assert '"${aws_s3_bucket.agentcore_artifacts.arn}/"' in audit
