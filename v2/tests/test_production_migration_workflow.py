"""Run the production wrapper with no network or deployed credentials."""

import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/v2-production-migrations.yml"
CA_SHA = "e5bb2084ccf45087bda1c9bffdea0eb15ee67f0b91646106e466714f9de3c7e3"
FAKE = r"""
import json, os, pathlib, subprocess, sys
from datetime import UTC, datetime, timedelta
name = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
mode = os.environ["FAILURE"]
trace = pathlib.Path(os.environ["TRACE"])
with trace.open("a") as out:
    out.write(name + " " + " ".join(args[:2]) + "\n")
def fail():
    print("PRIVATE_SENTINEL", file=sys.stderr)
    sys.exit(17)
if name == "aws":
    print("PRIVATE_SENTINEL", file=sys.stderr)
    if args[:2] == ["sts", "get-caller-identity"]:
        account = "000000000000" if mode == "account" else "920534282028"
        role = "wrong" if mode == "role" else "nova-toll-v2-production-migrations"
        arn_account = "000000000000" if mode == "arn-account" else account
        print(json.dumps({"Account": account, "Arn": f"arn:aws:sts::{arn_account}:assumed-role/{role}/test-session"}))
    elif args[:2] == ["rds", "describe-db-instances"]:
        now = datetime.now(UTC)
        recovery = now - timedelta(minutes=5)
        if mode == "stale": recovery = now - timedelta(minutes=31)
        if mode == "future": recovery = now + timedelta(minutes=5)
        value = recovery.isoformat()
        if mode == "naive": value = recovery.replace(tzinfo=None).isoformat()
        if mode == "invalid-time": value = "not-a-time"
        db = {"DBInstanceIdentifier":"nova-toll-db", "DBName":"nova_toll",
              "DbiResourceId":"db-WHGCQ3B5SB4WPB5RTJMU3CE664", "DBInstanceStatus":"available",
              "PubliclyAccessible":False,"StorageEncrypted":True,"Engine":"postgres",
              "IAMDatabaseAuthenticationEnabled":True,"BackupRetentionPeriod":7,
              "Endpoint":{"Port":5432,"Address":"nova-toll-db.fixture.us-east-1.rds.amazonaws.com"},
              "LatestRestorableTime":value}
        if mode == "public": db["PubliclyAccessible"] = True
        if mode == "retention": db["BackupRetentionPeriod"] = 0
        if mode == "resource": db["DbiResourceId"] = "wrong"
        if mode == "region": db["Endpoint"]["Address"] = "nova-toll-db.fixture.eu-west-1.rds.amazonaws.com"
        if mode == "missing-time": del db["LatestRestorableTime"]
        print(json.dumps({"DBInstances":[db]}))
    elif args[:2] == ["rds", "generate-db-auth-token"]:
        if mode == "token": fail()
        print("PRIVATE_TOKEN")
    else: raise AssertionError(args)
elif name == "sha256sum":
    print(("0" * 64 if mode == "ca" else os.environ["CA_SHA"]) + "  " + args[0])
elif name == "getent":
    print(("8.8.8.8" if mode == "address" else "172.31.83.200") + " STREAM fixture")
elif name == "tailscale":
    print(json.dumps({"BackendState":"Stopped" if mode == "tailscale" else "Running"}))
elif name == "ip":
    print(json.dumps([{"dst":"172.31.83.200", "dev":"eth0" if mode == "route" else "tailscale0"}]))
elif name == "cp":
    if mode == "evidence-copy": fail()
    sys.exit(subprocess.run([os.environ["REAL_CP"], *args]).returncode)
elif name == "python3":
    if args == ["v2/scripts/run_production_migrations.py"]:
        assert os.environ["PGPASSWORD"] == "PRIVATE_TOKEN"
        assert os.environ["PGHOSTADDR"] == "172.31.83.200"
        assert os.environ["PGDATABASE"] == "nova_toll"
        assert os.environ["PGUSER"] == "schema_migrator_production"
        assert os.environ["PGSSLMODE"] == "verify-full"
        if mode == "runner": fail()
        versions = {"pricing":"1.3.0", "oracle":"1.14.0"}
        data = {"commit":os.environ["PRODUCTION_MIGRATION_CANDIDATE"], "database":"nova_toll",
                "user":"schema_migrator_production","status":"ok","before":versions,
                "after":versions,"applied":[],"run_id":"12345678-1234-4234-8234-123456789abc"}
        if mode == "apply":
            data["before"] = {"pricing":"1.2.0", "oracle":"1.13.0"}
            data["applied"] = ["v2/db/migrations/031_upgrade_pricing_1_2_0_to_1_3_0.sql"]
        if mode == "runner-commit": data["commit"] = "c" * 40
        if mode == "runner-after": data["after"] = {"pricing":"1.2.0", "oracle":"1.13.0"}
        if mode == "runner-shape": del data["after"]
        print(json.dumps(data))
    elif args and args[0] == "-":
        source = sys.stdin.read()
        if "socket.create_connection" in source:
            if mode == "socket": fail()
        else:
            sys.exit(subprocess.run([os.environ["REAL_PYTHON"], *args],input=source,text=True).returncode)
    else:
        sys.exit(subprocess.run([os.environ["REAL_PYTHON"], *args]).returncode)
else: raise AssertionError(name)
"""


def _workflow_step(name: str) -> str:
    workflow: dict[str, Any] = yaml.safe_load(WORKFLOW.read_text())
    return next(
        step["run"]
        for step in workflow["jobs"]["migrate"]["steps"]
        if step.get("name", step.get("id")) == name
    )


def _admission() -> dict[str, object]:
    return {
        "release_id": 7,
        "tag": "v1.2.3",
        "candidate": "b" * 40,
        "listener_run": 11,
        "listener_attempt": 1,
        "development_run": 12,
        "development_attempt": 2,
        "development_deployment": 9,
        "evidence_artifact": {"id": 13, "digest": "sha256:" + "c" * 64},
        "bundle_id": 10,
        "bundle_digest": "sha256:" + "d" * 64,
        "schema_versions": {"pricing": "1.3.0", "oracle": "1.14.0"},
        "consumer_run": 14,
        "consumer_attempt": 1,
        "claim_id": 15,
    }


@pytest.mark.parametrize("invalid", [False, True])
def test_actual_workflow_admission_binds_object_and_sanitizes_failure(
    tmp_path: Path, invalid: bool
) -> None:
    (tmp_path / "trusted").symlink_to(ROOT, target_is_directory=True)
    runner = tmp_path / "runner"
    runner.mkdir()
    admission = _admission()
    if invalid:
        admission["candidate"] = "not-a-sha"
    env = {
        "PATH": os.defpath,
        "ADMISSION": json.dumps(admission),
        "RUNNER_TEMP": str(runner),
        "GITHUB_STEP_SUMMARY": str(tmp_path / "summary"),
        "GITHUB_OUTPUT": str(tmp_path / "output"),
        "GITHUB_RUN_ID": "14",
        "GITHUB_RUN_ATTEMPT": "1",
    }
    result = subprocess.run(
        ["bash", "-c", _workflow_step("admission")],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if invalid:
        assert result.returncode != 0
        assert result.stderr.count("status=fail") == 1
        assert "stage=release-verification status=fail" in result.stderr
    else:
        assert result.returncode == 0, result.stderr
        assert json.loads((runner / "admission.json").read_text()) == admission
        assert "candidate=" + "b" * 40 in (tmp_path / "output").read_text()


def test_actual_delivery_evidence_emits_the_validated_canary_once(
    tmp_path: Path,
) -> None:
    (tmp_path / "trusted").symlink_to(ROOT, target_is_directory=True)
    runner = tmp_path / "runner"
    runner.mkdir()
    admission = _admission()
    (runner / "v2-production-migrations-evidence.json").write_text(
        json.dumps(
            {
                "candidate": "b" * 40,
                "release_id": 7,
                "claim_id": 15,
                "status": "ok",
            }
        )
    )
    canary = {
        "schema_version": 1,
        "runtime_version": "8",
        "proxy_version": "8",
        "call_count": 1,
        "total_usd": "4.25",
        "elapsed_ms": 1,
        "model": "gpt-5.6-luna",
        "tool_contract": "1.5.0",
        "prompt_version": "2.0.2",
        "renderer_version": "1.0.0",
        "success": True,
        "commit": "b" * 40,
        "run_id": "14",
        "attempt": "1",
        "deployment_id": "15",
        "artifact_id": "10",
        "artifact_digest": "sha256:" + "d" * 64,
    }
    (runner / "production-canary-evidence.json").write_text(json.dumps(canary))
    output = tmp_path / "output"
    result = subprocess.run(
        ["bash", "-c", _workflow_step("delivery-evidence")],
        cwd=tmp_path,
        env={
            "PATH": os.defpath,
            "RUNNER_TEMP": str(runner),
            "GITHUB_STEP_SUMMARY": str(tmp_path / "summary"),
            "GITHUB_OUTPUT": str(output),
            "GITHUB_RUN_ID": "14",
            "GITHUB_RUN_ATTEMPT": "1",
            "CANDIDATE": "b" * 40,
            "ADMISSION": json.dumps(admission),
        },
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    delivery = json.loads(output.read_text().split("=", 1)[1])
    assert delivery["canary"] == canary
    assert not (runner / "production-canary-evidence.json").exists()


@pytest.mark.parametrize(
    "step,failure,stage",
    [
        (
            "Revalidate release claim and exact candidate before credentials",
            "revalidate",
            "release-verification",
        ),
        (
            "Verify exact candidate migration sources before credentials",
            "bundle",
            "artifact-download",
        ),
    ],
)
def test_actual_workflow_precredential_blocks_sanitize_failure(
    tmp_path: Path, step: str, failure: str, stage: str
) -> None:
    (tmp_path / "trusted").symlink_to(ROOT, target_is_directory=True)
    (tmp_path / "candidate").symlink_to(ROOT, target_is_directory=True)
    runner = tmp_path / "runner"
    runner.mkdir()
    (runner / "admission.json").write_text(json.dumps(_admission()))
    binary = tmp_path / "bin"
    binary.mkdir()
    command = binary / ("python3" if failure == "revalidate" else "gh")
    command.write_text("#!/usr/bin/env bash\necho PRIVATE_SENTINEL >&2\nexit 17\n")
    command.chmod(0o700)
    env = {
        "PATH": str(binary) + os.pathsep + os.defpath,
        "RUNNER_TEMP": str(runner),
        "GITHUB_STEP_SUMMARY": str(tmp_path / "summary"),
        "GITHUB_REPOSITORY": "rhprasad0/nova-toll-budget-agent",
        "GITHUB_WORKSPACE": str(tmp_path),
        "BUNDLE_ID": "10",
        "BUNDLE_DIGEST": "sha256:" + "d" * 64,
        "CANDIDATE": "b" * 40,
        "PRICING": "1.3.0",
        "ORACLE": "1.14.0",
    }
    result = subprocess.run(
        ["bash", "-c", _workflow_step(step)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode != 0
    assert "PRIVATE_SENTINEL" not in result.stdout + result.stderr
    assert result.stderr.count("status=fail") == 1
    assert f"stage={stage} status=fail" in result.stderr


def test_actual_workflow_ca_block_uses_trusted_helper_from_candidate_directory(
    tmp_path: Path,
) -> None:
    (tmp_path / "trusted").symlink_to(ROOT, target_is_directory=True)
    (tmp_path / "candidate").symlink_to(ROOT, target_is_directory=True)
    runner = tmp_path / "runner"
    runner.mkdir()
    binary = tmp_path / "bin"
    binary.mkdir()
    curl = binary / "curl"
    curl.write_text("#!/usr/bin/env bash\necho PRIVATE_SENTINEL >&2\nexit 17\n")
    curl.chmod(0o700)
    result = subprocess.run(
        ["bash", "-c", _workflow_step("Fetch pinned RDS CA bundle")],
        cwd=tmp_path / "candidate" / "v2",
        env={
            "PATH": str(binary) + os.pathsep + os.defpath,
            "RUNNER_TEMP": str(runner),
            "GITHUB_STEP_SUMMARY": str(tmp_path / "summary"),
            "GITHUB_WORKSPACE": str(tmp_path),
        },
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode != 0
    assert "PRIVATE_SENTINEL" not in result.stdout + result.stderr
    assert result.stderr.count("status=fail") == 1
    assert "stage=rds-ca status=fail" in result.stderr


def _clean_git_environment(
    environment: dict[str, str] | None = None,
) -> dict[str, str]:
    clean = dict(os.environ if environment is None else environment)
    for key in tuple(clean):
        if key.startswith("GIT_"):
            del clean[key]
    return clean


def _scripts_checkout(checkout: Path, dependencies: tuple[str, ...]) -> None:
    for relative in dependencies:
        destination = checkout / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((ROOT / relative).read_bytes())
    git_environment = _clean_git_environment()
    subprocess.run(
        ["git", "init", "--quiet", str(checkout)], check=True, env=git_environment
    )
    subprocess.run(
        ["git", "-C", str(checkout), "config", "user.name", "fixture"],
        check=True,
        env=git_environment,
    )
    subprocess.run(
        ["git", "-C", str(checkout), "config", "user.email", "fixture@example.com"],
        check=True,
        env=git_environment,
    )
    subprocess.run(
        ["git", "-C", str(checkout), "add", "v2/scripts"],
        check=True,
        env=git_environment,
    )
    subprocess.run(
        ["git", "-C", str(checkout), "commit", "--quiet", "-m", "fixture"],
        check=True,
        env=git_environment,
    )


def _commit_scripts_checkout(checkout: Path) -> None:
    git_environment = _clean_git_environment()
    subprocess.run(
        ["git", "-C", str(checkout), "add", "v2/scripts"],
        check=True,
        env=git_environment,
    )
    subprocess.run(
        ["git", "-C", str(checkout), "commit", "--quiet", "-m", "altered"],
        check=True,
        env=git_environment,
    )


def test_scripts_checkout_ignores_hook_git_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clean_environment = _clean_git_environment()
    decoy = tmp_path / "decoy"
    subprocess.run(
        ["git", "init", "--quiet", str(decoy)], check=True, env=clean_environment
    )
    (decoy / "marker").write_text("decoy\n")
    for command in (
        ["git", "-C", str(decoy), "config", "user.name", "decoy"],
        ["git", "-C", str(decoy), "config", "user.email", "decoy@example.com"],
        ["git", "-C", str(decoy), "config", "fixture.decoy", "unchanged"],
        ["git", "-C", str(decoy), "add", "marker"],
        ["git", "-C", str(decoy), "commit", "--quiet", "-m", "decoy"],
    ):
        subprocess.run(command, check=True, env=clean_environment)
    before_head = subprocess.run(
        ["git", "-C", str(decoy), "rev-parse", "HEAD"],
        check=True,
        env=clean_environment,
        capture_output=True,
        text=True,
    ).stdout
    before_config = subprocess.run(
        ["git", "-C", str(decoy), "config", "--get", "fixture.decoy"],
        check=True,
        env=clean_environment,
        capture_output=True,
        text=True,
    ).stdout
    before_index = (decoy / ".git/index").read_bytes()
    monkeypatch.setenv("GIT_DIR", str(decoy / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(decoy))
    monkeypatch.setenv("GIT_INDEX_FILE", str(decoy / ".git/index"))
    dependencies = (
        "v2/scripts/adopt_production_baseline.py",
        "v2/scripts/bootstrap_development_database.py",
        "v2/scripts/check_schema_versions.py",
        "v2/scripts/classify_deployment_error.py",
        "v2/scripts/run_development_migrations.py",
        "v2/scripts/run_private_stage.sh",
        "v2/scripts/run_production_migrations.py",
        "v2/scripts/run_production_migrations_workflow.sh",
    )
    trusted = tmp_path / "trusted"
    candidate = tmp_path / "candidate"
    _scripts_checkout(trusted, dependencies)
    _scripts_checkout(candidate, dependencies)
    changed = candidate / "v2/scripts/run_production_migrations.py"
    changed.write_bytes(changed.read_bytes() + b"# fixture mutation\n")
    _commit_scripts_checkout(candidate)
    fixture_head = subprocess.run(
        ["git", "-C", str(candidate), "rev-parse", "HEAD"],
        check=True,
        env=_clean_git_environment(),
        capture_output=True,
        text=True,
    ).stdout
    assert fixture_head
    assert fixture_head != before_head
    assert (
        subprocess.run(
            ["git", "-C", str(trusted), "status", "--porcelain"],
            check=True,
            env=_clean_git_environment(),
            capture_output=True,
            text=True,
        ).stdout
        == ""
    )
    assert (
        subprocess.run(
            ["git", "-C", str(candidate), "status", "--porcelain"],
            check=True,
            env=_clean_git_environment(),
            capture_output=True,
            text=True,
        ).stdout
        == ""
    )
    assert (
        subprocess.run(
            ["git", "-C", str(decoy), "rev-parse", "HEAD"],
            check=True,
            env=_clean_git_environment(),
            capture_output=True,
            text=True,
        ).stdout
        == before_head
    )
    assert (
        subprocess.run(
            ["git", "-C", str(decoy), "config", "--get", "fixture.decoy"],
            check=True,
            env=_clean_git_environment(),
            capture_output=True,
            text=True,
        ).stdout
        == before_config
    )
    assert (decoy / ".git/index").read_bytes() == before_index


@pytest.mark.parametrize(
    ("candidate_change", "expected_success"),
    [
        ("v2/scripts/adopt_production_baseline.py", False),
        ("v2/scripts/bootstrap_development_database.py", False),
        ("v2/scripts/check_schema_versions.py", False),
        ("v2/scripts/classify_deployment_error.py", False),
        ("v2/scripts/run_development_migrations.py", False),
        ("v2/scripts/run_private_stage.sh", False),
        ("v2/scripts/run_production_migrations.py", False),
        ("v2/scripts/run_production_migrations_workflow.sh", False),
        ("untracked-hashlib", False),
        ("committed-hashlib", False),
        ("mode-change", False),
        ("status-failure", False),
        ("clean", True),
    ],
)
def test_actual_workflow_checks_complete_candidate_scripts_tree(
    tmp_path: Path, candidate_change: str, expected_success: bool
) -> None:
    dependencies = (
        "v2/scripts/adopt_production_baseline.py",
        "v2/scripts/bootstrap_development_database.py",
        "v2/scripts/check_schema_versions.py",
        "v2/scripts/classify_deployment_error.py",
        "v2/scripts/run_development_migrations.py",
        "v2/scripts/run_private_stage.sh",
        "v2/scripts/run_production_migrations.py",
        "v2/scripts/run_production_migrations_workflow.sh",
    )
    trusted_checkout = tmp_path / "trusted"
    candidate_checkout = tmp_path / "candidate"
    _scripts_checkout(trusted_checkout, dependencies)
    _scripts_checkout(candidate_checkout, dependencies)
    if candidate_change in dependencies:
        changed = candidate_checkout / candidate_change
        changed.write_bytes(changed.read_bytes() + b"# altered\n")
        _commit_scripts_checkout(candidate_checkout)
    elif candidate_change in {"untracked-hashlib", "committed-hashlib"}:
        (candidate_checkout / "v2/scripts/hashlib.py").write_text(
            "raise SystemExit('shadow')\n"
        )
        if candidate_change == "committed-hashlib":
            _commit_scripts_checkout(candidate_checkout)
    elif candidate_change == "mode-change":
        changed = candidate_checkout / "v2/scripts/run_production_migrations.py"
        changed.chmod(0o755)
        _commit_scripts_checkout(candidate_checkout)
    runner = tmp_path / "runner"
    runner.mkdir()
    (runner / "admission.json").write_text(json.dumps(_admission()))
    binary = tmp_path / "bin"
    binary.mkdir()
    commands = {
        "gh": "#!/usr/bin/env bash\nprintf x\n",
        "dd": '#!/usr/bin/env bash\ncat >/dev/null\nfor arg in "$@"; do case $arg in of=*) : > "${arg#of=}";; esac; done\n',
        "stat": "#!/usr/bin/env bash\necho 0\n",
        "sha256sum": '#!/usr/bin/env bash\nif [[ $1 == *production-migration-release.zip ]]; then echo "${BUNDLE_DIGEST#sha256:}  $1"; else exec /usr/bin/sha256sum "$@"; fi\n',
        "python3": "#!/usr/bin/env bash\nexit 0\n",
        "git": """#!/usr/bin/env bash
set -eu
if [[ " $* " == *" rev-parse HEAD"* ]]; then
  printf '%s\\n' "$CANDIDATE"
elif [[ " $* " == *" status "* ]] && [[ "${STATUS_FAILURE:-}" == 1 ]]; then
  exit 17
else
  exec "$REAL_GIT" "$@"
fi
""",
        "aws": '#!/usr/bin/env bash\nprintf aws >>"$TRACE"\nexit 17\n',
        "jq": '#!/usr/bin/env bash\necho "$CANDIDATE"\n',
        "cp": "#!/usr/bin/env bash\nexit 0\n",
    }
    for name, body in commands.items():
        command = binary / name
        command.write_text(body)
        command.chmod(0o700)
    real_git = shutil.which("git")
    assert real_git
    result = subprocess.run(
        [
            "bash",
            "-c",
            _workflow_step(
                "Verify exact candidate migration sources before credentials"
            ),
        ],
        cwd=tmp_path,
        env=_clean_git_environment(
            {
                "PATH": str(binary) + os.pathsep + os.defpath,
                "RUNNER_TEMP": str(runner),
                "GITHUB_STEP_SUMMARY": str(tmp_path / "summary"),
                "GITHUB_REPOSITORY": "rhprasad0/nova-toll-budget-agent",
                "GITHUB_WORKSPACE": str(tmp_path),
                "BUNDLE_ID": "10",
                "BUNDLE_DIGEST": "sha256:" + "d" * 64,
                "CANDIDATE": "b" * 40,
                "PRICING": "1.3.0",
                "ORACLE": "1.14.0",
                "REAL_GIT": real_git,
                "STATUS_FAILURE": "1" if candidate_change == "status-failure" else "",
                "TRACE": str(tmp_path / "trace"),
            }
        ),
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert not (tmp_path / "trace").exists()
    if expected_success:
        assert result.returncode == 0, result.stderr
    else:
        assert result.returncode != 0
        assert result.stderr.count("status=fail") == 1
        assert "stage=artifact-download status=fail" in result.stderr


def test_workflow_expressions_are_executable_and_private_stages_are_fixed() -> None:
    source = WORKFLOW.read_text()
    assert r"\${{" not in source
    assert "jq -e 'select(" in source
    for stage in ("release-verification", "artifact-download", "rds-ca"):
        assert f"run_private_stage {stage}" in source
    assert "git -C trusted ls-tree -r -z HEAD -- v2/scripts" in source
    assert "git -C candidate ls-tree -r -z HEAD -- v2/scripts" in source
    assert "cmp -s" in source
    assert (
        "status --porcelain=v1 --untracked-files=all --ignored=matching -- v2/scripts"
        in source
    )
    assert "candidate-scripts.status" in source
    assert 'NotAction:"s3:GetObjectVersion"' in source
    assert 'NotResource:("arn:aws:s3:::" + .saved_plan.bucket + "/plans/*")' in source
    assert 'StringEquals:{"s3:VersionId":.saved_plan.version_id}' in source
    assert "release-overlay/release-manifest.json" in source


def test_third_party_actions_follow_explicit_deploy_credential_clears() -> None:
    workflow: dict[str, Any] = yaml.safe_load(WORKFLOW.read_text())
    steps = workflow["jobs"]["migrate"]["steps"]
    names = [step.get("name", step.get("uses", "")) for step in steps]
    assert names.index("Clear deploy credentials before Tailscale") < names.index(
        "tailscale/github-action@780049a30b6ff5c378a9e7b389d15ece7a204888"
    )
    assert names.index("Clear deploy credentials before evidence upload") < names.index(
        "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a"
    )
    clear = next(
        step
        for step in steps
        if step.get("name") == "Clear deploy credentials before Tailscale"
    )
    assert "AWS_SESSION_TOKEN" in clear["run"]
    assert "production-plan.tfplan" in clear["run"]


@pytest.mark.parametrize(
    "failure,stage",
    [
        ("", ""),
        ("ca", "rds-ca"),
        ("account", "migration-identity"),
        ("role", "migration-identity"),
        ("arn-account", "migration-identity"),
        ("public", "migration-database"),
        ("resource", "migration-database"),
        ("region", "migration-database"),
        ("retention", "migration-database"),
        ("missing-time", "migration-database"),
        ("stale", "migration-database"),
        ("future", "migration-database"),
        ("naive", "migration-database"),
        ("invalid-time", "migration-database"),
        ("address", "migration-route"),
        ("tailscale", "migration-route"),
        ("route", "migration-route"),
        ("socket", "migration-socket"),
        ("token", "migration-token"),
        ("runner", "migration-runner"),
        ("apply", ""),
        ("runner-commit", "migration-evidence"),
        ("runner-after", "migration-evidence"),
        ("runner-shape", "migration-evidence"),
        ("evidence-copy", "migration-evidence"),
    ],
)
def test_actual_production_wrapper_boundaries(
    tmp_path: Path, failure: str, stage: str
) -> None:
    scripts = tmp_path / "v2/scripts"
    scripts.mkdir(parents=True)
    for name in (
        "run_production_migrations_workflow.sh",
        "run_private_stage.sh",
        "classify_deployment_error.py",
    ):
        shutil.copyfile(ROOT / "v2/scripts" / name, scripts / name)
    ca = tmp_path / "v2/infra/build/ca/rds-ca-bundle.pem"
    ca.parent.mkdir(parents=True)
    ca.write_text("fixture CA; digest command is isolated below")
    binary = tmp_path / "bin"
    binary.mkdir()
    for name in ("aws", "sha256sum", "getent", "tailscale", "ip", "python3", "cp"):
        command = binary / name
        command.write_text(f"#!{sys.executable}\n" + FAKE)
        command.chmod(0o700)
    temporary = tmp_path / "runner"
    temporary.mkdir()
    real_cp = shutil.which("cp")
    assert real_cp
    env = {
        "PATH": str(binary) + os.pathsep + os.defpath,
        "REAL_PYTHON": sys.executable,
        "REAL_CP": real_cp,
        "CA_SHA": CA_SHA,
        "FAILURE": failure,
        "TRACE": str(tmp_path / "trace"),
        "RUNNER_TEMP": str(temporary),
        "GITHUB_STEP_SUMMARY": str(tmp_path / "summary"),
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_REPOSITORY": "rhprasad0/nova-toll-budget-agent",
        "GITHUB_SHA": "a" * 40,
        "PRODUCTION_MIGRATION_CANDIDATE": "b" * 40,
        "PRODUCTION_MIGRATION_ADMISSION": json.dumps(
            {
                "release_id": 7,
                "tag": "v1.2.3",
                "candidate": "b" * 40,
                "listener_run": 11,
                "listener_attempt": 1,
                "development_run": 12,
                "development_attempt": 2,
                "development_deployment": 9,
                "evidence_artifact": {"id": 13, "digest": "sha256:" + "c" * 64},
                "bundle_id": 10,
                "bundle_digest": "sha256:" + "d" * 64,
                "schema_versions": {"pricing": "1.3.0", "oracle": "1.14.0"},
                "consumer_run": 14,
                "consumer_attempt": 1,
                "claim_id": 15,
            }
        ),
    }
    result = subprocess.run(
        ["bash", str(scripts / "run_production_migrations_workflow.sh")],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    logs = result.stdout + result.stderr + (tmp_path / "summary").read_text()
    assert "PRIVATE_SENTINEL" not in logs
    assert "PRIVATE_TOKEN" not in logs
    assert "nova-toll-db.fixture" not in logs
    assert not list(temporary.glob("production-migration*.out"))
    assert not list(temporary.glob("production-migration*.err"))
    trace = (tmp_path / "trace").read_text()
    if failure and failure != "apply":
        assert result.returncode != 0
        failures = [
            line for line in result.stderr.splitlines() if "status=fail" in line
        ]
        assert len(failures) == 1, result.stderr
        assert f"stage={stage} " in failures[0]
        if stage not in {"migration-runner", "migration-evidence"}:
            assert "python3 v2/scripts/run_production_migrations.py" not in trace
        if stage not in {"migration-token", "migration-runner", "migration-evidence"}:
            assert "aws rds generate-db-auth-token" not in trace
    else:
        assert result.returncode == 0, result.stderr
        evidence = json.loads(
            (temporary / "v2-production-migrations-evidence.json").read_text()
        )
        assert evidence["candidate"] == "b" * 40
        assert evidence["consumer_run"] == 14
        assert evidence["applied"] == (
            ["v2/db/migrations/031_upgrade_pricing_1_2_0_to_1_3_0.sql"]
            if failure == "apply"
            else []
        )
        if failure == "apply":
            assert evidence["before"] == {"pricing": "1.2.0", "oracle": "1.13.0"}
            assert evidence["after"] == {"pricing": "1.3.0", "oracle": "1.14.0"}
        assert evidence["status"] == "ok"


def _deploy_environment(tmp_path: Path, failure: str) -> dict[str, str]:
    (tmp_path / "trusted").symlink_to(ROOT, target_is_directory=True)
    (tmp_path / "candidate").symlink_to(ROOT, target_is_directory=True)
    runner, binary = tmp_path / "runner", tmp_path / "bin"
    runner.mkdir()
    binary.mkdir()
    checksum = subprocess.check_output(["sha256sum"], input=b"PLAN").decode().split()[0]
    encoded = __import__("base64").b64encode(bytes.fromhex(checksum)).decode()
    fake = (
        r"""#!"""
        + sys.executable
        + r"""
import json, os, pathlib, sys
args=sys.argv[1:]; name=pathlib.Path(sys.argv[0]).name; failure=os.environ["FAILURE"]
def value(flag): return args[args.index(flag)+1]
if name == "aws":
  pathlib.Path(os.environ["AWS_MARKER"]).write_text("aws")
  if args[:2] == ["sts", "get-caller-identity"]: print(json.dumps({"Account":"920534282028","Arn":"arn:aws:sts::920534282028:assumed-role/nova-toll-production-deploy/test"}))
  elif args[:2] == ["ssm", "get-parameter"]:
    if failure == "token": raise SystemExit(17)
    print("PRIVATE_TOKEN")
  elif args[:2] == ["s3api", "head-object"]:
    key=value("--key")
    if failure == "head": raise SystemExit(17)
    if key.endswith(".tflock"):
      if failure == "lock": raise SystemExit(0)
      if failure == "lock-access":
        print("AccessDenied", file=sys.stderr); raise SystemExit(1)
      print("An error occurred (404) Not Found", file=sys.stderr); raise SystemExit(1)
    if key.endswith("terraform.tfstate"): print(json.dumps({"VersionId":"state-after" if os.environ.get("APPLY") else "state-version"}))
    else: print(json.dumps({"VersionId":"plan-version","ChecksumSHA256":"wrong" if failure == "checksum" else os.environ["CHECKSUM"],"SSEKMSKeyId":os.environ["KMS"],"ServerSideEncryption":"aws:kms"}))
  elif args[:2] == ["s3api", "get-object"]:
    destination=pathlib.Path(args[-1]); destination.write_bytes(b'{"lineage":"11111111-1111-1111-1111-111111111111","serial":1}' if any("terraform.tfstate" in value for value in args) else b"PLAN")
  else: raise SystemExit(17)
elif name == "terraform":
  if "apply" in args:
    if failure == "apply": raise SystemExit(17)
    assert pathlib.Path(args[-1]).read_bytes() == b"PLAN"
    pathlib.Path(os.environ["APPLY_MARKER"]).write_text("apply")
  elif "state" in args: print('{"lineage":"wrong","serial":1}' if failure == "state" else '{"lineage":"11111111-1111-1111-1111-111111111111","serial":2}')
  elif "show" in args: print("{}")
elif name == "python3":
  if any("check_development_release.py" in value for value in args):
    if failure == "readiness": raise SystemExit(17)
  elif any("check_production_release.py" in value for value in args):
    if "validate-saved-plan" in args: os.execv(sys.executable, [sys.executable, *args])
    pathlib.Path(value("--output")).write_text("{}")
  else: os.execv(sys.executable, [sys.executable, *args])
"""
    )
    for command in ("aws", "terraform", "python3"):
        path = binary / command
        path.write_text(fake)
        path.chmod(0o700)
    return {
        "PATH": str(binary) + os.pathsep + os.defpath,
        "REAL_JQ": shutil.which("jq") or "jq",
        "FAILURE": failure,
        "CHECKSUM": encoded,
        "KMS": "arn:aws:kms:us-east-1:920534282028:key/8fc1450b-0b5c-4afe-8c0a-cb150aab5da7",
        "PLAN_BUCKET": "nova-toll-tfstate-920534282028",
        "PLAN_KEY": "plans/release-7-v1.2.3/14/release.tfplan",
        "PLAN_VERSION": "plan-version",
        "PLAN_CHECKSUM": encoded,
        "PLAN_KMS": "arn:aws:kms:us-east-1:920534282028:key/8fc1450b-0b5c-4afe-8c0a-cb150aab5da7",
        "STATE": '{"lineage":"11111111-1111-1111-1111-111111111111","serial":1,"version_id":"state-version"}',
        "RUNNER_TEMP": str(runner),
        "GITHUB_WORKSPACE": str(tmp_path),
        "GITHUB_STEP_SUMMARY": str(tmp_path / "summary"),
        "GITHUB_OUTPUT": str(tmp_path / "output"),
        "GITHUB_RUN_ID": "14",
        "GITHUB_RUN_ATTEMPT": "1",
        "CANDIDATE": "b" * 40,
        "APPLY_MARKER": str(tmp_path / "applied"),
        "AWS_MARKER": str(tmp_path / "aws-called"),
    }


def _saved_contract() -> tuple[dict[str, Any], dict[str, Any]]:
    now = datetime.now(UTC).replace(microsecond=0)
    admission: dict[str, Any] = {
        "release_id": 7,
        "tag": "v1.2.3",
        "candidate": "b" * 40,
        "listener_run": 11,
        "listener_attempt": 1,
        "development_run": 12,
        "development_attempt": 2,
        "development_deployment": 9,
        "evidence_artifact": {"id": 13, "digest": "sha256:" + "c" * 64},
        "bundle_id": 10,
        "bundle_digest": "sha256:" + "d" * 64,
        "schema_versions": {"pricing": "1.3.0", "oracle": "1.14.0"},
        "consumer_run": 14,
        "consumer_attempt": 1,
        "claim_id": 15,
    }
    saved: dict[str, Any] = {
        **admission,
        "schema_version": 1,
        "evidence_digest": admission["evidence_artifact"]["digest"],
        "planner_run": 14,
        "planner_attempt": 1,
        "plan_counts": {},
        "saved_plan": {
            "bucket": "nova-toll-tfstate-920534282028",
            "key": "plans/release-7-v1.2.3/14/release.tfplan",
            "version_id": "plan-version",
            "checksum": "A" * 43 + "=",
            "kms_key_arn": "arn:aws:kms:us-east-1:920534282028:key/8fc1450b-0b5c-4afe-8c0a-cb150aab5da7",
        },
        "state": {
            "lineage": "11111111-1111-1111-1111-111111111111",
            "serial": 1,
            "version_id": "state-version",
        },
        "created_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "expires_at": (now + timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    return admission, saved


def _session_allows(
    policy: dict[str, Any], action: str, resource: str, version: str
) -> bool:
    for statement in policy["Statement"]:
        applies = (
            action in statement.get("Action", [])
            if isinstance(statement.get("Action"), list)
            else action == statement.get("Action")
            if "Action" in statement
            else action != statement.get("NotAction")
        )
        if not applies:
            continue
        if "Resource" in statement:
            allowed_resource = fnmatchcase(resource, statement["Resource"])
        else:
            allowed_resource = not fnmatchcase(resource, statement["NotResource"])
        if not allowed_resource:
            continue
        expected = (
            statement.get("Condition", {}).get("StringEquals", {}).get("s3:VersionId")
        )
        if expected is None or version == expected:
            return True
    return False


def test_actual_saved_plan_emits_and_enforces_exact_session_policy(
    tmp_path: Path,
) -> None:
    env = _deploy_environment(tmp_path, "")
    admission, saved = _saved_contract()
    (tmp_path / "runner" / "admission.json").write_text(json.dumps(admission))
    env["SAVED_PLAN"] = json.dumps(saved)
    result = subprocess.run(
        ["bash", "-c", _workflow_step("saved-plan")],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    output = dict(
        line.split("=", 1)
        for line in (tmp_path / "output").read_text().splitlines()
        if "=" in line
    )
    policy = json.loads(output["session_policy"])
    bucket = "arn:aws:s3:::nova-toll-tfstate-920534282028"
    requests: list[tuple[str, str, str, bool]] = []

    def get_object_version(key: str, version: str) -> bool:
        allowed = _session_allows(
            policy, "s3:GetObjectVersion", f"{bucket}/{key}", version
        )
        requests.append(("s3:GetObjectVersion", key, version, allowed))
        return allowed

    assert get_object_version(
        "plans/release-7-v1.2.3/14/release.tfplan", "plan-version"
    )
    assert not get_object_version(
        "plans/release-8-v1.2.3/14/release.tfplan", "plan-version"
    )
    assert not get_object_version(
        "plans/release-7-v1.2.3/14/release.tfplan", "wrong-version"
    )
    assert [request[-1] for request in requests] == [True, False, False]


@pytest.mark.parametrize(
    "step", ["saved-plan", "Revalidate exact saved plan and state before apply"]
)
@pytest.mark.parametrize(
    "mutation",
    [
        "malformed",
        "candidate",
        "claim",
        "planner-run",
        "expired",
        "future",
        "key",
        "version",
        "checksum",
        "kms",
        "state",
    ],
)
def test_actual_saved_plan_validation_stops_before_aws(
    tmp_path: Path, step: str, mutation: str
) -> None:
    env = _deploy_environment(tmp_path, "")
    admission, saved = _saved_contract()
    if mutation == "malformed":
        saved_input = "{}"
    else:
        changed = json.loads(json.dumps(saved))
        if mutation == "candidate":
            changed["candidate"] = "a" * 40
        elif mutation == "claim":
            changed["claim_id"] = 99
        elif mutation == "planner-run":
            changed["planner_run"] = 99
        elif mutation == "expired":
            changed["expires_at"] = changed["created_at"]
        elif mutation == "future":
            future = datetime.now(UTC) + timedelta(hours=1)
            changed["created_at"] = future.strftime("%Y-%m-%dT%H:%M:%SZ")
            changed["expires_at"] = (future + timedelta(hours=24)).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
        elif mutation == "key":
            changed["saved_plan"]["key"] = "plans/release-8-v1.2.3/14/release.tfplan"
        elif mutation == "version":
            changed["saved_plan"]["version_id"] = ""
        elif mutation == "checksum":
            changed["saved_plan"]["checksum"] = "not-a-checksum"
        elif mutation == "kms":
            changed["saved_plan"]["kms_key_arn"] = (
                "arn:aws:kms:us-east-1:920534282028:key/other"
            )
        elif mutation == "state":
            changed["state"]["serial"] = "not-a-serial"
        saved_input = json.dumps(changed)
    (tmp_path / "runner" / "admission.json").write_text(json.dumps(admission))
    env.update(
        {
            "ADMISSION": json.dumps(admission),
            "SAVED_PLAN": saved_input,
            "GH_TOKEN": "fixture",
        }
    )
    result = subprocess.run(
        ["bash", "-c", _workflow_step(step)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode != 0
    assert result.stderr.count("status=fail") == 1
    assert not (tmp_path / "aws-called").exists()


@pytest.mark.parametrize("failure", ["", "checksum", "head", "token"])
def test_actual_deploy_preflight_stops_before_migration_or_apply(
    tmp_path: Path, failure: str
) -> None:
    result = subprocess.run(
        [
            "bash",
            "-c",
            _workflow_step("Verify exact saved plan and state before migration"),
        ],
        cwd=tmp_path,
        env=_deploy_environment(tmp_path, failure),
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert "PRIVATE_TOKEN" not in result.stdout + result.stderr
    assert not (tmp_path / "applied").exists()
    if failure:
        assert result.returncode != 0
        assert result.stderr.count("status=fail") == 1
    else:
        assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("failure", ["", "checksum", "head"])
def test_actual_reassumed_deploy_rechecks_before_apply(
    tmp_path: Path, failure: str
) -> None:
    env = _deploy_environment(tmp_path, failure)
    admission, saved = _saved_contract()
    env.update(
        {
            "ADMISSION": json.dumps(admission),
            "SAVED_PLAN": json.dumps(saved),
            "GH_TOKEN": "fixture",
        }
    )
    result = subprocess.run(
        [
            "bash",
            "-c",
            _workflow_step("Revalidate exact saved plan and state before apply"),
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert "PRIVATE_TOKEN" not in result.stdout + result.stderr
    assert not (tmp_path / "applied").exists()
    if failure:
        assert result.returncode != 0
        assert result.stderr.count("status=fail") == 1
        assert not (tmp_path / "runner" / "production-plan.tfplan").exists()
    else:
        assert result.returncode == 0, result.stderr
        assert (tmp_path / "runner" / "production-plan.tfplan").read_bytes() == b"PLAN"


def test_actual_recheck_then_apply_consumes_the_retained_exact_plan(
    tmp_path: Path,
) -> None:
    env = _deploy_environment(tmp_path, "")
    admission, saved = _saved_contract()
    env.update(
        {
            "ADMISSION": json.dumps(admission),
            "SAVED_PLAN": json.dumps(saved),
            "GH_TOKEN": "fixture",
            "APPLY": "1",
        }
    )
    env.pop("APPLY")
    recheck = subprocess.run(
        [
            "bash",
            "-c",
            _workflow_step("Revalidate exact saved plan and state before apply"),
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert recheck.returncode == 0, recheck.stderr
    plan = tmp_path / "runner" / "production-plan.tfplan"
    assert plan.read_bytes() == b"PLAN"
    env["APPLY"] = "1"
    apply = subprocess.run(
        [
            "bash",
            "-c",
            _workflow_step(
                "Apply the one verified production plan and check readiness"
            ),
        ],
        cwd=tmp_path / "candidate",
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert apply.returncode == 0, apply.stderr
    assert (tmp_path / "applied").exists()
    assert not plan.exists()


@pytest.mark.parametrize(
    "failure", ["", "apply", "readiness", "lock", "lock-access", "state", "token"]
)
def test_actual_saved_apply_and_readiness_boundaries(
    tmp_path: Path, failure: str
) -> None:
    env = _deploy_environment(tmp_path, failure)
    env["APPLY"] = "1"
    env["STATE"] = (
        '{"lineage":"11111111-1111-1111-1111-111111111111","serial":2,"version_id":"state-version"}'
    )
    (tmp_path / "runner" / "production-plan.tfplan").write_bytes(b"PLAN")
    result = subprocess.run(
        [
            "bash",
            "-c",
            _workflow_step(
                "Apply the one verified production plan and check readiness"
            ),
        ],
        cwd=tmp_path / "candidate",
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert "PRIVATE_TOKEN" not in result.stdout + result.stderr
    if failure:
        assert result.returncode != 0
        assert result.stderr.count("status=fail") == 1
    else:
        assert result.returncode == 0, result.stderr
        assert (tmp_path / "applied").exists()
