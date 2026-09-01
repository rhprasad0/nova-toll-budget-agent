# pyright: reportUnknownParameterType=false, reportMissingParameterType=false, reportUnknownMemberType=false, reportUnknownLambdaType=false, reportUnknownVariableType=false, reportIndexIssue=false, reportArgumentType=false

import importlib.util
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts" / "deploy_oracle_migration.py"
REPO = SCRIPT.parents[2]
SPEC = importlib.util.spec_from_file_location("deployed_migration", SCRIPT)
assert SPEC and SPEC.loader
migration = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(migration)


def test_only_reviewed_environments_and_fixed_targets_are_accepted():
    assert SCRIPT.parents[1] == migration.V2_ROOT
    assert migration.MIGRATION.is_file()
    assert (
        SCRIPT.parents[1] / "infra/build/loader/rds-ca-bundle.pem"
        == migration.CA_BUNDLE
    )
    assert (
        SCRIPT.parents[1] / "build/deployed-migration-evidence"
        == migration.EVIDENCE_ROOT
    )
    assert set(migration.ENVIRONMENTS) == {"development", "production"}
    assert migration.ENVIRONMENTS["development"] == (
        "nova_toll_development",
        "oracle_migrator_development",
    )
    assert migration.ENVIRONMENTS["production"] == ("nova_toll", "oracle_migrator")
    assert migration.RDS_RESOURCE_ID == "db-WHGCQ3B5SB4WPB5RTJMU3CE664"
    assert migration.main([]) == 2
    assert migration.main(["development; psql"]) == 2


def test_migrator_iam_is_mfa_gated_and_has_only_the_two_reviewed_logins():
    iam = (REPO / "infra/iam.tf").read_text()
    policy = iam.split('data "aws_iam_policy_document" "oracle_migrator"', 1)[1].split(
        'resource "aws_iam_role_policy" "oracle_migrator"', 1
    )[0]
    assert 'name                 = "nova-toll-v2-database-migrator"' in iam
    assert 'variable = "aws:MultiFactorAuthPresent"' in iam
    assert policy.count("rds-db:connect") == 1
    assert policy.count("oracle_migrator_development") == 1
    assert policy.count('/oracle_migrator"') == 1
    assert "*" not in policy


def test_runner_uses_tls_iam_auth_and_the_matching_owner_role():
    source = SCRIPT.read_text()
    assert '"PGSSLMODE": "verify-full"' in source
    assert '"generate-db-auth-token"' in source
    assert '"--set", "ON_ERROR_STOP=1"' in source
    assert 'f"SET ROLE {owner}"' in source


def test_rds_target_rejects_public_wrong_or_unrestorable_instances(monkeypatch):
    instance = {
        "DBInstanceIdentifier": migration.RDS_IDENTIFIER,
        "DbiResourceId": migration.RDS_RESOURCE_ID,
        "PubliclyAccessible": False,
        "IAMDatabaseAuthenticationEnabled": True,
        "DBInstanceStatus": "available",
        "BackupRetentionPeriod": 7,
        "LatestRestorableTime": datetime.now(UTC).isoformat(),
        "Endpoint": {"Address": "nova-toll-db.example.rds.amazonaws.com"},
    }
    monkeypatch.setattr(
        migration,
        "command",
        lambda *_args, **_kwargs: json.dumps({"DBInstances": [instance]}),
    )
    monkeypatch.setattr(
        migration.socket,
        "getaddrinfo",
        lambda *_args: [(None, None, None, None, ("172.31.0.1", 5432))],
    )
    assert migration.rds_target({}, True) == instance["Endpoint"]["Address"]
    instance["PubliclyAccessible"] = True
    with pytest.raises(migration.Stop):
        migration.rds_target({}, True)
    instance["PubliclyAccessible"] = False
    instance.pop("LatestRestorableTime")
    with pytest.raises(migration.Stop):
        migration.rds_target({}, True)
    instance["LatestRestorableTime"] = datetime.now(UTC).isoformat()
    instance["BackupRetentionPeriod"] = 6
    with pytest.raises(migration.Stop):
        migration.rds_target({}, True)


def test_development_evaluation_refuses_ambient_database_target(monkeypatch):
    monkeypatch.setenv("DB_HOST", "wrong.example")
    with pytest.raises(migration.Stop):
        migration.capture_eval("case", "window", "suite")


def test_development_evaluation_refuses_ambient_database_port(monkeypatch):
    monkeypatch.setenv("DB_PORT", "5432")
    with pytest.raises(migration.Stop):
        migration.capture_eval("case", "window", "suite")


def test_development_evaluation_binds_the_reviewed_target_and_identities(
    monkeypatch, tmp_path
):
    results = tmp_path / "eval/results"
    results.mkdir(parents=True)
    monkeypatch.setattr(migration, "V2_ROOT", tmp_path)
    monkeypatch.setattr(migration, "CA_BUNDLE", tmp_path / "rds-ca.pem")
    monkeypatch.setattr(
        migration, "rds_target", lambda *_args: "nova-toll-db.example.rds.amazonaws.com"
    )
    captured = {}

    def fake_command(_args, *, env=None, input=None):
        captured.update(env or {})
        (results / "new.json").write_text(
            json.dumps(
                {
                    "cases": [{"name": "case"}],
                    "detailed_results": [[{"test_pass": True}]],
                }
            )
        )
        return ""

    monkeypatch.setattr(migration, "command", fake_command)
    migration.capture_eval("case", "window", "suite")
    assert {
        key: captured[key]
        for key in (
            "DB_HOST",
            "DB_PORT",
            "DB_NAME",
            "DB_USER",
            "PRICING_DB_USER",
            "AWS_PROFILE",
            "AWS_DEFAULT_REGION",
            "DB_CA_BUNDLE_PATH",
        )
    } == {
        "DB_HOST": "nova-toll-db.example.rds.amazonaws.com",
        "DB_PORT": "5432",
        "DB_NAME": "nova_toll_development",
        "DB_USER": "tollchat_agent_development",
        "PRICING_DB_USER": "pricing_caller_development",
        "AWS_PROFILE": "nova-toll-prod",
        "AWS_DEFAULT_REGION": "us-east-1",
        "DB_CA_BUNDLE_PATH": str(migration.CA_BUNDLE),
    }


def test_operator_outputs_are_ignored_without_ignoring_tracked_eval_history():
    def ignored(path: str) -> bool:
        return (
            subprocess.run(
                ["git", "check-ignore", "-q", path], cwd=REPO, check=False
            ).returncode
            == 0
        )

    assert ignored(
        "v2/build/deployed-migration-evidence/development-release-receipt.txt"
    )
    assert ignored("v2/eval/results/new-live-report.json")
    assert not ignored("v2/eval/results/20260822T150912Z.json")


def test_state_requires_exact_versions_and_postconditions():
    migration.require_state((migration.SOURCE, migration.PRICING, 1, 0), before=True)
    migration.require_state((migration.TARGET, migration.PRICING, 996, 1), before=False)
    for state, before in [
        (("1.13.0", migration.PRICING, 1, 0), True),
        ((migration.TARGET, "1.2.0", 996, 1), False),
        ((migration.TARGET, migration.PRICING, 995, 1), False),
        ((migration.TARGET, migration.PRICING, 996, 0), False),
    ]:
        with pytest.raises(migration.Stop):
            migration.require_state(state, before=before)


def test_digest_is_pinned_to_the_reviewed_migration(monkeypatch, tmp_path):
    path = tmp_path / "030_upgrade_oracle_1_13_1_to_1_14_0.sql"
    path.write_text("not reviewed")
    monkeypatch.setattr(migration, "MIGRATION", path)
    with pytest.raises(migration.Stop):
        migration.migration_digest()


def test_evidence_is_unique_owner_only_and_production_requires_matching_dev(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(migration, "EVIDENCE_ROOT", tmp_path)
    destination = migration.evidence_directory("development", "a" * 40)
    report = tmp_path / "report.json"
    report.write_text(
        json.dumps(
            {
                "cases": [
                    {"name": "leesburg-to-washington-i395-current-price"},
                    {"name": "leesburg-to-washington-i395-job-offer"},
                ],
                "detailed_results": [[{"test_pass": True}], [{"test_pass": True}]],
            }
        )
    )
    migration.write_evidence(
        destination,
        {
            "environment": "development",
            "commit": "a" * 40,
            "timestamp_utc": "2026-08-31T00:00:00+00:00",
            "migration": "030_upgrade_oracle_1_13_1_to_1_14_0.sql",
            "migration_sha256": "b" * 64,
            "rds_identifier": "nova-toll-db",
            "rds_resource_id": migration.RDS_RESOURCE_ID,
            "oracle_before": migration.SOURCE,
            "pricing_before": migration.PRICING,
            "oracle_after": migration.TARGET,
            "pricing_after": migration.PRICING,
            "connections": "996",
            "handoffs": "1",
        },
        immutable=False,
    )
    record = migration.parse_record(destination / "migration.txt")
    for name in ("current", "annual"):
        target = destination / f"{name}.json"
        target.write_bytes(report.read_bytes())
        record[f"{name}_report_sha256"] = migration.sha256(target)
    record.update(
        {
            "schema_label": "oracle-1.14.0",
            "current_case": "leesburg-to-washington-i395-current-price",
            "current_pass": "true",
            "annual_case": "leesburg-to-washington-i395-job-offer",
            "annual_pass": "true",
        }
    )
    (destination / "i395-evals.txt").write_text(
        "".join(f"{key}={value}\n" for key, value in sorted(record.items()))
    )
    for item in destination.iterdir():
        item.chmod(0o400)
    destination.chmod(0o500)
    assert destination.stat().st_mode & 0o222 == 0
    migration.read_development_evidence("a" * 40, "b" * 64)
    with pytest.raises(migration.Stop):
        migration.read_development_evidence("different", "b" * 64)
    with pytest.raises(migration.Stop):
        migration.write_evidence(destination, {"environment": "development"})


def test_external_failures_do_not_echo_tokens_or_connection_details(
    monkeypatch, capsys
):
    sentinel = "postgresql://token-secret"

    def fail(*_args, **_kwargs):
        raise migration.Stop("required command failed: aws")

    monkeypatch.setattr(migration, "require_tools", fail)
    assert migration.main(["development"]) == 1
    captured = capsys.readouterr()
    assert sentinel not in captured.out + captured.err
