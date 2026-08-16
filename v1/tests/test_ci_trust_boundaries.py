import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
MAIN_SUBJECT = (
    "repo:rhprasad0@91573985/nova-toll-budget-agent@1306930324:ref:refs/heads/main"
)


def test_openai_ci_credentials_are_main_only() -> None:
    workflow = (WORKFLOWS / "ci.yml").read_text()
    iam = (ROOT / "infra" / "iam.tf").read_text()
    trust = iam.split('data "aws_iam_policy_document" "github_ci_assume"', 1)[1].split(
        'resource "aws_iam_role" "github_ci"', 1
    )[0]

    assert "github.event.pull_request.head.repo.full_name" not in workflow
    assert MAIN_SUBJECT in trust
    assert ":pull_request" not in trust
    assert "refs/heads/*" not in trust


def test_agent_eval_runners_are_not_in_required_ci() -> None:
    ci = (WORKFLOWS / "ci.yml").read_text()
    assert "python eval/deterministic/" not in ci
    assert "python eval/simulated/" not in ci
    assert not (WORKFLOWS / "nightly-evals.yml").exists()
    assert not (WORKFLOWS / "batch-judge-collector.yml").exists()


def test_claude_pr_review_has_no_secret_bearing_workflow() -> None:
    assert not (WORKFLOWS / "security-review.yml").exists()
    workflows = "\n".join(workflow.read_text() for workflow in WORKFLOWS.glob("*.y*ml"))
    assert "CLAUDE_API_KEY" not in workflows
    assert "claude-code-security-review" not in workflows


def test_trivy_scans_vulnerabilities_and_terraform_without_secrets() -> None:
    workflow = yaml.load((WORKFLOWS / "trivy.yml").read_text(), Loader=yaml.BaseLoader)

    assert workflow["on"] == {
        "push": {"branches": ["main"]},
        "pull_request": "",
        "schedule": [{"cron": "0 6 * * 1"}],
    }

    steps = workflow["jobs"]["scan"]["steps"]
    trivy_steps = [
        step
        for step in steps
        if step.get("uses", "").startswith("aquasecurity/trivy-action@")
    ]
    assert len(trivy_steps) == 1
    assert trivy_steps[0]["with"] == {
        "scan-type": "fs",
        "scan-ref": ".",
        "scanners": "vuln,misconfig",
        "severity": "HIGH,CRITICAL",
        "exit-code": "1",
        "trivyignores": ".trivyignore.yaml",
    }

    actions = [step["uses"].rsplit("@", 1)[1] for step in steps if "uses" in step]
    assert actions
    assert all(re.fullmatch(r"[0-9a-f]{40}", ref) for ref in actions)


def test_trivy_exceptions_are_narrow_and_security_findings_are_fixed() -> None:
    ignores = yaml.load(
        (REPO_ROOT / ".trivyignore.yaml").read_text(), Loader=yaml.BaseLoader
    )
    assert ignores == {
        "misconfigurations": [
            {
                "id": "AVD-AWS-0104",
                "paths": ["v1/infra/agentcore.tf"],
                "statement": "The runtime must reach the public OpenAI API over HTTPS.",
                "expired_at": "2027-02-13",
            },
            {
                "id": "AVD-AWS-0104",
                "paths": ["v1/infra/network.tf"],
                "statement": "The Tailscale exit node must forward peer-selected internet traffic.",
                "expired_at": "2027-02-13",
            },
            {
                "id": "AVD-AWS-0132",
                "paths": ["v1/infra/agentcore.tf"],
                "statement": "Versioned deployment artifacts contain no user data and use SSE-S3.",
                "expired_at": "2027-02-13",
            },
            {
                "id": "AVD-AWS-0132",
                "paths": ["v1/infra/site.tf"],
                "statement": "The bucket contains public static assets and uses SSE-S3.",
                "expired_at": "2027-02-13",
            },
            {
                "id": "AVD-AWS-0131",
                "paths": ["v1/infra/tailscale.tf"],
                "statement": "Encrypt by staged router cutover; replacing the sole bridge unattended risks an outage.",
                "expired_at": "2027-02-13",
            },
        ]
    }

    lambda_tf = (ROOT / "infra/lambda.tf").read_text()
    observability = (ROOT / "infra/observability.tf").read_text()
    kms = (ROOT / "infra/kms.tf").read_text()
    tailscale = (ROOT / "infra/tailscale.tf").read_text()

    assert "sqs_managed_sse_enabled = true" in lambda_tf
    assert "kms_master_key_id = aws_kms_key.alerts.arn" in observability
    assert 'resource "aws_kms_key" "alerts"' in kms
    assert 'identifiers = ["cloudwatch.amazonaws.com"]' in kms
    assert re.search(r'http_tokens\s+= "required"', tailscale)
    assert "root_block_device" not in tailscale


def test_terraform_pr_checks_are_credential_free() -> None:
    workflow = (WORKFLOWS / "terraform.yml").read_text()
    iam = (ROOT / "infra" / "iam.tf").read_text()
    apply_trust = iam.split(
        'data "aws_iam_policy_document" "terraform_apply_assume"', 1
    )[1].split('resource "aws_iam_role" "terraform_apply"', 1)[0]

    assert "\n  plan:\n" not in workflow
    assert "nova-toll-terraform-plan" not in workflow
    assert "terraform_plan" not in iam
    assert MAIN_SUBJECT in apply_trust
    assert ":pull_request" not in apply_trust


def test_cloudflare_token_is_handed_off_without_destroying_ssm_parameter() -> None:
    ssm = (ROOT / "infra" / "ssm.tf").read_text()
    variables = (ROOT / "infra" / "variables.tf").read_text()
    terraform = "\n".join(path.read_text() for path in (ROOT / "infra").glob("*.tf"))
    handoff = """removed {
  from = aws_ssm_parameter.cloudflare_api_token

  lifecycle {
    destroy = false
  }
}"""

    assert "/nova-toll/cloudflare-api-token" not in terraform
    assert handoff in ssm
    assert terraform.count("aws_ssm_parameter.cloudflare_api_token") == 1
    assert "cloudflare_api_token_param_name" not in variables
