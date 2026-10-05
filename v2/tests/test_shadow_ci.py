"""Shadow CI remains credential-free until real reviewed inputs are installed."""

from pathlib import Path

import pytest
import yaml

from eval import corpus, golden, shadow_ci


def test_shadow_readiness_waits_for_real_inputs_but_rejects_partial_sets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    public = tmp_path / "active"
    monkeypatch.setattr(corpus, "PUBLIC", public)
    monkeypatch.setattr(shadow_ci, "APPROVAL", tmp_path / "approval.json")
    assert shadow_ci.prepare()["ready"] is False
    public.mkdir()
    with pytest.raises(ValueError, match="No active golden corpus"):
        shadow_ci.prepare()


def test_shadow_workflow_uses_approved_runtime_before_fixed_read_only_role() -> None:
    root = golden.V2.parent
    ci = yaml.safe_load((root / ".github/workflows/ci.yml").read_text())
    job = ci["jobs"]["shadow-eval"]
    assert job["needs"] == "shadow-readiness"
    assert "head.repo.full_name == github.repository" in job["if"]
    assert job["uses"] == "./.github/workflows/v2-shadow-eval.yml"
    workflow = yaml.safe_load(
        (root / ".github/workflows/v2-shadow-eval.yml").read_text()
    )
    steps = workflow["jobs"]["evaluate"]["steps"]
    verify = next(
        i for i, step in enumerate(steps) if "--verify-runtime" in step.get("run", "")
    )
    credentials = next(
        i
        for i, step in enumerate(steps)
        if "configure-aws-credentials" in step.get("uses", "")
    )
    assert verify < credentials
    assert steps[credentials]["with"]["allowed-account-ids"] == "903859731897"
    assert steps[credentials]["with"]["role-to-assume"].endswith(
        "nova-toll-v2-shadow-eval-dev"
    )
    command = next(
        step["run"]
        for step in steps
        if step.get("name") == "Evaluate all ten shadow cases once"
    )
    assert "--budget-usd 2" in command and "--trials-per-case 1" in command
    assert "--cases" not in command
    policy = (root / "infra/shadow_eval.tf").read_text()
    assert 'Action   = ["ssm:GetParameter"]' in policy
    assert "parameter/nova-toll/openai_api_key" in policy
    assert "v2-shadow-eval.yml@refs/heads/main" in policy
