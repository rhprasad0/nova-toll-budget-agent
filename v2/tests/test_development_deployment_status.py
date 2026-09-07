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
    }.items():
        monkeypatch.setenv(key, value)
    needs: dict[str, Any] = {
        job: {"result": "success", "outputs": {}}
        for job in ("admission", "release-record", "build", "oidc-proof", "deploy")
    }
    needs["release-record"]["outputs"] = {"deployment_id": "7"}
    needs["deploy"]["outputs"] = {"verified": "success"}
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


def test_same_run_failed_deploy_rerun_reuses_verified_build(
    context: tuple[Any, ...], monkeypatch: pytest.MonkeyPatch
) -> None:
    needs, _, _, calls, tmp_path = context
    monkeypatch.setenv("NEEDS_JSON", json.dumps(needs))
    status.finish()
    payload = calls[-1][2]
    assert payload["state"] == "success"
    assert payload["auto_inactive"] is False
    assert payload["log_url"].endswith("/attempts/2")
    assert "sha256:" in (tmp_path / "summary").read_text()


@pytest.mark.parametrize("outcome", ["failure", "cancelled", "skipped", "missing"])
def test_non_success_never_passes(
    context: tuple[Any, ...], monkeypatch: pytest.MonkeyPatch, outcome: str
) -> None:
    needs, _, _, calls, _ = context
    needs["deploy"]["result"] = outcome
    monkeypatch.setenv("NEEDS_JSON", json.dumps(needs))
    with pytest.raises(ValueError):
        status.finish()
    assert calls[-1][2]["state"] == "failure"


def test_failed_build_records_failure_without_artifact(
    context: tuple[Any, ...], monkeypatch: pytest.MonkeyPatch
) -> None:
    needs, _, _, calls, tmp_path = context
    needs["build"] = {"result": "failure", "outputs": {}}
    needs["deploy"]["result"] = "skipped"
    monkeypatch.setenv("NEEDS_JSON", json.dumps(needs))
    with pytest.raises(ValueError):
        status.finish()
    assert calls[-1][2]["state"] == "failure"
    assert '"artifact_id": "unavailable"' in (tmp_path / "summary").read_text()


@pytest.mark.parametrize(
    "wrong", ["run", "sha", "attempt", "record", "digest", "smoke"]
)
def test_wrong_ownership_or_evidence_fails_closed(
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
    elif wrong == "digest":
        needs["build"]["outputs"]["artifact_digest"] = "private injected content"
    else:
        needs["deploy"]["outputs"] = {}
    monkeypatch.setenv("NEEDS_JSON", json.dumps(needs))
    with pytest.raises(ValueError):
        status.finish()
    assert not any(
        payload and payload.get("state") == "success" for _, _, payload in calls
    )


def test_create_exact_record_without_native_inactivation(
    context: tuple[Any, ...],
) -> None:
    _, _, _, calls, tmp_path = context
    status.create()
    payload = calls[0][2]
    assert payload["auto_merge"] is False
    assert payload["production_environment"] is False
    assert payload["required_contexts"] == []
    assert payload["payload"]["created_attempt"] == 2
    assert calls[-1][2]["auto_inactive"] is False
    assert (tmp_path / "output").read_text() == "deployment_id=7\n"


def test_status_api_failure_does_not_write_success(
    context: tuple[Any, ...], monkeypatch: pytest.MonkeyPatch
) -> None:
    needs, _, _, _, tmp_path = context
    monkeypatch.setenv("NEEDS_JSON", json.dumps(needs))
    original = status.api

    def fail_status(
        method: str, path: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if path.endswith("/statuses"):
            raise ValueError("API failed")
        return original(method, path, payload)

    monkeypatch.setattr(status, "api", fail_status)
    with pytest.raises(ValueError):
        status.finish()
    assert not (tmp_path / "summary").exists()
