"""Offline ownership and finality checks for explicit deployment evidence."""

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts/development_deployment_status.py"
spec = importlib.util.spec_from_file_location("deployment_status", SCRIPT)
assert spec and spec.loader
status = importlib.util.module_from_spec(spec)
spec.loader.exec_module(status)


@pytest.fixture
def context(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Any, ...]:
    sha = "a" * 40
    for key, value in {
        "GITHUB_SHA": sha,
        "GITHUB_REPOSITORY": status.REPOSITORY,
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_RUN_ID": "123",
        "GITHUB_RUN_ATTEMPT": "2",
        "GITHUB_OUTPUT": str(tmp_path / "output"),
        "GITHUB_STEP_SUMMARY": str(tmp_path / "summary"),
        "RUNNER_TEMP": str(tmp_path),
        "PREPARE_OUTCOME": "success",
        "UPLOAD_OUTCOME": "success",
        "EVIDENCE_ARTIFACT_NAME": "v2-development-evidence-123-2",
        "EVIDENCE_ARTIFACT_ID": "101",
        "RAW_EVIDENCE_ARTIFACT_DIGEST": "c" * 64,
    }.items():
        monkeypatch.setenv(key, value)
    needs: dict[str, Any] = {
        job: {"result": "success", "outputs": {}}
        for job in ("admission", "release-record", "build", "deploy")
    }
    needs["release-record"]["outputs"] = {"deployment_id": "7"}
    needs["deploy"]["outputs"] = {
        "verified": "success",
        "canary": json.dumps(
            {
                "schema_version": 1,
                "runtime_version": "8",
                "proxy_version": "12",
                "call_count": 1,
                "total_usd": "4.25",
                "elapsed_ms": 10,
                "model": "gpt-5.6-luna",
                "tool_contract": "1.5.0",
                "prompt_version": "2.3.0",
                "renderer_version": "1.0.0",
                "success": True,
                "commit": sha,
                "run_id": 123,
                "attempt": 2,
                "deployment_id": 7,
                "artifact_id": 99,
                "artifact_digest": "sha256:" + "b" * 64,
            }
        ),
        "verified_pricing_schema": "1.2.3",
        "verified_oracle_schema": "1.14.0",
    }
    needs["build"]["outputs"] = {
        "artifact_id": "99",
        "artifact_digest": "sha256:" + "b" * 64,
        "pricing_schema": "1.2.3",
        "oracle_schema": "1.14.0",
    }
    record = {
        "id": 7,
        "sha": sha,
        "environment": status.ENVIRONMENT,
        "task": "development-release",
        "payload": {"run_id": 123, "created_attempt": 1, "sha": sha},
    }
    current = {"head_sha": sha, "run_attempt": 2}
    calls: list[tuple[str, str, dict[str, Any] | None]] = []

    def fake_api(
        method: str, path: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        calls.append((method, path, payload))
        if path == "actions/runs/123":
            return current
        return record

    monkeypatch.setattr(status, "api", fake_api)
    return needs, record, current, calls, tmp_path


def _finish(monkeypatch: pytest.MonkeyPatch, needs: dict[str, Any]) -> None:
    monkeypatch.setenv("NEEDS_JSON", json.dumps(needs))
    monkeypatch.setattr(
        status.sys, "argv", ["development_deployment_status.py", "finish"]
    )
    assert status.main() == 0


def test_prepare_writes_exact_versioned_evidence_then_finish_publishes_success(
    context: tuple[Any, ...], monkeypatch: pytest.MonkeyPatch
) -> None:
    needs, _, _, calls, tmp_path = context
    monkeypatch.setenv("NEEDS_JSON", json.dumps(needs))
    status.prepare()
    evidence = json.loads((tmp_path / status.EVIDENCE_FILE).read_text())
    assert evidence == {
        "schema_version": 1,
        "repository": status.REPOSITORY,
        "environment": status.ENVIRONMENT,
        "commit": "a" * 40,
        "deployment_id": 7,
        "run_id": 123,
        "attempt": 2,
        "artifact_id": 99,
        "artifact_digest": "sha256:" + "b" * 64,
        "schema_versions": {
            "declared": {"pricing": "1.2.3", "oracle": "1.14.0"},
            "installed": {"pricing": "1.2.3", "oracle": "1.14.0"},
        },
        "readiness": "success",
        "canary": {
            "schema_version": 1,
            "runtime_version": "8",
            "proxy_version": "12",
            "call_count": 1,
            "total_usd": "4.25",
            "elapsed_ms": 10,
            "model": "gpt-5.6-luna",
            "tool_contract": "1.5.0",
            "prompt_version": "2.3.0",
            "renderer_version": "1.0.0",
            "success": True,
            "commit": "a" * 40,
            "run_id": 123,
            "attempt": 2,
            "deployment_id": 7,
            "artifact_id": 99,
            "artifact_digest": "sha256:" + "b" * 64,
        },
    }
    assert calls == []
    _finish(monkeypatch, needs)
    payload = calls[-1][2]
    assert payload and payload["state"] == "success"
    assert payload["auto_inactive"] is False
    assert payload["log_url"].endswith("/attempts/2")
    summary = (tmp_path / "summary").read_text()
    assert '"state": "pending"' in summary
    assert "stage=release-status status=pass" in summary
    assert "evidence_artifact_digest" in summary
    assert "sha256:" + "c" * 64 in summary


@pytest.mark.parametrize("outcome", ["failure", "cancelled", "skipped", "missing"])
def test_non_success_prerequisite_never_passes(
    context: tuple[Any, ...], monkeypatch: pytest.MonkeyPatch, outcome: str
) -> None:
    needs, _, _, calls, tmp_path = context
    needs["deploy"]["result"] = outcome
    monkeypatch.setenv("NEEDS_JSON", json.dumps(needs))
    with pytest.raises(ValueError):
        status.finish()
    assert calls[-1][2] and calls[-1][2]["state"] == "failure"
    assert '"artifact_id": "unavailable"' in (tmp_path / "summary").read_text()


@pytest.mark.parametrize("stage", ["prepare", "upload"])
def test_failed_publication_stage_never_passes(
    context: tuple[Any, ...], monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    needs, _, _, calls, _ = context
    monkeypatch.setenv("NEEDS_JSON", json.dumps(needs))
    monkeypatch.setenv(f"{stage.upper()}_OUTCOME", "failure")
    with pytest.raises(ValueError):
        status.finish()
    assert [
        payload["state"] for _, path, payload in calls if path.endswith("/statuses")
    ] == ["failure"]


@pytest.mark.parametrize(
    "wrong",
    [
        "run",
        "sha",
        "attempt",
        "record",
        "bundle",
        "digest",
        "schema",
        "installed",
        "readiness",
        "publication_id",
        "publication_digest",
        "publication_name",
        "canary_bool",
        "canary_version",
    ],
)
def test_wrong_identity_or_evidence_fails_closed(
    context: tuple[Any, ...], monkeypatch: pytest.MonkeyPatch, wrong: str
) -> None:
    needs, record, current, calls, _ = context
    if wrong == "run":
        record["payload"]["run_id"] = 124
    elif wrong == "sha":
        record["sha"] = "c" * 40
    elif wrong == "attempt":
        current["run_attempt"] = 3
    elif wrong == "record":
        needs["release-record"]["outputs"] = {}
    elif wrong == "bundle":
        needs["build"]["outputs"]["artifact_id"] = "0"
    elif wrong == "digest":
        needs["build"]["outputs"]["artifact_digest"] = "private injected content"
    elif wrong == "schema":
        needs["build"]["outputs"]["pricing_schema"] = "not-a-version"
    elif wrong == "installed":
        needs["deploy"]["outputs"]["verified_pricing_schema"] = "9.9.9"
    elif wrong == "readiness":
        needs["deploy"]["outputs"].pop("verified")
    elif wrong in {"canary_bool", "canary_version"}:
        canary = json.loads(needs["deploy"]["outputs"]["canary"])
        canary["elapsed_ms" if wrong == "canary_bool" else "runtime_version"] = (
            True if wrong == "canary_bool" else "v8"
        )
        needs["deploy"]["outputs"]["canary"] = json.dumps(canary)
    elif wrong == "publication_id":
        monkeypatch.setenv("EVIDENCE_ARTIFACT_ID", "0")
    elif wrong == "publication_digest":
        monkeypatch.setenv("RAW_EVIDENCE_ARTIFACT_DIGEST", "sha256:" + "c" * 64)
    else:
        monkeypatch.setenv("EVIDENCE_ARTIFACT_NAME", "prior-attempt-evidence")
    monkeypatch.setenv("NEEDS_JSON", json.dumps(needs))
    with pytest.raises(ValueError):
        status.finish()
    assert not any(
        payload and payload.get("state") == "success" for _, _, payload in calls
    )


@pytest.mark.parametrize("bad", ["private string", [], None])
def test_nested_non_mapping_outputs_fail_closed(
    context: tuple[Any, ...], monkeypatch: pytest.MonkeyPatch, bad: Any
) -> None:
    needs, _, _, calls, _ = context
    needs["build"]["outputs"] = bad
    monkeypatch.setenv("NEEDS_JSON", json.dumps(needs))
    with pytest.raises(ValueError):
        status.finish()
    assert calls[-1][2] and calls[-1][2]["state"] == "failure"


def test_same_run_failed_deploy_rerun_uses_current_attempt(
    context: tuple[Any, ...], monkeypatch: pytest.MonkeyPatch
) -> None:
    needs, _, _, calls, tmp_path = context
    _finish(monkeypatch, needs)
    assert calls[-1][2] and calls[-1][2]["log_url"].endswith("/attempts/2")
    assert "v2-development-evidence-123-2" in (tmp_path / "summary").read_text()


def test_create_exact_record_without_native_inactivation(
    context: tuple[Any, ...],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _, _, _, calls, tmp_path = context
    monkeypatch.setattr(
        status.sys, "argv", ["development_deployment_status.py", "create"]
    )
    assert status.main() == 0
    events = capsys.readouterr().err
    assert "stage=release-record status=pass" in events
    assert "stage=release-status" not in events
    payload = calls[0][2]
    assert payload and payload["auto_merge"] is False
    assert payload["production_environment"] is False
    assert payload["required_contexts"] == []
    assert payload["payload"]["created_attempt"] == 2
    assert calls[-1][2] and calls[-1][2]["auto_inactive"] is False
    assert (tmp_path / "output").read_text() == "deployment_id=7\n"


def test_prepare_then_failed_upload_never_passes_release_status(
    context: tuple[Any, ...],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    needs, _, _, calls, tmp_path = context
    monkeypatch.setenv("NEEDS_JSON", json.dumps(needs))
    monkeypatch.setattr(
        status.sys, "argv", ["development_deployment_status.py", "prepare"]
    )
    assert status.main() == 0
    prepare_events = capsys.readouterr().err
    assert prepare_events.count("stage=release-evidence-prepare status=start") == 1
    assert prepare_events.count("stage=release-evidence-prepare status=pass") == 1
    assert "stage=release-status status=pass" not in prepare_events
    assert (tmp_path / status.EVIDENCE_FILE).exists()

    monkeypatch.setenv("UPLOAD_OUTCOME", "failure")
    monkeypatch.setattr(
        status.sys, "argv", ["development_deployment_status.py", "finish"]
    )
    assert status.main() == 1
    finish_events = capsys.readouterr().err
    assert finish_events.count("stage=release-status status=start") == 1
    assert finish_events.count("stage=release-status status=fail") == 1
    assert "stage=release-status status=pass" not in finish_events
    assert [
        payload["state"] for _, path, payload in calls if path.endswith("/statuses")
    ] == ["failure"]


def test_status_api_failure_does_not_write_success(
    context: tuple[Any, ...],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    needs, _, _, calls, tmp_path = context
    monkeypatch.setenv("NEEDS_JSON", json.dumps(needs))
    original = status.api
    status_attempts: list[dict[str, Any] | None] = []

    def fail_status(
        method: str, path: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if path.endswith("/statuses"):
            status_attempts.append(payload)
            raise ValueError("API failed")
        return original(method, path, payload)

    monkeypatch.setattr(status, "api", fail_status)
    monkeypatch.setattr(
        status.sys, "argv", ["development_deployment_status.py", "finish"]
    )
    assert status.main() == 1
    assert "reason=publisher_failed" in capsys.readouterr().err
    assert len(status_attempts) == 1
    assert not any(
        payload and payload.get("state") == "success" for _, _, payload in calls
    )
    summary = (tmp_path / "summary").read_text()
    assert '"state": "pending"' in summary
    assert '"state": "success"' not in summary
    assert "stage=release-status status=fail" in summary


def test_summary_failure_posts_failure_before_any_success(
    context: tuple[Any, ...], monkeypatch: pytest.MonkeyPatch
) -> None:
    needs, _, _, calls, tmp_path = context
    monkeypatch.setenv("NEEDS_JSON", json.dumps(needs))
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(tmp_path))
    with pytest.raises(ValueError):
        status.finish()
    assert [
        payload["state"] for _, path, payload in calls if path.endswith("/statuses")
    ] == ["failure"]


def test_upstream_failure_reason_is_fixed_and_progress_is_mirrored(
    context: tuple[Any, ...],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    needs, _, _, calls, tmp_path = context
    needs["deploy"]["result"] = "failure"
    monkeypatch.setenv("NEEDS_JSON", json.dumps(needs))
    monkeypatch.setattr(
        status.sys, "argv", ["development_deployment_status.py", "finish"]
    )
    assert status.main() == 1
    captured = capsys.readouterr()
    assert "reason=upstream_failed" in captured.err
    assert "private" not in captured.err
    assert calls[-1][2] and calls[-1][2]["state"] == "failure"
    assert "reason=upstream_failed" in (tmp_path / "summary").read_text()


def test_malformed_needs_reason_does_not_expose_nested_content(
    context: tuple[Any, ...],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    needs, _, _, _, _ = context
    needs["build"] = "secret nested evidence"
    monkeypatch.setenv("NEEDS_JSON", json.dumps(needs))
    monkeypatch.setattr(
        status.sys, "argv", ["development_deployment_status.py", "prepare"]
    )
    assert status.main() == 1
    captured = capsys.readouterr()
    assert "stage=release-evidence-prepare status=fail" in captured.err
    assert "stage=release-status" not in captured.err
    assert "reason=malformed_evidence" in captured.err
    assert "secret nested evidence" not in captured.err
