import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent
WORKFLOWS = REPO_ROOT / ".github" / "workflows"


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
