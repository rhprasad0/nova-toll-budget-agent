#!/usr/bin/env python3
"""Exercise legacy retirement against the verified disposable PostgreSQL 17 service."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[2]
RETIRER_PATH = ROOT / "v2/scripts/retire_legacy_development_database.py"
BOOTSTRAP_PATH = ROOT / "v2/scripts/bootstrap_development_database.py"
HOST = os.environ.get("PGHOST", "")
PORT = os.environ.get("PGPORT", "")
USER = os.environ.get("PGUSER", "")
PRODUCTION = "nova_toll"
DEVELOPMENT = "nova_toll_development"
EXTERNAL = "nova_toll_retirement_external"
LATE_DEPENDENCY_ROLE = "nova_toll_retirement_late_dependency"
OWNER = "postgres"
FIXTURE_OWNER = "nova_toll_retirement_admin"
PRODUCTION_ROLES = (
    "pricing_loader_writer",
    "pricing_reader",
    "oracle_owner",
    "tollchat_agent",
    "pricing_caller",
    "report_publisher",
)
DEVELOPMENT_ROLES = tuple(f"{role}_development" for role in PRODUCTION_ROLES)
ALL_ROLES = PRODUCTION_ROLES + DEVELOPMENT_ROLES
_fixture_started = False

_spec = importlib.util.spec_from_file_location("legacy_retirer", RETIRER_PATH)
assert _spec and _spec.loader
retirer = cast(Any, importlib.util.module_from_spec(_spec))
_spec.loader.exec_module(retirer)
_bootstrap_spec = importlib.util.spec_from_file_location(
    "development_bootstrap", BOOTSTRAP_PATH
)
assert _bootstrap_spec and _bootstrap_spec.loader
bootstrap = cast(Any, importlib.util.module_from_spec(_bootstrap_spec))
_bootstrap_spec.loader.exec_module(bootstrap)


def _environment(database: str = "postgres") -> dict[str, str]:
    if not HOST or not PORT or not USER:
        raise AssertionError("PGHOST, PGPORT, and PGUSER are required")
    environment = os.environ.copy()
    environment.update(
        {
            "PGHOST": HOST,
            "PGPORT": PORT,
            "PGUSER": USER,
            "PGDATABASE": database,
            "PGSSLMODE": "disable",
        }
    )
    environment.pop("PGPASSWORD", None)
    return environment


def _run(
    command: list[str], *, database: str = "postgres", sql: str | None = None
) -> str:
    result = subprocess.run(
        command,
        input=sql,
        text=True,
        capture_output=True,
        env=_environment(database),
        check=False,
    )
    if result.returncode:
        raise AssertionError(result.stderr[-1000:])
    return result.stdout.strip()


def _sql(sql: str, database: str = "postgres") -> str:
    return _run(
        [
            "psql",
            "-X",
            "--set",
            "ON_ERROR_STOP=1",
            "--tuples-only",
            "--no-align",
            "--quiet",
            "--dbname",
            database,
        ],
        database=database,
        sql=sql,
    )


def _psql_file(path: Path, database: str, *, role: str | None = None) -> None:
    command = [
        "psql",
        "-X",
        "--set",
        "ON_ERROR_STOP=1",
        "--dbname",
        database,
    ]
    if role is not None:
        command.extend(("--command", f"SET ROLE {role}"))
    command.extend(("--file", str(path)))
    result = subprocess.run(
        command,
        text=True,
        capture_output=True,
        env=_environment(database),
        check=False,
    )
    if result.returncode:
        raise AssertionError(result.stderr[-1000:])


def _system_identifier() -> str:
    return _sql("SELECT system_identifier FROM pg_control_system()")


def _require_fixture_target() -> None:
    container = os.environ.get("POSTGRES_CONTAINER_ID", "")
    if not container:
        raise AssertionError("POSTGRES_CONTAINER_ID is required")
    image = _run(["docker", "inspect", "--format", "{{.Config.Image}}", container])
    if image != "postgis/postgis:17-3.5":
        raise AssertionError("focused retirement test requires postgis/postgis:17-3.5")
    container_identifier = _run(
        [
            "docker",
            "exec",
            container,
            "psql",
            "-X",
            "--username",
            "postgres",
            "--dbname",
            "postgres",
            "--tuples-only",
            "--no-align",
            "--command",
            "SELECT system_identifier FROM pg_control_system()",
        ]
    )
    if not _system_identifier() or _system_identifier() != container_identifier:
        raise AssertionError("focused retirement target does not match its container")
    databases = _sql("SELECT datname FROM pg_database ORDER BY datname")
    if databases != (
        "nova_toll\nnova_toll_development\npostgres\ntemplate0\n"
        "template1\ntemplate_postgis"
    ):
        raise AssertionError(
            "focused retirement test requires the initialized bootstrap fixture"
        )
    if _sql("SELECT count(*) FROM pg_roles WHERE rolname = 'rds_iam'") != "1":
        raise AssertionError("runner bootstrap baseline is missing rds_iam")
    if _sql("SELECT count(*) FROM pg_roles WHERE rolname = 'rdsadmin'") != "0":
        raise AssertionError("focused retirement fixture has a stale pinned-owner role")
    if (
        _sql(
            "SELECT count(*) FROM pg_roles WHERE rolname = ANY(ARRAY["
            + ",".join(repr(role) for role in ALL_ROLES)
            + "])"
        )
        != "12"
    ):
        raise AssertionError(
            "focused retirement fixture has the wrong initialized roles"
        )
    if (
        _sql(
            "SELECT shobj_description(oid, 'pg_database') FROM pg_database "
            "WHERE datname = 'nova_toll'"
        )
        != "environment=production"
    ):
        raise AssertionError("initialized production comment baseline is wrong")
    if (
        _sql(
            "SELECT shobj_description(oid, 'pg_database') FROM pg_database "
            "WHERE datname = 'nova_toll_development'"
        )
        != "environment=development"
    ):
        raise AssertionError("initialized development comment baseline is wrong")
    if (
        _sql(
            "SELECT count(*) FROM pg_roles WHERE rolname LIKE '%\\_development' ESCAPE '\\' "
            "AND shobj_description(oid, 'pg_authid') = 'environment=development'"
        )
        != "6"
    ):
        raise AssertionError("initialized development role comments are wrong")


def _setup() -> None:
    _sql(
        f"CREATE ROLE {FIXTURE_OWNER} NOLOGIN;"
        f"ALTER DATABASE {PRODUCTION} OWNER TO {FIXTURE_OWNER};"
        f"DROP DATABASE {DEVELOPMENT} WITH (FORCE);"
        f"CREATE DATABASE {DEVELOPMENT} OWNER {FIXTURE_OWNER} TEMPLATE template0;"
    )
    with tempfile.TemporaryDirectory(prefix="nova-toll-legacy-fixture-") as directory:
        rendered = Path(directory)
        for relative in (
            "v2/db/schema.sql",
            "v2/db/analysis.sql",
            "v2/db/roles.sql",
            "v2/db/oracle/schema.sql",
            "v2/db/oracle/data.sql",
        ):
            destination = rendered / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            bootstrap.render(ROOT / relative, destination)
        _psql_file(rendered / "v2/db/schema.sql", DEVELOPMENT, role=FIXTURE_OWNER)
        _psql_file(rendered / "v2/db/roles.sql", DEVELOPMENT)
        _psql_file(rendered / "v2/db/oracle/schema.sql", DEVELOPMENT)
    _sql(
        f"COMMENT ON DATABASE {DEVELOPMENT} IS 'environment=development';"
        f"REVOKE CONNECT ON DATABASE {DEVELOPMENT} FROM PUBLIC;"
        f"GRANT CONNECT ON DATABASE {DEVELOPMENT} TO "
        + ",".join(DEVELOPMENT_ROLES)
        + ";"
        "DO $$ DECLARE role_name name; BEGIN "
        "FOREACH role_name IN ARRAY ARRAY["
        + ",".join(repr(role) for role in DEVELOPMENT_ROLES)
        + "]::name[] LOOP EXECUTE format('COMMENT ON ROLE %I IS NULL', role_name); "
        "END LOOP; END $$;"
    )
    _assert_baseline()


def _assert_baseline() -> None:
    if (
        _sql(
            "SELECT count(*) FROM pg_database WHERE datname = 'nova_toll' "
            "AND shobj_description(oid, 'pg_database') = 'environment=production'"
        )
        != "1"
        or _sql(
            "SELECT count(*) FROM pg_database WHERE datname = 'nova_toll_development' "
            "AND shobj_description(oid, 'pg_database') = 'environment=development'"
        )
        != "1"
    ):
        raise AssertionError("legacy database labels are not exact")
    if (
        _sql(
            "SELECT count(*) FROM pg_roles WHERE rolname LIKE '%\\_development' ESCAPE '\\' "
            "AND shobj_description(oid, 'pg_authid') IS NULL"
        )
        != "6"
    ):
        raise AssertionError("legacy role comments are not NULL")
    if (
        int(
            _sql(
                "SELECT count(*) FROM pg_shdepend "
                "WHERE dbid = (SELECT oid FROM pg_database "
                "WHERE datname = 'nova_toll_development') "
                "AND refclassid = 'pg_authid'::regclass "
                "AND deptype = 'a' "
                "AND refobjid IN (SELECT oid FROM pg_roles WHERE rolname = ANY(ARRAY["
                + ",".join(repr(role) for role in DEVELOPMENT_ROLES)
                + "]))",
                DEVELOPMENT,
            )
        )
        < 1
    ):
        raise AssertionError("authorized in-target role dependencies are missing")
    if (
        _sql(
            "SELECT coalesce(array_agg(extname ORDER BY extname), ARRAY[]::name[]) "
            "FROM pg_extension",
            DEVELOPMENT,
        )
        != "{plpgsql,postgis}"
    ):
        raise AssertionError("fixture extensions are not exact")
    if (
        _sql(
            "SELECT extowner::regrole FROM pg_extension WHERE extname IN ('plpgsql', 'postgis') "
            "GROUP BY extowner::regrole ORDER BY extowner::regrole",
            DEVELOPMENT,
        )
        != "postgres"
    ):
        raise AssertionError("fixture extension owner is not the disposable analogue")
    if (
        _sql("SELECT datdba::regrole FROM pg_database WHERE datname = 'nova_toll'")
        != FIXTURE_OWNER
        or _sql(
            "SELECT nspowner::regrole FROM pg_namespace WHERE nspname = 'pricing'",
            DEVELOPMENT,
        )
        != FIXTURE_OWNER
    ):
        raise AssertionError("fixture ordinary owner baseline is not exact")


def _cleanup_fixture() -> None:
    if (
        _sql("SELECT count(*) FROM pg_database WHERE datname = 'nova_toll_development'")
        == "1"
    ):
        _sql(f"DROP DATABASE {DEVELOPMENT} WITH (FORCE);")
    if _sql("SELECT count(*) FROM pg_database WHERE datname = 'nova_toll'") == "1":
        _sql(f"ALTER DATABASE {PRODUCTION} OWNER TO postgres;")
    if _sql(f"SELECT count(*) FROM pg_roles WHERE rolname = '{FIXTURE_OWNER}'") == "1":
        _sql(f"DROP ROLE {FIXTURE_OWNER};")


def _production_snapshot() -> str:
    return _sql(
        "SELECT jsonb_build_object("
        "'database', (SELECT jsonb_build_object('comment', shobj_description(oid, 'pg_database'), 'owner', datdba) "
        "FROM pg_database WHERE datname = 'nova_toll'),"
        "'roles', (SELECT jsonb_agg(jsonb_build_object('name', rolname, 'login', rolcanlogin, 'super', rolsuper) ORDER BY rolname) "
        "FROM pg_roles WHERE rolname = ANY(ARRAY['pricing_loader_writer','pricing_reader','oracle_owner','tollchat_agent','pricing_caller','report_publisher'])),"
        "'acl', (SELECT jsonb_agg(jsonb_build_object('grantee', privilege.grantee, 'privilege', privilege.privilege_type) ORDER BY privilege.grantee, privilege.privilege_type) "
        "FROM pg_database database, LATERAL aclexplode(database.datacl) privilege WHERE database.datname = 'nova_toll' AND privilege.privilege_type = 'CONNECT')"
        ")::text"
    )


def _local_psql(
    calls: list[str],
) -> Callable[[str, int, Path, str, str], bool]:
    def local_psql(
        host: str, port: int, ca_file: Path, sql: str, database: str = "postgres"
    ) -> bool:
        del host, port, ca_file
        calls.append(f"{database}|{sql}")
        result = subprocess.run(
            ["psql", "-X", "--set", "ON_ERROR_STOP=1", "--dbname", database],
            input=sql,
            text=True,
            capture_output=True,
            env=_environment(database),
            check=False,
        )
        return result.returncode == 0

    return local_psql


def _expect_preflight_failure(label: str) -> None:
    calls: list[str] = []

    retirer._psql = _local_psql(calls)
    try:
        retirer.retire(HOST, int(PORT), Path("/dev/null"), True)
    except retirer.RetirementError:
        pass
    else:
        raise AssertionError(f"retirement accepted hostile preflight fixture: {label}")
    if any("DROP DATABASE" in call or "DROP ROLE" in call for call in calls):
        raise AssertionError("failed preflight reached a destructive statement")
    _sql(
        "COMMENT ON DATABASE nova_toll IS 'environment=production';"
        "COMMENT ON DATABASE nova_toll_development IS 'environment=development';"
    )
    _sql(
        "DO $$ DECLARE role_name name; BEGIN FOREACH role_name IN ARRAY ARRAY["
        + ",".join(repr(role) for role in DEVELOPMENT_ROLES)
        + "]::name[] LOOP EXECUTE format('COMMENT ON ROLE %I IS NULL', role_name); END LOOP; END $$;"
    )


def _main() -> int:
    global _fixture_started
    _require_fixture_target()
    # The disposable image's postgres role is the pinned RDS system-owner analogue;
    # production SQL remains bound to rdsadmin and this replacement is test-local.
    retirer.DEVELOPMENT_PREFLIGHT_SQL = retirer.DEVELOPMENT_PREFLIGHT_SQL.replace(
        "to_regrole('rdsadmin')", "to_regrole('postgres')"
    )
    _fixture_started = True
    _setup()
    production_snapshot = _production_snapshot()

    for statement in (
        "COMMENT ON DATABASE nova_toll IS 'unexpected';",
        "COMMENT ON DATABASE nova_toll IS NULL;",
        "COMMENT ON DATABASE nova_toll_development IS NULL;",
        "COMMENT ON DATABASE nova_toll_development IS 'unexpected';",
        "COMMENT ON ROLE pricing_loader_writer_development IS 'unexpected';",
    ):
        _sql(statement)
        _expect_preflight_failure(statement)

    for create, drop, label in (
        (
            "CREATE TABLE public.foreign_table (id integer);"
            "ALTER TABLE public.foreign_table OWNER TO postgres;",
            "DROP TABLE public.foreign_table;",
            "foreign public table ownership",
        ),
        (
            "CREATE FUNCTION public.foreign_function() RETURNS integer LANGUAGE sql AS 'SELECT 1';"
            "ALTER FUNCTION public.foreign_function() OWNER TO postgres;",
            "DROP FUNCTION public.foreign_function();",
            "foreign public function ownership",
        ),
        (
            "CREATE DOMAIN public.foreign_domain AS oracle.geometry;"
            "ALTER DOMAIN public.foreign_domain OWNER TO postgres;",
            "DROP DOMAIN public.foreign_domain;",
            "foreign public domain ownership",
        ),
        (
            "CREATE TYPE public.foreign_type AS (id integer);"
            "ALTER TYPE public.foreign_type OWNER TO postgres;",
            "DROP TYPE public.foreign_type;",
            "foreign public type ownership",
        ),
        (
            "SELECT lo_create(2147483000::oid);",
            "SELECT lo_unlink(2147483000::oid);",
            "foreign large object ownership",
        ),
    ):
        _sql(create, DEVELOPMENT)
        _expect_preflight_failure(label)
        _sql(drop, DEVELOPMENT)

    _sql(
        "CREATE ROLE unknown_acl NOLOGIN; GRANT CONNECT ON DATABASE nova_toll_development TO unknown_acl;"
    )
    _expect_preflight_failure("unknown database ACL")
    _sql(
        "REVOKE CONNECT ON DATABASE nova_toll_development FROM unknown_acl; DROP ROLE unknown_acl;"
    )

    _sql(f"CREATE DATABASE {EXTERNAL} OWNER {OWNER} TEMPLATE template0;")
    _sql(
        "CREATE SCHEMA foreign_schema AUTHORIZATION pricing_reader_development;",
        EXTERNAL,
    )
    _expect_preflight_failure("external role dependency")
    _sql(f"DROP DATABASE {EXTERNAL} WITH (FORCE);")

    _assert_baseline()
    calls: list[str] = []
    retirer._psql = _local_psql(calls)
    retirer.retire(HOST, int(PORT), Path("/dev/null"), True)
    if not any(
        "DROP DATABASE nova_toll_development WITH (FORCE);" in call for call in calls
    ):
        raise AssertionError("successful retirement did not drop the exact database")
    if _production_snapshot() != production_snapshot:
        raise AssertionError("successful retirement changed production state")
    if (
        _sql(
            "SELECT count(*) FROM pg_roles WHERE rolname IN ("
            + ",".join(repr(role) for role in DEVELOPMENT_ROLES)
            + ")"
        )
        != "0"
    ):
        raise AssertionError("successful retirement left a development role")
    _sql(
        f"CREATE ROLE {LATE_DEPENDENCY_ROLE} NOLOGIN; "
        f"GRANT CONNECT ON DATABASE {PRODUCTION} TO {LATE_DEPENDENCY_ROLE};"
    )
    if (
        _sql(
            "SELECT count(*) FROM pg_shdepend "
            "WHERE refclassid = 'pg_authid'::regclass "
            f"AND refobjid = to_regrole('{LATE_DEPENDENCY_ROLE}')"
        )
        != "1"
    ):
        raise AssertionError("late shared role dependency was not created")
    late_calls: list[str] = []
    retirer._psql = _local_psql(late_calls)
    if retirer._psql(
        HOST,
        int(PORT),
        Path("/dev/null"),
        retirer.ROLE_DEPENDENCY_SQL.format(role=LATE_DEPENDENCY_ROLE),
        "postgres",
    ):
        raise AssertionError("late shared role dependency bypassed the role guard")
    if any("DROP ROLE" in call for call in late_calls):
        raise AssertionError("late shared role dependency reached a role drop")
    _sql(
        f"REVOKE CONNECT ON DATABASE {PRODUCTION} FROM {LATE_DEPENDENCY_ROLE}; "
        f"DROP ROLE {LATE_DEPENDENCY_ROLE};"
    )
    if _production_snapshot() != production_snapshot:
        raise AssertionError("late dependency proof changed production state")
    _sql(f"ALTER DATABASE {PRODUCTION} OWNER TO postgres;")
    _sql(f"DROP ROLE {FIXTURE_OWNER};")
    _fixture_started = False
    print("legacy disposable retirement checks passed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(_main())
    except (AssertionError, ValueError, subprocess.SubprocessError) as error:
        if _fixture_started:
            with suppress(AssertionError, ValueError, subprocess.SubprocessError):
                _cleanup_fixture()
        print(f"legacy disposable retirement checks stopped: {error}", file=sys.stderr)
        raise SystemExit(1) from error
