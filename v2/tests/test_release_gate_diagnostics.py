"""Gate failures retain finite public reasons while private details stay private."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import blue_green as gate
from scripts import classify_deployment_error as diagnostics
from scripts import release_blue_green as release


@pytest.mark.parametrize(
    "reason",
    [
        "phase_boundary",
        "incomplete_or_drift",
        "public_chat_code",
        "public_chat_identity",
        "secret-token=do-not-print\nprovider",
    ],
)
def test_main_reports_only_allowlisted_gate_reason(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    reason: str,
) -> None:
    def rejected(_environment: str) -> None:
        raise gate.Rejected(reason)

    monkeypatch.setattr(release, "configure", rejected)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "release_blue_green.py",
            "prepare-plan",
            "--terraform-root",
            str(tmp_path),
            "--bundle-root",
            str(tmp_path),
            "--foundation-vars",
            str(tmp_path / "foundation.json"),
            "--work-dir",
            str(tmp_path),
            "--output",
            str(tmp_path / "result.json"),
            "--claim",
            "test",
        ],
    )
    assert release.main() == 1
    output = capsys.readouterr()
    expected = reason if reason in diagnostics.GATE_REASONS else "gate_rejected"
    assert output.err == f"deployment_gate_reason={expected}\n"
    assert diagnostics.classify_text(output.err) == expected
    assert "secret-token" not in output.out + output.err


@pytest.mark.parametrize("reason", diagnostics.GATE_REASONS)
def test_private_stage_preserves_reason_without_private_output(
    tmp_path: Path, reason: str
) -> None:
    root = Path(__file__).resolve().parents[2]
    command = """
source v2/scripts/run_private_stage.sh
fail() {
  printf 'deployment_gate_reason=%s\n' "$GATE_REASON" >&2
  printf 'private-secret'
  return 7
}
run_private_stage plan "$RUNNER_TEMP/out" "$RUNNER_TEMP/err" fail
"""
    result = subprocess.run(
        ["bash", "-c", command],
        cwd=root,
        env={**os.environ, "RUNNER_TEMP": str(tmp_path), "GATE_REASON": reason},
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 7
    assert f"exit=7 reason={reason}" in result.stderr
    assert "private-secret" not in result.stdout + result.stderr
    assert str(tmp_path) not in result.stdout + result.stderr


@pytest.mark.parametrize(
    "text",
    [
        "deployment_gate_reason=secret-token",
        "deployment_gate_reason=phase_boundary secret-token",
        "prefix deployment_gate_reason=phase_boundary",
    ],
)
def test_unknown_or_partial_markers_are_not_exposed(text: str) -> None:
    assert diagnostics.classify_text(text) == "unclassified"


@pytest.mark.parametrize(
    "error,reason",
    [
        (release.checks.CheckFailure("canary_grounding"), "canary_grounding"),
        (gate.Rejected("serving_identity"), "serving_identity"),
        (
            release.checks.CheckFailure("private-secret\ncanary_grounding"),
            "unclassified",
        ),
    ],
)
def test_canary_stage_preserves_only_fixed_failure_reasons(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    error: ValueError,
    reason: str,
) -> None:
    summary = tmp_path / "summary"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setattr(release.time, "monotonic", lambda: 0.0)
    with pytest.raises(type(error)), release.timed_stage("candidate-canary"):
        raise error
    output = capsys.readouterr().err
    assert f"status=fail elapsed=0 exit=1 reason={reason}" in summary.read_text()
    assert diagnostics.classify_text(output) == reason
    assert "private-secret" not in output + summary.read_text()


@pytest.mark.parametrize(
    "error,reason",
    [
        (release.checks.CheckFailure("canary_evidence"), "canary_evidence"),
        (gate.Rejected("invoked_release"), "invoked_release"),
        (RuntimeError("private-secret\ncanary_evidence"), "observation_failed"),
    ],
)
def test_observation_retains_bounded_reasons_and_recovers_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    error: Exception,
    reason: str,
) -> None:
    summary = tmp_path / "summary"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    elapsed = 0.0
    monkeypatch.setattr(release.time, "monotonic", lambda: elapsed)
    recovered: list[bool] = []

    def probe() -> bool:
        nonlocal elapsed
        elapsed += 7
        raise error

    def recover() -> bool:
        recovered.append(True)
        return True

    result = release.observe(
        probe, recover, clock=lambda: elapsed, sleep=lambda _: None
    )
    assert result == {
        "deployment": "failed",
        "recovery": "recovered",
        "probes": [False, False],
    }
    assert recovered == [True]
    output = capsys.readouterr().err
    assert diagnostics.classify_text(output) == reason
    for index in (1, 2):
        assert (
            f"stage=observation-probe-{index} status=fail elapsed=7 exit=1 reason={reason}"
            in summary.read_text()
        )
    assert "observation-probe-3" not in summary.read_text()
    assert "private-secret" not in output + summary.read_text()
