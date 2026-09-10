"""Execute the actual production workflow shell without AWS credentials."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/v2-production-plan.yml"
MIGRATION_WORKFLOW = ROOT / ".github/workflows/v2-production-migrations.yml"
KMS = "arn:aws:kms:us-east-1:920534282028:key/8fc1450b-0b5c-4afe-8c0a-cb150aab5da7"


def _step(name: str) -> str:
    workflow: dict[str, Any] = yaml.safe_load(WORKFLOW.read_text())
    return next(
        step["run"]
        for step in workflow["jobs"]["planner"]["steps"]
        if step.get("name", step.get("id")) == name
    )


def _result_step(name: str) -> str:
    workflow: dict[str, Any] = yaml.safe_load(WORKFLOW.read_text())
    return next(
        step["run"]
        for step in workflow["jobs"]["release-result"]["steps"]
        if step.get("name", step.get("id")) == name
    )


def _migration_step(name: str) -> str:
    workflow: dict[str, Any] = yaml.safe_load(MIGRATION_WORKFLOW.read_text())
    return next(
        step["run"]
        for step in workflow["jobs"]["migrate"]["steps"]
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
    elif args[:2] == ["s3api", "head-object"]:
        print(json.dumps({"VersionId": "state-version"}))
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
        plan = {"resource_changes": [{"address": "aws_s3_bucket.site", "mode": "managed", "provider_name": "registry.terraform.io/hashicorp/aws", "change": {"actions": ["no-op"], "after_unknown": {}}}], "output_changes": {}}
        if mode == "validator":
            plan["resource_drift"] = [{"private-malicious-plan-value": "PRIVATE_SENTINEL"}]
        print(json.dumps(plan))
    elif "state" in args and "pull" in args:
        print(json.dumps({"lineage": "11111111-1111-1111-1111-111111111111", "serial": 1}))
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
    (temporary / "admission.json").write_text(
        json.dumps(
            {
                "release_id": 7,
                "tag": "v1.2.3",
                "candidate": "a" * 40,
                "listener_run": 11,
                "listener_attempt": 1,
                "development_run": 12,
                "development_attempt": 2,
                "development_deployment": 9,
                "evidence_artifact": {
                    "id": 13,
                    "name": "v2-development-evidence-12-2",
                    "size_in_bytes": 4096,
                    "archive_download_url": "https://api.github.test/artifacts/13/zip",
                    "expired": False,
                    "created_at": "2026-01-01T00:00:00Z",
                    "updated_at": "2026-01-01T00:01:00Z",
                    "expires_at": "2999-01-01T00:00:00Z",
                    "workflow_run": {"id": 12},
                    "digest": "sha256:" + "c" * 64,
                },
                "bundle_id": 10,
                "bundle_digest": "sha256:" + "b" * 64,
                "schema_versions": {"pricing": "1.3.0", "oracle": "1.14.0"},
                "consumer_run": 15,
                "consumer_attempt": 1,
                "claim_id": 14,
            }
        )
    )
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


def test_reusable_migration_permissions_and_cancellation_env_are_valid() -> None:
    workflow: dict[str, Any] = yaml.safe_load(WORKFLOW.read_text())
    migration: dict[str, Any] = yaml.safe_load(MIGRATION_WORKFLOW.read_text())
    permissions = {
        "actions": "read",
        "contents": "read",
        "deployments": "read",
        "id-token": "write",
    }

    assert workflow["jobs"]["migrate"]["permissions"] == permissions
    assert migration["jobs"]["migrate"]["permissions"] == permissions
    for name in ("evidence", "Record terminal release status"):
        step = next(
            step
            for step in workflow["jobs"]["release-result"]["steps"]
            if step.get("name", step.get("id")) == name
        )
        assert step["env"]["CANCELLED"] == "${{ job.status == 'cancelled' }}"


@pytest.mark.parametrize(
    "failure,stage",
    [
        ("", ""),
        ("account", "account-identity"),
        ("plan", "plan"),
        ("validator", "validator"),
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
        if failure == "validator":
            assert result.stdout == "production_plan_rejection=drift\n"
            assert "private-malicious-plan-value" not in result.stdout + result.stderr
        if failure in {"account", "plan", "validator", "upload"}:
            assert not (tmp_path / "uploaded").exists()
    else:
        assert result.returncode == 0, result.stderr
        summary = (tmp_path / "summary").read_text()
        assert "PRIVATE_" not in summary
        published = json.loads(summary.split("```json\n", 1)[1].split("\n```", 1)[0])
        evidence = json.loads((tmp_path / "output").read_text().split("=", 1)[1])
        assert set(published) == {
            "candidate",
            "bundle_id",
            "bundle_digest",
            "evidence_artifact",
            "plan_counts",
            "expires_at",
            "state",
            "saved_plan",
        }
        for field in (
            "candidate",
            "bundle_id",
            "bundle_digest",
            "evidence_artifact",
            "plan_counts",
            "expires_at",
            "state",
        ):
            assert published[field] == evidence[field]
        assert published["saved_plan"] == {
            field: evidence["saved_plan"][field]
            for field in ("bucket", "key", "version_id", "checksum")
        }
        assert evidence["listener_attempt"] == 1
        assert evidence["development_attempt"] == 2
        assert evidence["evidence_artifact"] == {
            "id": 13,
            "digest": "sha256:" + "c" * 64,
        }
        assert evidence["saved_plan"]["version_id"] == "private-version"
        assert evidence["saved_plan"]["key"] == (tmp_path / "uploaded").read_text()
        assert evidence["state"]["version_id"] == "state-version"


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


@pytest.mark.parametrize(
    "planner,migrate,cancelled,evidence,outcome",
    [
        ("success", "success", "false", "valid", "success"),
        ("success", "success", "true", "valid", "failed"),
        ("success", "success", "false", "missing", "failed"),
        ("success", "success", "false", "malformed", "failed"),
        ("success", "success", "false", "wrong", "failed"),
        ("success", "success", "false", "wrong-run", "failed"),
        ("success", "success", "false", "wrong-attempt", "failed"),
        ("skipped", "skipped", "false", "valid", "failed"),
    ],
)
def test_finalizer_evidence_derives_explicit_success_or_failure(
    tmp_path: Path,
    planner: str,
    migrate: str,
    cancelled: str,
    evidence: str,
    outcome: str,
) -> None:
    (tmp_path / "v2").symlink_to(ROOT / "v2", target_is_directory=True)
    (tmp_path / "runner").mkdir()
    admission = {
        "release_id": 7,
        "claim_id": 14,
        "candidate": "a" * 40,
        "bundle_id": 10,
        "bundle_digest": "sha256:" + "b" * 64,
    }
    migration_evidence: object = {
        "schema_version": 1,
        "candidate": admission["candidate"],
        "release_id": 7,
        "claim_id": 14,
        "migration": "success",
        "apply": "success",
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
            "prompt_version": "2.0.2",
            "renderer_version": "1.0.0",
            "success": True,
            "commit": admission["candidate"],
            "run_id": "15",
            "attempt": "1",
            "deployment_id": "14",
            "artifact_id": "10",
            "artifact_digest": admission["bundle_digest"],
        },
    }
    if evidence == "missing":
        migration_evidence = ""
    elif evidence == "wrong":
        migration_evidence = {**migration_evidence, "claim_id": 99}
    elif evidence == "wrong-run":
        canary = dict(cast(dict[str, object], migration_evidence["canary"]))
        canary["run_id"] = "16"
        migration_evidence = {
            **migration_evidence,
            "canary": canary,
        }
    elif evidence == "wrong-attempt":
        canary = dict(cast(dict[str, object], migration_evidence["canary"]))
        canary["attempt"] = "2"
        migration_evidence = {
            **migration_evidence,
            "canary": canary,
        }
    raw_evidence = (
        "{"
        if evidence == "malformed"
        else json.dumps(migration_evidence)
        if migration_evidence
        else ""
    )
    result = subprocess.run(
        ["bash", "-c", _result_step("evidence")],
        cwd=tmp_path,
        env={
            "PATH": os.defpath,
            "RUNNER_TEMP": str(tmp_path / "runner"),
            "GITHUB_STEP_SUMMARY": str(tmp_path / "summary"),
            "GITHUB_OUTPUT": str(tmp_path / "output"),
            "ADMISSION": json.dumps(admission),
            "PLANNER": planner,
            "MIGRATE": migrate,
            "MIGRATION_EVIDENCE": raw_evidence,
            "CANCELLED": cancelled,
            "GITHUB_RUN_ID": "15",
            "GITHUB_RUN_ATTEMPT": "1",
        },
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "outcome=" + outcome in (tmp_path / "output").read_text()
    artifact = json.loads(
        (tmp_path / "runner/production-release-evidence.json").read_text()
    )
    assert artifact["outcome"] == outcome
    assert (artifact["canary"] is not None) == (evidence == "valid")


def test_actual_delivery_emitter_reaches_the_parent_finalizer(tmp_path: Path) -> None:
    (tmp_path / "trusted").symlink_to(ROOT, target_is_directory=True)
    (tmp_path / "v2").symlink_to(ROOT / "v2", target_is_directory=True)
    runner = tmp_path / "runner"
    runner.mkdir()
    admission = {
        "release_id": 7,
        "claim_id": 14,
        "candidate": "a" * 40,
        "bundle_id": 10,
        "bundle_digest": "sha256:" + "b" * 64,
    }
    (runner / "v2-production-migrations-evidence.json").write_text(
        json.dumps(
            {
                "candidate": admission["candidate"],
                "release_id": 7,
                "claim_id": 14,
                "status": "ok",
            }
        )
    )
    (runner / "production-canary-evidence.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "runtime_version": "8",
                "proxy_version": "12",
                "call_count": 1,
                "total_usd": "4.25",
                "elapsed_ms": 10,
                "model": "gpt-5.6-luna",
                "tool_contract": "1.5.0",
                "prompt_version": "2.0.2",
                "renderer_version": "1.0.0",
                "success": True,
                "commit": admission["candidate"],
                "run_id": "15",
                "attempt": "1",
                "deployment_id": "14",
                "artifact_id": "10",
                "artifact_digest": admission["bundle_digest"],
            }
        )
    )
    child_output = tmp_path / "child-output"
    child_env: dict[str, str] = {
        "PATH": os.defpath,
        "RUNNER_TEMP": str(runner),
        "GITHUB_STEP_SUMMARY": str(tmp_path / "summary"),
        "GITHUB_OUTPUT": str(child_output),
        "GITHUB_RUN_ID": "15",
        "GITHUB_RUN_ATTEMPT": "1",
        "CANDIDATE": str(admission["candidate"]),
        "ADMISSION": json.dumps(admission),
    }
    child = subprocess.run(
        ["bash", "-c", _migration_step("delivery-evidence")],
        cwd=tmp_path,
        env=child_env,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert child.returncode == 0, child.stderr
    parent = subprocess.run(
        ["bash", "-c", _result_step("evidence")],
        cwd=tmp_path,
        env={
            "PATH": os.defpath,
            "RUNNER_TEMP": str(runner),
            "GITHUB_STEP_SUMMARY": str(tmp_path / "summary"),
            "GITHUB_OUTPUT": str(tmp_path / "parent-output"),
            "ADMISSION": json.dumps(admission),
            "PLANNER": "success",
            "MIGRATE": "success",
            "MIGRATION_EVIDENCE": child_output.read_text().split("=", 1)[1],
            "CANCELLED": "false",
            "GITHUB_RUN_ID": "15",
            "GITHUB_RUN_ATTEMPT": "1",
        },
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert parent.returncode == 0, parent.stderr
    artifact = json.loads((runner / "production-release-evidence.json").read_text())
    assert artifact["outcome"] == "success"
    assert artifact["canary"]["run_id"] == "15"


def test_finalizer_upload_is_always_required_and_terminal_status_is_always_run() -> (
    None
):
    workflow: dict[str, Any] = yaml.safe_load(WORKFLOW.read_text())
    steps = workflow["jobs"]["release-result"]["steps"]
    upload = next(step for step in steps if step.get("id") == "upload")
    terminal = next(
        step for step in steps if step.get("name") == "Record terminal release status"
    )
    assert upload["if"] == "${{ always() }}"
    assert upload["with"]["if-no-files-found"] == "error"
    assert terminal["if"] == "${{ always() }}"


@pytest.mark.parametrize(
    "outcome,cancelled,api_failure,expected",
    [
        ("success", "false", False, 0),
        ("failed", "false", False, 1),
        ("success", "true", False, 1),
        ("success", "false", True, 1),
    ],
)
def test_finalizer_status_is_private_and_fails_closed(
    tmp_path: Path, outcome: str, cancelled: str, api_failure: bool, expected: int
) -> None:
    (tmp_path / "v2").symlink_to(ROOT / "v2", target_is_directory=True)
    (tmp_path / "runner").mkdir()
    binary = tmp_path / "bin"
    binary.mkdir()
    python = binary / "python3"
    python.write_text(
        f"#!{sys.executable}\nimport json,os,sys\nif any('check_production_release.py' in a for a in sys.argv[1:]):\n output=sys.argv[sys.argv.index('--output')+1]; open(output, 'w').write(json.dumps({{'claim_id':14}})); raise SystemExit(0)\nos.execv({sys.executable!r}, [{sys.executable!r}, *sys.argv[1:]])\n"
    )
    python.chmod(0o700)
    gh = binary / "gh"
    gh.write_text(
        '#!/usr/bin/env bash\nprintf \'%s\' "$*" >"$STATUS_MARKER"\nif [[ $API_FAILURE == 1 ]]; then exit 17; fi\n'
    )
    gh.chmod(0o700)
    admission = {"claim_id": 14}
    result = subprocess.run(
        ["bash", "-c", _result_step("Record terminal release status")],
        cwd=tmp_path,
        env={
            "PATH": str(binary) + os.pathsep + os.defpath,
            "RUNNER_TEMP": str(tmp_path / "runner"),
            "GITHUB_STEP_SUMMARY": str(tmp_path / "summary"),
            "ADMISSION": json.dumps(admission),
            "OUTCOME": outcome,
            "UPLOAD": "success",
            "CANCELLED": cancelled,
            "GITHUB_REPOSITORY": "rhprasad0/nova-toll-budget-agent",
            "GITHUB_RUN_ID": "15",
            "GITHUB_RUN_ATTEMPT": "1",
            "STATUS_MARKER": str(tmp_path / "status"),
            "API_FAILURE": "1" if api_failure else "",
        },
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if expected:
        assert result.returncode != 0, result.stderr
    else:
        assert result.returncode == 0, result.stderr
    assert "PRIVATE" not in result.stdout + result.stderr
    assert (tmp_path / "status").exists()
