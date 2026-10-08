"""Shadow CI validates inputs before credentials and requires pass cubed >=70%."""

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import Mock

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
    assert not (root / ".github/workflows/v2-shadow-ci.yml").exists()
    job = ci["jobs"]["shadow-evaluation"]
    assert job["needs"] == "shadow-readiness"
    assert "head.repo.full_name == github.repository" in job["if"]
    assert "github.event_name == 'pull_request'" in job["if"]
    assert "github.actor_id == '91573985'" in job["if"]
    assert "outputs.ready == 'true'" in job["if"]
    assert re.fullmatch(
        r"rhprasad0/nova-toll-budget-agent/\.github/workflows/v2-shadow-eval\.yml@[0-9a-f]{40}",
        job["uses"],
    )
    revision = job["uses"].rsplit("@", 1)[1]
    assert (
        subprocess.check_output(
            ["git", "show", f"{revision}:.github/workflows/v2-shadow-eval.yml"],
            cwd=root,
        )
        == (root / ".github/workflows/v2-shadow-eval.yml").read_bytes()
    )
    assert "continue-on-error" not in ci["jobs"]["shadow-readiness"]
    readiness = ci["jobs"]["shadow-readiness"]["steps"]
    assert any("jq -e '.ready == true'" in s.get("run", "") for s in readiness)
    workflow = yaml.safe_load(
        (root / ".github/workflows/v2-shadow-eval.yml").read_text()
    )
    evaluation = workflow["jobs"]["evaluate"]
    assert "environment" not in evaluation
    assert "continue-on-error" not in evaluation
    steps = evaluation["steps"]
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
        "EVENT_NAME": "pull_request",
        "ACTOR_ID": "91573985",
        "WORKFLOW_REF": "rhprasad0/nova-toll-budget-agent/.github/workflows/ci.yml@refs/pull/1/merge",
        "GITHUB_REF": "refs/pull/1/merge",
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
                "EVENT_NAME": "workflow_run",
                "ACTOR_ID": "123456",
                "WORKFLOW_REF": "rhprasad0/nova-toll-budget-agent/.github/workflows/other.yml@refs/pull/1/merge",
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
        if step.get("name") == "Evaluate all ten shadow cases three times"
    )
    assert "--budget-usd 2" in command and "--trials-per-case 3" in command
    assert "--cases" not in command
    policy = (root / "infra/shadow_eval.tf").read_text()
    assert 'Action   = ["ssm:GetParameter"]' in policy
    assert "parameter/nova-toll/openai_api_key" in policy
    assert job["uses"] in policy
    assert 'variable = "token.actions.githubusercontent.com:actor_id"' in policy
    assert 'values   = ["91573985"]' in policy
    assert '1306930324:pull_request"' in policy
    assert "golden-evaluation" not in policy
    assert "refs/pull" not in policy and "gh-readonly-queue" not in policy


@pytest.mark.parametrize("scored_trials", [30, 28])
def test_shadow_report_preserves_incomplete_measurements(
    scored_trials: int, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    data: dict[str, Any] = {
        "manifest": {
            "mode": "run",
            "identity": {
                "commit": "a" * 40,
                "corpus": {"evaluation_scope": "shadow", "trials_per_case": 1},
                "harness_version": "2.5.17",
                "execution": {"trials_per_case": 3},
                "cases": [{}] * 10,
            },
        },
        "full_corpus_complete": scored_trials == 30,
        "overall": {
            "successful_trials": 26,
            "overall_pass_rate": 26 / 30,
            "passing_all_three_cases": 6,
            "pass_cubed": 0.6,
            "scored_trials": scored_trials,
            "inconclusive_trials": 30 - scored_trials,
            "failure_counts": {"actor_validity": 30 - scored_trials},
            "cost_usd": {"agent": 0.1, "actor": 0.05, "judge": 0.05},
        },
    }
    monkeypatch.setattr(shadow_ci.run, "render", Mock(return_value=data))
    result = shadow_ci.report(tmp_path)
    assert result["passed"] == 26 and result["expected_trials"] == 30
    assert result["pass_rate"] == 26 / 30
    assert result["pass_cubed"] == 0.6
    assert result["passing_all_three_cases"] == 6 and result["case_count"] == 10
    assert result["complete"] is (scored_trials == 30)
    assert result["scored_trials"] == scored_trials
    assert result["inconclusive_trials"] == 30 - scored_trials
    assert result["failure_counts"] == {"actor_validity": 30 - scored_trials}
    data["manifest"]["identity"]["corpus"]["evaluation_scope"] = "training"
    with pytest.raises(ValueError, match="ten-case, three-trial shadow run"):
        shadow_ci.report(tmp_path)
    data["manifest"]["identity"]["corpus"]["evaluation_scope"] = "shadow"
    data["manifest"]["identity"]["execution"]["trials_per_case"] = 1
    with pytest.raises(ValueError, match="ten-case, three-trial shadow run"):
        shadow_ci.report(tmp_path)


def test_shadow_summary_reports_failure_before_checkout(tmp_path: Path) -> None:
    workflow = yaml.safe_load(
        (golden.V2.parent / ".github/workflows/v2-shadow-eval.yml").read_text()
    )
    step = next(
        s
        for s in workflow["jobs"]["evaluate"]["steps"]
        if s.get("name") == "Report shadow results"
    )
    assert step["if"] == "always()" and step["working-directory"] == "."
    summary = tmp_path / "summary.md"
    result = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", step["run"]],
        cwd=tmp_path,
        env={
            **os.environ,
            "RUNNER_TEMP": str(tmp_path),
            "GITHUB_STEP_SUMMARY": str(summary),
        },
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "no score is available" in summary.read_text()
    assert "::error::" in result.stdout


@pytest.mark.parametrize(
    ("pass_cubed", "complete", "accepted"),
    [(0.6, True, False), (0.7, True, True), (0.8, True, True), (0.9, False, False)],
)
def test_shadow_gate_requires_seven_complete_passing_triples(
    pass_cubed: float, complete: bool, accepted: bool, tmp_path: Path
) -> None:
    workflow = yaml.safe_load(
        (golden.V2.parent / ".github/workflows/v2-shadow-eval.yml").read_text()
    )
    step = next(
        s
        for s in workflow["jobs"]["evaluate"]["steps"]
        if s.get("name") == "Report shadow results"
    )
    output = tmp_path / "shadow-run"
    output.mkdir()
    (output / "manifest.json").write_text("{}")
    report = tmp_path / "report.json"
    report.write_text(
        json.dumps(
            {
                "source_commit": "a" * 40,
                "passed": 20 + round(pass_cubed * 10),
                "expected_trials": 30,
                "passing_all_three_cases": round(pass_cubed * 10),
                "case_count": 10,
                "pass_cubed": pass_cubed,
                "scored_trials": 30 if complete else 29,
                "inconclusive_trials": 0 if complete else 1,
                "complete": complete,
                "cost_usd": 0.2,
            }
        )
    )
    uv = tmp_path / "uv"
    uv.write_text('#!/bin/sh\ncat "$SHADOW_TEST_REPORT"\n')
    uv.chmod(0o700)
    summary = tmp_path / "summary.md"
    result = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", step["run"]],
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": f"{tmp_path}:{os.environ['PATH']}",
            "SHADOW_TEST_REPORT": str(report),
            "RUNNER_TEMP": str(tmp_path),
            "GITHUB_STEP_SUMMARY": str(summary),
        },
        capture_output=True,
        text=True,
    )
    assert (result.returncode == 0) is accepted
    assert "required >=70%" in summary.read_text()
    assert ("::error::" in result.stdout) is (not accepted)
