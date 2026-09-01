#!/usr/bin/env python3
"""Run the reviewed Oracle 1.13.1 -> 1.14.0 deployment migration.

This is deliberately an operator command, never a CI command.  It accepts only
an environment name and keeps credentials in subprocess environments.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

V2_ROOT = Path(__file__).resolve().parents[1]
MIGRATION = V2_ROOT / "db/migrations/030_upgrade_oracle_1_13_1_to_1_14_0.sql"
CA_BUNDLE = V2_ROOT / "infra/build/loader/rds-ca-bundle.pem"
EVIDENCE_ROOT = V2_ROOT / "build/deployed-migration-evidence"
ACCOUNT = "920534282028"
REGION = "us-east-1"
RDS_IDENTIFIER = "nova-toll-db"
RDS_RESOURCE_ID = "db-WHGCQ3B5SB4WPB5RTJMU3CE664"
ROLE_ARN = f"arn:aws:iam::{ACCOUNT}:role/nova-toll-v2-database-migrator"
TARGET = "1.14.0"
SOURCE = "1.13.1"
PRICING = "1.3.0"
MIGRATION_SHA256 = "101ee53eb4e37f00e4bf711d9c97bf97b4c53981f5b0a6bd7a932cfea9ecee40"
ENVIRONMENTS = {
    "development": ("nova_toll_development", "oracle_migrator_development"),
    "production": ("nova_toll", "oracle_migrator"),
}
OWNERS = {
    "oracle_migrator_development": "oracle_owner_development",
    "oracle_migrator": "oracle_owner",
}
MIGRATION_RECORD_KEYS = {
    "environment",
    "commit",
    "timestamp_utc",
    "migration",
    "migration_sha256",
    "rds_identifier",
    "rds_resource_id",
    "oracle_before",
    "pricing_before",
    "oracle_after",
    "pricing_after",
    "connections",
    "handoffs",
}


class Stop(RuntimeError):
    """A fail-closed deployment stop; messages must contain no secrets."""


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_record(path: Path) -> dict[str, str]:
    if not path.is_file() or path.is_symlink():
        raise Stop("migration evidence file is unsafe")
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.count("=") != 1:
            raise Stop("migration evidence is malformed")
        key, value = line.split("=", 1)
        if not key or not value or key in values:
            raise Stop("migration evidence has duplicate or empty fields")
        values[key] = value
    return values


def command(
    args: list[str], *, env: dict[str, str] | None = None, input: str | None = None
) -> str:
    try:
        result = subprocess.run(
            args, input=input, text=True, env=env, capture_output=True, check=True
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise Stop(f"required command failed: {args[0]}") from error
    return result.stdout.strip()


def require_tools() -> None:
    for tool in ("aws", "psql", "git"):
        if shutil.which(tool) is None:
            raise Stop(f"required command is missing: {tool}")
    if not CA_BUNDLE.is_file() or CA_BUNDLE.is_symlink():
        raise Stop("reviewed RDS CA bundle is missing")


def checked_main() -> str:
    if command(["git", "status", "--porcelain"], env=os.environ.copy()):
        raise Stop("checkout is dirty")
    if command(["git", "branch", "--show-current"]) != "main":
        raise Stop("migration must run from merged main")
    commit = command(["git", "rev-parse", "HEAD"])
    if commit != command(["git", "rev-parse", "origin/main"]):
        raise Stop("checkout is not the reviewed current origin/main")
    return commit


def migration_digest() -> str:
    if not MIGRATION.is_file() or MIGRATION.is_symlink():
        raise Stop("reviewed migration is missing")
    digest = hashlib.sha256(MIGRATION.read_bytes()).hexdigest()
    if digest != MIGRATION_SHA256:
        raise Stop("reviewed migration digest does not match")
    return digest


def assumed_environment() -> dict[str, str]:
    base = os.environ.copy()
    base["AWS_PROFILE"] = "nova-toll-prod"
    account = command(
        ["aws", "sts", "get-caller-identity", "--query", "Account", "--output", "text"],
        env=base,
    )
    region = command(["aws", "configure", "get", "region"], env=base)
    if account != ACCOUNT or region != REGION:
        raise Stop("operator profile has the wrong AWS account or region")
    raw = command(
        [
            "aws",
            "sts",
            "assume-role",
            "--role-arn",
            ROLE_ARN,
            "--role-session-name",
            "oracle-migration",
            "--duration-seconds",
            "900",
            "--query",
            "Credentials",
            "--output",
            "json",
        ],
        env=base,
    )
    try:
        credentials = json.loads(raw)
        access_key = credentials["AccessKeyId"]
        secret_key = credentials["SecretAccessKey"]
        session_token = credentials["SessionToken"]
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise Stop("MFA-gated migrator role assumption failed") from error
    if not all(
        isinstance(value, str) and value
        for value in (access_key, secret_key, session_token)
    ):
        raise Stop("MFA-gated migrator role returned invalid credentials")
    return {
        **base,
        "AWS_ACCESS_KEY_ID": access_key,
        "AWS_SECRET_ACCESS_KEY": secret_key,
        "AWS_SESSION_TOKEN": session_token,
        "AWS_DEFAULT_REGION": REGION,
    }


def rds_target(env: dict[str, str], production: bool) -> str:
    raw = command(
        [
            "aws",
            "rds",
            "describe-db-instances",
            "--db-instance-identifier",
            RDS_IDENTIFIER,
            "--region",
            REGION,
            "--output",
            "json",
        ],
        env=env,
    )
    try:
        instance = json.loads(raw)["DBInstances"][0]
        endpoint = instance["Endpoint"]["Address"]
        valid = (
            instance["DBInstanceIdentifier"] == RDS_IDENTIFIER
            and instance["DbiResourceId"] == RDS_RESOURCE_ID
            and instance["PubliclyAccessible"] is False
            and instance["IAMDatabaseAuthenticationEnabled"] is True
            and isinstance(endpoint, str)
            and endpoint.endswith(".rds.amazonaws.com")
        )
        addresses = {item[4][0] for item in socket.getaddrinfo(endpoint, 5432)}
        private_route = bool(addresses) and all(
            ipaddress.ip_address(address) in ipaddress.ip_network("172.31.0.0/16")
            for address in addresses
        )
        valid = valid and private_route
        if production:
            restorable = datetime.fromisoformat(
                str(instance["LatestRestorableTime"]).replace("Z", "+00:00")
            )
            valid = (
                valid
                and instance["DBInstanceStatus"] == "available"
                and int(instance["BackupRetentionPeriod"]) >= 7
                and restorable <= datetime.now(UTC)
                and datetime.now(UTC) - restorable < timedelta(hours=1)
            )
    except (
        KeyError,
        IndexError,
        OSError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ) as error:
        raise Stop("RDS target verification failed") from error
    if not valid:
        raise Stop("RDS target is not the reviewed private migration target")
    return endpoint


def psql(
    env: dict[str, str],
    database: str,
    user: str,
    host: str,
    sql: str | None = None,
    file: Path | None = None,
) -> str:
    token = command(
        [
            "aws",
            "rds",
            "generate-db-auth-token",
            "--hostname",
            host,
            "--port",
            "5432",
            "--username",
            user,
            "--region",
            REGION,
        ],
        env=env,
    )
    if not token:
        raise Stop("IAM database token generation failed")
    connection = {
        **env,
        "PGHOST": host,
        "PGPORT": "5432",
        "PGDATABASE": database,
        "PGUSER": user,
        "PGPASSWORD": token,
        "PGSSLMODE": "verify-full",
        "PGSSLROOTCERT": str(CA_BUNDLE),
    }
    args = ["psql", "-X", "--set", "ON_ERROR_STOP=1", "--tuples-only", "--no-align"]
    if sql is not None:
        args.extend(["--command", sql])
    if file is not None:
        owner = OWNERS[user]
        args = [
            "psql",
            "-X",
            "--set",
            "ON_ERROR_STOP=1",
            "--command",
            f"SET ROLE {owner}",
            "--file",
            str(file),
        ]
    return command(args, env=connection)


def database_state(
    env: dict[str, str], database: str, user: str, host: str
) -> tuple[str, str, int, int]:
    row = psql(
        env,
        database,
        user,
        host,
        "SELECT (SELECT version FROM oracle.schema_version WHERE singleton), (SELECT version FROM pricing.schema_version WHERE singleton), (SELECT count(*) FROM oracle.toll_connection), (SELECT count(*) FROM oracle.toll_connection WHERE connection_id = 'i495_1829_to_dulles_toll_road');",
    )
    try:
        oracle, pricing, connections, handoffs = row.split("|")
        return oracle, pricing, int(connections), int(handoffs)
    except ValueError as error:
        raise Stop("database version verification failed") from error


def verify_identity(env: dict[str, str], database: str, user: str, host: str) -> None:
    owner = OWNERS[user]
    row = psql(
        env,
        database,
        user,
        host,
        "SELECT current_user, "
        "(SELECT string_agg(granted.rolname, ',' ORDER BY granted.rolname) "
        "FROM pg_auth_members membership JOIN pg_roles granted ON granted.oid = membership.roleid "
        "WHERE membership.member = (SELECT oid FROM pg_roles WHERE rolname = current_user)), "
        "rolcanlogin, rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls, "
        "has_database_privilege(current_user, current_database(), 'CONNECT'), "
        "has_database_privilege(current_user, CASE current_database() WHEN 'nova_toll' THEN 'nova_toll_development' ELSE 'nova_toll' END, 'CONNECT');",
    )
    try:
        (
            current,
            memberships,
            login,
            superuser,
            createdb,
            createrole,
            replication,
            bypassrls,
            own_connect,
            other_connect,
        ) = row.split("|")
    except ValueError as error:
        raise Stop("migrator identity verification failed") from error
    if (
        current != user
        or memberships != f"{owner},rds_iam"
        or login != "t"
        or any(
            value != "f"
            for value in (superuser, createdb, createrole, replication, bypassrls)
        )
        or own_connect != "t"
        or other_connect != "f"
    ):
        raise Stop("migrator identity is not the reviewed isolated login")


def require_state(state: tuple[str, str, int, int], *, before: bool) -> None:
    oracle, pricing, connections, handoffs = state
    expected = SOURCE if before else TARGET
    if (
        oracle != expected
        or pricing != PRICING
        or (not before and (connections != 996 or handoffs != 1))
    ):
        raise Stop(
            "database schema/data precondition failed"
            if before
            else "database migration postcondition failed"
        )


def evidence_directory(environment: str, commit: str) -> Path:
    EVIDENCE_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    if EVIDENCE_ROOT.is_symlink():
        raise Stop("evidence root is unsafe")
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    destination = EVIDENCE_ROOT / f"{environment}-{stamp}-{commit[:12]}"
    if destination.exists() or destination.is_symlink():
        raise Stop("migration evidence destination already exists")
    return destination


def read_development_evidence(commit: str, digest: str) -> None:
    if (
        not EVIDENCE_ROOT.is_dir()
        or EVIDENCE_ROOT.is_symlink()
        or EVIDENCE_ROOT.stat().st_mode & 0o022
    ):
        raise Stop("immutable development evidence is missing")
    candidates: list[Path] = []
    for path in EVIDENCE_ROOT.iterdir():
        if path.is_symlink() or not path.is_dir() or (path.stat().st_mode & 0o222):
            continue
        record = path / "migration.txt"
        manifest = path / "i395-evals.txt"
        reports = (path / "current.json", path / "annual.json")
        if (
            record.is_file()
            and manifest.is_file()
            and not record.stat().st_mode & 0o222
            and not manifest.stat().st_mode & 0o222
            and all(report.is_file() and not report.is_symlink() for report in reports)
            and not record.is_symlink()
            and not manifest.is_symlink()
        ):
            try:
                record_values = parse_record(record)
                manifest_values = parse_record(manifest)
                validate_eval_report(
                    reports[0], "leesburg-to-washington-i395-current-price"
                )
                validate_eval_report(
                    reports[1], "leesburg-to-washington-i395-job-offer"
                )
            except Stop:
                continue
            expected = record_values | {
                "schema_label": "oracle-1.14.0",
                "current_case": "leesburg-to-washington-i395-current-price",
                "current_pass": "true",
                "annual_case": "leesburg-to-washington-i395-job-offer",
                "annual_pass": "true",
                "current_report_sha256": sha256(reports[0]),
                "annual_report_sha256": sha256(reports[1]),
            }
            if (
                set(record_values) == MIGRATION_RECORD_KEYS
                and record_values["environment"] == "development"
                and record_values["commit"] == commit
                and record_values["migration_sha256"] == digest
                and manifest_values == expected
            ):
                candidates.append(path)
    if len(candidates) != 1:
        raise Stop("exact immutable development migration/eval evidence is required")


def validate_eval_report(path: Path, case: str) -> None:
    try:
        report: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        cases = cast(list[dict[str, Any]], report["cases"])
        results = cast(list[list[dict[str, Any]]], report["detailed_results"])
        position = next(
            index for index, item in enumerate(cases) if item["name"] == case
        )
        result = results[position]
        if len(result) != 1:
            raise ValueError
        passed = result[0]["test_pass"]
    except (
        KeyError,
        StopIteration,
        IndexError,
        TypeError,
        json.JSONDecodeError,
    ) as error:
        raise Stop("I-395 evaluation report is invalid") from error
    if passed is not True:
        raise Stop("I-395 evaluation did not pass")


def capture_eval(case: str, window: str, suite: str) -> Path:
    if os.environ.get("DB_HOST") or os.environ.get("DB_PORT"):
        raise Stop("development evaluations refuse ambient database targets")
    host = rds_target(
        {**os.environ, "AWS_PROFILE": "nova-toll-prod", "AWS_DEFAULT_REGION": REGION},
        False,
    )
    results = V2_ROOT / "eval/results"
    before = set(results.glob("*.json"))
    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in {"DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "PRICING_DB_USER"}
    }
    command(
        [
            "uv",
            "run",
            "python",
            "eval/run_evaluation.py",
            "--window",
            window,
            "--suite",
            suite,
        ],
        env={
            **environment,
            "AWS_PROFILE": "nova-toll-prod",
            "AWS_DEFAULT_REGION": REGION,
            "DB_NAME": "nova_toll_development",
            "DB_HOST": host,
            "DB_PORT": "5432",
            "DB_USER": "tollchat_agent_development",
            "PRICING_DB_USER": "pricing_caller_development",
            "DB_CA_BUNDLE_PATH": str(CA_BUNDLE),
        },
    )
    created = set(results.glob("*.json")) - before
    if len(created) != 1:
        raise Stop("evaluation did not produce exactly one report")
    report = created.pop()
    validate_eval_report(report, case)
    return report


def write_evidence(
    destination: Path,
    values: dict[str, str],
    *,
    immutable: bool = True,
) -> None:
    if (
        destination.exists()
        or destination.is_symlink()
        or destination.parent != EVIDENCE_ROOT
    ):
        raise Stop("migration evidence destination already exists or is unsafe")
    temporary = Path(tempfile.mkdtemp(prefix=".migration-", dir=EVIDENCE_ROOT))
    try:
        (temporary / "migration.txt").write_text(
            "".join(f"{key}={value}\n" for key, value in values.items()),
            encoding="utf-8",
        )
        if immutable:
            for item in temporary.iterdir():
                item.chmod(0o400)
            temporary.chmod(0o500)
        else:
            temporary.chmod(0o700)
        temporary.rename(destination)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1 or argv[0] not in ENVIRONMENTS:
        print(
            "usage: deploy_oracle_migration.py {development|production}",
            file=sys.stderr,
        )
        return 2
    try:
        environment = argv[0]
        require_tools()
        commit = checked_main()
        digest = migration_digest()
        if environment == "production":
            read_development_evidence(commit, digest)
        aws_env = assumed_environment()
        database, user = ENVIRONMENTS[environment]
        host = rds_target(aws_env, environment == "production")
        verify_identity(aws_env, database, user, host)
        before = database_state(aws_env, database, user, host)
        if before[0] == TARGET:
            require_state(before, before=False)
            after = before
        else:
            require_state(before, before=True)
            psql(aws_env, database, user, host, file=MIGRATION)
            after = database_state(aws_env, database, user, host)
            require_state(after, before=False)
        destination = evidence_directory(environment, commit)
        values = {
            "environment": environment,
            "commit": commit,
            "timestamp_utc": datetime.now(UTC).isoformat(),
            "migration": MIGRATION.name,
            "migration_sha256": digest,
            "rds_identifier": RDS_IDENTIFIER,
            "rds_resource_id": RDS_RESOURCE_ID,
            "oracle_before": before[0],
            "pricing_before": before[1],
            "oracle_after": after[0],
            "pricing_after": after[1],
            "connections": str(after[2]),
            "handoffs": str(after[3]),
        }
        write_evidence(destination, values, immutable=environment == "production")
        print(f"{environment} migration verified; evidence: {destination}")
        return 0
    except Stop as error:
        print(f"migration stopped: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
