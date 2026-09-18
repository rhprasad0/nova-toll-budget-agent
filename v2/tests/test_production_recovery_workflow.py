"""Fixed recovery boundary and actual result/size guards, without credentials."""

import json
import shlex
import subprocess
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml

WORKFLOW = Path(__file__).parents[2] / ".github/workflows/v2-production-recovery.yml"


def test_fixed_protected_recovery_workflow() -> None:
    workflow = yaml.safe_load(WORKFLOW.read_text())
    assert set(workflow[True]["workflow_dispatch"]["inputs"]) == {
        "claim_id",
        "record_version",
        "expected_state_sha256",
    }
    assert workflow["concurrency"] == {
        "group": "v2-production-release-delivery",
        "cancel-in-progress": False,
    }
    job = workflow["jobs"]["recover"]
    assert job["environment"] == "production"
    assert "github.ref == 'refs/heads/main'" in job["if"]
    assert "github.run_attempt == 1" in job["if"]
    steps = job["steps"]
    assert steps[0]["with"]["ref"] == "${{ github.sha }}"
    credentials = next(s for s in steps if "role-to-assume" in s.get("with", {}))
    assert (
        credentials["with"]["role-to-assume"]
        == "arn:aws:iam::920534282028:role/nova-toll-production-deploy"
    )
    for step in steps:
        if "run" in step:
            subprocess.run(["bash", "-n"], input=step["run"], text=True, check=True)
    text = WORKFLOW.read_text()
    assert "run_production_migrations" not in text and "chatEnabled" not in text
    assert text.count('release_blue_green.py" recover') == 1
    assert "--verify-checkout" in text
    assert "-lockfile=readonly" in text


@pytest.mark.parametrize("change", [None, "unverified", "identity", "failed", "exit"])
def test_recovery_result_guard_requires_verified_retained_identities(
    tmp_path: Path, change: str | None
) -> None:
    steps = yaml.safe_load(WORKFLOW.read_text())["jobs"]["recover"]["steps"]
    body = next(
        s["run"] for s in steps if s.get("name", "").startswith("Restore retained")
    )
    guard = body[body.index('test "$status" -eq 1') :]
    slot = {
        k: k
        for k in (
            "release_id",
            "proxy_arn",
            "proxy_version",
            "runtime_arn",
            "runtime_version",
            "endpoint",
            "asset_prefix",
        )
    }
    prepared = {"active": "blue", "slots": {"blue": slot, "green": slot}}
    (tmp_path / "controller").mkdir()
    (tmp_path / "controller/context.json").write_text(
        json.dumps({"prepared": prepared})
    )
    result: dict[str, Any] = {
        "deployment": "failed",
        "recovery": "recovered",
        "active": "blue",
        "releases": {"blue": dict(slot), "green": dict(slot)},
    }
    if change == "unverified":
        result["active"] = "unverified"
    if change == "identity":
        result["releases"]["green"]["release_id"] = "other"
    if change == "failed":
        result["recovery"] = "failed"
    (tmp_path / "result.json").write_text(json.dumps(result))
    status = 0 if change == "exit" else 1
    run = subprocess.run(
        [
            "bash",
            "-euc",
            f"private={shlex.quote(str(tmp_path))}\nstatus={status}\n" + guard,
        ],
        capture_output=True,
    )
    assert (run.returncode == 0) == (change is None)


def test_recovery_archive_guard_rejects_oversized_members(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    steps = yaml.safe_load(WORKFLOW.read_text())["jobs"]["recover"]["steps"]
    body = next(
        s["run"]
        for s in steps
        if s.get("name", "").startswith("Verify the original bundle")
    )
    line = next(
        line.strip()
        for line in body.splitlines()
        if line.strip().startswith("python3 -c ")
    )
    program = shlex.split(line)[2]
    monkeypatch.setattr(sys, "argv", ["guard", "bounded.zip"])

    def oversized(_path: str) -> SimpleNamespace:
        return SimpleNamespace(infolist=lambda: [SimpleNamespace(file_size=268435457)])

    monkeypatch.setattr(zipfile, "ZipFile", oversized)
    with pytest.raises(SystemExit) as error:
        exec(program, {})
    assert error.value.code is True
