"""Keep the reviewed release-manifest fingerprint exception narrow."""

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest


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
