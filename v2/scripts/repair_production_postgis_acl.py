#!/usr/bin/env python3
"""Repair the two fixed PostGIS type ACLs before baseline adoption."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import adopt_production_baseline as adopt

ROOT = adopt.ROOT
APPROVAL_ENV = "NOVA_TOLL_PRODUCTION_APPROVAL"
APPROVAL_TOKEN = "REPAIR_NOVA_TOLL_PRODUCTION_POSTGIS_ACL"
SUCCESS_MARKER = "TOLLCHAT_PRODUCTION_POSTGIS_ACL_REPAIRED"


class RepairError(RuntimeError):
    """A sanitized, phase-specific failure from the repair boundary."""

    def __init__(self, phase: str) -> None:
        super().__init__(phase)
        self.phase = phase


def repair_sql() -> str:
    """Render the one fixed transaction that repairs the two type ACLs."""

    return f"""\\set ON_ERROR_STOP on
BEGIN;
SET LOCAL search_path = pg_catalog, pg_temp;
SET LOCAL lock_timeout = '3s';
SET LOCAL statement_timeout = '10s';
SELECT pg_advisory_xact_lock(hashtextextended('tollchat-production-postgis-acl-repair', 0));

CREATE TEMP TABLE _postgis_acl_repair_state (needs_repair boolean NOT NULL) ON COMMIT DROP;
DO $$
DECLARE
  target record;
  owner_oid oid;
  oracle_owner_oid oid;
  public_usage integer;
  owner_usage integer;
  oracle_owner_usage integer;
  acl_rows integer;
  drift_count integer := 0;
  repaired_count integer := 0;
BEGIN
  SELECT oid INTO owner_oid FROM pg_roles WHERE rolname = 'rdsadmin';
  SELECT oid INTO oracle_owner_oid FROM pg_roles WHERE rolname = 'oracle_owner';
  IF current_database() <> 'nova_toll'
     OR current_user <> 'nova_toll_admin'
     OR owner_oid IS NULL
     OR oracle_owner_oid IS NULL
     OR NOT EXISTS (
       SELECT 1 FROM pg_roles WHERE rolname = current_user AND rolinherit
     )
     OR (SELECT count(*)
         FROM pg_auth_members membership
         JOIN pg_roles granted ON granted.oid = membership.roleid
         JOIN pg_roles member ON member.oid = membership.member
         WHERE granted.rolname = 'rds_superuser'
           AND member.rolname = current_user) <> 1
     OR EXISTS (
       SELECT 1
       FROM pg_auth_members membership
       JOIN pg_roles granted ON granted.oid = membership.roleid
       JOIN pg_roles member ON member.oid = membership.member
       WHERE granted.rolname = 'rds_superuser'
         AND member.rolname = current_user
         AND (NOT membership.inherit_option
              OR NOT membership.set_option
              OR membership.admin_option)
     )
     OR EXISTS (
       SELECT 1
       FROM pg_auth_members membership
       JOIN pg_roles granted ON granted.oid = membership.roleid
       JOIN pg_roles member ON member.oid = membership.member
       WHERE granted.rolname = 'rdsadmin' AND member.rolname = current_user
     )
     OR NOT EXISTS (
       SELECT 1 FROM pg_namespace
       WHERE nspname = 'oracle' AND nspowner = oracle_owner_oid
     )
     OR NOT EXISTS (
       SELECT 1
       FROM pg_extension extension
       JOIN pg_namespace namespace ON namespace.oid = extension.extnamespace
       WHERE extension.extname = 'postgis'
         AND extension.extversion = '3.5.6'
         AND namespace.nspname = 'oracle'
         AND extension.extowner = owner_oid
     ) THEN
    RAISE EXCEPTION 'fixed PostGIS repair identity guard failed';
  END IF;

  FOR target IN
    SELECT type.oid, type.typname, type.typowner, type.typacl
    FROM pg_type type
    JOIN pg_namespace namespace ON namespace.oid = type.typnamespace
    WHERE namespace.nspname = 'oracle'
      AND type.typname IN ('geometry', 'geography')
    ORDER BY type.typname
  LOOP
    IF target.typowner <> owner_oid
       OR (SELECT count(*) FROM pg_depend dependency
           JOIN pg_extension extension ON extension.oid = dependency.refobjid
           WHERE dependency.classid = 'pg_type'::regclass
             AND dependency.objid = target.oid
             AND dependency.refclassid = 'pg_extension'::regclass
             AND dependency.deptype = 'e'
             AND extension.extname = 'postgis') <> 1 THEN
      RAISE EXCEPTION 'fixed PostGIS repair target guard failed';
    END IF;
    SELECT count(*) FILTER (WHERE privilege.grantee = 0
                              AND privilege.privilege_type = 'USAGE'
                              AND NOT privilege.is_grantable),
           count(*) FILTER (WHERE privilege.grantee = owner_oid
                              AND privilege.grantor = owner_oid
                              AND privilege.privilege_type = 'USAGE'
                              AND NOT privilege.is_grantable),
           count(*) FILTER (WHERE privilege.grantee = oracle_owner_oid
                              AND privilege.privilege_type = 'USAGE'
                              AND NOT privilege.is_grantable),
           count(*)
      INTO public_usage, owner_usage, oracle_owner_usage, acl_rows
      FROM aclexplode(target.typacl) privilege;
    IF acl_rows <> 2 OR owner_usage <> 1 THEN
      RAISE EXCEPTION 'fixed PostGIS repair ACL guard failed';
    ELSIF public_usage = 1 AND oracle_owner_usage = 0 THEN
      drift_count := drift_count + 1;
    ELSIF public_usage = 0 AND oracle_owner_usage = 1 THEN
      repaired_count := repaired_count + 1;
    ELSE
      RAISE EXCEPTION 'fixed PostGIS repair ACL guard failed';
    END IF;
  END LOOP;
  IF drift_count + repaired_count <> 2 OR (drift_count <> 0 AND repaired_count <> 0) THEN
    RAISE EXCEPTION 'fixed PostGIS repair target inventory failed';
  END IF;
  INSERT INTO _postgis_acl_repair_state VALUES (drift_count = 2);
END $$;

CREATE TEMP TABLE _postgis_acl_repair_snapshot (
  object_kind text NOT NULL,
  object_oid oid NOT NULL,
  auxiliary_oid oid NOT NULL DEFAULT 0,
  owner_oid oid,
  acl text,
  detail text NOT NULL DEFAULT ''
) ON COMMIT DROP;
INSERT INTO _postgis_acl_repair_snapshot
SELECT 'namespace', namespace.oid, 0, namespace.nspowner, namespace.nspacl::text, namespace.nspname
FROM pg_namespace namespace WHERE namespace.nspname = 'oracle';
INSERT INTO _postgis_acl_repair_snapshot
SELECT 'class', relation.oid, 0, relation.relowner, relation.relacl::text, relation.relname
FROM pg_class relation JOIN pg_namespace namespace ON namespace.oid = relation.relnamespace
WHERE namespace.nspname = 'oracle';
INSERT INTO _postgis_acl_repair_snapshot
SELECT 'procedure', procedure.oid, 0, procedure.proowner, procedure.proacl::text,
       procedure.proname || '(' || oidvectortypes(procedure.proargtypes) || ')'
FROM pg_proc procedure JOIN pg_namespace namespace ON namespace.oid = procedure.pronamespace
WHERE namespace.nspname = 'oracle';
INSERT INTO _postgis_acl_repair_snapshot
SELECT 'type', type.oid, 0, type.typowner, type.typacl::text, type.typname
FROM pg_type type JOIN pg_namespace namespace ON namespace.oid = type.typnamespace
WHERE namespace.nspname = 'oracle';
INSERT INTO _postgis_acl_repair_snapshot
SELECT 'extension', extension.oid, extension.extnamespace, extension.extowner, NULL,
       extension.extname || '|' || extension.extversion || '|' || namespace.nspname
FROM pg_extension extension JOIN pg_namespace namespace ON namespace.oid = extension.extnamespace
WHERE extension.extname = 'postgis';
INSERT INTO _postgis_acl_repair_snapshot
SELECT 'dependency', dependency.objid, dependency.refobjid, NULL, NULL,
       dependency.classid::text || '|' || dependency.refclassid::text || '|' || dependency.deptype::text
FROM pg_depend dependency
JOIN pg_extension extension ON extension.oid = dependency.refobjid
JOIN pg_type type ON type.oid = dependency.objid
JOIN pg_namespace namespace ON namespace.oid = type.typnamespace
WHERE dependency.classid = 'pg_type'::regclass
  AND dependency.refclassid = 'pg_extension'::regclass
  AND dependency.deptype = 'e'
  AND extension.extname = 'postgis'
  AND namespace.nspname = 'oracle'
  AND type.typname IN ('geometry', 'geography');

DO $$
BEGIN
  IF (SELECT needs_repair FROM _postgis_acl_repair_state) THEN
    REVOKE USAGE ON TYPE oracle.geometry, oracle.geography FROM PUBLIC;
    GRANT USAGE ON TYPE oracle.geometry, oracle.geography TO oracle_owner;
  END IF;
END $$;

DO $$
DECLARE
  target record;
  owner_oid oid;
  oracle_owner_oid oid;
BEGIN
  SELECT oid INTO owner_oid FROM pg_roles WHERE rolname = 'rdsadmin';
  SELECT oid INTO oracle_owner_oid FROM pg_roles WHERE rolname = 'oracle_owner';
  FOR target IN
    SELECT type.oid, type.typowner, type.typacl FROM pg_type type
    JOIN pg_namespace namespace ON namespace.oid = type.typnamespace
    WHERE namespace.nspname = 'oracle' AND type.typname IN ('geometry', 'geography')
  LOOP
    IF target.typowner <> owner_oid
       OR (SELECT count(*) FROM aclexplode(target.typacl)) <> 2
       OR (SELECT count(*) FROM aclexplode(target.typacl) privilege
           WHERE privilege.grantee = owner_oid AND privilege.grantor = owner_oid
             AND privilege.privilege_type = 'USAGE' AND NOT privilege.is_grantable) <> 1
       OR (SELECT count(*) FROM aclexplode(target.typacl) privilege
           WHERE privilege.grantee = 0 AND privilege.privilege_type = 'USAGE') <> 0
       OR (SELECT count(*) FROM aclexplode(target.typacl) privilege
           WHERE privilege.grantee = oracle_owner_oid
             AND privilege.privilege_type = 'USAGE' AND NOT privilege.is_grantable) <> 1 THEN
      RAISE EXCEPTION 'fixed PostGIS repair postflight ACL guard failed';
    END IF;
  END LOOP;
  IF EXISTS (
    WITH current_snapshot AS (
      SELECT 'namespace'::text AS object_kind, namespace.oid AS object_oid, 0::oid AS auxiliary_oid,
             namespace.nspowner AS owner_oid, namespace.nspacl::text AS acl,
             namespace.nspname::text AS detail
      FROM pg_namespace namespace WHERE namespace.nspname = 'oracle'
      UNION ALL
      SELECT 'class', relation.oid, 0::oid, relation.relowner, relation.relacl::text, relation.relname
      FROM pg_class relation JOIN pg_namespace namespace ON namespace.oid = relation.relnamespace
      WHERE namespace.nspname = 'oracle'
      UNION ALL
      SELECT 'procedure', procedure.oid, 0::oid, procedure.proowner, procedure.proacl::text,
             procedure.proname || '(' || oidvectortypes(procedure.proargtypes) || ')'
      FROM pg_proc procedure JOIN pg_namespace namespace ON namespace.oid = procedure.pronamespace
      WHERE namespace.nspname = 'oracle'
      UNION ALL
      SELECT 'type', type.oid, 0::oid, type.typowner, type.typacl::text, type.typname
      FROM pg_type type JOIN pg_namespace namespace ON namespace.oid = type.typnamespace
      WHERE namespace.nspname = 'oracle'
      UNION ALL
      SELECT 'extension', extension.oid, extension.extnamespace, extension.extowner, NULL::text,
             extension.extname || '|' || extension.extversion || '|' || namespace.nspname
      FROM pg_extension extension JOIN pg_namespace namespace ON namespace.oid = extension.extnamespace
      WHERE extension.extname = 'postgis'
      UNION ALL
      SELECT 'dependency', dependency.objid, dependency.refobjid, NULL::oid, NULL::text,
             dependency.classid::text || '|' || dependency.refclassid::text || '|' || dependency.deptype::text
      FROM pg_depend dependency
      JOIN pg_extension extension ON extension.oid = dependency.refobjid
      JOIN pg_type type ON type.oid = dependency.objid
      JOIN pg_namespace namespace ON namespace.oid = type.typnamespace
      WHERE dependency.classid = 'pg_type'::regclass
        AND dependency.refclassid = 'pg_extension'::regclass
        AND dependency.deptype = 'e'
        AND extension.extname = 'postgis'
        AND namespace.nspname = 'oracle'
        AND type.typname IN ('geometry', 'geography')
    ), normalized_snapshot AS (
      SELECT snapshot.object_kind, snapshot.object_oid, snapshot.auxiliary_oid,
             snapshot.owner_oid,
             CASE WHEN snapshot.object_kind = 'type'
                         AND snapshot.detail IN ('geometry', 'geography')
                  THEN NULL ELSE snapshot.acl END AS acl,
             snapshot.detail
      FROM _postgis_acl_repair_snapshot snapshot
    ), normalized_current AS (
      SELECT current.object_kind, current.object_oid, current.auxiliary_oid,
             current.owner_oid,
             CASE WHEN current.object_kind = 'type'
                         AND current.detail IN ('geometry', 'geography')
                  THEN NULL ELSE current.acl END AS acl,
             current.detail
      FROM current_snapshot current
    )
    SELECT 1 FROM (
      (SELECT * FROM normalized_snapshot EXCEPT SELECT * FROM normalized_current)
      UNION ALL
      (SELECT * FROM normalized_current EXCEPT SELECT * FROM normalized_snapshot)
    ) difference
  ) THEN
    RAISE EXCEPTION 'fixed PostGIS repair boundary changed';
  END IF;
END $$;
COMMIT;
\\echo {SUCCESS_MARKER}
"""


def run() -> dict[str, str]:
    """Run the fixed repair once; callers must reconcile uncertain outcomes."""

    if os.environ.get(APPROVAL_ENV) != APPROVAL_TOKEN:
        raise RepairError("approval")
    try:
        identity = adopt._rds_identity()  # pyright: ignore[reportPrivateUsage]
        endpoint, url_port, rootcert = adopt._admin_url(  # pyright: ignore[reportPrivateUsage]
            identity.endpoint
        )
        secret = adopt._admin_secret(identity.secret_arn)  # pyright: ignore[reportPrivateUsage]
    except (adopt.AdoptionError, OSError, subprocess.SubprocessError) as error:
        raise RepairError("identity") from error
    if endpoint != identity.endpoint or (
        url_port is not None and url_port != identity.port
    ):
        raise RepairError("identity")
    environment = adopt._psql_environment(  # pyright: ignore[reportPrivateUsage]
        identity, secret, identity.port, rootcert
    )
    try:
        result = subprocess.run(
            ["psql", "-X", "--no-psqlrc", "--set", "ON_ERROR_STOP=1", "--quiet"],
            input=repair_sql(),
            text=True,
            capture_output=True,
            env=environment,
            cwd=ROOT,
            timeout=90,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise RepairError("outcome") from error
    finally:
        del environment, secret
    if (
        result.returncode != 0
        or result.stderr
        or result.stdout.splitlines().count(SUCCESS_MARKER) != 1
    ):
        raise RepairError("outcome")
    return {"database": adopt.DATABASE, "status": "committed"}


def main() -> int:
    if len(sys.argv) != 1:
        print(
            "production PostGIS ACL repair argument validation failed", file=sys.stderr
        )
        return 2
    try:
        print(json.dumps(run(), sort_keys=True, separators=(",", ":")))
    except RepairError as error:
        print(f"production PostGIS ACL repair {error.phase} failed", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
