from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

V2_ROOT = Path(__file__).resolve().parents[1]
PLAN_VALIDATOR = V2_ROOT / "scripts" / "validate_legacy_retirement_plan.py"
DATABASE_RETIRER = V2_ROOT / "scripts" / "retire_legacy_development_database.py"
RUNBOOK = V2_ROOT / "RUNBOOK.md"
DNS_WORKFLOW = (
    V2_ROOT.parent / ".github" / "workflows" / "v2-production-foundation-dns.yml"
)
RETAINED = (
    "cloudflare_dns_record.apex[0]",
    'cloudflare_dns_record.site_cert_validation["dev.tollchat.ai"]',
    "aws_bedrock_guardrail.tollchat",
    "aws_bedrock_guardrail_version.tollchat",
)
ACCOUNT = "920534282028"
SOURCE_REMOTE = "https://github.com/rhprasad0/nova-toll-budget-agent.git"
SOURCE_COMMIT = "4c1f684c02bf81187c2cc5f15883727cf15b11ee"
DB_HOST = "nova-toll-db.abc.us-east-1.rds.amazonaws.com"
DB_PORT = 5432
SECRET_ARN = "arn:aws:secretsmanager:us-east-1:920534282028:secret:nova-toll-db-fixture"

_validator_spec = importlib.util.spec_from_file_location(
    "legacy_retirement_validator_fixture", PLAN_VALIDATOR
)
assert _validator_spec and _validator_spec.loader
_validator_module = importlib.util.module_from_spec(_validator_spec)
sys.modules[_validator_spec.name] = _validator_module
_validator_spec.loader.exec_module(_validator_module)
INSTANCE_ADDRESSES = _validator_module.LEGACY_APPLICATION_INSTANCE_ADDRESSES

_database_spec = importlib.util.spec_from_file_location(
    "legacy_database_retirement_fixture", DATABASE_RETIRER
)
assert _database_spec and _database_spec.loader
_database_module = importlib.util.module_from_spec(_database_spec)
sys.modules[_database_spec.name] = _database_module
_database_spec.loader.exec_module(_database_module)


def _instance_identifier(address: str) -> str:
    if address == RETAINED[0]:
        return "a" * 32
    if address == RETAINED[1]:
        return "b" * 32
    if address == RETAINED[2]:
        return "c" * 32
    if address == RETAINED[3]:
        return "d" * 32
    if address == "aws_lambda_function.loader":
        return "f" * 32
    if address == "aws_lambda_function.publisher":
        return "e" * 32
    if address.startswith("aws_cloudfront_distribution."):
        return "E" + hashlib.sha256(address.encode()).hexdigest()[:15].upper()
    if address.startswith("cloudflare_dns_record."):
        return hashlib.sha256(address.encode()).hexdigest()[:32]
    return hashlib.sha256(address.encode()).hexdigest()


def _resource(address: str, identifier: str) -> dict[str, object]:
    base, _, raw_index = address.partition("[")
    resource_type, name = base.split(".", 1)
    instance: dict[str, object] = {"attributes": {"id": identifier}}
    if raw_index:
        instance["index_key"] = json.loads("[" + raw_index)[0]
    return {
        "type": resource_type,
        "name": name,
        "instances": [instance],
    }


def _state_and_plan(
    tmp_path: Path, *, include_data: bool = False
) -> tuple[Path, Path, Path]:
    identifiers = {
        address: _instance_identifier(address) for address in INSTANCE_ADDRESSES
    }
    resources = [
        _resource(address, identifiers[address])
        for address in sorted(INSTANCE_ADDRESSES)
    ]
    if include_data:
        resources.append(
            {
                "mode": "data",
                "type": "aws_caller_identity",
                "name": "current",
                "instances": [{"attributes": {"account_id": ACCOUNT}}],
            }
        )
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"resources": resources}), encoding="utf-8")
    plan = tmp_path / "plan.json"
    changes = [
        {
            "address": address,
            "type": address.split(".", 1)[0],
            "change": {
                "actions": ["delete"],
                "before": {"id": identifiers[address]},
                "after": None,
            },
        }
        for address in sorted(INSTANCE_ADDRESSES - set(RETAINED))
    ]
    if include_data:
        changes.append(
            {
                "address": "data.aws_caller_identity.current",
                "mode": "data",
                "type": "aws_caller_identity",
                "change": {"actions": ["no-op"], "before": {}, "after": {}},
            }
        )
    plan.write_text(json.dumps({"resource_changes": changes}), encoding="utf-8")
    identity = tmp_path / "live-identity.json"
    identity_resources = [
        {
            "address": address,
            "type": address.split(".", 1)[0],
            "id": identifiers[address],
            "account_id": ACCOUNT,
        }
        for address in sorted(INSTANCE_ADDRESSES)
    ]
    identity.write_text(
        json.dumps(
            {
                "manifest": "legacy-live-identity-v1",
                "account_id": ACCOUNT,
                "source_remote": SOURCE_REMOTE,
                "source_commit": SOURCE_COMMIT,
                "identity_source": "account-scoped-live-api-v1",
                "resources": identity_resources,
            }
        ),
        encoding="utf-8",
    )
    return state, plan, identity


def _run_validator(
    state: Path, plan: Path, identity: Path
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(PLAN_VALIDATOR),
            "--state",
            str(state),
            "--plan",
            str(plan),
            "--identity-manifest",
            str(identity),
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def test_plan_validator_accepts_only_exact_delete_set(tmp_path: Path) -> None:
    state, plan, identity = _state_and_plan(tmp_path)
    result = _run_validator(state, plan, identity)
    assert result.returncode == 0, result.stderr
    manifest = json.loads(result.stdout)
    assert manifest["state_instances"] == 166
    assert manifest["data_instances"] == 0
    assert manifest["retained_instances"] == 4
    assert manifest["delete_instances"] == 162
    assert all(
        value not in result.stdout
        for value in ("loader", "f" * 32, str(state), ACCOUNT)
    )


def test_plan_validator_handles_approved_data_separately(tmp_path: Path) -> None:
    state, plan, identity = _state_and_plan(tmp_path, include_data=True)
    document = json.loads(plan.read_text(encoding="utf-8"))
    document["resource_changes"][-1]["change"]["actions"] = ["read"]
    plan.write_text(json.dumps(document), encoding="utf-8")
    result = _run_validator(state, plan, identity)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["data_instances"] == 1


@pytest.mark.parametrize(
    ("change", "address", "identifier"),
    [
        (
            {"actions": ["create"], "before": None, "after": {}},
            "aws_lambda_function.loader",
            "f" * 32,
        ),
        (
            {"actions": ["update"], "before": {"id": "f" * 32}, "after": {}},
            "aws_lambda_function.loader",
            "f" * 32,
        ),
        (
            {
                "actions": ["delete", "create"],
                "before": {"id": "f" * 32},
                "after": None,
            },
            "aws_lambda_function.loader",
            "f" * 32,
        ),
        (
            {"actions": ["read"], "before": {"id": "f" * 32}, "after": None},
            "aws_lambda_function.loader",
            "f" * 32,
        ),
        (
            {"actions": ["delete"], "before": {"id": "f" * 32}, "after": None},
            "aws_lambda_function.unknown",
            "f" * 32,
        ),
        (
            {"actions": ["delete"], "before": {"id": "1" * 32}, "after": None},
            "aws_lambda_function.loader",
            "1" * 32,
        ),
        (
            {"actions": ["delete"], "before": {"id": "a" * 32}, "after": None},
            RETAINED[0],
            "a" * 32,
        ),
    ],
)
def test_plan_validator_rejects_adversarial_plan(
    tmp_path: Path, change: dict[str, object], address: str, identifier: str
) -> None:
    state, plan, identity = _state_and_plan(tmp_path)
    document = json.loads(plan.read_text(encoding="utf-8"))
    document["resource_changes"] = [{"address": address, "change": change}]
    plan.write_text(json.dumps(document), encoding="utf-8")
    result = _run_validator(state, plan, identity)
    assert result.returncode != 0
    assert "legacy retirement plan rejected" in result.stderr
    assert identifier not in result.stderr


def test_plan_validator_rejects_shared_rds_state(tmp_path: Path) -> None:
    state, plan, identity = _state_and_plan(tmp_path)
    document = json.loads(state.read_text(encoding="utf-8"))
    document["resources"].append(
        {
            "type": "aws_db_instance",
            "name": "main",
            "instances": [{"attributes": {"id": "nova-toll-db"}}],
        }
    )
    state.write_text(json.dumps(document), encoding="utf-8")
    result = _run_validator(state, plan, identity)
    assert result.returncode != 0


@pytest.mark.parametrize("field", ["source_remote", "source_commit"])
def test_plan_validator_requires_canonical_review_source(
    tmp_path: Path, field: str
) -> None:
    state, plan, identity = _state_and_plan(tmp_path)
    document = json.loads(identity.read_text(encoding="utf-8"))
    document[field] = "untrusted"
    identity.write_text(json.dumps(document), encoding="utf-8")
    result = _run_validator(state, plan, identity)
    assert result.returncode != 0


def test_plan_validator_rejects_poisoned_state_or_live_identity_mapping(
    tmp_path: Path,
) -> None:
    state, plan, identity = _state_and_plan(tmp_path)
    state_document = json.loads(state.read_text(encoding="utf-8"))
    state_document["resources"][-1]["instances"][0]["attributes"]["id"] = "a" * 32
    state.write_text(json.dumps(state_document), encoding="utf-8")
    result = _run_validator(state, plan, identity)
    assert result.returncode != 0

    state, plan, identity = _state_and_plan(tmp_path)
    identity_document = json.loads(identity.read_text(encoding="utf-8"))
    identity_document["resources"][-1]["id"] = "a" * 32
    identity.write_text(json.dumps(identity_document), encoding="utf-8")
    result = _run_validator(state, plan, identity)
    assert result.returncode != 0


def test_plan_validator_rejects_explicit_address_type_mismatch(
    tmp_path: Path,
) -> None:
    state, plan, identity = _state_and_plan(tmp_path)
    state_document = json.loads(state.read_text(encoding="utf-8"))
    state_document["resources"][0]["address"] = RETAINED[0]
    state_document["resources"][0]["type"] = "aws_s3_bucket"
    state.write_text(json.dumps(state_document), encoding="utf-8")
    result = _run_validator(state, plan, identity)
    assert result.returncode != 0


@pytest.mark.parametrize(
    ("resource_type", "name", "original_index", "poisoned_index"),
    [
        ("aws_cloudwatch_log_group", "agentcore_runtime", "preview", 999),
        ("cloudflare_dns_record", "apex", 0, 999),
    ],
)
def test_plan_validator_rejects_poisoned_count_or_foreach_index(
    tmp_path: Path,
    resource_type: str,
    name: str,
    original_index: object,
    poisoned_index: object,
) -> None:
    state, plan, identity = _state_and_plan(tmp_path)
    document = json.loads(state.read_text(encoding="utf-8"))
    resource = next(
        item
        for item in document["resources"]
        if item.get("type") == resource_type
        and item.get("name") == name
        and item["instances"][0].get("index_key") == original_index
    )
    assert resource["instances"][0]["index_key"] == original_index
    resource["instances"][0]["index_key"] = poisoned_index
    state.write_text(json.dumps(document), encoding="utf-8")
    result = _run_validator(state, plan, identity)
    assert result.returncode != 0


def test_plan_validator_rejects_missing_or_extra_reviewed_instance(
    tmp_path: Path,
) -> None:
    state, plan, identity = _state_and_plan(tmp_path)
    document = json.loads(state.read_text(encoding="utf-8"))
    resource = next(
        item
        for item in document["resources"]
        if item.get("type") == "aws_cloudwatch_log_group"
        and item.get("name") == "agentcore_runtime"
        and item["instances"][0].get("index_key") == "preview"
    )
    document["resources"].remove(resource)
    state.write_text(json.dumps(document), encoding="utf-8")
    result = _run_validator(state, plan, identity)
    assert result.returncode != 0

    state, plan, identity = _state_and_plan(tmp_path)
    document = json.loads(state.read_text(encoding="utf-8"))
    resource = next(
        item
        for item in document["resources"]
        if item.get("type") == "aws_cloudwatch_log_group"
        and item.get("name") == "agentcore_runtime"
        and item["instances"][0].get("index_key") == "preview"
    )
    resource["instances"][0]["index_key"] = "unexpected"
    state.write_text(json.dumps(document), encoding="utf-8")
    result = _run_validator(state, plan, identity)
    assert result.returncode != 0


def _fake_psql(
    tmp_path: Path,
    *,
    fail_on: str = "",
    survive_role: str = "",
    null_comment_target: str = "",
) -> tuple[Path, Path]:
    log = tmp_path / "psql.log"
    marker = tmp_path / "survived-role"
    executable = tmp_path / "psql"
    executable.write_text(
        "#!/usr/bin/env python3\n"
        "import os, pathlib, sys\n"
        f"log = pathlib.Path({str(log)!r})\n"
        f"marker = pathlib.Path({str(marker)!r})\n"
        "sql = sys.stdin.read()\n"
        "with log.open('a') as stream:\n"
        "    stream.write(os.environ.get('PGDATABASE', '') + '|' + os.environ.get('PGSSLMODE', '') + '|' + os.environ.get('PGHOST', '') + '|' + sql.replace('\\n', ' ') + '\\n')\n"
        f"if {survive_role!r} and 'DROP ROLE {survive_role};' in sql:\n"
        "    marker.write_text('recreated', encoding='utf-8')\n"
        f"if {survive_role!r} and 'role postcondition failed' in sql and marker.exists():\n"
        "    sys.exit(1)\n"
        f"if {null_comment_target!r} and {null_comment_target!r} in sql and \"IS DISTINCT FROM 'environment=development'\" in sql:\n"
        "    sys.exit(1)\n"
        f"sys.exit(1 if {fail_on!r} and {fail_on!r} in sql else 0)\n",
        encoding="utf-8",
    )
    executable.chmod(0o700)
    return executable, log


def _fake_aws(tmp_path: Path) -> Path:
    executable = tmp_path / "aws"
    rds_response = json.dumps(
        [
            {
                "DBInstanceIdentifier": "nova-toll-db",
                "DBInstanceStatus": "available",
                "PubliclyAccessible": False,
                "Endpoint": {"Address": DB_HOST, "Port": DB_PORT},
                "MasterUserSecret": {"SecretArn": SECRET_ARN},
            }
        ]
    )
    executable.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        "arguments = sys.argv[1:]\n"
        "if 'get-caller-identity' in arguments:\n"
        f"    print({ACCOUNT!r})\n"
        "elif 'describe-db-instances' in arguments:\n"
        f"    print({rds_response!r})\n"
        "else:\n"
        "    raise SystemExit(1)\n",
        encoding="utf-8",
    )
    executable.chmod(0o700)
    return executable


def _run_database(
    tmp_path: Path,
    *,
    execute: bool = False,
    approval: str | None = None,
    fail_on: str = "",
    host: str = "nova-toll-db.abc.us-east-1.rds.amazonaws.com",
    port: int = 5432,
    bad_ca: bool = False,
    survive_role: str = "",
    null_comment_target: str = "",
    handoff_secret_arn: str = SECRET_ARN,
    ambient_profile: str | None = None,
    pin_ca_for_fixture: bool = True,
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    _, log = _fake_psql(
        tmp_path,
        fail_on=fail_on,
        survive_role=survive_role,
        null_comment_target=null_comment_target,
    )
    _fake_aws(tmp_path)
    ca_file = tmp_path / "ca.pem"
    ca_file.write_text("fixture", encoding="utf-8")
    digest = hashlib.sha256(ca_file.read_bytes()).hexdigest()
    handoff = tmp_path / "handoff.json"
    handoff.write_text(
        json.dumps(
            {
                "manifest": "legacy-db-handoff-v1",
                "account_id": ACCOUNT,
                "region": "us-east-1",
                "instance_identifier": "nova-toll-db",
                "host": host,
                "port": port,
                "ca_sha256": digest,
                "secret_arn": handoff_secret_arn,
            }
        ),
        encoding="utf-8",
    )
    if bad_ca:
        ca_file.write_text("changed", encoding="utf-8")
    environment = os.environ.copy()
    environment["PATH"] = f"{tmp_path}{os.pathsep}{environment['PATH']}"
    # Deliberately hostile ambient PG* values prove they are ignored.
    environment["PGHOST"] = "attacker.example"
    environment["PGUSER"] = "ambient-user"
    environment["PGPASSWORD"] = "ambient-password"
    environment["RETIRE_LEGACY_HANDOFF_APPROVED"] = "YES"
    environment["RETIRE_LEGACY_DB_USER"] = "fixture-user"
    environment["RETIRE_LEGACY_DB_PASSWORD"] = "fixture-password"
    for key in (
        "AWS_PROFILE",
        "AWS_DEFAULT_REGION",
        "AWS_REGION",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_SECURITY_TOKEN",
    ):
        environment.pop(key, None)
    if ambient_profile is not None:
        environment["AWS_PROFILE"] = ambient_profile
    if approval is None:
        environment.pop("RETIRE_LEGACY_DEVELOPMENT_APPROVED", None)
    else:
        environment["RETIRE_LEGACY_DEVELOPMENT_APPROVED"] = approval
    runner = tmp_path / "retirement-runner.py"
    # Keep the synthetic CA fixture small; production always retains the
    # immutable module pin and the separate test below proves self-consistent
    # arbitrary CA material is rejected against that pin.
    pin = f"module.APPROVED_CA_SHA256 = {digest!r}\n" if pin_ca_for_fixture else ""
    runner.write_text(
        "import importlib.util, pathlib, sys\n"
        f"spec = importlib.util.spec_from_file_location('retirer', {str(DATABASE_RETIRER)!r})\n"
        "module = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(module)\n"
        f"{pin}"
        "raise SystemExit(module.main(sys.argv[1:]))\n",
        encoding="utf-8",
    )
    command = [
        sys.executable,
        str(runner),
        "--host",
        host,
        "--port",
        str(port),
        "--ca-file",
        str(ca_file),
        "--handoff",
        str(handoff),
    ]
    if execute:
        command.append("--execute")
    result = subprocess.run(
        command, capture_output=True, text=True, env=environment, check=False
    )
    return result, log.read_text(encoding="utf-8").splitlines() if log.exists() else []


def test_database_default_is_read_only_and_tls_is_pinned(tmp_path: Path) -> None:
    result, calls = _run_database(tmp_path)
    assert result.returncode == 0, result.stderr
    assert len(calls) == 2
    assert all("DROP " not in line for line in calls)
    assert all(
        "|verify-full|nova-toll-db.abc.us-east-1.rds.amazonaws.com" in line
        for line in calls
    )
    assert "attacker.example" not in "".join(calls)


def test_database_requires_connect_for_every_role_before_and_after_retirement() -> None:
    for role in _database_module.PRODUCTION_ROLES:
        check = f"NOT has_database_privilege('{role}', 'nova_toll', 'CONNECT')"
        assert check in _database_module.PREFLIGHT_SQL
        assert check in _database_module.PRODUCTION_INVARIANTS
        assert check in _database_module.FINAL_SQL
    for role in _database_module.DEVELOPMENT_ROLES:
        check = (
            f"NOT has_database_privilege('{role}', 'nova_toll_development', 'CONNECT')"
        )
        assert check in _database_module.PREFLIGHT_SQL


def test_database_rejects_unapproved_incoming_app_role_grant(tmp_path: Path) -> None:
    for sql in (
        _database_module.PREFLIGHT_SQL,
        _database_module.PRODUCTION_INVARIANTS,
        _database_module.FINAL_SQL,
    ):
        assert "OR granted_role.rolname IN" in sql
        for role in _database_module.APP_ROLES:
            assert f"'{role}'" in sql
        assert "granted_role.rolname = 'rds_iam'" in sql

    # The fake server models an incoming GRANT app_role TO attacker by failing
    # the exact preflight membership contract before any destructive statement.
    result, calls = _run_database(
        tmp_path,
        execute=True,
        approval="YES",
        fail_on="role membership is outside the reviewed contract",
    )
    assert result.returncode != 0
    assert len(calls) == 1
    assert all("DROP " not in line for line in calls)


def test_database_missing_connect_grant_stops_before_drop(tmp_path: Path) -> None:
    result, calls = _run_database(
        tmp_path,
        execute=True,
        approval="YES",
        fail_on="required database CONNECT grant is missing",
    )
    assert result.returncode != 0
    assert len(calls) == 1
    assert all("DROP " not in line for line in calls)


def test_database_null_environment_comments_stop_before_drop(tmp_path: Path) -> None:
    preflight = _database_module.PREFLIGHT_SQL
    assert "IS DISTINCT FROM 'environment=development'" in preflight
    assert "shobj_description(oid, 'pg_authid')" in preflight
    targets = [
        "obj_description(development_oid, 'pg_database')",
        *[f"'{role}'" for role in _database_module.DEVELOPMENT_ROLES],
    ]
    for index, target in enumerate(targets):
        case_dir = tmp_path / f"null-comment-{index}"
        case_dir.mkdir()
        result, calls = _run_database(
            case_dir,
            execute=True,
            approval="YES",
            null_comment_target=target,
        )
        assert result.returncode != 0
        assert len(calls) == 1
        assert all("DROP " not in line for line in calls)


def test_database_valid_environment_comments_allow_preflight_and_drop(
    tmp_path: Path,
) -> None:
    result, calls = _run_database(
        tmp_path,
        execute=True,
        approval="YES",
    )
    assert result.returncode == 0, result.stderr
    assert len(calls) > 1
    assert any(
        "DROP DATABASE nova_toll_development WITH (FORCE);" in line for line in calls
    )


def test_database_missing_production_connect_grant_stops_after_database_drop(
    tmp_path: Path,
) -> None:
    result, calls = _run_database(
        tmp_path,
        execute=True,
        approval="YES",
        fail_on="production database CONNECT grant is missing",
    )
    assert result.returncode != 0
    assert len(calls) == 4
    assert "DROP DATABASE nova_toll_development WITH (FORCE);" in calls[2]
    assert all("DROP ROLE" not in line for line in calls)


def test_database_rejects_invalid_host_port_and_ca(tmp_path: Path) -> None:
    result, calls = _run_database(tmp_path, host="attacker.example")
    assert result.returncode != 0 and not calls
    result, calls = _run_database(tmp_path, host="attacker.rds.amazonaws.com")
    assert result.returncode != 0 and not calls
    result, calls = _run_database(tmp_path, port=0)
    assert result.returncode != 0 and not calls
    result, calls = _run_database(tmp_path, bad_ca=True)
    assert result.returncode != 0 and not calls
    result, calls = _run_database(tmp_path, pin_ca_for_fixture=False)
    assert result.returncode != 0 and not calls


def test_database_rejects_mismatched_secret_or_ambient_profile(
    tmp_path: Path,
) -> None:
    result, calls = _run_database(
        tmp_path,
        handoff_secret_arn="arn:aws:secretsmanager:us-east-1:920534282028:secret:other",
    )
    assert result.returncode != 0 and not calls
    result, calls = _run_database(tmp_path, ambient_profile="attacker")
    assert result.returncode != 0 and not calls


def test_database_execute_requires_literal_approval(tmp_path: Path) -> None:
    result, calls = _run_database(tmp_path, execute=True)
    assert result.returncode != 0
    assert not calls
    assert "fixture-password" not in result.stderr


def test_database_stops_on_unknown_outcome(tmp_path: Path) -> None:
    result, calls = _run_database(
        tmp_path,
        execute=True,
        approval="YES",
        fail_on="DROP DATABASE nova_toll_development",
    )
    assert result.returncode != 0
    assert len(calls) == 4
    assert "DROP DATABASE nova_toll_development WITH (FORCE);" in calls[2]
    assert all("DROP ROLE" not in line for line in calls)
    assert "CASCADE" not in "".join(calls)


def test_database_dependency_failure_stops_before_mutation(tmp_path: Path) -> None:
    result, calls = _run_database(
        tmp_path, execute=True, approval="YES", fail_on="pg_subscription"
    )
    assert result.returncode != 0
    assert len(calls) == 2
    assert all("DROP " not in line for line in calls)


def test_database_postcondition_failure_stops_after_drop(tmp_path: Path) -> None:
    result, calls = _run_database(
        tmp_path, execute=True, approval="YES", fail_on="database postcondition failed"
    )
    assert result.returncode != 0
    assert len(calls) == 4
    assert "DROP DATABASE nova_toll_development WITH (FORCE);" in calls[2]


def test_database_role_dependency_failure_stops_before_role_drop(
    tmp_path: Path,
) -> None:
    result, calls = _run_database(
        tmp_path, execute=True, approval="YES", fail_on="another database"
    )
    assert result.returncode != 0
    assert len(calls) == 5
    assert "DROP DATABASE nova_toll_development WITH (FORCE);" in calls[2]
    assert "DROP ROLE" not in "\n".join(calls)


def test_database_execute_drops_only_exact_targets(tmp_path: Path) -> None:
    result, calls = _run_database(tmp_path, execute=True, approval="YES")
    assert result.returncode == 0, result.stderr
    sql = "\n".join(calls)
    assert "DROP DATABASE nova_toll_development WITH (FORCE);" in sql
    for role in (
        "pricing_loader_writer_development",
        "pricing_reader_development",
        "oracle_owner_development",
        "tollchat_agent_development",
        "pricing_caller_development",
        "report_publisher_development",
    ):
        assert f"DROP ROLE {role};" in sql
    assert "DROP DATABASE nova_toll_development CASCADE" not in sql
    assert "DROP ROLE IF EXISTS" not in sql
    assert "ambient-password" not in sql
    assert "fixture-password" not in result.stdout + result.stderr
    assert "rolname IN ('')" in sql
    assert "<> 0" in sql


def test_database_stops_when_a_dropped_role_survives_or_reappears(
    tmp_path: Path,
) -> None:
    result, calls = _run_database(
        tmp_path,
        execute=True,
        approval="YES",
        survive_role="pricing_loader_writer_development",
    )
    assert result.returncode != 0
    assert len(calls) == 7
    assert "DROP ROLE pricing_loader_writer_development;" in calls[5]
    assert "role postcondition failed" in calls[6]
    assert "pricing_loader_writer_development" in calls[6]


def test_saved_plan_readonly_fd_survives_named_path_replacement(
    tmp_path: Path,
) -> None:
    plan = tmp_path / "legacy-retirement.tfplan"
    plan.write_bytes(b"reviewed-plan")
    plan.chmod(0o400)
    descriptor = os.open(plan, os.O_RDONLY)
    try:
        original = os.fstat(descriptor)
        plan.unlink()
        plan.write_bytes(b"attacker-replacement")
        current = os.fstat(descriptor)
        assert (current.st_dev, current.st_ino) == (original.st_dev, original.st_ino)
        assert os.read(descriptor, len(b"reviewed-plan")) == b"reviewed-plan"
    finally:
        os.close(descriptor)


def test_retirement_runbook_and_sources_keep_the_lower_pr_boundary() -> None:
    runbook = RUNBOOK.read_text(encoding="utf-8")
    database = DATABASE_RETIRER.read_text(encoding="utf-8")
    workflow = DNS_WORKFLOW.read_text(encoding="utf-8")
    for required in (
        "source-only lower PR",
        "retirement-archives/",
        "4c1f684",
        "terraform plan -destroy",
        "cloudflare_dns_record.apex[0]",
        "RETIRE_LEGACY_DEVELOPMENT_APPROVED=YES",
        "DROP DATABASE nova_toll_development WITH (FORCE)",
        "production database `nova_toll`",
        "LIVE_IDENTITY_MANIFEST",
        "STATE_SSEKMS_KEY_ID",
        "DESTROY_PLAN_JSON",
        "RETIRE_LEGACY_REVIEWED_PLAN_SHA256",
        "source_remote",
        "source_commit",
        "identity_source",
        "assert_current_state",
        "one exact multi-address",
        "head-after-detach.json",
        "LIVE_STATE_AFTER_DETACH",
        "state-list-after-detach.txt",
        "PLAN_STATE_VERSION",
        "PLAN_STATE_SERIAL",
        "retained identity cardinality",
        "without automatically restoring",
        "head-before-plan-render.json",
        "head-immediately-before-render.json",
        "head-immediately-before-apply.json",
        "RETIRE_LEGACY_HANDOFF_APPROVED=YES",
        "no safe compare-and-swap delete operation",
    ):
        assert required in runbook
    detach_section = runbook[
        runbook.index(
            "The following is the bounded archive/detach skeleton"
        ) : runbook.index("Replace each `EXPECTED_*` marker")
    ]
    assert (
        detach_section.count('terraform_prod -chdir="$COMPAT_ROOT/v2/infra" state rm')
        == 1
    )
    state_rm_index = detach_section.index(
        'terraform_prod -chdir="$COMPAT_ROOT/v2/infra" state rm'
    )
    for address in (
        "'cloudflare_dns_record.apex[0]'",
        "'cloudflare_dns_record.site_cert_validation[\"dev.tollchat.ai\"]'",
        "'aws_bedrock_guardrail.tollchat'",
        "'aws_bedrock_guardrail_version.tollchat'",
    ):
        assert address in detach_section[state_rm_index:]
    assert (
        detach_section.index('assert_current_state "$STATE_VERSION"') < state_rm_index
    )
    head_after_index = detach_section.index("head-after-detach.json", state_rm_index)
    assert state_rm_index < head_after_index
    plan_serial_index = detach_section.index("PLAN_STATE_SERIAL=")
    assert head_after_index < plan_serial_index
    state_list_after_index = detach_section.index(
        "state-list-after-detach.txt", plan_serial_index
    )
    assert plan_serial_index < state_list_after_index
    for required in (
        "FOUNDATION_SHARED_DENY_TYPES",
        "APPROVED_DATA_BASE_ADDRESSES",
        "pg_subscription",
        "pg_publication",
        "pg_replication_slots",
        "pg_foreign_table",
        "schema ownership",
    ):
        assert required in database or required in PLAN_VALIDATOR.read_text(
            encoding="utf-8"
        )
    assert "DROP DATABASE nova_toll_development CASCADE" not in database
    assert "DROP DATABASE IF EXISTS" not in database
    assert "DROP ROLE IF EXISTS" not in database
    assert "bootstrap_development_database" not in database
    assert "030_upgrade_oracle" not in database
    assert '"stage-validation", "cutover", "rollback"' in workflow
    assert "DELETE" not in workflow
    assert "describe-db-instances" in database
    assert "PRODUCTION_PROFILE" in database
    assert "APPROVED_CA_SHA256" in database
    assert (
        "e5bb2084ccf45087bda1c9bffdea0eb15ee67f0b91646106e466714f9de3c7e3" in database
    )
    for required in (
        "stat -Lc",
        "chmod 400",
        "PLAN_METADATA",
        "/proc/self/fd/",
        'apply "$PLAN_FD_PATH"',
    ):
        assert required in runbook
