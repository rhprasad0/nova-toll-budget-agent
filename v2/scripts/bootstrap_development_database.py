#!/usr/bin/env python3
"""Create the one-time isolated development TollChat database.

The caller supplies an administrator PostgreSQL connection through PG* or
NOVA_TOLL_ADMIN_URL. This program deliberately has no AWS or credential logic.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from contextlib import suppress
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[2]
DATABASES = {"production": "nova_toll", "development": "nova_toll_development"}
ROLES = {
    "production": (
        "pricing_loader_writer",
        "pricing_reader",
        "oracle_owner",
        "tollchat_agent",
        "pricing_caller",
        "report_publisher",
    ),
    "development": (
        "pricing_loader_writer_development",
        "pricing_reader_development",
        "oracle_owner_development",
        "tollchat_agent_development",
        "pricing_caller_development",
        "report_publisher_development",
    ),
}
IDENTIFIER = re.compile(r"[a-z][a-z0-9_]*\Z")


def run(
    *args: str, input: str | None = None, env: dict[str, str] | None = None
) -> None:
    subprocess.run(args, input=input, text=True, check=True, env=env)


def tls_environment(query: str) -> dict[str, str]:
    if not query:
        return {}
    values: dict[str, str] = {}
    try:
        for pair in query.split("&"):
            if not pair or "=" not in pair:
                raise ValueError
            key, value = pair.split("=", 1)
            if re.search(r"%(?![0-9A-Fa-f]{2})", key + value):
                raise ValueError
            key = unquote(key, errors="strict")
            value = unquote(value, errors="strict")
            if (
                not key
                or not value
                or key in values
                or key not in {"sslmode", "sslrootcert"}
            ):
                raise ValueError
            values[key] = value
    except (UnicodeDecodeError, ValueError):
        raise RuntimeError("NOVA_TOLL_ADMIN_URL has invalid TLS settings") from None
    if values.get("sslmode") != "verify-full":
        raise RuntimeError("NOVA_TOLL_ADMIN_URL has invalid TLS settings")
    return {
        "PGSSLMODE": values["sslmode"],
        **({"PGSSLROOTCERT": values["sslrootcert"]} if "sslrootcert" in values else {}),
    }


def psql(database: str, *, sql: str | None = None, file: Path | None = None) -> None:
    admin_url = os.environ.get("NOVA_TOLL_ADMIN_URL")
    command = ["psql", "-X", "--set", "ON_ERROR_STOP=1"]
    if admin_url is not None:
        if not admin_url:
            raise RuntimeError("NOVA_TOLL_ADMIN_URL must not be empty")
        try:
            parsed = urlsplit(admin_url)
        except ValueError:
            raise RuntimeError(
                "NOVA_TOLL_ADMIN_URL must be a PostgreSQL connection URL"
            ) from None
        if (
            parsed.scheme not in ("postgres", "postgresql")
            or not parsed.hostname
            or not parsed.username
            or ("?" in admin_url and not parsed.query)
            or "#" in admin_url
            or "," in parsed.hostname
            or (parsed.path and not re.fullmatch(r"/[A-Za-z0-9_]+", parsed.path))
        ):
            raise RuntimeError(
                "NOVA_TOLL_ADMIN_URL must be a PostgreSQL connection URL"
            )
        try:
            port = parsed.port
        except ValueError:
            raise RuntimeError(
                "NOVA_TOLL_ADMIN_URL must be a PostgreSQL connection URL"
            ) from None
        environment = {
            key: value for key, value in os.environ.items() if not key.startswith("PG")
        }
        environment.update(
            {
                "PGHOST": parsed.hostname,
                "PGUSER": unquote(parsed.username),
                "PGDATABASE": database,
            }
        )
        if parsed.password is not None:
            environment["PGPASSWORD"] = unquote(parsed.password)
        if port is not None:
            environment["PGPORT"] = str(port)
        environment.update(tls_environment(parsed.query))
    else:
        environment = os.environ.copy()
        if not environment.get("PGHOST") or not environment.get("PGUSER"):
            raise RuntimeError("set NOVA_TOLL_ADMIN_URL or both PGHOST and PGUSER")
        command.extend(("--dbname", database))
    if file is not None:
        command.extend(("--file", str(file)))
    run(*command, input=sql, env=environment)


def render(source: Path, destination: Path) -> None:
    replacements = dict(zip(ROLES["production"], ROLES["development"], strict=True))
    pattern = re.compile(r"\b(" + "|".join(map(re.escape, replacements)) + r")\b")
    destination.write_text(
        pattern.sub(lambda match: replacements[match[0]], source.read_text())
    )


def rollback_development() -> None:
    psql(
        "postgres",
        sql=f"""
DROP DATABASE IF EXISTS {DATABASES["development"]} WITH (FORCE);
DROP ROLE IF EXISTS {", ".join(ROLES["development"])};
""",
    )


def main() -> int:
    if len(sys.argv) != 1:
        print("usage: bootstrap_development_database.py", file=sys.stderr)
        return 2
    if any(
        not IDENTIFIER.fullmatch(name) for names in ROLES.values() for name in names
    ):
        raise RuntimeError("bootstrap role map contains an unsafe identifier")
    if len(set(ROLES["production"] + ROLES["development"])) != 12:
        raise RuntimeError("bootstrap role map contains duplicate identifiers")

    dev_roles = ", ".join(repr(role) for role in ROLES["development"])
    psql(
        "postgres",
        sql=f"""
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = '{DATABASES["production"]}') THEN
    RAISE EXCEPTION 'required production database is missing';
  END IF;
  IF EXISTS (SELECT 1 FROM pg_database WHERE datname = '{DATABASES["development"]}') THEN
    RAISE EXCEPTION 'development database already exists';
  END IF;
  IF to_regrole('rds_iam') IS NULL THEN
    RAISE EXCEPTION 'required rds_iam role is missing';
  END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname IN ({dev_roles})) THEN
    RAISE EXCEPTION 'development role already exists';
  END IF;
  IF (SELECT count(*) FROM pg_roles WHERE rolname IN ({", ".join(repr(role) for role in ROLES["production"])})) <> 6 THEN
    RAISE EXCEPTION 'required production role is missing';
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
    RAISE EXCEPTION 'production role has unsafe attributes';
  END IF;
  IF EXISTS (
    SELECT 1 FROM pg_auth_members membership
    JOIN pg_roles member_role ON member_role.oid = membership.member
    JOIN pg_roles granted_role ON granted_role.oid = membership.roleid
    WHERE member_role.rolname IN ('pricing_loader_writer', 'pricing_reader', 'tollchat_agent', 'pricing_caller', 'report_publisher')
      AND granted_role.rolname <> 'rds_iam'
  ) OR EXISTS (
    SELECT 1 FROM pg_auth_members membership JOIN pg_roles member_role ON member_role.oid = membership.member
    WHERE member_role.rolname = 'oracle_owner'
  ) OR NOT pg_has_role('pricing_loader_writer', 'rds_iam', 'MEMBER')
    OR NOT pg_has_role('pricing_reader', 'rds_iam', 'MEMBER')
    OR NOT pg_has_role('tollchat_agent', 'rds_iam', 'MEMBER')
    OR NOT pg_has_role('pricing_caller', 'rds_iam', 'MEMBER')
    OR NOT pg_has_role('report_publisher', 'rds_iam', 'MEMBER')
  THEN
    RAISE EXCEPTION 'production role has unexpected membership';
  END IF;
  IF EXISTS (
    SELECT 1 FROM pg_database database, LATERAL aclexplode(database.datacl) privilege
    WHERE database.datname = 'nova_toll' AND privilege.privilege_type = 'CONNECT'
      AND privilege.grantee NOT IN (0, database.datdba)
      AND privilege.grantee NOT IN (to_regrole('pricing_loader_writer'), to_regrole('pricing_reader'),
        to_regrole('oracle_owner'), to_regrole('tollchat_agent'), to_regrole('pricing_caller'),
        to_regrole('report_publisher'))
  ) THEN
    RAISE EXCEPTION 'production database has unexpected CONNECT grantee';
  END IF;
END $$;
""",
    )

    with tempfile.TemporaryDirectory(prefix="nova-toll-development-") as directory:
        rendered = Path(directory)
        for relative in (
            "v2/db/schema.sql",
            "v2/db/analysis.sql",
            "v2/db/roles.sql",
            "v2/db/oracle/schema.sql",
            "v2/db/oracle/data.sql",
        ):
            source = ROOT / relative
            destination = rendered / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            render(source, destination)
        # schema.sql resolves analysis.sql beside itself via \ir.
        created_development = False
        try:
            psql(
                "postgres",
                sql="CREATE DATABASE nova_toll_development TEMPLATE template0;",
            )
            created_development = True
            psql(DATABASES["development"], file=rendered / "v2/db/schema.sql")
            psql(DATABASES["development"], file=rendered / "v2/db/roles.sql")
            psql(DATABASES["development"], file=rendered / "v2/db/oracle/schema.sql")
            psql(
                DATABASES["development"],
                sql="""
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_foreign_server)
     OR EXISTS (SELECT 1 FROM pg_user_mappings)
     OR EXISTS (SELECT 1 FROM pg_extension WHERE extname IN ('dblink', 'postgres_fdw', 'pg_cron')
                OR extname LIKE 'postgis_%') THEN
    RAISE EXCEPTION 'development database has forbidden integration objects';
  END IF;
END $$;
""",
            )

            prod_roles = ", ".join(ROLES["production"])
            dev_roles_sql = ", ".join(ROLES["development"])
            psql(
                "postgres",
                sql=f"""
BEGIN;
COMMENT ON DATABASE nova_toll IS 'environment=production';
COMMENT ON DATABASE nova_toll_development IS 'environment=development';
COMMENT ON ROLE pricing_loader_writer_development IS 'environment=development';
COMMENT ON ROLE pricing_reader_development IS 'environment=development';
COMMENT ON ROLE oracle_owner_development IS 'environment=development';
COMMENT ON ROLE tollchat_agent_development IS 'environment=development';
COMMENT ON ROLE pricing_caller_development IS 'environment=development';
COMMENT ON ROLE report_publisher_development IS 'environment=development';
REVOKE CONNECT ON DATABASE nova_toll FROM PUBLIC;
REVOKE CONNECT ON DATABASE nova_toll_development FROM PUBLIC;
GRANT CONNECT ON DATABASE nova_toll TO {prod_roles};
GRANT CONNECT ON DATABASE nova_toll_development TO {dev_roles_sql};
DO $$
DECLARE
  role_name text;
  production_roles text[] := ARRAY[{", ".join(repr(role) for role in ROLES["production"])}];
  development_roles text[] := ARRAY[{", ".join(repr(role) for role in ROLES["development"])}];
BEGIN
  IF EXISTS (
    SELECT 1 FROM pg_database database, LATERAL aclexplode(database.datacl) privilege
    WHERE database.datname IN ('nova_toll', 'nova_toll_development')
      AND privilege.grantee = 0 AND privilege.privilege_type = 'CONNECT'
  ) THEN RAISE EXCEPTION 'PUBLIC retains database CONNECT'; END IF;
  IF EXISTS (
    SELECT 1 FROM pg_database database, LATERAL aclexplode(database.datacl) privilege
    WHERE database.datname = 'nova_toll' AND privilege.privilege_type = 'CONNECT'
      AND privilege.grantee <> database.datdba
      AND privilege.grantee NOT IN (to_regrole('pricing_loader_writer'), to_regrole('pricing_reader'),
        to_regrole('oracle_owner'), to_regrole('tollchat_agent'), to_regrole('pricing_caller'),
        to_regrole('report_publisher'))
  ) OR EXISTS (
    SELECT 1 FROM pg_database database, LATERAL aclexplode(database.datacl) privilege
    WHERE database.datname = 'nova_toll_development' AND privilege.privilege_type = 'CONNECT'
      AND privilege.grantee <> database.datdba
      AND privilege.grantee NOT IN (to_regrole('pricing_loader_writer_development'),
        to_regrole('pricing_reader_development'), to_regrole('oracle_owner_development'),
        to_regrole('tollchat_agent_development'), to_regrole('pricing_caller_development'),
        to_regrole('report_publisher_development'))
  ) THEN RAISE EXCEPTION 'database has unexpected CONNECT grantee'; END IF;
  FOREACH role_name IN ARRAY production_roles LOOP
    IF NOT has_database_privilege(role_name, 'nova_toll', 'CONNECT')
       OR has_database_privilege(role_name, 'nova_toll_development', 'CONNECT') THEN
      RAISE EXCEPTION 'production role % has wrong database CONNECT', role_name;
    END IF;
  END LOOP;
  FOREACH role_name IN ARRAY development_roles LOOP
    IF NOT has_database_privilege(role_name, 'nova_toll_development', 'CONNECT')
       OR has_database_privilege(role_name, 'nova_toll', 'CONNECT') THEN
      RAISE EXCEPTION 'development role % has wrong database CONNECT', role_name;
    END IF;
  END LOOP;
  IF EXISTS (
    SELECT 1 FROM pg_auth_members membership
    JOIN pg_roles member_role ON member_role.oid = membership.member
    JOIN pg_roles granted_role ON granted_role.oid = membership.roleid
    WHERE member_role.rolname IN ('pricing_loader_writer_development', 'pricing_reader_development',
      'tollchat_agent_development', 'pricing_caller_development', 'report_publisher_development')
      AND granted_role.rolname <> 'rds_iam'
  ) OR EXISTS (
    SELECT 1 FROM pg_auth_members membership JOIN pg_roles member_role ON member_role.oid = membership.member
    WHERE member_role.rolname = 'oracle_owner_development'
  ) THEN RAISE EXCEPTION 'development role has unexpected membership'; END IF;
END $$;
COMMIT;
""",
            )
        except Exception:
            if created_development:
                with suppress(RuntimeError, subprocess.CalledProcessError):
                    rollback_development()
            raise

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, subprocess.CalledProcessError):
        print("development bootstrap failed", file=sys.stderr)
        raise SystemExit(1) from None
