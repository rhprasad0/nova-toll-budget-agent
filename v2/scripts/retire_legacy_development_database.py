#!/usr/bin/env python3
"""Fail-closed, one-shot retirement of the legacy development database."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import NoReturn, cast

PRODUCTION_DATABASE = "nova_toll"
DEVELOPMENT_DATABASE = "nova_toll_development"
PRODUCTION_ROLES = (
    "pricing_loader_writer",
    "pricing_reader",
    "oracle_owner",
    "tollchat_agent",
    "pricing_caller",
    "report_publisher",
)
DEVELOPMENT_ROLES = (
    "pricing_loader_writer_development",
    "pricing_reader_development",
    "oracle_owner_development",
    "tollchat_agent_development",
    "pricing_caller_development",
    "report_publisher_development",
)
HOST_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]*[.]rds[.]amazonaws[.]com$")
PRODUCTION_ACCOUNT = "920534282028"
PRODUCTION_REGION = "us-east-1"
PRODUCTION_PROFILE = "nova-toll-prod"
DB_INSTANCE = "nova-toll-db"
HANDOFF_MANIFEST = "legacy-db-handoff-v1"
APPROVED_EXTENSIONS = ("plpgsql", "postgis")
RUNBOOK_HANDOFF_APPROVED = "YES"
RUNBOOK_CREDENTIALS_ENV = (
    "RETIRE_LEGACY_DB_USER",
    "RETIRE_LEGACY_DB_PASSWORD",
)
AWS_CREDENTIAL_ENV = {
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "AWS_SECURITY_TOKEN",
}
SECRET_ARN_PATTERN = re.compile(
    r"^arn:aws:secretsmanager:us-east-1:920534282028:secret:[^\s]+$"
)
APPROVED_CA_SHA256 = "e5bb2084ccf45087bda1c9bffdea0eb15ee67f0b91646106e466714f9de3c7e3"


def _sql_list(values: tuple[str, ...]) -> str:
    return ", ".join("'" + value + "'" for value in values)


def _missing_connect_grants(roles: tuple[str, ...], database: str) -> str:
    return " OR ".join(
        f"NOT has_database_privilege('{role}', '{database}', 'CONNECT')"
        for role in roles
    )


APP_ROLES = PRODUCTION_ROLES + DEVELOPMENT_ROLES
REVIEWED_RDS_IAM_MEMBERS = tuple(
    role
    for role in APP_ROLES
    if role not in ("oracle_owner", "oracle_owner_development")
)


def _unexpected_app_membership(roles: tuple[str, ...]) -> str:
    return f"""EXISTS (
    SELECT 1 FROM pg_auth_members membership
    JOIN pg_roles member_role ON member_role.oid = membership.member
    JOIN pg_roles granted_role ON granted_role.oid = membership.roleid
    WHERE (member_role.rolname IN ({_sql_list(roles)})
       OR granted_role.rolname IN ({_sql_list(roles)}))
      AND NOT (member_role.rolname IN ({_sql_list(REVIEWED_RDS_IAM_MEMBERS)})
               AND granted_role.rolname = 'rds_iam')
  )"""


PREFLIGHT_SQL = f"""
DO $$
DECLARE
  production_oid oid;
  development_oid oid;
BEGIN
  IF current_database() <> 'postgres' THEN
    RAISE EXCEPTION 'retirement requires the postgres maintenance database';
  END IF;
  SELECT oid INTO production_oid FROM pg_database WHERE datname = '{PRODUCTION_DATABASE}';
  SELECT oid INTO development_oid FROM pg_database WHERE datname = '{DEVELOPMENT_DATABASE}';
  IF production_oid IS NULL OR development_oid IS NULL THEN
    RAISE EXCEPTION 'exact production and development databases are required';
  END IF;
  IF obj_description(production_oid, 'pg_database') IS DISTINCT FROM 'environment=production'
     OR obj_description(development_oid, 'pg_database') IS DISTINCT FROM 'environment=development' THEN
    RAISE EXCEPTION 'database environment comments are wrong';
  END IF;
  IF (SELECT datdba FROM pg_database WHERE oid = production_oid)
       <> (SELECT datdba FROM pg_database WHERE oid = development_oid) THEN
    RAISE EXCEPTION 'database ownership is not the reviewed shared owner';
  END IF;
  IF (SELECT count(*) FROM pg_roles WHERE rolname IN ({_sql_list(PRODUCTION_ROLES)})) <> 6
     OR (SELECT count(*) FROM pg_roles WHERE rolname IN ({_sql_list(DEVELOPMENT_ROLES)})) <> 6 THEN
    RAISE EXCEPTION 'exact production and development roles are required';
  END IF;
  IF EXISTS (
    SELECT 1 FROM pg_roles
    WHERE rolname IN ({_sql_list(DEVELOPMENT_ROLES)})
      AND shobj_description(oid, 'pg_authid') IS DISTINCT FROM 'environment=development'
  ) THEN
    RAISE EXCEPTION 'development role environment comments are wrong';
  END IF;
  IF {_missing_connect_grants(PRODUCTION_ROLES, PRODUCTION_DATABASE)}
     OR {_missing_connect_grants(DEVELOPMENT_ROLES, DEVELOPMENT_DATABASE)} THEN
    RAISE EXCEPTION 'required database CONNECT grant is missing';
  END IF;
  IF EXISTS (
    SELECT 1 FROM pg_roles
    WHERE rolname LIKE '%\\_development' ESCAPE '\\'
      AND rolname NOT IN ({_sql_list(DEVELOPMENT_ROLES)})
  ) THEN
    RAISE EXCEPTION 'unexpected development role exists';
  END IF;
  IF EXISTS (
    SELECT 1 FROM pg_roles
    WHERE rolname = 'oracle_owner'
      AND (rolcanlogin OR rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls)
  ) OR EXISTS (
    SELECT 1 FROM pg_roles
    WHERE rolname IN ('pricing_loader_writer', 'pricing_reader', 'tollchat_agent', 'pricing_caller', 'report_publisher')
      AND (NOT rolcanlogin OR rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls)
  ) OR EXISTS (
    SELECT 1 FROM pg_roles
    WHERE rolname = 'oracle_owner_development'
      AND (rolcanlogin OR rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls)
  ) OR EXISTS (
    SELECT 1 FROM pg_roles
    WHERE rolname IN ('pricing_loader_writer_development', 'pricing_reader_development', 'tollchat_agent_development', 'pricing_caller_development', 'report_publisher_development')
      AND (NOT rolcanlogin OR rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls)
  ) THEN
    RAISE EXCEPTION 'role attributes are outside the reviewed contract';
  END IF;
  IF {_unexpected_app_membership(APP_ROLES)} THEN
    RAISE EXCEPTION 'role membership is outside the reviewed contract';
  END IF;
  IF NOT pg_has_role('pricing_loader_writer', 'rds_iam', 'MEMBER')
     OR NOT pg_has_role('pricing_reader', 'rds_iam', 'MEMBER')
     OR NOT pg_has_role('tollchat_agent', 'rds_iam', 'MEMBER')
     OR NOT pg_has_role('pricing_caller', 'rds_iam', 'MEMBER')
     OR NOT pg_has_role('report_publisher', 'rds_iam', 'MEMBER')
     OR NOT pg_has_role('pricing_loader_writer_development', 'rds_iam', 'MEMBER')
     OR NOT pg_has_role('pricing_reader_development', 'rds_iam', 'MEMBER')
     OR NOT pg_has_role('tollchat_agent_development', 'rds_iam', 'MEMBER')
     OR NOT pg_has_role('pricing_caller_development', 'rds_iam', 'MEMBER')
     OR NOT pg_has_role('report_publisher_development', 'rds_iam', 'MEMBER') THEN
    RAISE EXCEPTION 'required rds_iam membership is missing';
  END IF;
  IF EXISTS (
    SELECT 1 FROM pg_database database, LATERAL aclexplode(database.datacl) privilege
    WHERE database.datname = '{PRODUCTION_DATABASE}' AND privilege.privilege_type = 'CONNECT'
      AND privilege.grantee <> database.datdba
      AND privilege.grantee NOT IN (to_regrole('pricing_loader_writer'), to_regrole('pricing_reader'), to_regrole('oracle_owner'),
        to_regrole('tollchat_agent'), to_regrole('pricing_caller'), to_regrole('report_publisher'))
  ) OR EXISTS (
    SELECT 1 FROM pg_database database, LATERAL aclexplode(database.datacl) privilege
    WHERE database.datname = '{DEVELOPMENT_DATABASE}' AND privilege.privilege_type = 'CONNECT'
      AND privilege.grantee <> database.datdba
      AND privilege.grantee NOT IN (to_regrole('pricing_loader_writer_development'), to_regrole('pricing_reader_development'), to_regrole('oracle_owner_development'),
        to_regrole('tollchat_agent_development'), to_regrole('pricing_caller_development'), to_regrole('report_publisher_development'))
  ) THEN
    RAISE EXCEPTION 'database has unexpected CONNECT grantee';
  END IF;
  IF EXISTS (SELECT 1 FROM pg_database WHERE datname = '{PRODUCTION_DATABASE}' AND has_database_privilege('pricing_loader_writer_development', datname, 'CONNECT'))
     OR EXISTS (SELECT 1 FROM pg_database WHERE datname = '{DEVELOPMENT_DATABASE}' AND has_database_privilege('pricing_loader_writer', datname, 'CONNECT')) THEN
    RAISE EXCEPTION 'production and development database isolation is broken';
  END IF;
  IF EXISTS (
    SELECT 1 FROM pg_shdepend dependency
    WHERE dependency.dbid = 0 AND dependency.classid = 'pg_database'::regclass
      AND dependency.objid = development_oid
      AND dependency.refobjid <> (SELECT datdba FROM pg_database WHERE oid = development_oid)
  ) THEN
    RAISE EXCEPTION 'development database has an unexpected shared dependency';
  END IF;
END $$;
"""

DEVELOPMENT_PREFLIGHT_SQL = """
DO $$
DECLARE
  database_owner name;
BEGIN
  SELECT pg_get_userbyid(datdba) INTO database_owner
  FROM pg_database WHERE datname = current_database();
  IF (SELECT count(*) FROM pg_namespace WHERE nspname = 'pricing') <> 1
     OR (SELECT nspowner::regrole::name FROM pg_namespace WHERE nspname = 'pricing') <> database_owner
     OR (SELECT count(*) FROM pg_namespace WHERE nspname = 'oracle') <> 1
     OR (SELECT nspowner::regrole::name FROM pg_namespace WHERE nspname = 'oracle') <> 'oracle_owner_development' THEN
    RAISE EXCEPTION 'development schema ownership is outside the reviewed baseline';
  END IF;
  IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast', 'public', 'pricing', 'oracle'))
     OR EXISTS (SELECT 1 FROM pg_class WHERE relnamespace IN (
       SELECT oid FROM pg_namespace WHERE nspname IN ('pricing', 'oracle')
     ) AND relowner NOT IN ((SELECT datdba FROM pg_database WHERE datname = current_database()), to_regrole('oracle_owner_development'), to_regrole('pricing_loader_writer_development'),
       to_regrole('pricing_reader_development'), to_regrole('tollchat_agent_development'), to_regrole('pricing_caller_development'),
       to_regrole('report_publisher_development'))) THEN
    RAISE EXCEPTION 'development database has unexpected object ownership';
  END IF;
  IF (SELECT coalesce(array_agg(extname ORDER BY extname), ARRAY[]::name[])
      FROM pg_extension) <> ARRAY['plpgsql'::name, 'postgis'::name]
     OR (SELECT extnamespace::regnamespace::name FROM pg_extension WHERE extname = 'postgis') <> 'oracle' THEN
    RAISE EXCEPTION 'development extension baseline is not exact';
  END IF;
  IF EXISTS (SELECT 1 FROM pg_subscription)
     OR EXISTS (SELECT 1 FROM pg_publication)
     OR EXISTS (SELECT 1 FROM pg_replication_slots)
     OR EXISTS (SELECT 1 FROM pg_foreign_server)
     OR EXISTS (SELECT 1 FROM pg_user_mappings)
     OR EXISTS (SELECT 1 FROM pg_foreign_table)
     OR EXISTS (SELECT 1 FROM pg_foreign_data_wrapper)
     OR EXISTS (SELECT 1 FROM pg_event_trigger)
     OR EXISTS (SELECT 1 FROM pg_publication_rel)
     OR EXISTS (SELECT 1 FROM pg_depend dependency
                WHERE dependency.deptype NOT IN ('n', 'a', 'i', 'e', 'p'))
     OR EXISTS (SELECT 1 FROM pg_shdepend dependency
                WHERE dependency.dbid = 0
                  AND dependency.deptype NOT IN ('a', 'o', 'r'))
     OR EXISTS (SELECT 1 FROM pg_depend dependency
                WHERE dependency.deptype = 'e'
                  AND dependency.refclassid <> 'pg_extension'::regclass) THEN
    RAISE EXCEPTION 'development database has an unreviewed integration or dependency';
  END IF;
END $$;
"""

PRODUCTION_INVARIANTS = f"""
  IF (SELECT obj_description(oid, 'pg_database') FROM pg_database WHERE datname = '{PRODUCTION_DATABASE}') IS DISTINCT FROM 'environment=production'
     OR (SELECT count(*) FROM pg_roles WHERE rolname IN ({_sql_list(PRODUCTION_ROLES)})) <> 6 THEN
    RAISE EXCEPTION 'production database or role contract changed';
  END IF;
  IF EXISTS (
    SELECT 1 FROM pg_roles
    WHERE rolname = 'oracle_owner'
      AND (rolcanlogin OR rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls)
  ) OR EXISTS (
    SELECT 1 FROM pg_roles
    WHERE rolname IN ('pricing_loader_writer', 'pricing_reader', 'tollchat_agent', 'pricing_caller', 'report_publisher')
      AND (NOT rolcanlogin OR rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls)
  ) THEN
    RAISE EXCEPTION 'production role attributes changed';
  END IF;
  IF {_unexpected_app_membership(APP_ROLES)} OR NOT pg_has_role('pricing_loader_writer', 'rds_iam', 'MEMBER')
    OR NOT pg_has_role('pricing_reader', 'rds_iam', 'MEMBER')
    OR NOT pg_has_role('tollchat_agent', 'rds_iam', 'MEMBER')
    OR NOT pg_has_role('pricing_caller', 'rds_iam', 'MEMBER')
    OR NOT pg_has_role('report_publisher', 'rds_iam', 'MEMBER') THEN
    RAISE EXCEPTION 'production role membership changed';
  END IF;
  IF {_missing_connect_grants(PRODUCTION_ROLES, PRODUCTION_DATABASE)} THEN
    RAISE EXCEPTION 'production database CONNECT grant is missing';
  END IF;
  IF EXISTS (
    SELECT 1 FROM pg_database database, LATERAL aclexplode(database.datacl) privilege
    WHERE database.datname = '{PRODUCTION_DATABASE}' AND privilege.privilege_type = 'CONNECT'
      AND privilege.grantee <> database.datdba
      AND privilege.grantee NOT IN (to_regrole('pricing_loader_writer'), to_regrole('pricing_reader'), to_regrole('oracle_owner'),
        to_regrole('tollchat_agent'), to_regrole('pricing_caller'), to_regrole('report_publisher'))
  ) THEN
    RAISE EXCEPTION 'production database CONNECT contract changed';
  END IF;
"""

POST_DATABASE_SQL = f"""
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_database WHERE datname = '{DEVELOPMENT_DATABASE}')
     OR NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = '{PRODUCTION_DATABASE}') THEN
    RAISE EXCEPTION 'database postcondition failed';
  END IF;
{PRODUCTION_INVARIANTS}
END $$;
"""

POST_ROLE_SQL = f"""
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_database WHERE datname = '{DEVELOPMENT_DATABASE}')
     OR NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = '{PRODUCTION_DATABASE}')
     OR EXISTS (SELECT 1 FROM pg_roles WHERE rolname IN ({{dropped}}))
     OR (SELECT count(*) FROM pg_roles WHERE rolname IN ({{remaining}})) <> {{remaining_count}}
     OR EXISTS (
       SELECT 1 FROM pg_roles
       WHERE rolname LIKE '%\\_development' ESCAPE '\\'
         AND rolname NOT IN ({_sql_list(DEVELOPMENT_ROLES)})
     ) THEN
    RAISE EXCEPTION 'role postcondition failed';
  END IF;
{PRODUCTION_INVARIANTS}
END $$;
"""

ROLE_DEPENDENCY_SQL = """
DO $$
DECLARE
  target_role oid := to_regrole('{role}');
BEGIN
  IF target_role IS NULL THEN
    RAISE EXCEPTION 'exact development role is missing';
  END IF;
  IF EXISTS (
    SELECT 1 FROM pg_auth_members
    WHERE member = target_role AND roleid <> to_regrole('rds_iam')
  ) THEN
    RAISE EXCEPTION 'development role has an unexpected membership';
  END IF;
  IF EXISTS (
    SELECT 1 FROM pg_shdepend
    WHERE refobjid = target_role AND dbid <> 0
  ) THEN
    RAISE EXCEPTION 'development role has a dependency in another database';
  END IF;
  IF EXISTS (
    SELECT 1 FROM pg_shdepend
    WHERE refobjid = target_role AND dbid = 0 AND deptype NOT IN ('a', 'o')
  ) THEN
    RAISE EXCEPTION 'development role has an unexpected shared dependency';
  END IF;
END $$;
"""

FINAL_SQL = f"""
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_database WHERE datname = '{DEVELOPMENT_DATABASE}')
     OR EXISTS (SELECT 1 FROM pg_roles WHERE rolname IN ({_sql_list(DEVELOPMENT_ROLES)}))
     OR NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = '{PRODUCTION_DATABASE}')
     OR (SELECT obj_description(oid, 'pg_database') FROM pg_database WHERE datname = '{PRODUCTION_DATABASE}') IS DISTINCT FROM 'environment=production'
     OR (SELECT count(*) FROM pg_roles WHERE rolname IN ({_sql_list(PRODUCTION_ROLES)})) <> 6 THEN
    RAISE EXCEPTION 'final production-preservation check failed';
  END IF;
{PRODUCTION_INVARIANTS}
END $$;
"""


class RetirementError(Exception):
    """A preflight or postcondition failed without exposing command output."""


CONTRACT_SHA256 = hashlib.sha256(
    (
        PRODUCTION_DATABASE
        + "\0"
        + DEVELOPMENT_DATABASE
        + "\0"
        + "\0".join(DEVELOPMENT_ROLES)
    ).encode()
).hexdigest()


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise RetirementError


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(add_help=True)
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--ca-file", required=True)
    parser.add_argument("--handoff", required=True)
    parser.add_argument("--execute", action="store_true")
    return parser


def _validate_connection(
    host: str, port: int, ca_file: str, handoff: str
) -> tuple[Path, dict[str, object]]:
    if not HOST_PATTERN.fullmatch(host) or not 1 <= port <= 65535:
        raise RetirementError
    path = Path(ca_file)
    if not path.is_absolute() or not path.is_file() or path.is_symlink():
        raise RetirementError
    handoff_path = Path(handoff)
    if (
        not handoff_path.is_absolute()
        or not handoff_path.is_file()
        or handoff_path.is_symlink()
    ):
        raise RetirementError
    try:
        document = json.loads(handoff_path.read_text(encoding="utf-8"))
        ca_digest = hashlib.sha256(path.read_bytes()).hexdigest()
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise RetirementError from None
    if not isinstance(document, dict):
        raise RetirementError
    document = cast(dict[str, object], document)
    if set(document) != {
        "manifest",
        "account_id",
        "region",
        "instance_identifier",
        "host",
        "port",
        "ca_sha256",
        "secret_arn",
    }:
        raise RetirementError
    manifest = document.get("manifest")
    account_id = document.get("account_id")
    region = document.get("region")
    instance_identifier = document.get("instance_identifier")
    document_host = document.get("host")
    document_port = document.get("port")
    ca_sha256 = document.get("ca_sha256")
    secret_arn = document.get("secret_arn")
    if (
        manifest != HANDOFF_MANIFEST
        or account_id != PRODUCTION_ACCOUNT
        or region != PRODUCTION_REGION
        or instance_identifier != DB_INSTANCE
        or document_host != host
        or isinstance(document_port, bool)
        or not isinstance(document_port, int)
        or document_port != port
        or not isinstance(ca_sha256, str)
        or not re.fullmatch(r"[0-9a-f]{64}", ca_sha256)
        or ca_sha256 != APPROVED_CA_SHA256
        or not isinstance(secret_arn, str)
        or not SECRET_ARN_PATTERN.fullmatch(secret_arn)
        or ca_digest != APPROVED_CA_SHA256
        or ca_sha256 != ca_digest
    ):
        raise RetirementError
    return path, document


def _aws_environment() -> dict[str, str]:
    for key, expected in (
        ("AWS_PROFILE", PRODUCTION_PROFILE),
        ("AWS_DEFAULT_REGION", PRODUCTION_REGION),
        ("AWS_REGION", PRODUCTION_REGION),
    ):
        if os.environ.get(key) not in (None, expected):
            raise RetirementError
    if any(key in os.environ for key in AWS_CREDENTIAL_ENV):
        raise RetirementError
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("AWS_")
        and not key.startswith("PG")
        and key not in AWS_CREDENTIAL_ENV
        and key not in RUNBOOK_CREDENTIALS_ENV
    }
    environment.update(
        {
            "AWS_PROFILE": PRODUCTION_PROFILE,
            "AWS_DEFAULT_REGION": PRODUCTION_REGION,
            "AWS_REGION": PRODUCTION_REGION,
        }
    )
    return environment


def _aws_output(arguments: list[str]) -> str | None:
    try:
        result = subprocess.run(
            [
                "aws",
                "--profile",
                PRODUCTION_PROFILE,
                "--region",
                PRODUCTION_REGION,
                *arguments,
            ],
            text=True,
            capture_output=True,
            check=False,
            env=_aws_environment(),
            timeout=60,
        )
    except (OSError, RetirementError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout


def _verify_live_rds(handoff: dict[str, object]) -> tuple[str, int] | None:
    account = _aws_output(
        ["sts", "get-caller-identity", "--query", "Account", "--output", "text"]
    )
    if account is None or account.strip() != PRODUCTION_ACCOUNT:
        return None
    response = _aws_output(
        [
            "rds",
            "describe-db-instances",
            "--db-instance-identifier",
            DB_INSTANCE,
            "--query",
            "DBInstances",
            "--output",
            "json",
        ]
    )
    if response is None:
        return None
    try:
        instances = json.loads(response)
    except (TypeError, ValueError):
        return None
    if not isinstance(instances, list):
        return None
    instances = cast(list[object], instances)
    if len(instances) != 1:
        return None
    instance = instances[0]
    if not isinstance(instance, dict):
        return None
    instance = cast(dict[str, object], instance)
    endpoint = instance.get("Endpoint")
    secret = instance.get("MasterUserSecret")
    if not isinstance(endpoint, dict) or not isinstance(secret, dict):
        return None
    endpoint = cast(dict[str, object], endpoint)
    secret = cast(dict[str, object], secret)
    endpoint_address = endpoint.get("Address")
    endpoint_port = endpoint.get("Port")
    secret_arn = secret.get("SecretArn")
    if (
        instance.get("DBInstanceIdentifier") != DB_INSTANCE
        or instance.get("DBInstanceStatus") != "available"
        or instance.get("PubliclyAccessible") is not False
        or not isinstance(endpoint_address, str)
        or endpoint_address != handoff.get("host")
        or isinstance(endpoint_port, bool)
        or not isinstance(endpoint_port, int)
        or endpoint_port != handoff.get("port")
        or not isinstance(secret_arn, str)
        or secret_arn != handoff.get("secret_arn")
        or not SECRET_ARN_PATTERN.fullmatch(secret_arn)
    ):
        return None
    return endpoint_address, endpoint_port


def _psql(
    host: str, port: int, ca_file: Path, sql: str, database: str = "postgres"
) -> bool:
    credentials = {
        key: os.environ[key] for key in RUNBOOK_CREDENTIALS_ENV if os.environ.get(key)
    }
    if set(credentials) != set(RUNBOOK_CREDENTIALS_ENV):
        return False
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("PG") and key not in RUNBOOK_CREDENTIALS_ENV
    }
    environment.update(
        {
            "PGUSER": credentials["RETIRE_LEGACY_DB_USER"],
            "PGPASSWORD": credentials["RETIRE_LEGACY_DB_PASSWORD"],
            "PGHOST": host,
            "PGPORT": str(port),
            "PGSSLMODE": "verify-full",
            "PGSSLROOTCERT": str(ca_file),
            "PGDATABASE": database,
        }
    )
    command = [
        "psql",
        "-X",
        "--set",
        "ON_ERROR_STOP=1",
        "--dbname",
        database,
        "--tuples-only",
        "--no-align",
        "--quiet",
    ]
    try:
        result = subprocess.run(
            command,
            input=sql,
            text=True,
            capture_output=True,
            check=False,
            env=environment,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def _status(host: str, port: int, ca_file: Path, sql: str = POST_DATABASE_SQL) -> bool:
    return _psql(host, port, ca_file, sql)


def _mutate(
    host: str, port: int, ca_file: Path, sql: str, status_sql: str = POST_DATABASE_SQL
) -> bool:
    if _psql(host, port, ca_file, sql):
        return True
    _status(host, port, ca_file, status_sql)
    raise RetirementError


def _role_postcondition(index: int) -> str:
    dropped = _sql_list(DEVELOPMENT_ROLES[: index + 1]) or "''"
    remaining_roles = DEVELOPMENT_ROLES[index + 1 :]
    remaining = _sql_list(remaining_roles) or "''"
    return POST_ROLE_SQL.format(
        dropped=dropped,
        remaining=remaining,
        remaining_count=len(remaining_roles),
    )


def retire(host: str, port: int, ca_file: Path, execute: bool) -> None:
    if not _psql(host, port, ca_file, PREFLIGHT_SQL):
        raise RetirementError
    if not _psql(host, port, ca_file, DEVELOPMENT_PREFLIGHT_SQL, DEVELOPMENT_DATABASE):
        raise RetirementError
    if not execute:
        return
    _mutate(
        host,
        port,
        ca_file,
        f"DROP DATABASE {DEVELOPMENT_DATABASE} WITH (FORCE);",
    )
    if not _psql(host, port, ca_file, POST_DATABASE_SQL):
        raise RetirementError
    for index, role in enumerate(DEVELOPMENT_ROLES):
        if not _psql(host, port, ca_file, ROLE_DEPENDENCY_SQL.format(role=role)):
            raise RetirementError
        _mutate(
            host,
            port,
            ca_file,
            f"DROP ROLE {role};",
            _role_postcondition(index),
        )
        if not _psql(host, port, ca_file, _role_postcondition(index)):
            raise RetirementError
    if not _psql(host, port, ca_file, FINAL_SQL):
        raise RetirementError


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        ca_file, handoff = _validate_connection(
            args.host, args.port, args.ca_file, args.handoff
        )
        if os.environ.get("RETIRE_LEGACY_HANDOFF_APPROVED") != RUNBOOK_HANDOFF_APPROVED:
            raise RetirementError
        if any(not os.environ.get(name) for name in RUNBOOK_CREDENTIALS_ENV):
            raise RetirementError
        if (
            args.execute
            and os.environ.get("RETIRE_LEGACY_DEVELOPMENT_APPROVED") != "YES"
        ):
            raise RetirementError
        live_target = _verify_live_rds(handoff)
        if live_target is None:
            raise RetirementError
        live_host, live_port = live_target
        if (args.host, args.port) != live_target:
            raise RetirementError
        retire(live_host, live_port, ca_file, args.execute)
    except SystemExit:
        raise
    except (RetirementError, ValueError):
        print("legacy development database retirement stopped", file=sys.stderr)
        return 1
    mode = "execute" if args.execute else "preflight"
    print(
        f"status=pass mode={mode} databases_checked=2 production_roles=6 "
        f"development_roles=6 contract_sha256={CONTRACT_SHA256}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
