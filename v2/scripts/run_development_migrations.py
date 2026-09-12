#!/usr/bin/env python3
"""Run the immutable application migrations against the fixed dev database."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Final

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

import adopt_production_baseline as adoption
import bootstrap_development_database as bootstrap
import check_schema_versions as schema_checks

ROOT: Final = Path(__file__).resolve().parents[2]
REGISTRY_PATH: Final = ROOT / "v2/db/application-schemas.json"
MIGRATIONS_DIR: Final = ROOT / "v2/db/migrations"
DATABASE: Final = "nova_toll_development"
USER: Final = "schema_migrator_development"
PRODUCTION_DATABASE: Final = "nova_toll"
HISTORY_TABLE: Final = "tollchat_migration.schema_history"
LOCK_NAME: Final = "tollchat-development-schema-migrations"
OWNER_BY_SCHEMA: Final = {
    "pricing": "pricing_owner_development",
    "oracle": "oracle_owner_development",
}
CREATED_RUNTIME_ROLES: Final = {
    "pricing_caller_development",
    "report_publisher_development",
}
BOOTSTRAP_FILES: Final = {
    "001_create_pricing_schema.sql",
    "003_create_oracle_schema.sql",
    "003_create_oracle_schema.rollback.sql",
}
EVIDENCE_PATTERN: Final = re.compile(
    r"^commit=[0-9a-f]{40};run=[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
COMMIT_PATTERN: Final = re.compile(r"^[0-9a-f]{40}$")
TRANSACTION_BOUNDARY_PATTERN: Final = re.compile(
    r"(?is)(?:(?<=;)|\A)\s*(?P<boundary>"
    r"(?:BEGIN|COMMIT|ROLLBACK|START|END|ABORT|PREPARE)\b[^;]*;)"
)
PSQL_CONTROL_PATTERN: Final = re.compile(
    r"(?m)^[ \t]*\\(?P<command>gset|(?:if|elif)[ \t]+[^\n]+|else|endif|"
    r"set[ \t]+ON_ERROR_STOP[ \t]+on)[ \t]*\r?$"
)
SUPPORTED_PSQL_PREFIX: Final = re.compile(
    r"(?is)(?:\s|\\set[ \t]+ON_ERROR_STOP[ \t]+on[ \t]*(?:\r?\n|$))*\Z"
)
DEVELOPMENT_TRANSPORT_NETWORK: Final = ipaddress.ip_network("fd7a:115c:a1e0:b1a::/64")
PRODUCTION_RDS_ENDPOINT: Final = re.compile(
    r"^nova-toll-db[.][a-z0-9-]+[.]us-east-1[.]rds[.]amazonaws[.]com$"
)
PRODUCTION_RDS_PORT: Final = "5432"
PRODUCTION_MAX_MIGRATION_NUMBER: Final = 30


@dataclass(frozen=True)
class Migration:
    path: str
    schema: str
    previous: str
    target: str
    migration_id: str
    number: int
    source_sha256: str


@dataclass(frozen=True)
class MigrationProfile:
    """The only two fixed database identities supported by this runner."""

    name: str
    database: str
    user: str
    lock_name: str
    owners: dict[str, str]
    environment: str
    transport_network: ipaddress.IPv4Network | ipaddress.IPv6Network


DEVELOPMENT_PROFILE: Final = MigrationProfile(
    "development",
    DATABASE,
    USER,
    LOCK_NAME,
    OWNER_BY_SCHEMA,
    "environment=development",
    DEVELOPMENT_TRANSPORT_NETWORK,
)
PRODUCTION_PROFILE: Final = MigrationProfile(
    "production",
    "nova_toll",
    "schema_migrator_production",
    "tollchat-production-schema-migrations",
    {"pricing": "pricing_owner", "oracle": "oracle_owner"},
    "environment=production",
    ipaddress.ip_network("172.31.0.0/16"),
)


class MigrationError(RuntimeError):
    """A fail-closed local or database validation error."""


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _psql_path(path: Path) -> str:
    value = str(path)
    if "\x00" in value:
        raise MigrationError("rendered migration path contains a NUL")
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _run_capture(*args: str) -> str:
    result = subprocess.run(
        args,
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise MigrationError("required local repository check failed")
    return result.stdout.strip()


def _committed_bytes(relative: str) -> bytes:
    result = subprocess.run(
        ["git", "show", f"HEAD:{relative}"],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise MigrationError(f"committed migration source is unavailable: {relative}")
    return result.stdout


def _assert_migration_tree() -> None:
    current = MIGRATIONS_DIR
    while True:
        if current.is_symlink():
            raise MigrationError(f"migration path contains a symlink: {current}")
        if current == ROOT:
            return
        if current == current.parent:
            raise MigrationError("migration path is outside the assigned worktree")
        current = current.parent


def _assert_source_bytes(relative: str, path: Path, committed: bytes) -> None:
    if path.is_symlink() or not path.is_file():
        raise MigrationError(
            f"migration source is not a regular non-symlink file: {relative}"
        )
    if path.read_bytes() != committed:
        raise MigrationError(f"worktree migration differs from HEAD: {relative}")


def _source_bytes(relative: str, path: Path) -> bytes:
    committed = _committed_bytes(relative)
    _assert_source_bytes(relative, path, committed)
    return committed


def _tracked_modes() -> dict[str, str]:
    output = _run_capture("git", "ls-files", "--stage", "--", "v2/db/migrations")
    tracked: dict[str, str] = {}
    for line in output.splitlines():
        metadata, path = line.split("\t", 1)
        mode = metadata.split(maxsplit=1)[0]
        if path in tracked:
            raise MigrationError(f"duplicate tracked migration path: {path}")
        tracked[path] = mode
    return tracked


def _migration_candidates(
    schemas: tuple[schema_checks.RegisteredSchema, ...],
) -> tuple[Migration, ...]:
    _assert_migration_tree()
    tracked = _tracked_modes()
    filesystem_paths = {
        path.relative_to(ROOT).as_posix(): path
        for path in MIGRATIONS_DIR.iterdir()
        if path.is_file() or path.is_symlink()
    }
    if set(filesystem_paths) != set(tracked):
        missing = sorted(set(filesystem_paths) ^ set(tracked))
        raise MigrationError(
            f"migration directory has untracked or missing files: {missing}"
        )

    migrations: list[Migration] = []
    seen_ids: set[str] = set()
    seen_predecessors: set[tuple[str, str]] = set()
    for relative, path in sorted(filesystem_paths.items()):
        name = path.name
        if name in BOOTSTRAP_FILES:
            continue
        if tracked[relative] != "100644":
            raise MigrationError(
                f"migration source is not a regular non-symlink file: {relative}"
            )
        committed = _source_bytes(relative, path)
        owners: list[tuple[str, str, str]] = []
        for registered in schemas:
            parsed = schema_checks.upgrade_versions(registered.name, relative)
            if parsed is not None:
                owners.append((registered.name, *parsed))
        if len(owners) != 1:
            raise MigrationError(
                f"migration has no single registered owner: {relative}"
            )
        schema, previous, target = owners[0]
        if schema_checks.version_tuple(target) <= schema_checks.version_tuple(previous):
            raise MigrationError(f"migration is not monotonic: {relative}")
        predecessor = (schema, previous)
        if predecessor in seen_predecessors:
            raise MigrationError(f"migration predecessor is duplicated: {relative}")
        seen_predecessors.add(predecessor)
        migration_id = name
        if migration_id in seen_ids:
            raise MigrationError(f"migration id is duplicated: {migration_id}")
        seen_ids.add(migration_id)
        migrations.append(
            Migration(
                path=relative,
                schema=schema,
                previous=previous,
                target=target,
                migration_id=migration_id,
                number=int(name[:3]),
                source_sha256=hashlib.sha256(committed).hexdigest(),
            )
        )

    migrations.sort(key=lambda migration: migration.number)
    numbers = [migration.number for migration in migrations]
    if numbers != sorted(set(numbers)):
        raise MigrationError("migration filename numbers must strictly increase")
    return tuple(migrations)


def _production_migrations(
    migrations: tuple[Migration, ...],
) -> tuple[Migration, ...]:
    return tuple(
        migration
        for migration in migrations
        if migration.number <= PRODUCTION_MAX_MIGRATION_NUMBER
    )


def _registry(
    profile: MigrationProfile = DEVELOPMENT_PROFILE,
) -> tuple[tuple[schema_checks.RegisteredSchema, ...], dict[str, str]]:
    schemas = schema_checks.load_registry(REGISTRY_PATH.read_text(encoding="utf-8"))
    if {schema.name for schema in schemas} != set(profile.owners):
        raise MigrationError(
            f"{profile.name} migration registry does not match fixed schemas"
        )
    versions: dict[str, str] = {}
    for registered in schemas:
        canonical = ROOT / registered.canonical_sql
        if canonical.is_symlink() or not canonical.is_file():
            raise MigrationError(
                f"canonical schema source is not a regular file: {registered.canonical_sql}"
            )
        committed = _source_bytes(registered.canonical_sql, canonical)
        try:
            canonical_text = committed.decode("utf-8")
        except UnicodeDecodeError as error:
            raise MigrationError(
                f"canonical schema source is not UTF-8: {registered.canonical_sql}"
            ) from error
        version = schema_checks.schema_version(registered.name, canonical_text)
        if version is None:
            raise MigrationError(f"canonical schema has no version: {registered.name}")
        versions[registered.name] = version
    return schemas, versions


def _expected_values(migrations: tuple[Migration, ...]) -> str:
    rows = [
        "("
        + ", ".join(
            _sql_literal(value)
            for value in (
                migration.schema,
                migration.previous,
                migration.target,
                migration.migration_id,
                migration.path,
                migration.source_sha256,
            )
        )
        + ")"
        for migration in migrations
    ]
    if not rows:
        return "SELECT NULL::text, NULL::text, NULL::text, NULL::text, NULL::text, NULL::text WHERE false"
    return "VALUES\n        " + ",\n        ".join(rows)


def _baseline_values(baselines: tuple[bootstrap.Baseline, ...]) -> str:
    rows = [
        "("
        + ", ".join(
            _sql_literal(value)
            for value in (
                baseline.schema,
                baseline.version,
                baseline.migration_id,
                baseline.source_path,
                baseline.source_sha256,
                baseline.evidence,
            )
        )
        + ")"
        for baseline in baselines
    ]
    if not rows:
        return "SELECT NULL::text, NULL::text, NULL::text, NULL::text, NULL::text, NULL::text WHERE false"
    return "VALUES\n        " + ",\n        ".join(rows)


def _is_identifier_continuation(character: str) -> bool:
    """Return whether a character can continue a PostgreSQL identifier."""
    return (
        character == "_"
        or character == "$"
        or character.isalnum()
        or ord(character) >= 128
    )


def _mask_sql_literals(sql: str) -> str:
    masked = list(sql)
    index = 0
    while index < len(sql):
        if sql.startswith("--", index):
            end = sql.find("\n", index)
            end = len(sql) if end < 0 else end
            masked[index:end] = " " * (end - index)
            index = end
        elif sql.startswith("/*", index):
            end = sql.find("*/", index + 2)
            if end < 0:
                end = len(sql) - 2
            end += 2
            masked[index:end] = " " * (end - index)
            index = end
        elif sql[index] in "'\"":
            quote = sql[index]
            end = index + 1
            while end < len(sql):
                if sql[end] == quote:
                    if end + 1 < len(sql) and sql[end + 1] == quote:
                        end += 2
                        continue
                    end += 1
                    break
                end += 1
            masked[index:end] = " " * (end - index)
            index = end
        elif sql[index] == "$":
            if index > 0 and _is_identifier_continuation(sql[index - 1]):
                index += 1
                continue
            match = re.match(r"\$[A-Za-z_][A-Za-z0-9_]*\$|\$\$", sql[index:])
            if match is None:
                index += 1
                continue
            delimiter = match.group(0)
            end = sql.find(delimiter, index + len(delimiter))
            if end < 0:
                end = len(sql)
            else:
                end += len(delimiter)
            masked[index:end] = " " * (end - index)
            index = end
        else:
            index += 1
    return "".join(masked)


def _remove_terminal_commit(path: Path) -> None:
    """Prepare one private rendered migration for the session transaction."""
    try:
        sql = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise MigrationError("rendered migration is not valid UTF-8") from error
    masked = _mask_sql_literals(sql)

    def mask_control(match: re.Match[str]) -> str:
        # psql's gset ends a SQL statement; conditionals do not. Preserve offsets.
        first = ";" if match.group("command") == "gset" else " "
        return first + " " * (len(match.group()) - 1)

    statements = PSQL_CONTROL_PATTERN.sub(mask_control, masked)
    if "\\" in statements:
        raise MigrationError(f"migration transaction shape is unsupported: {path.name}")
    boundaries = list(TRANSACTION_BOUNDARY_PATTERN.finditer(statements))
    begins = [
        boundary
        for boundary in boundaries
        if boundary.group("boundary").upper().startswith("BEGIN")
    ]
    commits = [
        boundary
        for boundary in boundaries
        if boundary.group("boundary").upper().startswith("COMMIT")
    ]
    if (
        len(begins) != 1
        or len(commits) != 1
        or not SUPPORTED_PSQL_PREFIX.fullmatch(masked[: begins[0].start("boundary")])
        or any(
            masked[boundary.start("boundary") : boundary.end("boundary")]
            .strip()
            .upper()
            not in {"BEGIN;", "COMMIT;"}
            for boundary in boundaries
        )
        or begins[0].start("boundary") >= commits[0].start("boundary")
        or sql[commits[0].end("boundary") :].strip()
    ):
        raise MigrationError(f"migration transaction shape is unsupported: {path.name}")
    path.write_text(
        sql[: commits[0].start("boundary")] + sql[commits[0].end("boundary") :],
        encoding="utf-8",
    )


def _identity_sql(profile: MigrationProfile = DEVELOPMENT_PROFILE) -> str:
    if profile is PRODUCTION_PROFILE:
        return _production_identity_sql()
    return rf"""
DO $$
DECLARE
  migrator oid;
  pricing_owner oid;
  oracle_owner oid;
  membership_count integer;
BEGIN
  IF current_database() <> {_sql_literal(DATABASE)} THEN
    RAISE EXCEPTION 'development migration runner connected to the wrong database';
  END IF;
  IF current_user <> {_sql_literal(USER)} THEN
    RAISE EXCEPTION 'development migration runner connected as the wrong user';
  END IF;
  IF (SELECT shobj_description(oid, 'pg_database') FROM pg_database
      WHERE datname = current_database()) IS DISTINCT FROM 'environment=development' THEN
    RAISE EXCEPTION 'development database comment is not exact';
  END IF;
  SELECT oid INTO STRICT migrator FROM pg_roles WHERE rolname = {_sql_literal(USER)};
  SELECT oid INTO STRICT pricing_owner
  FROM pg_roles WHERE rolname = 'pricing_owner_development';
  SELECT oid INTO STRICT oracle_owner
  FROM pg_roles WHERE rolname = 'oracle_owner_development';
  IF (SELECT count(*) FROM pg_roles
      WHERE rolname IN ('pricing_caller_development', 'report_publisher_development')) <> 2 THEN
    RAISE EXCEPTION 'runtime roles required by released migrations are missing';
  END IF;
  IF EXISTS (
    SELECT 1 FROM pg_roles
    WHERE rolname IN ('pricing_owner_development', 'oracle_owner_development')
      AND (rolcanlogin OR rolsuper OR rolcreatedb OR rolcreaterole OR rolinherit
           OR rolreplication OR rolbypassrls)
  ) OR NOT EXISTS (
    SELECT 1 FROM pg_roles
    WHERE oid = migrator
      AND rolcanlogin AND NOT rolsuper AND NOT rolcreatedb AND NOT rolcreaterole
      AND NOT rolinherit AND NOT rolreplication AND NOT rolbypassrls
  ) THEN
    RAISE EXCEPTION 'development roles are not safely bounded';
  END IF;
  SELECT count(*) INTO STRICT membership_count
  FROM pg_auth_members WHERE member = migrator;
  IF membership_count <> 3 OR EXISTS (
    SELECT 1
    FROM pg_auth_members membership
    JOIN pg_roles granted_role ON granted_role.oid = membership.roleid
    WHERE membership.member = migrator
      AND granted_role.rolname NOT IN (
        'rds_iam', 'pricing_owner_development', 'oracle_owner_development'
      )
  ) OR EXISTS (
    SELECT 1
    FROM pg_auth_members membership
    JOIN pg_roles granted_role ON granted_role.oid = membership.roleid
    WHERE membership.member = migrator
      AND granted_role.rolname = 'rds_iam'
      AND (NOT membership.inherit_option OR NOT membership.set_option OR membership.admin_option)
  ) OR EXISTS (
    SELECT 1
    FROM pg_auth_members membership
    JOIN pg_roles granted_role ON granted_role.oid = membership.roleid
    WHERE membership.member = migrator
      AND granted_role.rolname IN ('pricing_owner_development', 'oracle_owner_development')
      AND (membership.inherit_option OR NOT membership.set_option OR membership.admin_option)
  ) THEN
    RAISE EXCEPTION 'development migrator memberships are not exact';
  END IF;
  IF NOT has_database_privilege(current_user, {_sql_literal(DATABASE)}, 'CONNECT')
     OR EXISTS (
       SELECT 1 FROM pg_database
       WHERE datname = {_sql_literal(PRODUCTION_DATABASE)}
         AND has_database_privilege(current_user, datname, 'CONNECT')
     ) THEN
    RAISE EXCEPTION 'development migrator has wrong database CONNECT privileges';
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_class relation
    JOIN pg_namespace namespace ON namespace.oid = relation.relnamespace
    WHERE namespace.nspname = 'tollchat_migration'
      AND relation.relname = 'schema_history'
  ) THEN
    RAISE EXCEPTION 'development migration history table is missing';
  END IF;
  IF EXISTS (
    SELECT 1 FROM pg_namespace namespace
    CROSS JOIN LATERAL aclexplode(namespace.nspacl) privilege
    WHERE namespace.nspname IN ('pricing', 'oracle', 'tollchat_migration')
      AND privilege.grantee = migrator
  ) OR EXISTS (
    SELECT 1 FROM pg_class relation
    JOIN pg_namespace namespace ON namespace.oid = relation.relnamespace
    CROSS JOIN LATERAL aclexplode(relation.relacl) privilege
    WHERE namespace.nspname IN ('pricing', 'oracle', 'tollchat_migration')
      AND privilege.grantee = migrator
  ) OR EXISTS (
    SELECT 1 FROM pg_proc procedure
    JOIN pg_namespace namespace ON namespace.oid = procedure.pronamespace
    CROSS JOIN LATERAL aclexplode(procedure.proacl) privilege
    WHERE namespace.nspname IN ('pricing', 'oracle', 'tollchat_migration')
      AND privilege.grantee = migrator
  ) OR EXISTS (
    SELECT 1 FROM pg_attribute attribute
    JOIN pg_class relation ON relation.oid = attribute.attrelid
    JOIN pg_namespace namespace ON namespace.oid = relation.relnamespace
    CROSS JOIN LATERAL aclexplode(attribute.attacl) privilege
    WHERE namespace.nspname IN ('pricing', 'oracle', 'tollchat_migration')
      AND attribute.attnum > 0 AND NOT attribute.attisdropped
      AND privilege.grantee = migrator
  ) OR EXISTS (
    SELECT 1 FROM pg_type type
    JOIN pg_namespace namespace ON namespace.oid = type.typnamespace
    CROSS JOIN LATERAL aclexplode(type.typacl) privilege
    WHERE namespace.nspname IN ('pricing', 'oracle', 'tollchat_migration')
      AND privilege.grantee = migrator
  ) THEN
    RAISE EXCEPTION 'development migrator has an unexpected direct application privilege';
  END IF;
  IF EXISTS (
    SELECT 1 FROM pg_namespace namespace
    CROSS JOIN LATERAL aclexplode(namespace.nspacl) privilege
    WHERE namespace.nspname = 'tollchat_migration' AND privilege.grantee = 0
  ) OR EXISTS (
    SELECT 1 FROM pg_class relation
    JOIN pg_namespace namespace ON namespace.oid = relation.relnamespace
    CROSS JOIN LATERAL aclexplode(relation.relacl) privilege
    WHERE namespace.nspname = 'tollchat_migration'
      AND relation.relname = 'schema_history' AND privilege.grantee = 0
  ) THEN
    RAISE EXCEPTION 'development migration history is not private';
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_namespace
    WHERE nspname = 'pricing' AND nspowner = pricing_owner
  ) OR NOT EXISTS (
    SELECT 1 FROM pg_namespace
    WHERE nspname = 'oracle' AND nspowner = oracle_owner
  ) OR NOT EXISTS (
    SELECT 1 FROM pg_namespace
    WHERE nspname = 'tollchat_migration' AND nspowner = pricing_owner
  ) OR NOT EXISTS (
    SELECT 1
    FROM pg_class relation
    JOIN pg_namespace namespace ON namespace.oid = relation.relnamespace
    WHERE namespace.nspname = 'tollchat_migration'
      AND relation.relname = 'schema_history'
      AND relation.relowner = pricing_owner
  ) THEN
    RAISE EXCEPTION 'application or migration schemas have unexpected owners';
  END IF;
  IF EXISTS (
    SELECT 1 FROM pg_namespace
    WHERE nspname IN ('pricing', 'oracle', 'tollchat_migration')
      AND nspowner = migrator
  ) OR EXISTS (
    SELECT 1
    FROM pg_class relation
    JOIN pg_namespace namespace ON namespace.oid = relation.relnamespace
    WHERE namespace.nspname IN ('pricing', 'oracle', 'tollchat_migration')
      AND relation.relowner = migrator
  ) OR EXISTS (
    SELECT 1
    FROM pg_proc procedure
    JOIN pg_namespace namespace ON namespace.oid = procedure.pronamespace
    WHERE namespace.nspname IN ('pricing', 'oracle', 'tollchat_migration')
      AND procedure.proowner = migrator
  ) OR EXISTS (
    SELECT 1
    FROM pg_type type
    JOIN pg_namespace namespace ON namespace.oid = type.typnamespace
    WHERE namespace.nspname IN ('pricing', 'oracle', 'tollchat_migration')
      AND type.typowner = migrator
  ) THEN
    RAISE EXCEPTION 'schema migrator owns application or migration objects';
  END IF;
  IF EXISTS (
    SELECT 1
    FROM pg_class relation
    JOIN pg_namespace namespace ON namespace.oid = relation.relnamespace
    WHERE namespace.nspname = 'pricing'
      AND relation.relowner <> pricing_owner
  ) OR EXISTS (
    SELECT 1
    FROM pg_proc procedure
    JOIN pg_namespace namespace ON namespace.oid = procedure.pronamespace
    WHERE namespace.nspname = 'pricing'
      AND procedure.proowner <> pricing_owner
  ) OR EXISTS (
    SELECT 1
    FROM pg_class relation
    JOIN pg_namespace namespace ON namespace.oid = relation.relnamespace
    WHERE namespace.nspname = 'oracle'
      AND relation.relkind IN ('r', 'v', 'm', 'f', 'p')
      AND NOT EXISTS (
        SELECT 1 FROM pg_depend dependency
        JOIN pg_extension extension ON extension.oid = dependency.refobjid
        WHERE dependency.classid = 'pg_class'::regclass
          AND dependency.objid = relation.oid
          AND dependency.deptype = 'e'
      )
      AND relation.relowner <> oracle_owner
  ) OR EXISTS (
    SELECT 1
    FROM pg_proc procedure
    JOIN pg_namespace namespace ON namespace.oid = procedure.pronamespace
    WHERE namespace.nspname = 'oracle'
      AND NOT EXISTS (
        SELECT 1 FROM pg_depend dependency
        JOIN pg_extension extension ON extension.oid = dependency.refobjid
        WHERE dependency.classid = 'pg_proc'::regclass
          AND dependency.objid = procedure.oid
          AND dependency.deptype = 'e'
      )
      AND procedure.proowner <> oracle_owner
  ) OR EXISTS (
    SELECT 1
    FROM pg_type type
    JOIN pg_namespace namespace ON namespace.oid = type.typnamespace
    WHERE namespace.nspname = 'pricing'
      AND type.typowner <> pricing_owner
  ) OR EXISTS (
    SELECT 1
    FROM pg_type type
    JOIN pg_namespace namespace ON namespace.oid = type.typnamespace
    WHERE namespace.nspname = 'oracle'
      AND NOT EXISTS (
        SELECT 1 FROM pg_depend dependency
        JOIN pg_extension extension ON extension.oid = dependency.refobjid
        WHERE dependency.classid = 'pg_type'::regclass
          AND dependency.objid = type.oid
          AND dependency.deptype = 'e'
      )
      AND type.typowner <> oracle_owner
  ) THEN
    RAISE EXCEPTION 'application objects are not owned by the fixed stable owner';
  END IF;
END $$;
"""


def _history_chain_sql(schema: str, live_sql: str, expected: str) -> str:
    return rf"""
WITH RECURSIVE
live(version) AS ({live_sql}),
baseline(version) AS (
  SELECT schema_version
  FROM {HISTORY_TABLE}
  WHERE schema_name = {_sql_literal(schema)} AND is_baseline
),
expected(schema_name, previous_version, target_version,
         migration_id, source_path, source_sha256) AS (
    SELECT schema_name, previous_version, target_version,
           migration_id, source_path, source_sha256
    FROM ({expected}) AS values_table(
      schema_name, previous_version, target_version,
      migration_id, source_path, source_sha256
    )
), chain(version, migration_id) AS (
  SELECT version, NULL::text FROM baseline
  UNION ALL
  SELECT expected.target_version, expected.migration_id
  FROM chain
  JOIN expected
    ON expected.schema_name = {_sql_literal(schema)}
   AND expected.previous_version = chain.version
  WHERE chain.version <> (SELECT version FROM live)
), needed AS (
  SELECT expected.*
  FROM chain
  JOIN expected ON expected.migration_id = chain.migration_id
  WHERE chain.migration_id IS NOT NULL
), checks AS (
  SELECT
    EXISTS (SELECT 1 FROM chain WHERE version = (SELECT version FROM live))
      AS chain_reaches_live,
    EXISTS (
      SELECT 1 FROM needed
      LEFT JOIN {HISTORY_TABLE} history
        ON history.schema_name = needed.schema_name
       AND history.migration_id = needed.migration_id
       AND history.schema_version = needed.target_version
       AND history.source_path = needed.source_path
       AND history.source_sha256 = needed.source_sha256
       AND NOT history.is_baseline
      WHERE history.migration_id IS NULL
    ) AS missing_history,
    EXISTS (
      SELECT 1 FROM {HISTORY_TABLE} history
      WHERE history.schema_name = {_sql_literal(schema)}
        AND NOT history.is_baseline
        AND NOT EXISTS (
          SELECT 1 FROM needed
          WHERE needed.migration_id = history.migration_id
        )
    ) AS extra_history
)
SELECT 1 / CASE
  WHEN chain_reaches_live AND NOT missing_history AND NOT extra_history THEN 1
  ELSE 0
END
FROM checks;
"""


def _history_preflight_sql(
    migrations: tuple[Migration, ...],
    canonical_versions: dict[str, str],
    baselines: tuple[bootstrap.Baseline, ...] | None = None,
    profile: MigrationProfile = DEVELOPMENT_PROFILE,
) -> str:
    del canonical_versions
    if baselines is None:
        baselines = bootstrap.load_baseline_manifest()
    expected = _expected_values(migrations)
    recognized_baselines = _baseline_values(baselines)
    return rf"""
SET ROLE {profile.owners["pricing"]};
DO $$
BEGIN
  IF (SELECT count(*) FROM {HISTORY_TABLE} WHERE is_baseline) <> 2
     OR (SELECT count(*) FROM {HISTORY_TABLE}
         WHERE schema_name = 'pricing' AND is_baseline) <> 1
     OR (SELECT count(*) FROM {HISTORY_TABLE}
         WHERE schema_name = 'oracle' AND is_baseline) <> 1
     OR EXISTS (
       SELECT 1 FROM {HISTORY_TABLE} history
       WHERE history.is_baseline
         AND NOT EXISTS (
           SELECT 1 FROM ({recognized_baselines}) AS baseline(
             schema_name, schema_version, migration_id, source_path,
             source_sha256, evidence
           )
           WHERE baseline.schema_name = history.schema_name
             AND baseline.schema_version = history.schema_version
             AND baseline.migration_id = history.migration_id
             AND baseline.source_path = history.source_path
             AND baseline.source_sha256 = history.source_sha256
             AND baseline.evidence = history.evidence
         )
     )
  THEN
    RAISE EXCEPTION '{profile.name} migration baseline is not exact';
  END IF;
END $$;
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM {HISTORY_TABLE} history
    WHERE NOT history.is_baseline AND NOT EXISTS (
      SELECT 1 FROM ({expected}) AS expected(
        schema_name, previous_version, target_version, migration_id, source_path, source_sha256
      )
      WHERE expected.schema_name = history.schema_name
        AND expected.target_version = history.schema_version
        AND expected.migration_id = history.migration_id
        AND expected.source_path = history.source_path
        AND expected.source_sha256 = history.source_sha256
    )
  ) THEN
    RAISE EXCEPTION 'migration history contains an unknown or edited source';
  END IF;
  IF EXISTS (
    SELECT 1 FROM ({expected}) AS expected(
      schema_name, previous_version, target_version, migration_id, source_path, source_sha256
    )
    JOIN {HISTORY_TABLE} history
      ON history.schema_name = expected.schema_name
     AND history.migration_id = expected.migration_id
    WHERE history.is_baseline
       OR history.schema_version <> expected.target_version
       OR history.source_path <> expected.source_path
       OR history.source_sha256 <> expected.source_sha256
       OR history.evidence !~ '^commit=[0-9a-f]{{40}};run=[0-9a-f]{{8}}-[0-9a-f]{{4}}-[1-5][0-9a-f]{{3}}-[89ab][0-9a-f]{{3}}-[0-9a-f]{{12}}$'
  ) THEN
    RAISE EXCEPTION 'migration history metadata is not exact';
  END IF;
END $$;
RESET ROLE;
SET ROLE {profile.owners["pricing"]};
{_history_chain_sql("pricing", "SELECT version FROM pricing.schema_version WHERE singleton", expected)}
{_history_chain_sql("oracle", "VALUES (:'oracle_before')", expected)}
RESET ROLE;
"""


def _migration_sql(
    migration: Migration,
    rendered_path: Path,
    commit: str,
    run_id: str,
    profile: MigrationProfile = DEVELOPMENT_PROFILE,
) -> str:
    owner = profile.owners[migration.schema]
    apply_variable = f"apply_{migration.number}"
    evidence = f"commit={commit};run={run_id}"
    post_migration_guard = (
        _production_postgis_type_guard() if profile is PRODUCTION_PROFILE else ""
    )
    return rf"""
SET ROLE {profile.owners["pricing"]};
SELECT NOT EXISTS (
  SELECT 1 FROM {HISTORY_TABLE}
  WHERE schema_name = {_sql_literal(migration.schema)}
    AND migration_id = {_sql_literal(migration.migration_id)}
) AS no_history_{migration.number}\gset
SET ROLE {owner};
SELECT (SELECT version FROM {migration.schema}.schema_version WHERE singleton)
    = {_sql_literal(migration.previous)}
    AND (:'no_history_{migration.number}' = 't') AS {apply_variable}\gset
\if :{apply_variable}
\ir {_psql_path(rendered_path)}
{post_migration_guard}
RESET ROLE;
SET ROLE {profile.owners["pricing"]};
INSERT INTO {HISTORY_TABLE} (
  schema_name, schema_version, migration_id, source_path, source_sha256, evidence, is_baseline
) VALUES (
  {_sql_literal(migration.schema)}, {_sql_literal(migration.target)},
  {_sql_literal(migration.migration_id)}, {_sql_literal(migration.path)},
  {_sql_literal(migration.source_sha256)}, {_sql_literal(evidence)}, false
);
COMMIT;
\echo TOLLCHAT_APPLIED_{run_id} {migration.path}
\endif
RESET ROLE;
"""


def _final_sql(
    migrations: tuple[Migration, ...],
    canonical_versions: dict[str, str],
    run_id: str,
    profile: MigrationProfile = DEVELOPMENT_PROFILE,
) -> str:
    expected = _expected_values(migrations)
    return rf"""
SET ROLE {profile.owners["pricing"]};
DO $$
BEGIN
  IF (SELECT version FROM pricing.schema_version WHERE singleton) <> {_sql_literal(canonical_versions["pricing"])}
     OR EXISTS (
       SELECT 1 FROM {HISTORY_TABLE} history
       WHERE history.schema_name IN ('pricing', 'oracle') AND NOT history.is_baseline
         AND NOT EXISTS (
           SELECT 1 FROM ({expected}) AS expected(
             schema_name, previous_version, target_version, migration_id, source_path, source_sha256
           )
           WHERE expected.schema_name = history.schema_name
             AND expected.target_version = history.schema_version
             AND expected.migration_id = history.migration_id
             AND expected.source_path = history.source_path
             AND expected.source_sha256 = history.source_sha256
         )
     ) THEN
    RAISE EXCEPTION 'pricing canonical version or history verification failed';
  END IF;
END $$;
RESET ROLE;
SET ROLE {profile.owners["oracle"]};
DO $$
BEGIN
  IF (SELECT version FROM oracle.schema_version WHERE singleton) <> {_sql_literal(canonical_versions["oracle"])} THEN
    RAISE EXCEPTION 'oracle canonical version or history verification failed';
  END IF;
END $$;
SELECT version AS oracle_after FROM oracle.schema_version WHERE singleton\gset
RESET ROLE;
SET ROLE {profile.owners["pricing"]};
SELECT version AS pricing_after FROM pricing.schema_version WHERE singleton\gset
{_history_chain_sql("pricing", "SELECT version FROM pricing.schema_version WHERE singleton", expected)}
{_history_chain_sql("oracle", "VALUES (:'oracle_after')", expected)}
RESET ROLE;
\echo TOLLCHAT_RESULT_{run_id} :pricing_before :oracle_before :pricing_after :oracle_after
SELECT pg_advisory_unlock(hashtext({_sql_literal(profile.lock_name)}));
"""


def _session_sql(
    migrations: tuple[Migration, ...],
    canonical_versions: dict[str, str],
    rendered: dict[str, Path],
    commit: str,
    run_id: str,
    baselines: tuple[bootstrap.Baseline, ...] | None = None,
    profile: MigrationProfile = DEVELOPMENT_PROFILE,
) -> str:
    if baselines is None:
        baselines = bootstrap.load_baseline_manifest()
    lines = [
        "\\pset pager off",
        "\\set ON_ERROR_STOP on",
        _identity_sql(profile),
        f"SELECT pg_advisory_lock(hashtext({_sql_literal(profile.lock_name)}));",
        f"SET ROLE {profile.owners['pricing']};",
        "SELECT version AS pricing_before FROM pricing.schema_version WHERE singleton\\gset",
        "RESET ROLE;",
        f"SET ROLE {profile.owners['oracle']};",
        "SELECT version AS oracle_before FROM oracle.schema_version WHERE singleton\\gset",
        "RESET ROLE;",
        _history_preflight_sql(migrations, canonical_versions, baselines, profile),
    ]
    if profile is PRODUCTION_PROFILE:
        lines.insert(3, _production_postgis_type_guard())
    lines.extend(
        _migration_sql(migration, rendered[migration.path], commit, run_id, profile)
        for migration in migrations
    )
    # Keep the established development hook signature used by the disposable
    # atomicity probe; production needs its distinct baseline evidence.
    if profile is DEVELOPMENT_PROFILE:
        lines.append(_final_sql(migrations, canonical_versions, run_id))
    else:
        lines.append(_final_sql(migrations, canonical_versions, run_id, profile))
    return "\n".join(lines)


def _psql_environment(
    profile: MigrationProfile = DEVELOPMENT_PROFILE,
) -> dict[str, str]:
    environment = os.environ.copy()
    transport = environment.pop("PGHOSTADDR", None)
    for key in ("PGDATABASE", "PGUSER", "PGSERVICE", "PGSERVICEFILE"):
        environment.pop(key, None)
    if profile is PRODUCTION_PROFILE:
        production_host = environment.pop("PGHOST", None)
        production_port = environment.pop("PGPORT", None)
        if (
            not isinstance(production_host, str)
            or not PRODUCTION_RDS_ENDPOINT.fullmatch(production_host)
            or production_port != PRODUCTION_RDS_PORT
            or transport is None
        ):
            raise MigrationError("production transport is not the fixed RDS endpoint")
        try:
            address = ipaddress.ip_address(transport)
        except ValueError as error:
            raise MigrationError(
                "production transport is not a private IPv4 address"
            ) from error
        if address not in profile.transport_network:
            raise MigrationError("production transport is not a private IPv4 address")
        environment.update(
            {
                "PGHOST": production_host,
                "PGHOSTADDR": transport,
                "PGPORT": PRODUCTION_RDS_PORT,
            }
        )
    elif transport is not None:
        try:
            address = ipaddress.ip_address(transport)
        except ValueError:
            address = None
        if address is not None and address in profile.transport_network:
            environment["PGHOSTADDR"] = transport
    environment.update({"PGDATABASE": profile.database, "PGUSER": profile.user})
    return environment


def _parse_result(stdout: str, run_id: str) -> tuple[dict[str, str], list[str]]:
    marker = f"TOLLCHAT_RESULT_{run_id} "
    result_line = next(
        (line for line in stdout.splitlines() if line.startswith(marker)), None
    )
    if result_line is None:
        raise MigrationError("migration session did not emit a verified result")
    fields = result_line[len(marker) :].split()
    if len(fields) != 4:
        raise MigrationError("migration session result was malformed")
    applied_marker = f"TOLLCHAT_APPLIED_{run_id} "
    applied = [
        line[len(applied_marker) :]
        for line in stdout.splitlines()
        if line.startswith(applied_marker)
    ]
    return {
        "pricing_before": fields[0],
        "oracle_before": fields[1],
        "pricing_after": fields[2],
        "oracle_after": fields[3],
    }, applied


def run(profile: MigrationProfile = DEVELOPMENT_PROFILE) -> dict[str, object]:
    if profile not in (DEVELOPMENT_PROFILE, PRODUCTION_PROFILE):
        raise MigrationError("migration profile is not fixed")
    baselines = (
        bootstrap.load_baseline_manifest()
        if profile is DEVELOPMENT_PROFILE
        else _production_baselines()
    )
    schemas, canonical_versions = (
        _registry() if profile is DEVELOPMENT_PROFILE else _registry(profile)
    )
    migrations = _migration_candidates(schemas)
    if profile is PRODUCTION_PROFILE:
        migrations = _production_migrations(migrations)
    commit = _run_capture("git", "rev-parse", "HEAD")
    if not COMMIT_PATTERN.fullmatch(commit):
        raise MigrationError("current checkout commit is not a canonical SHA-1")
    run_id = str(uuid.uuid4())
    evidence = f"commit={commit};run={run_id}"
    if not EVIDENCE_PATTERN.fullmatch(evidence):
        raise MigrationError("run evidence did not match the fixed grammar")
    with tempfile.TemporaryDirectory(
        prefix=f"nova-toll-{profile.name}-migrations-"
    ) as directory:
        rendered: dict[str, Path] = {}
        captured_sources: dict[str, bytes] = {}
        private = Path(directory)
        private.chmod(0o700)
        _assert_migration_tree()
        for migration in migrations:
            source = ROOT / migration.path
            captured_source = private / "sources" / migration.path
            destination = private / migration.path
            captured_source.parent.mkdir(parents=True, exist_ok=True)
            destination.parent.mkdir(parents=True, exist_ok=True)
            committed = _committed_bytes(migration.path)
            if hashlib.sha256(committed).hexdigest() != migration.source_sha256:
                raise MigrationError(
                    f"committed migration changed while being inspected: {migration.path}"
                )
            _assert_source_bytes(migration.path, source, committed)
            captured_source.write_bytes(committed)
            captured_source.chmod(0o600)
            if profile is DEVELOPMENT_PROFILE:
                bootstrap.render(captured_source, destination)
            else:
                destination.write_bytes(committed)
            _remove_terminal_commit(destination)
            destination.chmod(0o600)
            rendered[migration.path] = destination
            captured_sources[migration.path] = committed
            _assert_source_bytes(migration.path, source, committed)
        _assert_migration_tree()
        for migration in migrations:
            _assert_source_bytes(
                migration.path, ROOT / migration.path, captured_sources[migration.path]
            )
        session = (
            _session_sql(migrations, canonical_versions, rendered, commit, run_id)
            if profile is DEVELOPMENT_PROFILE
            else _session_sql(
                migrations,
                canonical_versions,
                rendered,
                commit,
                run_id,
                baselines,
                profile,
            )
        )
        result = subprocess.run(
            ["psql", "-X", "--no-psqlrc", "-v", "ON_ERROR_STOP=1"],
            input=session,
            text=True,
            capture_output=True,
            env=(
                _psql_environment()
                if profile is DEVELOPMENT_PROFILE
                else _psql_environment(profile)
            ),
            cwd=ROOT,
            check=False,
        )
        if result.returncode != 0:
            raise MigrationError(f"{profile.name} migration session failed")
        versions, applied = _parse_result(result.stdout, run_id)
    if (
        versions["pricing_after"] != canonical_versions["pricing"]
        or versions["oracle_after"] != canonical_versions["oracle"]
    ):
        raise MigrationError(
            f"{profile.name} migration session ended before canonical versions"
        )
    return {
        "database": profile.database,
        "user": profile.user,
        "before": {
            "pricing": versions["pricing_before"],
            "oracle": versions["oracle_before"],
        },
        "after": {
            "pricing": versions["pricing_after"],
            "oracle": versions["oracle_after"],
        },
        "applied": applied,
        "commit": commit,
        "run_id": run_id,
        "status": "ok",
    }


def _production_baselines() -> tuple[bootstrap.Baseline, ...]:
    """Bind the recurring runner to the two immutable adopted rows."""
    return tuple(
        bootstrap.Baseline(
            schema=baseline.schema,
            version=baseline.version,
            migration_id=baseline.migration_id,
            source_path=baseline.source_path,
            source_sha256=baseline.source_sha256,
            evidence=adoption.ADOPTION_EVIDENCE,
        )
        for baseline in bootstrap.load_baseline_manifest()
    )


def _production_identity_sql() -> str:
    """Check only recurring-production invariants, never adoption inventories."""
    return r"""
DO $$
DECLARE
  migrator oid;
  pricing_owner oid;
  oracle_owner oid;
BEGIN
  IF current_database() <> 'nova_toll'
     OR current_user <> 'schema_migrator_production'
     OR (SELECT shobj_description(oid, 'pg_database') FROM pg_database
         WHERE datname = current_database()) IS DISTINCT FROM 'environment=production' THEN
    RAISE EXCEPTION 'production migration identity is not exact';
  END IF;
  SELECT oid INTO STRICT migrator FROM pg_roles WHERE rolname = 'schema_migrator_production';
  SELECT oid INTO STRICT pricing_owner FROM pg_roles WHERE rolname = 'pricing_owner';
  SELECT oid INTO STRICT oracle_owner FROM pg_roles WHERE rolname = 'oracle_owner';
  IF NOT EXISTS (
       SELECT 1 FROM pg_roles WHERE oid = migrator
       AND rolcanlogin AND NOT rolsuper AND NOT rolcreatedb AND NOT rolcreaterole
       AND NOT rolinherit AND NOT rolreplication AND NOT rolbypassrls
     )
     OR NOT EXISTS (
       SELECT 1 FROM pg_roles WHERE oid = pricing_owner
       AND NOT rolcanlogin AND NOT rolsuper AND NOT rolcreatedb AND NOT rolcreaterole
       AND NOT rolinherit AND NOT rolreplication AND NOT rolbypassrls
     )
     OR NOT EXISTS (
       SELECT 1 FROM pg_roles WHERE oid = oracle_owner
       AND NOT rolcanlogin AND NOT rolsuper AND NOT rolcreatedb AND NOT rolcreaterole
       AND rolinherit AND NOT rolreplication AND NOT rolbypassrls
     )
     OR (SELECT count(*) FROM pg_auth_members WHERE member = migrator) <> 3
     OR EXISTS (
       SELECT 1 FROM pg_auth_members membership
       JOIN pg_roles granted ON granted.oid = membership.roleid
       WHERE membership.member = migrator
         AND granted.rolname NOT IN ('rds_iam', 'pricing_owner', 'oracle_owner')
     )
     OR EXISTS (
       SELECT 1 FROM pg_auth_members membership JOIN pg_roles granted ON granted.oid = membership.roleid
       WHERE membership.member = migrator AND granted.rolname = 'rds_iam'
         AND (NOT membership.inherit_option OR NOT membership.set_option OR membership.admin_option)
     )
     OR EXISTS (
       SELECT 1 FROM pg_auth_members membership JOIN pg_roles granted ON granted.oid = membership.roleid
       WHERE membership.member = migrator AND granted.rolname IN ('pricing_owner', 'oracle_owner')
         AND (membership.inherit_option OR NOT membership.set_option OR membership.admin_option)
     )
     OR NOT has_database_privilege(current_user, 'nova_toll', 'CONNECT')
     OR EXISTS (
       SELECT 1 FROM pg_database
       WHERE datname = 'nova_toll_development'
         AND has_database_privilege(current_user, datname, 'CONNECT')
     ) THEN
    RAISE EXCEPTION 'production migration roles or memberships are not exact';
  END IF;
  IF NOT EXISTS (
       SELECT 1 FROM pg_class relation JOIN pg_namespace namespace ON namespace.oid = relation.relnamespace
       WHERE namespace.nspname = 'tollchat_migration' AND relation.relname = 'schema_history'
     )
     OR NOT EXISTS (
       SELECT 1 FROM pg_class relation JOIN pg_namespace namespace ON namespace.oid = relation.relnamespace
       WHERE namespace.nspname = 'tollchat_migration' AND relation.relname = 'schema_history'
         AND relation.relowner = pricing_owner
     )
     OR EXISTS (
       SELECT 1 FROM pg_namespace namespace CROSS JOIN LATERAL aclexplode(namespace.nspacl) privilege
       WHERE namespace.nspname IN ('pricing', 'oracle', 'tollchat_migration') AND privilege.grantee = migrator
       UNION ALL
       SELECT 1 FROM pg_class relation JOIN pg_namespace namespace ON namespace.oid = relation.relnamespace
       CROSS JOIN LATERAL aclexplode(relation.relacl) privilege
       WHERE namespace.nspname IN ('pricing', 'oracle', 'tollchat_migration') AND privilege.grantee = migrator
       UNION ALL
       SELECT 1 FROM pg_attribute attribute JOIN pg_class relation ON relation.oid = attribute.attrelid
       JOIN pg_namespace namespace ON namespace.oid = relation.relnamespace
       CROSS JOIN LATERAL aclexplode(attribute.attacl) privilege
       WHERE namespace.nspname IN ('pricing', 'oracle', 'tollchat_migration')
         AND attribute.attnum > 0 AND NOT attribute.attisdropped AND privilege.grantee = migrator
       UNION ALL
       SELECT 1 FROM pg_proc procedure JOIN pg_namespace namespace ON namespace.oid = procedure.pronamespace
       CROSS JOIN LATERAL aclexplode(procedure.proacl) privilege
       WHERE namespace.nspname IN ('pricing', 'oracle', 'tollchat_migration') AND privilege.grantee = migrator
       UNION ALL
       SELECT 1 FROM pg_type type JOIN pg_namespace namespace ON namespace.oid = type.typnamespace
       CROSS JOIN LATERAL aclexplode(type.typacl) privilege
       WHERE namespace.nspname IN ('pricing', 'oracle', 'tollchat_migration') AND privilege.grantee = migrator
     )
     OR EXISTS (
       SELECT 1 FROM pg_namespace namespace CROSS JOIN LATERAL aclexplode(namespace.nspacl) privilege
       WHERE namespace.nspname = 'tollchat_migration' AND privilege.grantee = 0
       UNION ALL
       SELECT 1 FROM pg_class relation JOIN pg_namespace namespace ON namespace.oid = relation.relnamespace
       CROSS JOIN LATERAL aclexplode(relation.relacl) privilege
       WHERE namespace.nspname = 'tollchat_migration' AND relation.relname = 'schema_history'
         AND privilege.grantee = 0
     )
     OR NOT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'pricing' AND nspowner = pricing_owner)
     OR NOT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'oracle' AND nspowner = oracle_owner)
     OR NOT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'tollchat_migration' AND nspowner = pricing_owner)
     OR EXISTS (
       SELECT 1 FROM pg_namespace WHERE nspname IN ('pricing', 'oracle', 'tollchat_migration') AND nspowner = migrator
     ) OR EXISTS (
       SELECT 1 FROM pg_class relation JOIN pg_namespace namespace ON namespace.oid = relation.relnamespace
       WHERE namespace.nspname IN ('pricing', 'oracle', 'tollchat_migration') AND relation.relowner = migrator
     ) OR EXISTS (
       SELECT 1 FROM pg_proc procedure JOIN pg_namespace namespace ON namespace.oid = procedure.pronamespace
       WHERE namespace.nspname IN ('pricing', 'oracle', 'tollchat_migration') AND procedure.proowner = migrator
     ) OR EXISTS (
       SELECT 1 FROM pg_type type JOIN pg_namespace namespace ON namespace.oid = type.typnamespace
       WHERE namespace.nspname IN ('pricing', 'oracle', 'tollchat_migration') AND type.typowner = migrator
     ) OR EXISTS (
       SELECT 1 FROM pg_class relation JOIN pg_namespace namespace ON namespace.oid = relation.relnamespace
       WHERE namespace.nspname = 'pricing' AND relation.relowner <> pricing_owner
     ) OR EXISTS (
       SELECT 1 FROM pg_proc procedure JOIN pg_namespace namespace ON namespace.oid = procedure.pronamespace
       WHERE namespace.nspname = 'pricing' AND procedure.proowner <> pricing_owner
     ) OR EXISTS (
       SELECT 1 FROM pg_type type JOIN pg_namespace namespace ON namespace.oid = type.typnamespace
       WHERE namespace.nspname = 'pricing' AND type.typowner <> pricing_owner
     ) OR EXISTS (
       SELECT 1 FROM pg_class relation JOIN pg_namespace namespace ON namespace.oid = relation.relnamespace
       WHERE namespace.nspname = 'oracle' AND relation.relkind IN ('r', 'v', 'm', 'f', 'p')
         AND NOT EXISTS (
           SELECT 1 FROM pg_depend dependency JOIN pg_extension extension ON extension.oid = dependency.refobjid
           WHERE dependency.classid = 'pg_class'::regclass AND dependency.objid = relation.oid
             AND dependency.deptype = 'e'
         ) AND relation.relowner <> oracle_owner
     ) OR EXISTS (
       SELECT 1 FROM pg_proc procedure JOIN pg_namespace namespace ON namespace.oid = procedure.pronamespace
       WHERE namespace.nspname = 'oracle' AND NOT EXISTS (
         SELECT 1 FROM pg_depend dependency JOIN pg_extension extension ON extension.oid = dependency.refobjid
         WHERE dependency.classid = 'pg_proc'::regclass AND dependency.objid = procedure.oid
           AND dependency.deptype = 'e'
       ) AND procedure.proowner <> oracle_owner
     ) OR EXISTS (
       SELECT 1 FROM pg_type type JOIN pg_namespace namespace ON namespace.oid = type.typnamespace
       WHERE namespace.nspname = 'oracle' AND NOT EXISTS (
         SELECT 1 FROM pg_depend dependency JOIN pg_extension extension ON extension.oid = dependency.refobjid
         WHERE dependency.classid = 'pg_type'::regclass AND dependency.objid = type.oid
           AND dependency.deptype = 'e'
       ) AND type.typowner <> oracle_owner
     ) THEN
    RAISE EXCEPTION 'production migration ownership or direct ACL is not exact';
  END IF;
END $$;
"""


def _production_postgis_type_guard() -> str:
    """The approved RDS-owned PostGIS type exception, and nothing else."""
    return "DO $$\nBEGIN\n" + adoption.production_rds_postgis_type_guard() + "END $$;\n"


def run_production() -> dict[str, object]:
    return run(PRODUCTION_PROFILE)


def main() -> int:
    if len(sys.argv) != 1:
        print(f"usage: {Path(sys.argv[0]).name}", file=sys.stderr)
        return 2
    try:
        print(json.dumps(run(), sort_keys=True, separators=(",", ":")))
    except (MigrationError, OSError, ValueError, subprocess.SubprocessError):
        print("development migrations failed", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
