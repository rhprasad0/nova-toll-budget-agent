"""Shadow CI remains credential-free until real reviewed inputs are installed."""

import os
import subprocess
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
    assert "shadow-readiness" in ci["jobs"]
    follow_on = yaml.safe_load(
        (root / ".github/workflows/v2-shadow-ci.yml").read_text()
    )
    job = follow_on["jobs"]["evaluate"]
    assert job["needs"] == "prepare"
    prepare = follow_on["jobs"]["prepare"]
    assert "head_repository.full_name == github.repository" in prepare["if"]
    assert "conclusion == 'success'" in prepare["if"]
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
    guard = steps[0]["run"]
    approved = {
        "CANDIDATE_SHA": "a" * 40,
        "EVENT_SHA": "a" * 40,
        "EVENT_NAME": "workflow_run",
        "EVENT_CONCLUSION": "success",
        "EVENT_PATH": ".github/workflows/ci.yml",
        "EVENT_REPOSITORY": "rhprasad0/nova-toll-budget-agent",
        "HEAD_REPOSITORY": "rhprasad0/nova-toll-budget-agent",
        "PYTHON_VERSION": "3.13.16",
        "RUNNER_LABEL": "ubuntu-latest",
    }
    for changed in (
        {},
        *[
            {key: value}
            for key, value in {
                "CANDIDATE_SHA": "b" * 40,
                "EVENT_NAME": "pull_request",
                "EVENT_CONCLUSION": "failure",
                "EVENT_PATH": "other.yml",
                "HEAD_REPOSITORY": "someone/fork",
                "PYTHON_VERSION": "3.12.1",
                "RUNNER_LABEL": "self-hosted",
            }.items()
        ],
    ):
        result = subprocess.run(
            ["bash", "-euo", "pipefail", "-c", guard],
            env={**os.environ, **approved, **changed},
            capture_output=True,
        )
        assert (result.returncode == 0) is (not changed)
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
    assert "refs/pull" not in policy and "gh-readonly-queue" not in policy
