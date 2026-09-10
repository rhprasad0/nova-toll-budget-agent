"""Execute the actual production workflow shell without AWS credentials."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/v2-production-plan.yml"
KMS = "arn:aws:kms:us-east-1:920534282028:key/8fc1450b-0b5c-4afe-8c0a-cb150aab5da7"


def _step(name: str) -> str:
    workflow: dict[str, Any] = yaml.safe_load(WORKFLOW.read_text())
    return next(
        step["run"]
        for step in workflow["jobs"]["planner"]["steps"]
        if step.get("name", step.get("id")) == name
    )


FAKE_COMMAND = r"""
import json, os, pathlib, subprocess, sys
args = sys.argv[1:]
mode = os.environ["FAILURE"]
name = pathlib.Path(sys.argv[0]).name
print("PRIVATE_SENTINEL", file=sys.stderr)
def value(flag):
    return args[args.index(flag) + 1]
if name == "jq":
    if mode == "summary" and "release_id" in args:
        sys.exit(17)
    result = subprocess.run([os.environ["REAL_JQ"], *args], check=False)
    if mode == "summary-write" and "checksum" in args and "-e" in args:
        summary = pathlib.Path(os.environ["GITHUB_STEP_SUMMARY"])
        summary.unlink()
        summary.mkdir()
    sys.exit(result.returncode)
if name == "aws":
    if args[:2] == ["sts", "get-caller-identity"]:
        print("wrong" if mode == "account" else "920534282028")
    elif args[:2] == ["ssm", "get-parameter"]:
        print("PRIVATE_TOKEN")
    elif args[:2] == ["s3api", "put-object"]:
        if mode == "upload":
            sys.exit(19)
        assert value("--if-none-match") == "*"
        assert value("--expected-bucket-owner") == "920534282028"
        assert value("--server-side-encryption") == "aws:kms"
        pathlib.Path(os.environ["UPLOAD_MARKER"]).write_text(value("--key"))
        response = {"VersionId": "private-version", "ChecksumSHA256": value("--checksum-sha256"),
                    "SSEKMSKeyId": value("--ssekms-key-id"), "ServerSideEncryption": "aws:kms"}
        if mode in {"version", "checksum", "kms"}:
            response[{"version": "VersionId", "checksum": "ChecksumSHA256", "kms": "SSEKMSKeyId"}[mode]] = ""
        print(json.dumps(response))
    else:
        raise AssertionError(args)
elif name == "terraform":
    if "init" in args:
        assert "-backend-config=backend.production.hcl" in args
    elif "output" in args:
        fields = "vpc_id vpc_cidr_block rds_security_group_id agentcore_endpoint_security_group_id eventbridge_endpoint_security_group_id agentcore_vpc_endpoint_id agentcore_vpc_endpoint_dns_name tollchat_api_vpc_endpoint_id raw_bucket_name raw_kms_key_arn agentcore_artifacts_bucket_name alerts_topic_arn".split()
        foundation = dict.fromkeys(fields, "fixed")
        foundation.update(private_subnet_ids={"a": "subnet-a", "c": "subnet-c"}, db_instance={"address": "private", "identifier": "nova-toll-db", "port": 5432, "resource_id": "fixed"})
        print(json.dumps(foundation))
    elif "plan" in args:
        assert not any(arg.startswith("-target") for arg in args)
        if mode == "plan":
            sys.exit(18)
        pathlib.Path(next(arg.split("=", 1)[1] for arg in args if arg.startswith("-out="))).write_bytes(b"PRIVATE_PLAN")
    elif "show" in args:
        print(json.dumps({"resource_changes": [{"address": "aws_s3_bucket.site", "mode": "managed", "provider_name": "registry.terraform.io/hashicorp/aws", "change": {"actions": ["no-op"], "after_unknown": {}}}], "output_changes": {}}))
    else:
        raise AssertionError(args)
else:
    raise AssertionError(name)
"""


def _environment(tmp_path: Path, failure: str) -> dict[str, str]:
    (tmp_path / "trusted").symlink_to(ROOT, target_is_directory=True)
    temporary = tmp_path / "runner"
    temporary.mkdir()
    binary = tmp_path / "bin"
    binary.mkdir()
    for name in ("aws", "terraform", "jq"):
        path = binary / name
        path.write_text(f"#!{sys.executable}\n" + FAKE_COMMAND)
        path.chmod(0o700)
    jq = shutil.which("jq")
    assert jq
    return {
        "PATH": str(binary) + os.pathsep + os.defpath,
        "REAL_JQ": jq,
        "FAILURE": failure,
        "GITHUB_WORKSPACE": str(tmp_path),
        "RUNNER_TEMP": str(temporary),
        "GITHUB_STEP_SUMMARY": str(tmp_path / "summary"),
        "GITHUB_OUTPUT": str(tmp_path / "output"),
        "UPLOAD_MARKER": str(tmp_path / "uploaded"),
        "EXPECTED_ACCOUNT": "920534282028",
        "PLAN_BUCKET": "nova-toll-tfstate-920534282028",
        "TFSTATE_KMS_KEY_ARN": KMS,
        "RELEASE_ID": "7",
        "RELEASE_TAG": "v1.2.3",
        "CANDIDATE": "a" * 40,
        "BUNDLE_ID": "10",
        "BUNDLE_DIGEST": "sha256:" + "b" * 64,
        "LISTENER_RUN": "11",
        "LISTENER_ATTEMPT": "1",
        "DEVELOPMENT_RUN": "12",
        "DEVELOPMENT_ATTEMPT": "2",
        "DEVELOPMENT_DEPLOYMENT": "9",
        "EVIDENCE_ARTIFACT": "13",
        "EVIDENCE_DIGEST": "sha256:" + "c" * 64,
        "SCHEMA_VERSIONS": '{"pricing":"1.3.0","oracle":"1.14.0"}',
        "CLAIM_ID": "14",
        "GITHUB_RUN_ID": "15",
        "GITHUB_RUN_ATTEMPT": "1",
    }


@pytest.mark.parametrize(
    "failure,stage",
    [
        ("", ""),
        ("account", "account-identity"),
        ("plan", "plan"),
        ("upload", "artifact-metadata"),
        ("version", "artifact-metadata"),
        ("checksum", "artifact-metadata"),
        ("kms", "artifact-metadata"),
        ("summary", "release-status"),
        ("summary-write", "artifact-metadata"),
    ],
)
def test_actual_planner_shell_fails_privately_and_saves_exact_evidence(
    tmp_path: Path, failure: str, stage: str
) -> None:
    env = _environment(tmp_path, failure)
    result = subprocess.run(
        ["bash", "-c", _step("Plan and save the complete application candidate")],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert "PRIVATE_" not in result.stdout + result.stderr
    assert not (tmp_path / "runner/cloudflare-token").exists()
    assert not (tmp_path / "runner/production.tfplan").exists()
    if failure:
        assert result.returncode != 0
        assert result.stderr.count("status=fail") == 1, result.stderr
        assert f"stage={stage} status=fail" in result.stderr
        if failure in {"account", "plan", "upload"}:
            assert not (tmp_path / "uploaded").exists()
    else:
        assert result.returncode == 0, result.stderr
        summary = (tmp_path / "summary").read_text()
        assert "PRIVATE_" not in summary
        start = summary.index("{\n")
        evidence, _ = json.JSONDecoder().raw_decode(summary[start:])
        assert evidence["listener_attempt"] == "1"
        assert evidence["development_attempt"] == "2"
        assert evidence["saved_plan"]["version_id"] == "private-version"
        assert evidence["saved_plan"]["key"] == (tmp_path / "uploaded").read_text()
        assert len(evidence["local_sha256"]) == 64


@pytest.mark.parametrize("broken_output", [False, True])
def test_actual_admission_binding_preserves_json_object_and_records_output_failure(
    tmp_path: Path, broken_output: bool
) -> None:
    env = _environment(tmp_path, "")
    admission = {
        "release_id": 7,
        "tag": "v1.2.3",
        "candidate": "a" * 40,
        "bundle_id": 10,
        "bundle_digest": "sha256:" + "b" * 64,
        "schema_versions": {"pricing": "1.3.0", "oracle": "1.14.0"},
        "claim_id": 14,
    }
    env["ADMISSION"] = json.dumps(admission)
    if broken_output:
        env["GITHUB_OUTPUT"] = str(tmp_path / "missing/output")
    result = subprocess.run(
        ["bash", "-c", _step("admitted")],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert "PRIVATE_" not in result.stdout + result.stderr
    if broken_output:
        assert result.returncode != 0
        assert result.stderr.count("status=fail") == 1
    else:
        assert result.returncode == 0, result.stderr
        assert json.loads((tmp_path / "runner/admission.json").read_text()) == admission
        assert "candidate=" + "a" * 40 in (tmp_path / "output").read_text()
