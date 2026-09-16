"""Bootstrap approval and exact slot identities, without deployed credentials."""

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from scripts import blue_green as gate


def test_bootstrap_requires_exact_reviewed_binary_and_declared_move() -> None:
    raw = b"reviewed binary plan"
    digest = hashlib.sha256(raw).hexdigest()
    change = {
        "address": 'aws_lambda_function.tollchat_proxy["blue"]',
        "previous_address": "aws_lambda_function.tollchat_proxy",
        "change": {"actions": ["no-op"]},
    }
    plan = {
        "complete": True,
        "errored": False,
        "resource_drift": [],
        "variables": {"environment": {"value": "development"}},
        "resource_changes": [change],
    }
    gate.validate_bootstrap(plan, digest, raw)
    with pytest.raises(gate.Rejected, match="bootstrap_approval"):
        gate.validate_bootstrap(plan, digest, b"different binary")
    change["previous_address"] = "aws_lambda_function.loader"
    with pytest.raises(gate.Rejected, match="bootstrap_move"):
        gate.validate_bootstrap(plan, digest, raw)


@pytest.mark.skipif(shutil.which("terraform") is None, reason="Terraform is required")
def test_terraform_descriptors_reject_wildcard_runtime_identity(tmp_path: Path) -> None:
    source = (Path(__file__).parents[1] / "infra/releases.tf").read_text()
    variables = source.split('variable "active_slot"', 1)[0]
    (tmp_path / "main.tf").write_text(
        'variable "environment" { default = "development" }\n'
        + variables
        + '\noutput "slots" { value = var.release_slots }\n'
    )
    values: dict[str, Any] = {
        "release_slots": {
            name: {
                "release_id": name,
                "runtime_id": "nova_toll_v2_development"
                + ("_green" if name == "green" else "")
                + "-123",
                "runtime_key": f"releases/{name}/agentcore.zip",
                "runtime_object_version": "version1",
                "runtime_sha256": "a" * 64,
                "proxy_key": f"releases/{name}/chat-proxy.zip",
                "proxy_object_version": "version2",
                "proxy_sha256": "a" * 43 + "=",
                "runtime_environment": {},
                "proxy_environment": {},
                "asset_prefix": f"/releases/{name}",
            }
            for name in ("blue", "green")
        }
    }
    subprocess.run(
        ["terraform", "init", "-backend=false", "-input=false"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    for identity, success in (
        ("nova_toll_v2_development_green-123", True),
        ("*", False),
    ):
        values["release_slots"]["green"]["runtime_id"] = identity
        (tmp_path / "slots.tfvars.json").write_text(json.dumps(values))
        result = subprocess.run(
            [
                "terraform",
                "plan",
                "-input=false",
                "-refresh=false",
                "-no-color",
                "-var-file=slots.tfvars.json",
            ],
            cwd=tmp_path,
            capture_output=True,
            text=True,
        )
        assert (result.returncode == 0) == success, result.stderr
        if not success:
            assert "without wildcards" in result.stderr
