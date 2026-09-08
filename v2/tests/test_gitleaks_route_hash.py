"""Keep the public route-hash exception narrower than a secret finding."""

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


def test_route_hash_allowlist_preserves_secret_detection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scanner = shutil.which("gitleaks")
    if scanner is None:
        pytest.skip("gitleaks CLI is required for the scanner control")
    caller_git = tmp_path / "caller-git"
    caller_index = tmp_path / "caller-index"
    caller_index.write_bytes(b"caller index must remain unchanged")
    monkeypatch.setenv("GIT_DIR", str(caller_git))
    monkeypatch.setenv("GIT_INDEX_FILE", str(caller_index))
    config = Path(__file__).resolve().parents[2] / ".gitleaks.toml"
    shutil.copyfile(config, tmp_path / ".gitleaks.toml")
    digest = hashlib.sha256(
        b"synthetic scanner control, never a credential"
    ).hexdigest()
    manifest_name = "v2/eval/golden/manifest-v2.json"
    manifest = tmp_path / manifest_name
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        "\n".join(
            [
                json.dumps({"route_key": digest})[1:-1],
                json.dumps({"api_key": digest})[1:-1],
                json.dumps({"route_key": "g" + digest[1:]})[1:-1],
                json.dumps({"route_key": digest.upper()})[1:-1],
                json.dumps({"route_key": "sk_live_" + digest})[1:-1],
                json.dumps({"route_key": digest, "api_key": digest})[1:-1],
            ]
        )
        + "\n"
    )
    (tmp_path / "other.json").write_text(json.dumps({"route_key": digest})[1:-1])
    (tmp_path / "upsert.sql").write_text("s3_key = EXCLUDED.s3_key\n")
    # A directory scan needs no Git repository. Commit hooks export GIT_*;
    # never let those variables redirect a test subprocess into the caller.
    scanner_env = {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }
    report = tmp_path / "scanner-report.json"
    result = subprocess.run(
        [
            scanner,
            "dir",
            ".",
            "--redact",
            "--report-format",
            "json",
            "--report-path",
            str(report),
        ],
        cwd=tmp_path,
        env=scanner_env,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 1, "scanner must detect the synthetic controls"
    findings = json.loads(report.read_text())
    locations = {(item["File"], item["StartLine"]) for item in findings}
    assert locations == {
        *((manifest_name, line) for line in range(2, 7)),
        ("other.json", 1),
    }
    assert not caller_git.exists()
    assert caller_index.read_bytes() == b"caller index must remain unchanged"


def test_release_manifest_hash_allowlist_preserves_secret_detection(
    tmp_path: Path,
) -> None:
    scanner = shutil.which("gitleaks")
    if scanner is None:
        pytest.skip("gitleaks CLI is required for the scanner control")
    config = Path(__file__).resolve().parents[2] / ".gitleaks.toml"
    shutil.copyfile(config, tmp_path / ".gitleaks.toml")
    digest = hashlib.sha256(b"synthetic release fingerprint").hexdigest()
    manifest_name = "infra/development-release-manifest.json"
    manifest = tmp_path / manifest_name
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        "\n".join(
            [
                json.dumps({"v2/agent/public-api-gate.js": digest})[1:-1],
                json.dumps({"v2/agent/public-api-other.js": digest})[1:-1],
                json.dumps({"api_key": digest})[1:-1],
                json.dumps({"api_key": "sk_live_" + digest})[1:-1],
            ]
        )
        + "\n"
    )
    report = tmp_path / "scanner-report.json"
    result = subprocess.run(
        [
            scanner,
            "dir",
            ".",
            "--redact",
            "--report-format",
            "json",
            "--report-path",
            str(report),
        ],
        cwd=tmp_path,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 1, "scanner must detect the synthetic control"
    findings = json.loads(report.read_text())
    assert {(item["File"], item["StartLine"]) for item in findings} == {
        (manifest_name, 2),
        (manifest_name, 3),
        (manifest_name, 4),
    }
