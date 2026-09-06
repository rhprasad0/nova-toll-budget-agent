#!/usr/bin/env python3
"""Create the one-time isolated development TollChat database.

The caller supplies an administrator PostgreSQL connection through PG* or
NOVA_TOLL_ADMIN_URL. This program deliberately has no AWS or credential logic.
For a local port forward, NOVA_TOLL_RDS_LOCAL_PORT changes only the transport
address; PGHOST remains the verified RDS endpoint for TLS hostname validation.
Every local-forward subprocess uses an explicit admin URL with verify-full and
a nonempty reviewed CA bundle.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import NamedTuple, cast
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[2]
BASELINE_MANIFEST_PATH = ROOT / "v2/db/migration-baselines.json"
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
        "pricing_owner_development",
        "schema_migrator_development",
    ),
}
IDENTIFIER = re.compile(r"[a-z][a-z0-9_]*\Z")
RDS_ENDPOINT = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\Z")
LOCAL_PORT = re.compile(r"[1-9][0-9]{0,4}\Z")
DEVELOPMENT_RUNTIME_ROLE_COUNT = len(ROLES["production"])
PRICING_OWNER_TABLES = (
    "pricing.schema_version",
    "pricing.trip_pricing_i95",
    "pricing.trip_pricing_i66",
)
PRICING_OWNER_VIEWS = (
    "pricing.current_trip_pricing_i95",
    "pricing.current_trip_pricing_i66",
    "pricing.current_i95_direction",
    "pricing.i95_modeled_od_proxy",
    "pricing.modeled_trip_pricing_i95",
    "pricing.modeled_current_trip_pricing_i95",
    "pricing.i66_pricing_comparisons",
    "pricing.i95_i495_pricing_comparisons",
    "pricing.i66_ballpark_samples",
    "pricing.i95_i495_ballpark_samples",
)
BASELINE_EVIDENCE = "canonical bootstrap baseline; no application migration executed"
BASELINE_MIGRATION_ID = "baseline"
BASELINE_PATHS = {
    "pricing": "v2/db/schema.sql",
    "oracle": "v2/db/oracle/schema.sql",
}
VERSION_PATTERN = re.compile(r"^(0|[1-9][0-9]*)[.](0|[1-9][0-9]*)[.](0|[1-9][0-9]*)$")
SCHEMA_VERSION_PATTERN = re.compile(
    r"^-- (?P<schema>[a-z][a-z0-9_]*) schema version: (?P<version>\S+)$",
    re.MULTILINE,
)
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class Baseline(NamedTuple):
    schema: str
    version: str
    migration_id: str
    source_path: str
    source_sha256: str
    evidence: str


def load_baseline_manifest(
    path: Path | None = None,
) -> tuple[Baseline, ...]:
    manifest_path = path or BASELINE_MANIFEST_PATH
    try:
        raw: object = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as error:
        raise ValueError("development baseline manifest is invalid") from error
    if not isinstance(raw, list):
        raise ValueError("development baseline manifest must contain a list")

    baselines: list[Baseline] = []
    raw_items = cast(list[object], raw)
    keys = {
        "schema",
        "version",
        "migration_id",
        "source_path",
        "source_sha256",
        "evidence",
    }
    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            raise ValueError("development baseline manifest record is invalid")
        item = cast(dict[str, object], raw_item)
        if set(item) != keys:
            raise ValueError("development baseline manifest record is invalid")
        schema = item["schema"]
        version = item["version"]
        migration_id = item["migration_id"]
        source_path = item["source_path"]
        source_sha256 = item["source_sha256"]
        evidence = item["evidence"]
        if (
            not all(
                isinstance(value, str)
                for value in (
                    schema,
                    version,
                    migration_id,
                    source_path,
                    source_sha256,
                    evidence,
                )
            )
            or not isinstance(schema, str)
            or not isinstance(version, str)
            or not isinstance(migration_id, str)
            or not isinstance(source_path, str)
            or not isinstance(source_sha256, str)
            or not isinstance(evidence, str)
        ):
            raise ValueError("development baseline manifest record is invalid")
        if (
            schema not in BASELINE_PATHS
            or source_path != BASELINE_PATHS[schema]
            or migration_id != BASELINE_MIGRATION_ID
            or VERSION_PATTERN.fullmatch(version) is None
            or SHA256_PATTERN.fullmatch(source_sha256) is None
            or evidence != BASELINE_EVIDENCE
        ):
            raise ValueError("development baseline manifest record is invalid")
        baselines.append(
            Baseline(
                schema=schema,
                version=version,
                migration_id=migration_id,
                source_path=source_path,
                source_sha256=source_sha256,
                evidence=evidence,
            )
        )

    identities = [(baseline.schema, baseline.version) for baseline in baselines]
    sources = [
        (baseline.schema, baseline.source_path, baseline.source_sha256)
        for baseline in baselines
    ]
    if len(identities) != len(set(identities)) or len(sources) != len(set(sources)):
        raise ValueError("development baseline manifest contains duplicates")
    if {baseline.schema for baseline in baselines} != set(BASELINE_PATHS):
        raise ValueError("development baseline manifest lacks schema coverage")
    return tuple(baselines)


def baseline_for_canonical(schema: str, relative: str) -> Baseline:
    if BASELINE_PATHS.get(schema) != relative:
        raise RuntimeError("canonical source is not an approved baseline path")
    source = ROOT / relative
    try:
        content = source.read_bytes()
        text = content.decode("utf-8")
        digest = hashlib.sha256(content).hexdigest()
    except (OSError, UnicodeError) as error:
        raise RuntimeError("canonical source is unavailable") from error
    matches = [
        match.group("version")
        for match in SCHEMA_VERSION_PATTERN.finditer(text)
        if match.group("schema") == schema
    ]
    if len(matches) != 1 or VERSION_PATTERN.fullmatch(matches[0]) is None:
        raise RuntimeError("canonical source has no exact schema version")
    inserted = re.findall(
        rf"INSERT INTO {re.escape(schema)}[.]schema_version "
        rf"\(version\) VALUES \('([^']+)'\)",
        text,
    )
    if inserted != matches:
        raise RuntimeError("canonical source schema version is not exact")
    recognized = [
        baseline
        for baseline in load_baseline_manifest()
        if baseline.schema == schema
        and baseline.version == matches[0]
        and baseline.source_path == relative
        and baseline.source_sha256 == digest
    ]
    if len(recognized) != 1:
        raise RuntimeError("canonical source is not represented in baseline manifest")
    return recognized[0]


def run(
    *args: str, input: str | None = None, env: dict[str, str] | None = None
) -> None:
    subprocess.run(args, input=input, text=True, check=True, env=env)


def tls_environment(
    query: str, *, require_explicit: bool, fallback_rootcert: str | None = None
) -> dict[str, str]:
    values: dict[str, str] = {}
    if not query:
        if require_explicit:
            raise RuntimeError("NOVA_TOLL_ADMIN_URL requires explicit TLS settings")
        return {}
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
    if require_explicit and "sslrootcert" not in values:
        raise RuntimeError("NOVA_TOLL_ADMIN_URL has invalid TLS settings")
    rootcert = values.get("sslrootcert", fallback_rootcert)
    if rootcert is None or not rootcert.strip():
        if require_explicit:
            raise RuntimeError("NOVA_TOLL_ADMIN_URL has invalid TLS settings")
        return {"PGSSLMODE": "verify-full"}
    return {
        "PGSSLMODE": "verify-full",
        "PGSSLROOTCERT": rootcert.strip(),
    }


def expected_rds_endpoint() -> str | None:
    value = os.environ.get("NOVA_TOLL_EXPECTED_RDS_ENDPOINT")
    if value is None:
        return None
    value = value.strip().strip("[]")
    if not value or not RDS_ENDPOINT.fullmatch(value):
        raise RuntimeError("NOVA_TOLL_EXPECTED_RDS_ENDPOINT is invalid")
    return value.lower()


def local_transport_port() -> str | None:
    value = os.environ.get("NOVA_TOLL_RDS_LOCAL_PORT")
    if value is None:
        return None
    if not LOCAL_PORT.fullmatch(value) or int(value) > 65535:
        raise RuntimeError("NOVA_TOLL_RDS_LOCAL_PORT is invalid")
    return value


def psql(
    database: str,
    *,
    sql: str | None = None,
    file: Path | None = None,
    variables: dict[str, str] | None = None,
) -> None:
    admin_url = os.environ.get("NOVA_TOLL_ADMIN_URL")
    expected_endpoint = expected_rds_endpoint()
    local_port = local_transport_port()
    if local_port is not None and expected_endpoint is None:
        raise RuntimeError(
            "NOVA_TOLL_RDS_LOCAL_PORT requires the verified RDS endpoint"
        )
    if local_port is not None and admin_url is None:
        raise RuntimeError("NOVA_TOLL_RDS_LOCAL_PORT requires NOVA_TOLL_ADMIN_URL")
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
        if (
            expected_endpoint is not None
            and parsed.hostname.lower() != expected_endpoint
        ):
            raise RuntimeError(
                "NOVA_TOLL_ADMIN_URL is not bound to the verified RDS endpoint"
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
        if local_port is not None:
            environment["PGHOSTADDR"] = "127.0.0.1"
            environment["PGPORT"] = local_port
        environment.update(
            tls_environment(
                parsed.query,
                require_explicit=local_port is not None,
                fallback_rootcert=os.environ.get("PGSSLROOTCERT"),
            )
        )
    else:
        environment = os.environ.copy()
        if not environment.get("PGHOST") or not environment.get("PGUSER"):
            raise RuntimeError("set NOVA_TOLL_ADMIN_URL or both PGHOST and PGUSER")
        if (
            expected_endpoint is not None
            and environment["PGHOST"].strip("[]").lower() != expected_endpoint
        ):
            raise RuntimeError("PGHOST is not bound to the verified RDS endpoint")
        command.extend(("--dbname", database))
    if file is not None:
        command.extend(("--file", str(file)))
    if variables:
        command.extend(
            item
            for key, value in variables.items()
            for item in ("--variable", f"{key}={value}")
        )
    run(*command, input=sql, env=environment)


def render(source: Path, destination: Path) -> None:
    replacements = dict(
        zip(
            ROLES["production"],
            ROLES["development"][:DEVELOPMENT_RUNTIME_ROLE_COUNT],
            strict=True,
        )
    )
    pattern = re.compile(r"\b(" + "|".join(map(re.escape, replacements)) + r")\b")
    destination.write_text(
        pattern.sub(lambda match: replacements[match[0]], source.read_text())
    )


def prepare_development_ownership() -> None:
    """Create bounded owners and temporarily delegate ownership transfers."""

    psql(
        "postgres",
        sql="""
BEGIN;
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pricing_owner_development') THEN
    CREATE ROLE pricing_owner_development
      NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT
      NOREPLICATION NOBYPASSRLS;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'schema_migrator_development') THEN
    CREATE ROLE schema_migrator_development
      LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT
      NOREPLICATION NOBYPASSRLS;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'oracle_owner_development') THEN
    CREATE ROLE oracle_owner_development
      NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT
      NOREPLICATION NOBYPASSRLS;
  END IF;
  IF EXISTS (
    SELECT 1 FROM pg_roles
    WHERE rolname IN ('pricing_owner_development', 'oracle_owner_development')
      AND (rolcanlogin OR rolsuper OR rolcreatedb OR rolcreaterole
           OR rolreplication OR rolbypassrls)
  ) OR EXISTS (
    SELECT 1 FROM pg_roles
    WHERE rolname = 'schema_migrator_development'
      AND (NOT rolcanlogin OR rolsuper OR rolcreatedb OR rolcreaterole OR rolinherit
           OR rolreplication OR rolbypassrls)
  ) THEN
    RAISE EXCEPTION 'development ownership roles are not safely bounded';
  END IF;
END $$;
DO $$
DECLARE
  owner_role name;
  owner_roles name[] := ARRAY[
    'pricing_owner_development', 'oracle_owner_development'
  ];
BEGIN
  FOREACH owner_role IN ARRAY owner_roles LOOP
    IF NOT EXISTS (
      SELECT 1
      FROM pg_auth_members membership
      JOIN pg_roles member_role ON member_role.oid = membership.member
      JOIN pg_roles granted_role ON granted_role.oid = membership.roleid
      WHERE member_role.rolname = 'schema_migrator_development'
        AND granted_role.rolname = owner_role
        AND NOT membership.inherit_option
        AND membership.set_option
        AND NOT membership.admin_option
    ) THEN
      EXECUTE format(
        'GRANT %I TO schema_migrator_development WITH INHERIT FALSE, SET TRUE, ADMIN FALSE',
        owner_role
      );
    END IF;
    EXECUTE format(
      'GRANT %I TO %I WITH INHERIT FALSE, SET TRUE, ADMIN FALSE',
      owner_role, current_user
    );
  END LOOP;
END $$;
COMMIT;
""",
    )


def revoke_development_ownership() -> None:
    psql(
        "postgres",
        sql="""
DO $$
DECLARE
  owner_role name;
  owner_roles name[] := ARRAY[
    'pricing_owner_development', 'oracle_owner_development'
  ];
BEGIN
  FOREACH owner_role IN ARRAY owner_roles LOOP
    EXECUTE format('REVOKE %I FROM %I', owner_role, current_user);
  END LOOP;
END $$;
""",
    )


def bootstrap_development_objects(database: str) -> None:
    pricing_baseline = baseline_for_canonical("pricing", "v2/db/schema.sql")
    oracle_baseline = baseline_for_canonical("oracle", "v2/db/oracle/schema.sql")
    pricing_tables = "\n".join(
        f"ALTER TABLE {table} OWNER TO pricing_owner_development;"
        for table in PRICING_OWNER_TABLES
    )
    pricing_views = "\n".join(
        f"ALTER VIEW {view} OWNER TO pricing_owner_development;"
        for view in PRICING_OWNER_VIEWS
    )
    runtime_roles = ", ".join(ROLES["development"][:DEVELOPMENT_RUNTIME_ROLE_COUNT])
    prepare_development_ownership()
    try:
        psql(
            database,
            sql=f"""
BEGIN;
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM pg_roles
    WHERE rolname IN ('pricing_owner_development', 'oracle_owner_development')
      AND (rolcanlogin OR rolsuper OR rolcreatedb OR rolcreaterole
           OR rolreplication OR rolbypassrls)
  ) OR EXISTS (
    SELECT 1 FROM pg_roles
    WHERE rolname = 'schema_migrator_development'
      AND (NOT rolcanlogin OR rolsuper OR rolcreatedb OR rolcreaterole OR rolinherit
           OR rolreplication OR rolbypassrls)
  ) THEN
    RAISE EXCEPTION 'development ownership roles are not safely bounded';
  END IF;
END $$;

DO $$
DECLARE
  granted_role name;
  granted_roles name[] := ARRAY[
    'rds_iam', 'pricing_owner_development', 'oracle_owner_development'
  ];
BEGIN
  FOREACH granted_role IN ARRAY granted_roles LOOP
    IF NOT EXISTS (
      SELECT 1
      FROM pg_auth_members membership
      JOIN pg_roles member_role ON member_role.oid = membership.member
      JOIN pg_roles role_name ON role_name.oid = membership.roleid
      WHERE member_role.rolname = 'schema_migrator_development'
        AND role_name.rolname = granted_role
        AND (
          (granted_role = 'rds_iam'
           AND membership.inherit_option
           AND membership.set_option
           AND NOT membership.admin_option)
          OR (granted_role <> 'rds_iam'
              AND NOT membership.inherit_option
              AND membership.set_option
              AND NOT membership.admin_option)
        )
    ) THEN
      EXECUTE format(
        'GRANT %I TO schema_migrator_development WITH INHERIT %s, SET TRUE, ADMIN FALSE',
        granted_role, CASE WHEN granted_role = 'rds_iam' THEN 'TRUE' ELSE 'FALSE' END
      );
    END IF;
  END LOOP;
END $$;

GRANT USAGE, CREATE ON SCHEMA pricing TO pricing_owner_development;
{pricing_tables}
{pricing_views}
ALTER SCHEMA pricing OWNER TO pricing_owner_development;

CREATE SCHEMA IF NOT EXISTS tollchat_migration;
REVOKE ALL ON SCHEMA tollchat_migration FROM PUBLIC, {runtime_roles}, schema_migrator_development;
GRANT USAGE, CREATE ON SCHEMA tollchat_migration TO pricing_owner_development;
CREATE TABLE IF NOT EXISTS tollchat_migration.schema_history (
    schema_name text NOT NULL CHECK (schema_name IN ('pricing', 'oracle')),
    schema_version text NOT NULL CHECK (
        schema_version ~ '^(0|[1-9][0-9]*)[.](0|[1-9][0-9]*)[.](0|[1-9][0-9]*)$'
    ),
    migration_id text NOT NULL,
    source_path text NOT NULL CHECK (btrim(source_path) <> ''),
    source_sha256 text NOT NULL CHECK (source_sha256 ~ '^[0-9a-f]{{64}}$'),
    evidence text NOT NULL CHECK (btrim(evidence) <> ''),
    is_baseline boolean NOT NULL,
    recorded_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    PRIMARY KEY (schema_name, migration_id),
    UNIQUE (schema_name, schema_version),
    CHECK (
        (is_baseline AND migration_id = 'baseline')
        OR (NOT is_baseline AND migration_id <> 'baseline')
    )
);
REVOKE ALL ON tollchat_migration.schema_history
  FROM PUBLIC, {runtime_roles}, schema_migrator_development;
ALTER TABLE tollchat_migration.schema_history OWNER TO pricing_owner_development;
ALTER SCHEMA tollchat_migration OWNER TO pricing_owner_development;
SET LOCAL ROLE pricing_owner_development;
INSERT INTO tollchat_migration.schema_history (
    schema_name, schema_version, migration_id, source_path,
    source_sha256, evidence, is_baseline
) VALUES
    ('pricing', :'pricing_version', :'pricing_migration_id', :'pricing_source_path',
     :'pricing_sha256', :'pricing_evidence', true),
    ('oracle', :'oracle_version', :'oracle_migration_id', :'oracle_source_path',
     :'oracle_sha256', :'oracle_evidence', true)
ON CONFLICT (schema_name, migration_id) DO NOTHING;
COMMIT;
""",
            variables={
                "pricing_version": pricing_baseline.version,
                "pricing_migration_id": pricing_baseline.migration_id,
                "pricing_source_path": pricing_baseline.source_path,
                "pricing_sha256": pricing_baseline.source_sha256,
                "pricing_evidence": pricing_baseline.evidence,
                "oracle_version": oracle_baseline.version,
                "oracle_migration_id": oracle_baseline.migration_id,
                "oracle_source_path": oracle_baseline.source_path,
                "oracle_sha256": oracle_baseline.source_sha256,
                "oracle_evidence": oracle_baseline.evidence,
            },
        )
    finally:
        revoke_development_ownership()


def rollback_development() -> None:
    psql(
        "postgres",
        sql=f"""
DROP DATABASE IF EXISTS {DATABASES["development"]} WITH (FORCE);
DROP ROLE IF EXISTS {", ".join(ROLES["development"])};
""",
    )


def fresh_development_preflight() -> None:
    """Prove the Terraform-created database is still an empty fresh target."""

    if expected_rds_endpoint() is None:
        raise RuntimeError("fresh bootstrap requires the freshly verified RDS endpoint")
    development = DATABASES["development"]
    production_roles = ", ".join(repr(role) for role in ROLES["production"])
    psql(
        "postgres",
        sql=f"""
DO $$
BEGIN
  IF current_database() <> 'postgres' THEN
    RAISE EXCEPTION 'fresh bootstrap requires the postgres database';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = '{development}') THEN
    RAISE EXCEPTION 'fresh development database is missing';
  END IF;
  IF EXISTS (SELECT 1 FROM pg_database WHERE datname = '{DATABASES["production"]}')
     OR EXISTS (SELECT 1 FROM pg_roles WHERE rolname IN ({production_roles})) THEN
    RAISE EXCEPTION 'fresh development target is an existing split environment';
  END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname LIKE '%\\_development' ESCAPE '\\') THEN
    RAISE EXCEPTION 'development role already exists';
  END IF;
  IF to_regrole('rds_iam') IS NULL THEN
    RAISE EXCEPTION 'required rds_iam role is missing';
  END IF;
  IF EXISTS (
    SELECT 1 FROM pg_database database, LATERAL aclexplode(database.datacl) privilege
    WHERE database.datname = '{development}'
      AND privilege.grantee NOT IN (0, database.datdba)
  ) THEN
    RAISE EXCEPTION 'fresh development database has unexpected CONNECT grants';
  END IF;
  IF EXISTS (
    SELECT 1 FROM pg_shdescription
    WHERE objoid = (SELECT oid FROM pg_database WHERE datname = '{development}')
  ) THEN
    RAISE EXCEPTION 'fresh development database has an environment comment';
  END IF;
END $$;
""",
    )
    psql(
        development,
        sql=f"""
DO $$
BEGIN
  IF current_database() <> '{development}' THEN
    RAISE EXCEPTION 'fresh bootstrap connected to the wrong database';
  END IF;
  IF EXISTS (
    SELECT 1 FROM pg_namespace
    WHERE nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast', 'public')
      AND nspname NOT LIKE 'pg_temp_%'
      AND nspname NOT LIKE 'pg_toast_temp_%'
  ) OR EXISTS (
    SELECT 1
    FROM pg_class relation
    JOIN pg_namespace namespace ON namespace.oid = relation.relnamespace
    WHERE namespace.nspname = 'public'
  ) OR EXISTS (
    SELECT 1
    FROM pg_proc procedure
    JOIN pg_namespace namespace ON namespace.oid = procedure.pronamespace
    WHERE namespace.nspname = 'public'
  ) OR EXISTS (
    SELECT 1 FROM pg_extension WHERE extname <> 'plpgsql'
  ) THEN
    RAISE EXCEPTION 'fresh development database is not empty';
  END IF;
END $$;
""",
    )


def cleanup_fresh_development() -> None:
    """Remove only objects the fresh invocation could have created."""

    errors: list[Exception] = []
    for database, sql in (
        (
            DATABASES["development"],
            "DROP SCHEMA IF EXISTS tollchat_migration CASCADE;"
            " DROP SCHEMA IF EXISTS oracle CASCADE;"
            " DROP SCHEMA IF EXISTS pricing CASCADE;",
        ),
        (
            "postgres",
            f"""
REVOKE CONNECT ON DATABASE {DATABASES["development"]} FROM {", ".join(ROLES["development"])};
DROP ROLE IF EXISTS {", ".join(ROLES["development"])};
""",
        ),
        (
            "postgres",
            f"""
COMMENT ON DATABASE {DATABASES["development"]} IS NULL;
GRANT CONNECT ON DATABASE {DATABASES["development"]} TO PUBLIC;
""",
        ),
    ):
        try:
            psql(database, sql=sql)
        except Exception as error:  # pragma: no cover - exercised by live failures
            errors.append(error)
    if errors:
        raise RuntimeError("fresh development cleanup could not be proven") from errors[
            0
        ]


def fresh_development() -> int:
    fresh_development_preflight()
    with tempfile.TemporaryDirectory(
        prefix="nova-toll-fresh-development-"
    ) as directory:
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

        started = False
        try:
            started = True
            prepare_development_ownership()
            for relative in (
                "v2/db/schema.sql",
                "v2/db/roles.sql",
                "v2/db/oracle/schema.sql",
            ):
                psql(DATABASES["development"], file=rendered / relative)
            bootstrap_development_objects(DATABASES["development"])
            development_roles = ", ".join(ROLES["development"])
            role_comments = "\n".join(
                f"COMMENT ON ROLE {role} IS 'environment=development';"
                for role in ROLES["development"]
            )
            psql(
                "postgres",
                sql=f"""
BEGIN;
COMMENT ON DATABASE {DATABASES["development"]} IS 'environment=development';
{role_comments}
REVOKE CONNECT ON DATABASE {DATABASES["development"]} FROM PUBLIC;
GRANT CONNECT ON DATABASE {DATABASES["development"]} TO {development_roles};
COMMIT;
""",
            )
            psql(
                DATABASES["development"],
                file=ROOT / "v2/tests/development_bootstrap_contract.sql",
                variables={"fresh_development": "1"},
            )
        except Exception:
            if started:
                cleanup_fresh_development()
            raise
    return 0


def main() -> int:
    if any(
        not IDENTIFIER.fullmatch(name) for names in ROLES.values() for name in names
    ):
        raise RuntimeError("bootstrap role map contains an unsafe identifier")
    if len(set(ROLES["production"] + ROLES["development"])) != 14:
        raise RuntimeError("bootstrap role map contains duplicate identifiers")
    if len(sys.argv) == 2 and sys.argv[1] == "--fresh-development":
        return fresh_development()
    if sys.argv[1:]:
        print(
            "usage: bootstrap_development_database.py [--fresh-development]",
            file=sys.stderr,
        )
        return 2
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
            prepare_development_ownership()
            psql(DATABASES["development"], file=rendered / "v2/db/schema.sql")
            psql(DATABASES["development"], file=rendered / "v2/db/roles.sql")
            psql(DATABASES["development"], file=rendered / "v2/db/oracle/schema.sql")
            bootstrap_development_objects(DATABASES["development"])
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
{chr(10).join(f"COMMENT ON ROLE {role} IS 'environment=development';" for role in ROLES["development"])}
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
        to_regrole('report_publisher_development'), to_regrole('pricing_owner_development'),
        to_regrole('schema_migrator_development'))
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
