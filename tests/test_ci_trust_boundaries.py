from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
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


def test_claude_pr_review_has_no_secret_bearing_workflow() -> None:
    assert not (WORKFLOWS / "security-review.yml").exists()
    workflows = "\n".join(workflow.read_text() for workflow in WORKFLOWS.glob("*.y*ml"))
    assert "CLAUDE_API_KEY" not in workflows
    assert "claude-code-security-review" not in workflows


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
