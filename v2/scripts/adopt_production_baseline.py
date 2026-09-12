#!/usr/bin/env python3
"""Adopt the already deployed production schemas as immutable baselines.

This is a deliberately fixed-target, one-time operation.  It verifies the AWS
and PostgreSQL identity before opening one transaction; it does not accept a
database, manifest, endpoint, or migration path from its caller.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import ssl
import subprocess
import sys
from pathlib import Path
from types import MappingProxyType
from typing import NamedTuple, cast
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import bootstrap_development_database as bootstrap  # noqa: E402

ACCOUNT_ID = "920534282028"
REGION = "us-east-1"
DB_INSTANCE_IDENTIFIER = "nova-toll-db"
DATABASE = "nova_toll"
ADMIN_ROLE = "nova_toll_admin"
RDS_ENDPOINT_PATTERN = re.compile(
    r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?[.]rds[.]amazonaws[.]com\Z"
)
SECRET_ARN_PATTERN = re.compile(
    rf"arn:aws:secretsmanager:{re.escape(REGION)}:{ACCOUNT_ID}:secret:\S+\Z"
)
APPROVED_CA_SHA256 = "e5bb2084ccf45087bda1c9bffdea0eb15ee67f0b91646106e466714f9de3c7e3"
AWS_SERVICE_ENDPOINTS = MappingProxyType(
    {
        "sts": "https://sts.us-east-1.amazonaws.com",
        "rds": "https://rds.us-east-1.amazonaws.com",
        "secretsmanager": "https://secretsmanager.us-east-1.amazonaws.com",
    }
)
APPROVAL_TOKEN = "ADOPT_NOVA_TOLL_PRODUCTION_BASELINE"
APPROVAL_ENV = "NOVA_TOLL_PRODUCTION_APPROVAL"
ADMIN_URL_ENV = "NOVA_TOLL_ADMIN_URL"
EXPECTED_ENDPOINT_ENV = "NOVA_TOLL_EXPECTED_RDS_ENDPOINT"
HISTORY_SCHEMA = "tollchat_migration"
HISTORY_TABLE = "tollchat_migration.schema_history"
LOCK_NAME = "tollchat-production-baseline-adoption"
EXPECTED_CONNECTIONS = 996
ADOPTION_EVIDENCE = (
    "deployed canonical schema verified and adopted; no schema migration executed"
)

PRICING_TABLES = (
    "schema_version",
    "trip_pricing_i95",
    "trip_pricing_i66",
)
PRICING_VIEWS = (
    "current_trip_pricing_i95",
    "current_trip_pricing_i66",
    "current_i95_direction",
    "i95_modeled_od_proxy",
    "modeled_trip_pricing_i95",
    "modeled_current_trip_pricing_i95",
    "i66_pricing_comparisons",
    "i95_i495_pricing_comparisons",
    "i66_ballpark_samples",
    "i95_i495_ballpark_samples",
)
PRICING_OBJECTS = PRICING_TABLES + PRICING_VIEWS
PRICING_INDEXES = (
    "schema_version_pkey",
    "trip_pricing_i95_pkey",
    "trip_pricing_i95_od_lookup_idx",
    "trip_pricing_i66_pkey",
    "trip_pricing_i66_zone_lookup_idx",
)
PRICING_CATALOG_OBJECTS = PRICING_OBJECTS + PRICING_INDEXES
RUNTIME_ROLES = (
    "pricing_loader_writer",
    "pricing_reader",
    "tollchat_agent",
    "pricing_caller",
    "report_publisher",
)
DATABASE_ROLES = (*RUNTIME_ROLES, "oracle_owner")
OWNER_ROLES = ("pricing_owner", "oracle_owner")
ORACLE_APPLICATION_RELATIONS = (
    "schema_version",
    "toll_route_point",
    "toll_connection",
    "route_pricing_component",
)
ORACLE_APPLICATION_INDEXES = (
    "schema_version_pkey",
    "toll_route_point_pkey",
    "toll_route_point_network_id_source_node_id_point_type_direc_key",
    "toll_connection_pkey",
    "toll_connection_from_point_id_to_point_id_key",
    "toll_connection_from_point_idx",
)
ORACLE_APPLICATION_CATALOG_OBJECTS = (
    *ORACLE_APPLICATION_RELATIONS,
    *ORACLE_APPLICATION_INDEXES,
)
ORACLE_POSTGIS_CATALOG_OBJECTS = (
    "geography_columns",
    "geometry_columns",
    "geometry_dump",
    "spatial_ref_sys",
    "spatial_ref_sys_pkey",
    "valid_detail",
)
ORACLE_APPLICATION_FUNCTIONS = (
    "get_toll_route_prompt_points",
    "ramp_alternatives",
    "resolve_toll_route_internal",
    "resolve_toll_route",
    "route_pricing_legs",
    "validate_toll_route",
    "validate_pricing_route",
    "validate_ballpark_route",
    "get_priced_route_distance_miles",
    "i66_tolling_active",
    "get_i66_pricing_comparisons",
    "get_i95_i495_pricing_comparisons",
    "validate_ballpark_sample_request",
    "get_i66_ballpark_samples",
    "get_i95_i495_ballpark_samples",
    "get_annual_ballpark_summary",
    "get_i95_i495_report_inputs",
)
ORACLE_APPLICATION_SIGNATURES = (
    ("get_toll_route_prompt_points", ""),
    ("ramp_alternatives", "text, text, boolean"),
    ("resolve_toll_route_internal", "text, text, boolean"),
    ("resolve_toll_route", "text, text"),
    ("route_pricing_legs", "text[], text[]"),
    ("validate_toll_route", "text, text"),
    ("validate_pricing_route", "text, text"),
    ("validate_ballpark_route", "text, text"),
    ("get_priced_route_distance_miles", "jsonb"),
    ("i66_tolling_active", "text, timestamp without time zone"),
    ("get_i66_pricing_comparisons", "integer, integer, text"),
    ("get_i66_pricing_comparisons", "integer, integer"),
    ("get_i95_i495_pricing_comparisons", "integer"),
    (
        "validate_ballpark_sample_request",
        "time without time zone, date[], timestamp with time zone",
    ),
    (
        "get_i66_ballpark_samples",
        "integer, integer, text, time without time zone, date[], timestamp with time zone",
    ),
    (
        "get_i66_ballpark_samples",
        "integer, integer, time without time zone, date[], timestamp with time zone",
    ),
    (
        "get_i95_i495_ballpark_samples",
        "integer, time without time zone, date[], timestamp with time zone",
    ),
    (
        "get_annual_ballpark_summary",
        "jsonb, time without time zone, time without time zone, date[], jsonb, integer, timestamp with time zone",
    ),
    ("get_i95_i495_report_inputs", ""),
)
APPLICATION_DEFINITION_FINGERPRINTS = MappingProxyType(
    {
        "pricing.schema_version": "e952ca9c9ea6135734c76180e336e857cef45ccad6ce6133828f6d197ecbf524",
        "pricing.trip_pricing_i95": "16a71fd3892c590ce413dd99d6e1f881f20f0ac39bc97ff571ded1e71a74743f",
        "pricing.trip_pricing_i66": "e6470f1e33f4d5f6c875bf37d8a9dc64f00e031cd7fe9ca6b8e35075a661c424",
        "pricing.current_trip_pricing_i95": "03633b1e075226aaff017b7732a456a62c52d06fa3cbf6b39e5bf8037ab24399",
        "pricing.current_trip_pricing_i66": "6331024f0be13ccdae1cb836a73335e25c0b9a09fe66fc655d2a1d6f410ada68",
        "pricing.current_i95_direction": "95c6539ad7db982e559bd7036737b5ac6431313a6aaf71462bdf7b7dd36fde4e",
        "pricing.i95_modeled_od_proxy": "d06a0773b964ace18bc0c94886493a51543a4c3b5a26bdacbe00046bd0681471",
        "pricing.modeled_trip_pricing_i95": "a7a780aa4524cd4abed29ed765b39cd9463638361fbeb1147fd2f5c70b476cf2",
        "pricing.modeled_current_trip_pricing_i95": "fb60f25535d5dc92d4eae8048186b77acec271bf302ffa62b1174b7303bee33b",
        "pricing.i66_pricing_comparisons": "ae03d2423f3e8f34dd0c92be1ea83e31a4dc0c0302daf5d47c5ce0b5ff3ab08a",
        "pricing.i95_i495_pricing_comparisons": "7ca13fc0ee993857eb2a4c4e222b625b8b9c36716a3d2469d28599c243496cb0",
        "pricing.i66_ballpark_samples": "5b1cf4ab12de9faafe217ed57571287467106267082b4bdf69b8c5b39a72809d",
        "pricing.i95_i495_ballpark_samples": "92e7f6057aa5b49dfadba8457f12bfea7ff7565e9da1fde43fdb80c997b3368e",
        "oracle.schema_version": "4319dd9486f42a99c9f2b09dc66c65098e7111b5f9e03c551b37417b5236e964",
        "oracle.toll_route_point": "f10a8a4254ed19e1a8eb4602c7563eee9b1955bd8efa8657d2ea0f18c4c5363f",
        "oracle.toll_connection": "b08d0036c40d41c19ffe9954d301578a55342f7eec9f50347608b7f629ae890a",
        "oracle.route_pricing_component": "e3287098b6b6cc0a4723088acc858fbef1e1cb29fb2173a7c8207ebed680a2fb",
        "oracle.get_toll_route_prompt_points()": "8227549f86cc7fb309b2d9f87932442903905e6c3e442af132a1afbd7a2f192c",
        "oracle.ramp_alternatives(text, text, boolean)": "8803bf2d16204634d152850bdc9c129760708f359ddba3546bcb1c416fc84a47",
        "oracle.resolve_toll_route_internal(text, text, boolean)": "2fef1a8b98032af2d8022259485c7259d96f1f756224b7b94aa6a2154fd134e6",
        "oracle.resolve_toll_route(text, text)": "bf646bf2f3b2041bfb787e86dd2e9cae8dd4f11c06c0897a6b8ffa67d24d328b",
        "oracle.route_pricing_legs(text[], text[])": "beefd8b4ece23806969e30b07701965b645dfe42fe55987a7bc8e0602966cc0f",
        "oracle.validate_toll_route(text, text)": "9f35f80396770dff5c0a7198fc3446fa36cc81714ca7dd0b01634055a932b0cd",
        "oracle.validate_pricing_route(text, text)": "53c69752385f38ad8296a91b5c1793a8154bd48517d6145688782432a5cc77db",
        "oracle.validate_ballpark_route(text, text)": "fd0984dfc3e722563cb37c4deb4109bdec6cc0e5c5bd6d8800ee63c4b22e8f01",
        "oracle.get_priced_route_distance_miles(jsonb)": "7cc5436d8c6a59ab7c818a76183dc51ec9b546617a91ddad8b194f7bc366c325",
        "oracle.i66_tolling_active(text, timestamp without time zone)": "d57d7e10b31d7c659d1b29e0bf9d50372ac995b675525df2f7e17adcb31c8b94",
        "oracle.get_i66_pricing_comparisons(integer, integer, text)": "2228a8de24dd7a3b3a7024601c89a8a48b62321146ec3efde81b854d84b373bb",
        "oracle.get_i66_pricing_comparisons(integer, integer)": "7fbf86d2fbb6ed8d9f97e5ab645cc8df6b5c0a340daefce7c637c9adc06fedaa",
        "oracle.get_i95_i495_pricing_comparisons(integer)": "96ae13ca08f2e78ea9d18811a1a0a1483907384612a400079027ee34ba477492",
        "oracle.validate_ballpark_sample_request(time without time zone, date[], timestamp with time zone)": "6848eaf3445711d6aed0f6fcc2b93cc632e41f6e10f1a298d77a286923d707ae",
        "oracle.get_i66_ballpark_samples(integer, integer, text, time without time zone, date[], timestamp with time zone)": "c5b8938f70e1aaf552aa5f0010f3876bf54562643a71047b1847d7c68c365a77",
        "oracle.get_i66_ballpark_samples(integer, integer, time without time zone, date[], timestamp with time zone)": "d1317b309065c43e341a3e010f8a6c461acb90783970b57289aa0c2df4d3750f",
        "oracle.get_i95_i495_ballpark_samples(integer, time without time zone, date[], timestamp with time zone)": "f951ee4d02fff3ace2d6516a30bcdf4765069ee70c9f216292ab734a66241fd2",
        "oracle.get_annual_ballpark_summary(jsonb, time without time zone, time without time zone, date[], jsonb, integer, timestamp with time zone)": "0dcd4b49285a2b3f71b30803538c2116b3d3c4ea4093733ed0c6dd7c80f8dca7",
        "oracle.get_i95_i495_report_inputs()": "471943dcea829d284e85a432fef362e530912a2fd6335f98bfe39e4f316c4f4a",
    }
)
# Explicit runtime EXECUTE grants on the 19 application functions.  The
# identity argument strings use PostgreSQL's type-only catalog representation;
# owner ACL entries are implicit and are intentionally excluded.
ORACLE_FUNCTION_ACL_ALLOWLIST = (
    ("get_toll_route_prompt_points", "", "tollchat_agent"),
    ("validate_toll_route", "text, text", "tollchat_agent"),
    ("validate_pricing_route", "text, text", "pricing_caller"),
    ("get_i66_pricing_comparisons", "integer, integer, text", "pricing_caller"),
    ("get_i66_pricing_comparisons", "integer, integer", "pricing_caller"),
    ("get_i95_i495_pricing_comparisons", "integer", "pricing_caller"),
    ("validate_ballpark_route", "text, text", "pricing_caller"),
    ("get_priced_route_distance_miles", "jsonb", "pricing_caller"),
    (
        "get_i66_ballpark_samples",
        "integer, integer, text, time without time zone, date[], timestamp with time zone",
        "pricing_caller",
    ),
    (
        "get_i95_i495_ballpark_samples",
        "integer, time without time zone, date[], timestamp with time zone",
        "pricing_caller",
    ),
    (
        "get_annual_ballpark_summary",
        "jsonb, time without time zone, time without time zone, date[], jsonb, integer, timestamp with time zone",
        "pricing_caller",
    ),
    ("get_i95_i495_report_inputs", "", "report_publisher"),
)

# Non-owner grants from the reviewed canonical production contract.  Owner
# privileges are intentionally excluded: ownership changes are checked
# separately and PostgreSQL supplies the owner ACL.
PRICING_ACL_ALLOWLIST = MappingProxyType(
    {
        "schema": (
            ("pricing_loader_writer", "USAGE"),
            ("pricing_reader", "USAGE"),
            ("oracle_owner", "USAGE"),
        ),
        "schema_version": (("pricing_reader", "SELECT"),),
        "trip_pricing_i95": (
            ("pricing_loader_writer", "SELECT"),
            ("pricing_loader_writer", "INSERT"),
            ("pricing_loader_writer", "UPDATE"),
            ("pricing_reader", "SELECT"),
        ),
        "trip_pricing_i66": (
            ("pricing_loader_writer", "SELECT"),
            ("pricing_loader_writer", "INSERT"),
            ("pricing_loader_writer", "UPDATE"),
            ("pricing_reader", "SELECT"),
        ),
        "current_trip_pricing_i95": (("pricing_reader", "SELECT"),),
        "current_trip_pricing_i66": (("pricing_reader", "SELECT"),),
        "current_i95_direction": (
            ("pricing_reader", "SELECT"),
            ("oracle_owner", "SELECT"),
        ),
        "i95_modeled_od_proxy": (("pricing_reader", "SELECT"),),
        "modeled_trip_pricing_i95": (("pricing_reader", "SELECT"),),
        "modeled_current_trip_pricing_i95": (("pricing_reader", "SELECT"),),
        "i66_pricing_comparisons": (
            ("pricing_reader", "SELECT"),
            ("oracle_owner", "SELECT"),
        ),
        "i95_i495_pricing_comparisons": (
            ("pricing_reader", "SELECT"),
            ("oracle_owner", "SELECT"),
        ),
        "i66_ballpark_samples": (
            ("pricing_reader", "SELECT"),
            ("oracle_owner", "SELECT"),
        ),
        "i95_i495_ballpark_samples": (
            ("pricing_reader", "SELECT"),
            ("oracle_owner", "SELECT"),
        ),
    }
)

SCHEMA_VERSION_PATTERN = re.compile(
    r"^-- (?P<schema>[a-z][a-z0-9_]*) schema version: (?P<version>\S+)$",
    re.MULTILINE,
)
VERSION_PATTERN = re.compile(r"^(0|[1-9][0-9]*)[.](0|[1-9][0-9]*)[.](0|[1-9][0-9]*)$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class AdoptionError(RuntimeError):
    """A sanitized, expected failure from the adoption boundary."""


Baseline = bootstrap.Baseline


class RdsIdentity(NamedTuple):
    endpoint: str
    port: int
    secret_arn: str


class AdminSecret(NamedTuple):
    username: str
    password: str


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def load_baseline_manifest() -> tuple[Baseline, ...]:
    """Read the checked-in manifest and select its current canonical rows."""

    try:
        baselines = bootstrap.load_baseline_manifest(
            ROOT / "v2/db/migration-baselines.json"
        )
        selected = tuple(
            baseline
            for schema, relative in (
                ("pricing", "v2/db/schema.sql"),
                ("oracle", "v2/db/oracle/schema.sql"),
            )
            for baseline in (bootstrap.baseline_for_canonical(schema, relative),)
        )
    except (OSError, RuntimeError, UnicodeError, ValueError) as error:
        raise AdoptionError("canonical baseline manifest is invalid") from error
    if len(selected) != 2 or any(baseline not in baselines for baseline in selected):
        raise AdoptionError(
            "canonical baseline manifest is not the singleton production set"
        )
    return selected


def _canonical_baselines() -> tuple[Baseline, ...]:
    """Verify canonical source bytes before creating the mutation stream."""

    recognized = {baseline.schema: baseline for baseline in load_baseline_manifest()}
    result: list[Baseline] = []
    for schema, relative in (
        ("pricing", "v2/db/schema.sql"),
        ("oracle", "v2/db/oracle/schema.sql"),
    ):
        source = ROOT / relative
        try:
            content = source.read_bytes()
            text = content.decode("utf-8")
        except (OSError, UnicodeError) as error:
            raise AdoptionError("canonical schema source is unavailable") from error
        matches = [
            match.group("version")
            for match in SCHEMA_VERSION_PATTERN.finditer(text)
            if match.group("schema") == schema
        ]
        inserted = re.findall(
            rf"INSERT INTO {re.escape(schema)}[.]schema_version "
            rf"\(version\) VALUES \('([^']+)'\)",
            text,
        )
        baseline = recognized[schema]
        if (
            len(matches) != 1
            or inserted != matches
            or baseline.version != matches[0]
            or baseline.source_sha256 != hashlib.sha256(content).hexdigest()
        ):
            raise AdoptionError(
                "canonical schema source is not represented by its manifest"
            )
        result.append(baseline)
    return tuple(result)


def _pricing_acl_values() -> tuple[tuple[str, str, str], ...]:
    rows: list[tuple[str, str, str]] = []
    for object_name, grants in PRICING_ACL_ALLOWLIST.items():
        rows.extend((object_name, role, privilege) for role, privilege in grants)
    return tuple(rows)


def _application_definition_query() -> str:
    """Return the fixed catalog query used for canonical definitions.

    The target list is deliberately assembled from constants above.  This is
    an application-definition contract, not a general catalog diff: comments,
    ownership, and extension-owned objects are handled by their own checks.
    """

    relation_targets = tuple(("pricing", name) for name in PRICING_OBJECTS) + tuple(
        ("oracle", name) for name in ORACLE_APPLICATION_RELATIONS
    )
    relation_selects: list[str] = []
    for schema, name in relation_targets:
        relation_selects.append(
            f"""SELECT {_sql_literal(f"{schema}.{name}")} AS object_name,
       encode(sha256(convert_to(
         'relkind=' || relation.relkind::text
         || '|columns=' || coalesce((
              SELECT string_agg(
                format('%s|%s|%s|%s|%s', attribute.attnum,
                       attribute.attname,
                       pg_catalog.format_type(attribute.atttypid, attribute.atttypmod),
                       attribute.attnotnull,
                       coalesce(pg_catalog.pg_get_expr(defaults.adbin, defaults.adrelid), '')),
                E'\\n' ORDER BY attribute.attnum
              )
              FROM pg_catalog.pg_attribute AS attribute
              LEFT JOIN pg_catalog.pg_attrdef AS defaults
                ON defaults.adrelid = attribute.attrelid
               AND defaults.adnum = attribute.attnum
              WHERE attribute.attrelid = relation.oid
                AND attribute.attnum > 0
                AND NOT attribute.attisdropped
            ), '')
         || '|constraints=' || coalesce((
              SELECT string_agg(
                format('%s|%s', constraint_.contype,
                       pg_catalog.pg_get_constraintdef(constraint_.oid, true)),
                E'\\n' ORDER BY constraint_.contype,
                               pg_catalog.pg_get_constraintdef(constraint_.oid, true)
              )
              FROM pg_catalog.pg_constraint AS constraint_
              WHERE constraint_.conrelid = relation.oid
            ), '')
         || '|indexes=' || coalesce((
              SELECT string_agg(
                index_class.relname || '|' ||
                pg_catalog.pg_get_indexdef(index_class.oid),
                E'\\n' ORDER BY index_class.relname
              )
              FROM pg_catalog.pg_index AS index_
              JOIN pg_catalog.pg_class AS index_class
                ON index_class.oid = index_.indexrelid
              WHERE index_.indrelid = relation.oid
            ), '')
         || '|view=' || CASE WHEN relation.relkind IN ('v', 'm')
              THEN pg_catalog.pg_get_viewdef(relation.oid, true)
              ELSE '' END,
         'UTF8')), 'hex') AS fingerprint
FROM pg_catalog.pg_class AS relation
JOIN pg_catalog.pg_namespace AS namespace
  ON namespace.oid = relation.relnamespace
WHERE namespace.nspname = {_sql_literal(schema)}
  AND relation.relname = {_sql_literal(name)}"""
        )

    function_selects: list[str] = []
    for name, arguments in ORACLE_APPLICATION_SIGNATURES:
        function_selects.append(
            f"""SELECT {_sql_literal(f"oracle.{name}({arguments})")} AS object_name,
       encode(sha256(convert_to(
         'identity=' || oidvectortypes(procedure.proargtypes)
         || '|result=' || pg_catalog.pg_get_function_result(procedure.oid)
         || '|definition=' || pg_catalog.pg_get_functiondef(procedure.oid),
         'UTF8')), 'hex') AS fingerprint
FROM pg_catalog.pg_proc AS procedure
JOIN pg_catalog.pg_namespace AS namespace
  ON namespace.oid = procedure.pronamespace
WHERE namespace.nspname = 'oracle'
  AND procedure.proname = {_sql_literal(name)}
  AND oidvectortypes(procedure.proargtypes) = {_sql_literal(arguments)}"""
        )
    return "\nUNION ALL\n".join(relation_selects + function_selects)


def production_rds_postgis_type_guard() -> str:
    """Return the exact recurring RDS-owned PostGIS type exception."""
    return """
  IF EXISTS (
    WITH targets(type_name, type_oid, type_owner) AS (
      SELECT expected.type_name, type.oid, owner.rolname
      FROM (VALUES ('geometry'), ('geography')) AS expected(type_name)
      LEFT JOIN pg_type type
        ON type.typnamespace = 'oracle'::regnamespace AND type.typname = expected.type_name
      LEFT JOIN pg_roles owner ON owner.oid = type.typowner
    ), postgis(extension_oid) AS (
      SELECT extension.oid
      FROM pg_extension extension
      JOIN pg_namespace namespace ON namespace.oid = extension.extnamespace
      JOIN pg_roles owner ON owner.oid = extension.extowner
      WHERE extension.extname = 'postgis' AND namespace.nspname = 'oracle'
        AND owner.rolname = 'rdsadmin' AND extension.extversion = '3.5.6'
    ), expected_acl(type_name, grantee, grantor, privilege_type, is_grantable) AS (
      VALUES
        ('geometry', 'rdsadmin', 'rdsadmin', 'USAGE', false),
        ('geometry', 'PUBLIC', 'rdsadmin', 'USAGE', false),
        ('geography', 'rdsadmin', 'rdsadmin', 'USAGE', false),
        ('geography', 'PUBLIC', 'rdsadmin', 'USAGE', false)
    ), actual_acl(type_name, grantee, grantor, privilege_type, is_grantable) AS (
      SELECT target.type_name,
             CASE WHEN privilege.grantee = 0 THEN 'PUBLIC' ELSE grantee.rolname END,
             grantor.rolname,
             privilege.privilege_type, privilege.is_grantable
      FROM targets target
      CROSS JOIN LATERAL aclexplode((SELECT typacl FROM pg_type WHERE oid = target.type_oid)) privilege
      LEFT JOIN pg_roles grantee ON grantee.oid = privilege.grantee
      LEFT JOIN pg_roles grantor ON grantor.oid = privilege.grantor
    )
    SELECT 1 FROM targets target
    WHERE target.type_oid IS NULL OR target.type_owner IS DISTINCT FROM 'rdsadmin'
       OR (SELECT count(*) FROM postgis) <> 1
       OR (SELECT count(*) FROM pg_depend dependency
           WHERE dependency.classid = 'pg_type'::regclass AND dependency.objid = target.type_oid
             AND dependency.refclassid = 'pg_extension'::regclass) <> 1
       OR NOT EXISTS (
         SELECT 1 FROM pg_depend dependency JOIN postgis ON postgis.extension_oid = dependency.refobjid
         WHERE dependency.classid = 'pg_type'::regclass AND dependency.objid = target.type_oid
           AND dependency.refclassid = 'pg_extension'::regclass AND dependency.deptype = 'e'
       )
       OR (SELECT count(*) FROM actual_acl WHERE actual_acl.type_name = target.type_name) <> 2
       OR EXISTS (SELECT * FROM expected_acl EXCEPT SELECT * FROM actual_acl)
       OR EXISTS (SELECT * FROM actual_acl EXCEPT SELECT * FROM expected_acl)
  ) THEN
    RAISE EXCEPTION 'RDS PostGIS type ACL is outside the exact adoption exception';
  END IF;
"""


def adoption_sql(baselines: tuple[Baseline, ...] | None = None) -> str:
    """Render the single bounded transaction used by the production helper."""

    if baselines is None:
        baselines = _canonical_baselines()
    by_schema = {baseline.schema: baseline for baseline in baselines}
    pricing = by_schema["pricing"]
    oracle = by_schema["oracle"]
    relation_values = ", ".join(_sql_literal(name) for name in PRICING_OBJECTS)
    catalog_values = ", ".join(_sql_literal(name) for name in PRICING_CATALOG_OBJECTS)
    index_values = ", ".join(_sql_literal(name) for name in PRICING_INDEXES)
    oracle_relation_values = ", ".join(
        _sql_literal(name) for name in ORACLE_APPLICATION_RELATIONS
    )
    oracle_catalog_values = ", ".join(
        _sql_literal(name) for name in ORACLE_APPLICATION_CATALOG_OBJECTS
    )
    oracle_index_values = ", ".join(
        _sql_literal(name) for name in ORACLE_APPLICATION_INDEXES
    )
    oracle_postgis_values = ", ".join(
        _sql_literal(name) for name in ORACLE_POSTGIS_CATALOG_OBJECTS
    )
    oracle_function_values = ", ".join(
        _sql_literal(name) for name in ORACLE_APPLICATION_FUNCTIONS
    )
    application_relation_values = ",\n      ".join(
        "(" + ", ".join((_sql_literal(schema), _sql_literal(name))) + ")"
        for schema, names in (
            ("pricing", PRICING_OBJECTS),
            ("oracle", ORACLE_APPLICATION_RELATIONS),
        )
        for name in names
    )
    application_relation_locks = ", ".join(
        f"{schema}.{name}"
        for schema, names in (
            ("pricing", PRICING_OBJECTS),
            ("oracle", ORACLE_APPLICATION_RELATIONS),
        )
        for name in names
    )
    oracle_function_acl_values = ",\n      ".join(
        "("
        + ", ".join(
            (
                _sql_literal(name),
                _sql_literal(arguments),
                _sql_literal(role),
                _sql_literal("EXECUTE"),
                "FALSE",
            )
        )
        + ")"
        for name, arguments, role in ORACLE_FUNCTION_ACL_ALLOWLIST
    )
    runtime_values = ", ".join(_sql_literal(name) for name in RUNTIME_ROLES)
    database_values = ", ".join(_sql_literal(name) for name in DATABASE_ROLES)
    application_definition_query = _application_definition_query()
    application_definition_values = ",\n        ".join(
        "(" + ", ".join(_sql_literal(value) for value in row) + ")"
        for row in APPLICATION_DEFINITION_FINGERPRINTS.items()
    )
    acl_values = ",\n        ".join(
        "(" + ", ".join(_sql_literal(value) for value in row) + ", FALSE)"
        for row in _pricing_acl_values()
    )
    oracle_schema_acl_values = ",\n        ".join(
        "(" + ", ".join((_sql_literal(role), _sql_literal(privilege), "FALSE")) + ")"
        for role, privilege in (
            ("tollchat_agent", "USAGE"),
            ("pricing_caller", "USAGE"),
            ("report_publisher", "USAGE"),
        )
    )
    database_acl_values = ",\n        ".join(
        "(" + ", ".join((_sql_literal(role), _sql_literal(privilege), "FALSE")) + ")"
        for role, privilege in (
            [
                ("PUBLIC", "TEMPORARY"),
                (ADMIN_ROLE, "CONNECT"),
                (ADMIN_ROLE, "CREATE"),
                (ADMIN_ROLE, "TEMPORARY"),
            ]
            + [(role, "CONNECT") for role in DATABASE_ROLES]
        )
    )
    database_post_acl_values = ",\n        ".join(
        "(" + ", ".join((_sql_literal(role), _sql_literal(privilege), "FALSE")) + ")"
        for role, privilege in (
            [
                ("PUBLIC", "TEMPORARY"),
                (ADMIN_ROLE, "CONNECT"),
                (ADMIN_ROLE, "CREATE"),
                (ADMIN_ROLE, "TEMPORARY"),
                ("schema_migrator_production", "CONNECT"),
            ]
            + [(role, "CONNECT") for role in DATABASE_ROLES]
        )
    )
    baseline_values = ",\n        ".join(
        "("
        + ", ".join(
            _sql_literal(value)
            for value in (
                baseline.schema,
                baseline.version,
                baseline.migration_id,
                baseline.source_path,
                baseline.source_sha256,
                ADOPTION_EVIDENCE,
                "true",
            )
        )
        + ")"
        for baseline in baselines
    )
    history_ddl = """
CREATE SCHEMA tollchat_migration AUTHORIZATION pricing_owner;
REVOKE ALL ON SCHEMA tollchat_migration FROM PUBLIC;
CREATE TABLE tollchat_migration.schema_history (
    schema_name text NOT NULL CHECK (schema_name IN ('pricing', 'oracle')),
    schema_version text NOT NULL CHECK (
        schema_version ~ '^(0|[1-9][0-9]*)[.](0|[1-9][0-9]*)[.](0|[1-9][0-9]*)$'
    ),
    migration_id text NOT NULL,
    source_path text NOT NULL CHECK (btrim(source_path) <> ''),
    source_sha256 text NOT NULL CHECK (source_sha256 ~ '^[0-9a-f]{64}$'),
    evidence text NOT NULL CHECK (btrim(evidence) <> ''),
    is_baseline boolean NOT NULL CHECK (
        (is_baseline AND migration_id = 'baseline')
        OR (NOT is_baseline AND migration_id <> 'baseline')
    ),
    recorded_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    PRIMARY KEY (schema_name, migration_id),
    UNIQUE (schema_name, schema_version)
);
REVOKE ALL ON tollchat_migration.schema_history FROM PUBLIC;
GRANT USAGE ON SCHEMA tollchat_migration TO nova_toll_admin;
GRANT SELECT ON tollchat_migration.schema_history TO nova_toll_admin;
"""
    # The canonical column-ACL set is empty. Check that same fixed contract
    # before and after adoption; relation ACLs do not include column grants.
    column_acl_guard = """
  IF EXISTS (
    SELECT 1 FROM pg_attribute attribute
    JOIN pg_class relation ON relation.oid = attribute.attrelid
    JOIN pg_namespace namespace ON namespace.oid = relation.relnamespace
    CROSS JOIN LATERAL aclexplode(attribute.attacl) privilege
    WHERE namespace.nspname IN ('pricing', 'oracle')
  ) THEN
    RAISE EXCEPTION 'application column ACL is outside the empty canonical contract';
  END IF;
"""
    # Canonical application relations have no user triggers or policies and no
    # row security. Views retain only PostgreSQL's canonical _RETURN rewrite;
    # any other rule can change behavior without changing the definition
    # fingerprint above. Internal constraint triggers remain allowed.
    behavior_guard = f"""
  IF EXISTS (
    SELECT 1
    FROM pg_class relation
    JOIN pg_namespace namespace ON namespace.oid = relation.relnamespace
    WHERE (namespace.nspname, relation.relname) IN (VALUES
      {application_relation_values}
    )
      AND (relation.relrowsecurity OR relation.relforcerowsecurity)
  ) OR EXISTS (
    SELECT 1
    FROM pg_trigger trigger_
    JOIN pg_class relation ON relation.oid = trigger_.tgrelid
    JOIN pg_namespace namespace ON namespace.oid = relation.relnamespace
    WHERE (namespace.nspname, relation.relname) IN (VALUES
      {application_relation_values}
    )
      AND (NOT trigger_.tgisinternal OR trigger_.tgenabled <> 'O')
  ) OR EXISTS (
    SELECT 1
    FROM pg_policy policy
    JOIN pg_class relation ON relation.oid = policy.polrelid
    JOIN pg_namespace namespace ON namespace.oid = relation.relnamespace
    WHERE (namespace.nspname, relation.relname) IN (VALUES
      {application_relation_values}
    )
  ) OR EXISTS (
    SELECT 1
    FROM pg_rewrite rewrite
    JOIN pg_class relation ON relation.oid = rewrite.ev_class
    JOIN pg_namespace namespace ON namespace.oid = relation.relnamespace
    WHERE (namespace.nspname, relation.relname) IN (VALUES
      {application_relation_values}
    )
      AND (rewrite.rulename <> '_RETURN'
           OR relation.relkind NOT IN ('v', 'm')
           OR rewrite.ev_enabled <> 'O')
  ) THEN
    RAISE EXCEPTION 'application trigger, policy, row-security, or rewrite-rule inventory is outside the canonical contract';
  END IF;
"""
    environment_guard = """
  IF EXISTS (SELECT 1 FROM pg_auth_members WHERE member = to_regrole('rds_iam')) THEN
    RAISE EXCEPTION 'rds_iam must not inherit any other role';
  END IF;
  IF (SELECT count(*) FROM pg_extension) <> 2 OR EXISTS (
    SELECT 1 FROM pg_extension
    WHERE NOT (extname = 'plpgsql' AND extnamespace = 'pg_catalog'::regnamespace
               OR extname = 'postgis' AND extnamespace = 'oracle'::regnamespace
                  AND extversion ~ '^3[.]5([.]|$)')
  ) OR EXISTS (SELECT 1 FROM pg_foreign_data_wrapper)
    OR EXISTS (SELECT 1 FROM pg_foreign_server)
    OR EXISTS (SELECT 1 FROM pg_user_mappings) THEN
    RAISE EXCEPTION 'extensions or foreign access are outside the canonical contract';
  END IF;
"""
    rds_postgis_type_guard = production_rds_postgis_type_guard()
    # Canonical Oracle SQL grants only the function and relation rows below;
    # the two type rows are checked by the exact RDS exception above.
    extension_acl_guard = """
  IF EXISTS (
    WITH actual(kind, object_name, grantee, privilege_type, is_grantable) AS (
      SELECT 'function', format('%s(%s)', procedure.proname, oidvectortypes(procedure.proargtypes)),
             COALESCE(grantee.rolname, 'PUBLIC'), privilege.privilege_type, privilege.is_grantable
      FROM pg_proc procedure
      CROSS JOIN LATERAL aclexplode(procedure.proacl) privilege
      LEFT JOIN pg_roles grantee ON grantee.oid = privilege.grantee
      WHERE procedure.pronamespace = 'oracle'::regnamespace
        AND privilege.grantee <> procedure.proowner
        AND EXISTS (
          SELECT 1 FROM pg_depend dependency JOIN pg_extension extension ON extension.oid = dependency.refobjid
          WHERE dependency.classid = 'pg_proc'::regclass AND dependency.objid = procedure.oid
            AND dependency.refclassid = 'pg_extension'::regclass AND dependency.deptype = 'e'
            AND extension.extname = 'postgis'
        )
      UNION ALL
      SELECT 'relation', relation.relname, COALESCE(grantee.rolname, 'PUBLIC'),
             privilege.privilege_type, privilege.is_grantable
      FROM pg_class relation
      CROSS JOIN LATERAL aclexplode(relation.relacl) privilege
      LEFT JOIN pg_roles grantee ON grantee.oid = privilege.grantee
      WHERE relation.relnamespace = 'oracle'::regnamespace
        AND relation.relowner <> to_regrole('oracle_owner')
        AND privilege.grantee <> relation.relowner
      UNION ALL
      SELECT 'type', type.typname, COALESCE(grantee.rolname, 'PUBLIC'),
             privilege.privilege_type, privilege.is_grantable
      FROM pg_type type
      CROSS JOIN LATERAL aclexplode(type.typacl) privilege
      LEFT JOIN pg_roles grantee ON grantee.oid = privilege.grantee
      WHERE type.typnamespace = 'oracle'::regnamespace AND privilege.grantee <> type.typowner
    ), expected(kind, object_name, grantee, privilege_type, is_grantable) AS (
      VALUES
        ('function', 'st_distance(oracle.geography, oracle.geography, boolean)', 'oracle_owner', 'EXECUTE', false),
        ('function', 'st_asgeojson(oracle.geography, integer, integer)', 'oracle_owner', 'EXECUTE', false),
        ('relation', 'spatial_ref_sys', 'oracle_owner', 'SELECT', false),
        ('type', 'geometry', 'PUBLIC', 'USAGE', false),
        ('type', 'geography', 'PUBLIC', 'USAGE', false)
    )
    SELECT 1 FROM actual FULL JOIN expected
      USING (kind, object_name, grantee, privilege_type, is_grantable)
    WHERE actual.kind IS NULL OR expected.kind IS NULL
  ) THEN
    RAISE EXCEPTION 'PostGIS ACL is outside the canonical allowlist';
  END IF;
"""
    return f"""\\set ON_ERROR_STOP on
BEGIN;
SET LOCAL search_path = pg_catalog, pg_temp;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';
SET LOCAL idle_in_transaction_session_timeout = '2min';
SELECT pg_advisory_xact_lock(hashtext({_sql_literal(LOCK_NAME)}));
LOCK TABLE {application_relation_locks} IN ACCESS EXCLUSIVE MODE;

CREATE TEMP TABLE _canonical_application_definition (
    object_name text PRIMARY KEY,
    fingerprint text NOT NULL CHECK (fingerprint ~ '^[0-9a-f]{{64}}$')
) ON COMMIT DROP;
INSERT INTO _canonical_application_definition (object_name, fingerprint)
{application_definition_query};

DO $$
DECLARE
  role_name name;
BEGIN
  IF current_database() <> {_sql_literal(DATABASE)} THEN
    RAISE EXCEPTION 'production adoption connected to the wrong database';
  END IF;
  IF to_regrole({_sql_literal(ADMIN_ROLE)}) IS NULL
     OR to_regrole('rds_iam') IS NULL THEN
    RAISE EXCEPTION 'required production administrative roles are missing';
  END IF;
  IF (SELECT count(*) FROM _canonical_application_definition) <> {len(APPLICATION_DEFINITION_FINGERPRINTS)}
     OR EXISTS (
       SELECT * FROM _canonical_application_definition
       EXCEPT SELECT * FROM (VALUES
        {application_definition_values}
       ) AS expected(object_name, fingerprint)
     )
     OR EXISTS (
       SELECT * FROM (VALUES
        {application_definition_values}
       ) AS expected(object_name, fingerprint)
       EXCEPT SELECT * FROM _canonical_application_definition
     ) THEN
    RAISE EXCEPTION 'canonical application definition fingerprint mismatch';
  END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname IN ('pricing_owner', 'schema_migrator_production')) THEN
    RAISE EXCEPTION 'production adoption principals already exist';
  END IF;
  IF (SELECT count(*) FROM pricing.schema_version) <> 1
     OR (SELECT version FROM pricing.schema_version WHERE singleton) <> {_sql_literal(pricing.version)}
     OR (SELECT count(*) FROM oracle.schema_version) <> 1
     OR (SELECT version FROM oracle.schema_version WHERE singleton) <> {_sql_literal(oracle.version)}
     OR (SELECT count(*) FROM oracle.toll_connection) <> {EXPECTED_CONNECTIONS} THEN
    RAISE EXCEPTION 'production baseline invariant mismatch';
  END IF;
  IF to_regnamespace({_sql_literal(HISTORY_SCHEMA)}) IS NOT NULL
     OR to_regclass({_sql_literal(HISTORY_TABLE)}) IS NOT NULL THEN
    RAISE EXCEPTION 'production adoption history already exists';
  END IF;
{column_acl_guard}
{behavior_guard}
{environment_guard}
{rds_postgis_type_guard}
{extension_acl_guard}
  IF (SELECT nspowner::regrole::text FROM pg_namespace WHERE nspname = 'pricing') <> {_sql_literal(ADMIN_ROLE)}
     OR EXISTS (
       SELECT 1 FROM pg_class relation
       JOIN pg_namespace namespace ON namespace.oid = relation.relnamespace
       WHERE namespace.nspname = 'pricing' AND relation.relkind IN ('r', 'v', 'i')
         AND relation.relowner::regrole::text <> {_sql_literal(ADMIN_ROLE)}
     ) THEN
    RAISE EXCEPTION 'pricing ownership is outside the approved pre-adoption boundary';
  END IF;
  IF (SELECT count(*) FROM pg_class relation
      JOIN pg_namespace namespace ON namespace.oid = relation.relnamespace
      WHERE namespace.nspname = 'pricing'
        AND relation.relname IN ({catalog_values})) <> {len(PRICING_CATALOG_OBJECTS)}
     OR EXISTS (
       SELECT 1 FROM pg_class relation
       JOIN pg_namespace namespace ON namespace.oid = relation.relnamespace
       WHERE namespace.nspname = 'pricing'
         AND (relation.relname NOT IN ({catalog_values})
              OR relation.relname IN ({relation_values})
                 AND relation.relkind NOT IN ('r', 'v')
              OR relation.relname IN ({index_values})
                 AND relation.relkind <> 'i'
              OR relation.relowner::regrole::text <> {_sql_literal(ADMIN_ROLE)})
     )
     OR EXISTS (
       SELECT 1 FROM pg_class relation
       JOIN pg_namespace namespace ON namespace.oid = relation.relnamespace
       CROSS JOIN LATERAL aclexplode(relation.relacl) privilege
       WHERE namespace.nspname = 'pricing'
         AND relation.relname IN ({index_values})
         AND privilege.grantee <> relation.relowner
  ) THEN
    RAISE EXCEPTION 'pricing object inventory is outside the explicit allowlist';
  END IF;
  IF EXISTS (
    SELECT 1 FROM pg_proc WHERE pronamespace = 'pricing'::regnamespace
  ) OR EXISTS (
    SELECT 1 FROM pg_type type
    WHERE type.typnamespace = 'pricing'::regnamespace
      AND NOT EXISTS (
        SELECT 1 FROM pg_class relation
        JOIN pg_type row_type ON row_type.oid = relation.reltype
        WHERE relation.relnamespace = type.typnamespace
          AND relation.relname IN ({relation_values})
          AND type.oid IN (row_type.oid, row_type.typarray)
      )
  ) THEN
    RAISE EXCEPTION 'pricing functions or types are outside the explicit allowlist';
  END IF;
  IF EXISTS (
    SELECT 1 FROM pg_default_acl defaults
    WHERE defaults.defaclnamespace IN (
      SELECT oid FROM pg_namespace WHERE nspname IN ('pricing', 'oracle')
    ) OR defaults.defaclnamespace = 0
      OR defaults.defaclrole = to_regrole({_sql_literal(ADMIN_ROLE)})
  ) THEN
    RAISE EXCEPTION 'relevant default privileges are not empty';
  END IF;
  IF EXISTS (
    SELECT 1 FROM pg_roles
    WHERE rolname IN ({runtime_values})
      AND (NOT rolcanlogin OR NOT rolinherit OR rolsuper OR rolcreatedb OR rolcreaterole
           OR rolreplication OR rolbypassrls)
  ) OR EXISTS (
    SELECT 1 FROM pg_roles
    WHERE rolname = 'oracle_owner'
      AND (rolcanlogin OR rolsuper OR rolcreatedb OR rolcreaterole
           OR rolreplication OR rolbypassrls OR NOT rolinherit)
  ) THEN
    RAISE EXCEPTION 'runtime role attributes are outside the approved contract';
  END IF;
  IF EXISTS (
    SELECT 1 FROM pg_auth_members membership
    JOIN pg_roles member_role ON member_role.oid = membership.member
    JOIN pg_roles granted_role ON granted_role.oid = membership.roleid
    WHERE member_role.rolname IN ({runtime_values})
      AND granted_role.rolname <> 'rds_iam'
  ) OR EXISTS (
    SELECT 1 FROM pg_auth_members membership
    JOIN pg_roles member_role ON member_role.oid = membership.member
    WHERE member_role.rolname = 'oracle_owner'
  ) THEN
    RAISE EXCEPTION 'runtime role memberships are outside the approved contract';
  END IF;
  IF (SELECT count(*) FROM pg_auth_members membership
      JOIN pg_roles member_role ON member_role.oid = membership.member
      JOIN pg_roles granted_role ON granted_role.oid = membership.roleid
      WHERE member_role.rolname IN ({runtime_values})
        AND granted_role.rolname = 'rds_iam') <> {len(RUNTIME_ROLES)}
     OR EXISTS (
       SELECT 1 FROM pg_auth_members membership
       JOIN pg_roles member_role ON member_role.oid = membership.member
       JOIN pg_roles granted_role ON granted_role.oid = membership.roleid
       WHERE member_role.rolname IN ({runtime_values})
         AND granted_role.rolname = 'rds_iam'
         AND (NOT membership.inherit_option OR NOT membership.set_option OR membership.admin_option)
     ) THEN
    RAISE EXCEPTION 'runtime rds_iam membership options are outside the approved contract';
  END IF;
  FOREACH role_name IN ARRAY ARRAY[{database_values}]::name[] LOOP
    IF NOT has_database_privilege(role_name, current_database(), 'CONNECT') THEN
      RAISE EXCEPTION 'runtime role is missing database CONNECT';
    END IF;
  END LOOP;
  IF EXISTS (
    WITH expected(grantee, privilege_type, is_grantable) AS (
      VALUES
        {database_acl_values}
    ), actual AS (
      SELECT CASE WHEN privilege.grantee = 0 THEN 'PUBLIC'
                  ELSE grantee.rolname END,
             privilege.privilege_type,
             privilege.is_grantable
      FROM pg_database database
      CROSS JOIN LATERAL aclexplode(database.datacl) privilege
      LEFT JOIN pg_roles grantee ON grantee.oid = privilege.grantee
      WHERE database.datname = current_database()
    )
    SELECT * FROM actual EXCEPT SELECT * FROM expected
  ) OR EXISTS (
    WITH expected(grantee, privilege_type, is_grantable) AS (
      VALUES
        {database_acl_values}
    ), actual AS (
      SELECT CASE WHEN privilege.grantee = 0 THEN 'PUBLIC'
                  ELSE grantee.rolname END,
             privilege.privilege_type,
             privilege.is_grantable
      FROM pg_database database
      CROSS JOIN LATERAL aclexplode(database.datacl) privilege
      LEFT JOIN pg_roles grantee ON grantee.oid = privilege.grantee
      WHERE database.datname = current_database()
    )
    SELECT * FROM expected EXCEPT SELECT * FROM actual
  ) THEN
    RAISE EXCEPTION 'database ACL is outside the explicit allowlist';
  END IF;
  IF EXISTS (
    WITH expected(object_name, grantee, privilege_type, is_grantable) AS (
      VALUES {acl_values}
    ), actual AS (
      SELECT 'schema', grantee.rolname, privilege.privilege_type, privilege.is_grantable
      FROM pg_namespace namespace
      CROSS JOIN LATERAL aclexplode(namespace.nspacl) privilege
      JOIN pg_roles grantee ON grantee.oid = privilege.grantee
      WHERE namespace.nspname = 'pricing'
        AND grantee.rolname <> namespace.nspowner::regrole::text
      UNION ALL
      SELECT relation.relname, grantee.rolname, privilege.privilege_type, privilege.is_grantable
      FROM pg_class relation
      JOIN pg_namespace namespace ON namespace.oid = relation.relnamespace
      CROSS JOIN LATERAL aclexplode(relation.relacl) privilege
      JOIN pg_roles grantee ON grantee.oid = privilege.grantee
      WHERE namespace.nspname = 'pricing' AND relation.relkind IN ('r', 'v', 'i')
        AND grantee.rolname <> relation.relowner::regrole::text
    )
    SELECT * FROM actual EXCEPT SELECT * FROM expected
  ) OR EXISTS (
    WITH expected(object_name, grantee, privilege_type, is_grantable) AS (
      VALUES {acl_values}
    ), actual AS (
      SELECT 'schema', grantee.rolname, privilege.privilege_type, privilege.is_grantable
      FROM pg_namespace namespace
      CROSS JOIN LATERAL aclexplode(namespace.nspacl) privilege
      JOIN pg_roles grantee ON grantee.oid = privilege.grantee
      WHERE namespace.nspname = 'pricing'
        AND grantee.rolname <> namespace.nspowner::regrole::text
      UNION ALL
      SELECT relation.relname, grantee.rolname, privilege.privilege_type, privilege.is_grantable
      FROM pg_class relation
      JOIN pg_namespace namespace ON namespace.oid = relation.relnamespace
      CROSS JOIN LATERAL aclexplode(relation.relacl) privilege
      JOIN pg_roles grantee ON grantee.oid = privilege.grantee
      WHERE namespace.nspname = 'pricing' AND relation.relkind IN ('r', 'v', 'i')
        AND grantee.rolname <> relation.relowner::regrole::text
    )
    SELECT * FROM expected EXCEPT SELECT * FROM actual
  ) OR EXISTS (
    SELECT 1 FROM pg_namespace namespace
    CROSS JOIN LATERAL aclexplode(namespace.nspacl) privilege
    WHERE namespace.nspname = 'pricing' AND privilege.grantee = 0
  ) OR EXISTS (
    SELECT 1 FROM pg_class relation
    JOIN pg_namespace namespace ON namespace.oid = relation.relnamespace
    CROSS JOIN LATERAL aclexplode(relation.relacl) privilege
    WHERE namespace.nspname = 'pricing' AND relation.relkind IN ('r', 'v', 'i')
      AND privilege.grantee = 0
  ) THEN
    RAISE EXCEPTION 'pricing ACL inventory is outside the explicit allowlist';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'postgis') THEN
    RAISE EXCEPTION 'PostGIS extension is missing';
  END IF;
  IF (SELECT nspowner::regrole::text FROM pg_namespace WHERE nspname = 'oracle') <> 'oracle_owner'
     OR EXISTS (
       WITH expected(grantee, privilege_type, is_grantable) AS (
         VALUES
           {oracle_schema_acl_values}
       ), actual AS (
         SELECT CASE WHEN privilege.grantee = 0 THEN 'PUBLIC'
                     ELSE grantee.rolname END,
                privilege.privilege_type,
                privilege.is_grantable
         FROM pg_namespace namespace
         CROSS JOIN LATERAL aclexplode(namespace.nspacl) privilege
         LEFT JOIN pg_roles grantee ON grantee.oid = privilege.grantee
         WHERE namespace.nspname = 'oracle'
           AND privilege.grantee <> namespace.nspowner
       )
       SELECT * FROM actual EXCEPT SELECT * FROM expected
     ) OR EXISTS (
       WITH expected(grantee, privilege_type, is_grantable) AS (
         VALUES
           {oracle_schema_acl_values}
       ), actual AS (
         SELECT CASE WHEN privilege.grantee = 0 THEN 'PUBLIC'
                     ELSE grantee.rolname END,
                privilege.privilege_type,
                privilege.is_grantable
         FROM pg_namespace namespace
         CROSS JOIN LATERAL aclexplode(namespace.nspacl) privilege
         LEFT JOIN pg_roles grantee ON grantee.oid = privilege.grantee
         WHERE namespace.nspname = 'oracle'
           AND privilege.grantee <> namespace.nspowner
       )
       SELECT * FROM expected EXCEPT SELECT * FROM actual
     ) THEN
    RAISE EXCEPTION 'Oracle schema ownership or ACL is outside the explicit contract';
  END IF;
  IF EXISTS (
    SELECT 1 FROM pg_class relation
    JOIN pg_namespace namespace ON namespace.oid = relation.relnamespace
    WHERE namespace.nspname = 'oracle'
      AND relation.relname IN ({oracle_relation_values})
      AND relation.relowner::regrole::text <> 'oracle_owner'
  ) OR (SELECT count(*) FROM pg_class relation
        JOIN pg_namespace namespace ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = 'oracle'
          AND relation.relname IN ({oracle_catalog_values})) <> {len(ORACLE_APPLICATION_CATALOG_OBJECTS)}
     OR EXISTS (
       SELECT 1
       FROM pg_class relation
       JOIN pg_namespace namespace ON namespace.oid = relation.relnamespace
       WHERE namespace.nspname = 'oracle'
         AND NOT EXISTS (
           SELECT 1 FROM pg_depend dependency
           WHERE dependency.classid = 'pg_class'::regclass
             AND dependency.objid = relation.oid
             AND dependency.deptype = 'e'
         )
         AND relation.relname NOT IN ({oracle_postgis_values})
         AND (relation.relname NOT IN ({oracle_catalog_values})
              OR relation.relname IN ({oracle_relation_values})
                 AND relation.relkind NOT IN ('r', 'v')
              OR relation.relname IN ({oracle_index_values})
                 AND relation.relkind <> 'i'
              OR relation.relowner::regrole::text <> 'oracle_owner')
     ) THEN
    RAISE EXCEPTION 'Oracle application ownership boundary is not exact';
  END IF;
  IF EXISTS (
    SELECT 1 FROM pg_type type
    WHERE type.typnamespace = 'oracle'::regnamespace
      AND NOT EXISTS (
        SELECT 1 FROM pg_class relation
        JOIN pg_type row_type ON row_type.oid = relation.reltype
        WHERE relation.relnamespace = type.typnamespace
          AND relation.relname IN ({oracle_relation_values}, {oracle_postgis_values})
          AND type.oid IN (row_type.oid, row_type.typarray)
      )
      AND NOT EXISTS (
        SELECT 1 FROM pg_type extension_type
        JOIN pg_depend dependency ON dependency.classid = 'pg_type'::regclass
          AND dependency.objid = extension_type.oid
          AND dependency.refclassid = 'pg_extension'::regclass
          AND dependency.deptype = 'e'
        JOIN pg_extension extension ON extension.oid = dependency.refobjid
        WHERE extension.extname = 'postgis'
          AND extension_type.typnamespace = type.typnamespace
          AND type.oid IN (extension_type.oid, extension_type.typarray)
      )
  ) THEN
    RAISE EXCEPTION 'Oracle type inventory is outside the explicit allowlist';
  END IF;
  IF EXISTS (
    SELECT 1 FROM pg_class relation
    JOIN pg_namespace namespace ON namespace.oid = relation.relnamespace
    CROSS JOIN LATERAL aclexplode(relation.relacl) privilege
    WHERE namespace.nspname = 'oracle'
      AND NOT EXISTS (
        SELECT 1 FROM pg_depend dependency
        WHERE dependency.classid = 'pg_class'::regclass
          AND dependency.objid = relation.oid
          AND dependency.deptype = 'e'
      )
      AND privilege.grantee <> relation.relowner
  ) THEN
    RAISE EXCEPTION 'Oracle application relation ACL is not owner-only';
  END IF;
  IF EXISTS (
    SELECT 1 FROM pg_proc procedure
    JOIN pg_namespace namespace ON namespace.oid = procedure.pronamespace
    WHERE namespace.nspname = 'oracle'
      AND procedure.proname IN ({oracle_function_values})
      AND procedure.proowner::regrole::text <> 'oracle_owner'
  ) OR (SELECT count(*) FROM pg_proc procedure
        JOIN pg_namespace namespace ON namespace.oid = procedure.pronamespace
        WHERE namespace.nspname = 'oracle'
          AND procedure.proname IN ({oracle_function_values})
          AND NOT EXISTS (
            SELECT 1 FROM pg_depend dependency
            WHERE dependency.classid = 'pg_proc'::regclass
              AND dependency.objid = procedure.oid
              AND dependency.deptype = 'e'
          )) <> 19
     OR EXISTS (
       SELECT 1 FROM pg_proc procedure
       JOIN pg_namespace namespace ON namespace.oid = procedure.pronamespace
       WHERE namespace.nspname = 'oracle'
         AND NOT EXISTS (
           SELECT 1 FROM pg_depend dependency
           WHERE dependency.classid = 'pg_proc'::regclass
             AND dependency.objid = procedure.oid
             AND dependency.deptype = 'e'
         )
         AND procedure.proname NOT IN ({oracle_function_values})
     ) THEN
    RAISE EXCEPTION 'Oracle function ownership boundary is not exact';
  END IF;
  IF EXISTS (
    WITH expected(function_name, argument_types, grantee, privilege_type, is_grantable) AS (
      VALUES
      {oracle_function_acl_values}
    ), actual AS (
      SELECT procedure.proname,
             oidvectortypes(procedure.proargtypes),
             grantee.rolname,
             privilege.privilege_type,
             privilege.is_grantable
      FROM pg_proc procedure
      JOIN pg_namespace namespace ON namespace.oid = procedure.pronamespace
      CROSS JOIN LATERAL aclexplode(procedure.proacl) privilege
      LEFT JOIN pg_roles grantee ON grantee.oid = privilege.grantee
      WHERE namespace.nspname = 'oracle'
        AND procedure.proname IN ({oracle_function_values})
        AND privilege.grantee <> procedure.proowner
    )
    SELECT * FROM actual EXCEPT SELECT * FROM expected
  ) OR EXISTS (
    WITH expected(function_name, argument_types, grantee, privilege_type, is_grantable) AS (
      VALUES
      {oracle_function_acl_values}
    ), actual AS (
      SELECT procedure.proname,
             oidvectortypes(procedure.proargtypes),
             grantee.rolname,
             privilege.privilege_type,
             privilege.is_grantable
      FROM pg_proc procedure
      JOIN pg_namespace namespace ON namespace.oid = procedure.pronamespace
      CROSS JOIN LATERAL aclexplode(procedure.proacl) privilege
      LEFT JOIN pg_roles grantee ON grantee.oid = privilege.grantee
      WHERE namespace.nspname = 'oracle'
        AND procedure.proname IN ({oracle_function_values})
        AND privilege.grantee <> procedure.proowner
    )
    SELECT * FROM expected EXCEPT SELECT * FROM actual
  ) THEN
    RAISE EXCEPTION 'Oracle application function ACL is outside the explicit allowlist';
  END IF;
END $$;

CREATE TEMP TABLE _production_adoption_snapshot (
    object_kind text NOT NULL,
    object_oid oid NOT NULL,
    owner_oid oid NOT NULL,
    acl text,
    PRIMARY KEY (object_kind, object_oid)
) ON COMMIT DROP;
INSERT INTO _production_adoption_snapshot
SELECT 'pricing_schema', namespace.oid, namespace.nspowner,
       COALESCE((SELECT string_agg(
                           format('%s|%s|%s', privilege.grantee,
                                  privilege.privilege_type, privilege.is_grantable),
                           ',' ORDER BY privilege.grantee, privilege.privilege_type,
                           privilege.is_grantable)
                 FROM aclexplode(namespace.nspacl) privilege
                 WHERE privilege.grantee <> namespace.nspowner), '')
FROM pg_namespace namespace WHERE namespace.nspname = 'pricing';
INSERT INTO _production_adoption_snapshot
SELECT 'pricing_relation', relation.oid, relation.relowner,
       COALESCE((SELECT string_agg(
                           format('%s|%s|%s', privilege.grantee,
                                  privilege.privilege_type, privilege.is_grantable),
                           ',' ORDER BY privilege.grantee, privilege.privilege_type,
                           privilege.is_grantable)
                 FROM aclexplode(relation.relacl) privilege
                 WHERE privilege.grantee <> relation.relowner), '')
FROM pg_class relation JOIN pg_namespace namespace ON namespace.oid = relation.relnamespace
WHERE namespace.nspname = 'pricing' AND relation.relkind IN ('r', 'v', 'i');
INSERT INTO _production_adoption_snapshot
SELECT 'oracle_schema', namespace.oid, namespace.nspowner, namespace.nspacl::text
FROM pg_namespace namespace WHERE namespace.nspname = 'oracle';
INSERT INTO _production_adoption_snapshot
SELECT 'oracle_relation', relation.oid, relation.relowner, relation.relacl::text
FROM pg_class relation JOIN pg_namespace namespace ON namespace.oid = relation.relnamespace
WHERE namespace.nspname = 'oracle';
INSERT INTO _production_adoption_snapshot
SELECT 'oracle_function', procedure.oid, procedure.proowner, procedure.proacl::text
FROM pg_proc procedure JOIN pg_namespace namespace ON namespace.oid = procedure.pronamespace
WHERE namespace.nspname = 'oracle';
INSERT INTO _production_adoption_snapshot
SELECT 'oracle_type', type.oid, type.typowner, type.typacl::text
FROM pg_type type JOIN pg_namespace namespace ON namespace.oid = type.typnamespace
WHERE namespace.nspname = 'oracle';
INSERT INTO _production_adoption_snapshot
SELECT 'oracle_extension', extension.oid, extension.extowner, NULL
FROM pg_extension extension
JOIN pg_namespace namespace ON namespace.oid = extension.extnamespace
WHERE namespace.nspname = 'oracle' OR extension.extname = 'postgis';

CREATE ROLE pricing_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS;
CREATE ROLE schema_migrator_production LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS;
GRANT rds_iam TO schema_migrator_production WITH INHERIT TRUE, SET TRUE, ADMIN FALSE;
GRANT pricing_owner TO schema_migrator_production WITH INHERIT FALSE, SET TRUE, ADMIN FALSE;
GRANT oracle_owner TO schema_migrator_production WITH INHERIT FALSE, SET TRUE, ADMIN FALSE;
GRANT CONNECT ON DATABASE nova_toll TO schema_migrator_production;

GRANT pricing_owner TO CURRENT_USER WITH INHERIT FALSE, SET TRUE, ADMIN FALSE;
GRANT CREATE ON DATABASE nova_toll TO pricing_owner;
GRANT USAGE, CREATE ON SCHEMA pricing TO pricing_owner;
ALTER TABLE pricing.schema_version OWNER TO pricing_owner;
ALTER TABLE pricing.trip_pricing_i95 OWNER TO pricing_owner;
ALTER TABLE pricing.trip_pricing_i66 OWNER TO pricing_owner;
ALTER VIEW pricing.current_trip_pricing_i95 OWNER TO pricing_owner;
ALTER VIEW pricing.current_trip_pricing_i66 OWNER TO pricing_owner;
ALTER VIEW pricing.current_i95_direction OWNER TO pricing_owner;
ALTER VIEW pricing.i95_modeled_od_proxy OWNER TO pricing_owner;
ALTER VIEW pricing.modeled_trip_pricing_i95 OWNER TO pricing_owner;
ALTER VIEW pricing.modeled_current_trip_pricing_i95 OWNER TO pricing_owner;
ALTER VIEW pricing.i66_pricing_comparisons OWNER TO pricing_owner;
ALTER VIEW pricing.i95_i495_pricing_comparisons OWNER TO pricing_owner;
ALTER VIEW pricing.i66_ballpark_samples OWNER TO pricing_owner;
ALTER VIEW pricing.i95_i495_ballpark_samples OWNER TO pricing_owner;
ALTER SCHEMA pricing OWNER TO pricing_owner;

SET ROLE pricing_owner;
{history_ddl}
INSERT INTO tollchat_migration.schema_history
    (schema_name, schema_version, migration_id, source_path, source_sha256, evidence, is_baseline)
VALUES
        {baseline_values};
RESET ROLE;
REVOKE CREATE ON DATABASE nova_toll FROM pricing_owner;

DO $$
DECLARE
  expected_count integer;
BEGIN
{column_acl_guard}
{behavior_guard}
  IF NOT EXISTS (
    SELECT 1 FROM _production_adoption_snapshot snapshot
    JOIN pg_namespace namespace ON namespace.oid = snapshot.object_oid
    WHERE snapshot.object_kind = 'oracle_schema'
      AND namespace.nspname = 'oracle'
      AND namespace.nspowner = snapshot.owner_oid
      AND namespace.nspacl::text IS NOT DISTINCT FROM snapshot.acl
  ) THEN
    RAISE EXCEPTION 'Oracle schema ownership or ACL boundary changed';
  END IF;
{environment_guard}
{rds_postgis_type_guard}
{extension_acl_guard}
  SELECT count(*) INTO expected_count FROM tollchat_migration.schema_history;
  IF expected_count <> 2
     OR (SELECT count(*) FROM tollchat_migration.schema_history WHERE is_baseline) <> 2
     OR (SELECT count(*) FROM tollchat_migration.schema_history WHERE evidence <> {_sql_literal(ADOPTION_EVIDENCE)}) <> 0
     OR EXISTS (
       SELECT 1 FROM tollchat_migration.schema_history history
       WHERE NOT EXISTS (
         SELECT 1 FROM (VALUES {baseline_values}) AS expected(
           schema_name, schema_version, migration_id, source_path,
           source_sha256, evidence, is_baseline
         )
         WHERE expected.schema_name = history.schema_name
           AND expected.schema_version = history.schema_version
           AND expected.migration_id = history.migration_id
           AND expected.source_path = history.source_path
           AND expected.source_sha256 = history.source_sha256
           AND expected.evidence = history.evidence
           AND expected.is_baseline::boolean = history.is_baseline
       )
     )
     OR (SELECT count(*) FROM pg_roles WHERE rolname IN ('pricing_owner', 'schema_migrator_production')) <> 2
     OR EXISTS (
       SELECT 1 FROM pg_roles
       WHERE rolname = 'pricing_owner'
         AND (rolcanlogin OR rolsuper OR rolcreatedb OR rolcreaterole OR rolinherit
              OR rolreplication OR rolbypassrls)
     ) OR NOT EXISTS (
       SELECT 1 FROM pg_roles
       WHERE rolname = 'schema_migrator_production'
         AND rolcanlogin AND NOT rolsuper AND NOT rolcreatedb AND NOT rolcreaterole
         AND NOT rolinherit AND NOT rolreplication AND NOT rolbypassrls
     ) THEN
    RAISE EXCEPTION 'production adoption postcondition failed';
  END IF;
  IF (SELECT nspowner::regrole::text FROM pg_namespace WHERE nspname = 'pricing') <> 'pricing_owner'
     OR EXISTS (
       SELECT 1 FROM pg_class relation
       JOIN pg_namespace namespace ON namespace.oid = relation.relnamespace
       WHERE namespace.nspname = 'pricing' AND relation.relkind IN ('r', 'v', 'i')
         AND relation.relowner::regrole::text <> 'pricing_owner'
     ) OR (SELECT relowner::regrole::text FROM pg_class relation
           JOIN pg_namespace namespace ON namespace.oid = relation.relnamespace
           WHERE namespace.nspname = 'tollchat_migration' AND relation.relname = 'schema_history')
          <> 'pricing_owner' THEN
    RAISE EXCEPTION 'production ownership postcondition failed';
  END IF;
  IF (SELECT count(*) FROM pg_auth_members membership
      JOIN pg_roles member_role ON member_role.oid = membership.member
      WHERE member_role.rolname = 'schema_migrator_production') <> 3
     OR EXISTS (
       SELECT 1 FROM pg_auth_members membership
       JOIN pg_roles member_role ON member_role.oid = membership.member
       JOIN pg_roles granted_role ON granted_role.oid = membership.roleid
       WHERE member_role.rolname = 'schema_migrator_production'
         AND granted_role.rolname NOT IN ('rds_iam', 'pricing_owner', 'oracle_owner')
     ) OR EXISTS (
       SELECT 1 FROM pg_auth_members membership
       JOIN pg_roles member_role ON member_role.oid = membership.member
       JOIN pg_roles granted_role ON granted_role.oid = membership.roleid
       WHERE member_role.rolname = 'schema_migrator_production'
         AND granted_role.rolname = 'rds_iam'
         AND (NOT membership.inherit_option OR NOT membership.set_option OR membership.admin_option)
     ) OR EXISTS (
       SELECT 1 FROM pg_auth_members membership
       JOIN pg_roles member_role ON member_role.oid = membership.member
       JOIN pg_roles granted_role ON granted_role.oid = membership.roleid
       WHERE member_role.rolname = 'schema_migrator_production'
         AND granted_role.rolname IN ('pricing_owner', 'oracle_owner')
         AND (membership.inherit_option OR NOT membership.set_option OR membership.admin_option)
  ) OR has_database_privilege('schema_migrator_production', current_database(), 'CREATE') THEN
    RAISE EXCEPTION 'production migrator role postcondition failed';
  END IF;
  IF EXISTS (
    WITH expected(grantee, privilege_type, is_grantable) AS (
      VALUES
        {database_post_acl_values}
    ), actual AS (
      SELECT CASE WHEN privilege.grantee = 0 THEN 'PUBLIC'
                  ELSE grantee.rolname END,
             privilege.privilege_type,
             privilege.is_grantable
      FROM pg_database database
      CROSS JOIN LATERAL aclexplode(database.datacl) privilege
      LEFT JOIN pg_roles grantee ON grantee.oid = privilege.grantee
      WHERE database.datname = current_database()
    )
    SELECT * FROM actual EXCEPT SELECT * FROM expected
  ) OR EXISTS (
    WITH expected(grantee, privilege_type, is_grantable) AS (
      VALUES
        {database_post_acl_values}
    ), actual AS (
      SELECT CASE WHEN privilege.grantee = 0 THEN 'PUBLIC'
                  ELSE grantee.rolname END,
             privilege.privilege_type,
             privilege.is_grantable
      FROM pg_database database
      CROSS JOIN LATERAL aclexplode(database.datacl) privilege
      LEFT JOIN pg_roles grantee ON grantee.oid = privilege.grantee
      WHERE database.datname = current_database()
    )
    SELECT * FROM expected EXCEPT SELECT * FROM actual
  ) THEN
    RAISE EXCEPTION 'database ACL postcondition failed';
  END IF;
  IF EXISTS (
    SELECT * FROM (
      {application_definition_query}
    ) AS current_definition
    EXCEPT SELECT * FROM _canonical_application_definition
  ) OR EXISTS (
    SELECT * FROM _canonical_application_definition
    EXCEPT SELECT * FROM (
      {application_definition_query}
    ) AS current_definition
  ) THEN
    RAISE EXCEPTION 'canonical application definition changed during adoption';
  END IF;
  IF EXISTS (
    SELECT 1 FROM (
      SELECT oid AS namespace_oid, nspacl AS acl FROM pg_namespace
      UNION ALL SELECT relnamespace, relacl FROM pg_class
      UNION ALL SELECT pronamespace, proacl FROM pg_proc
      UNION ALL SELECT typnamespace, typacl FROM pg_type
      UNION ALL SELECT relation.relnamespace, attribute.attacl
        FROM pg_attribute attribute JOIN pg_class relation ON relation.oid = attribute.attrelid
    ) object_acl
    JOIN pg_namespace namespace ON namespace.oid = object_acl.namespace_oid
    CROSS JOIN LATERAL aclexplode(object_acl.acl) privilege
    WHERE namespace.nspname IN ('pricing', 'oracle', 'tollchat_migration')
      AND privilege.grantee = to_regrole('schema_migrator_production')
  ) THEN
    RAISE EXCEPTION 'production migrator has a direct application ACL';
  END IF;
  IF EXISTS (
    SELECT 1 FROM _production_adoption_snapshot snapshot
    JOIN pg_class relation ON snapshot.object_kind IN ('pricing_relation', 'oracle_relation')
      AND relation.oid = snapshot.object_oid
    WHERE snapshot.object_kind = 'oracle_relation'
      AND (relation.relowner <> snapshot.owner_oid
           OR relation.relacl::text IS DISTINCT FROM snapshot.acl)
  ) OR EXISTS (
    SELECT 1 FROM _production_adoption_snapshot snapshot
    JOIN pg_namespace namespace ON snapshot.object_kind = 'pricing_schema'
      AND namespace.oid = snapshot.object_oid
    WHERE COALESCE((SELECT string_agg(
                           format('%s|%s|%s', privilege.grantee,
                                  privilege.privilege_type, privilege.is_grantable),
                           ',' ORDER BY privilege.grantee, privilege.privilege_type,
                           privilege.is_grantable)
                    FROM aclexplode(namespace.nspacl) privilege
                    WHERE privilege.grantee <> namespace.nspowner), '')
          IS DISTINCT FROM snapshot.acl
  ) OR EXISTS (
    SELECT 1 FROM _production_adoption_snapshot snapshot
    JOIN pg_class relation ON snapshot.object_kind = 'pricing_relation'
      AND relation.oid = snapshot.object_oid
    WHERE COALESCE((SELECT string_agg(
                           format('%s|%s|%s', privilege.grantee,
                                  privilege.privilege_type, privilege.is_grantable),
                           ',' ORDER BY privilege.grantee, privilege.privilege_type,
                           privilege.is_grantable)
                    FROM aclexplode(relation.relacl) privilege
                    WHERE privilege.grantee <> relation.relowner), '')
          IS DISTINCT FROM snapshot.acl
  ) OR EXISTS (
    SELECT 1 FROM _production_adoption_snapshot snapshot
    JOIN pg_proc procedure ON snapshot.object_kind = 'oracle_function'
      AND procedure.oid = snapshot.object_oid
    WHERE procedure.proowner <> snapshot.owner_oid
       OR procedure.proacl::text IS DISTINCT FROM snapshot.acl
  ) OR EXISTS (
    SELECT 1
    FROM (SELECT * FROM _production_adoption_snapshot
          WHERE object_kind = 'oracle_type') snapshot
    FULL JOIN (SELECT oid, typowner, typacl FROM pg_type
               WHERE typnamespace = 'oracle'::regnamespace) type
      ON type.oid = snapshot.object_oid
    WHERE type.oid IS NULL OR snapshot.object_oid IS NULL
       OR type.typowner <> snapshot.owner_oid
       OR type.typacl::text IS DISTINCT FROM snapshot.acl
  ) OR EXISTS (
    SELECT 1 FROM _production_adoption_snapshot snapshot
    JOIN pg_extension extension ON snapshot.object_kind = 'oracle_extension'
      AND extension.oid = snapshot.object_oid
    WHERE extension.extowner <> snapshot.owner_oid
  ) THEN
    RAISE EXCEPTION 'Oracle/PostGIS ownership or ACL boundary changed';
  END IF;
END $$;

REVOKE SELECT ON tollchat_migration.schema_history FROM nova_toll_admin;
REVOKE USAGE ON SCHEMA tollchat_migration FROM nova_toll_admin;
RESET ROLE;
REVOKE pricing_owner FROM CURRENT_USER;
COMMIT;
\\echo TOLLCHAT_PRODUCTION_BASELINE_ADOPTED
"""


def _capture(*args: str) -> str:
    service = args[0] if args else ""
    endpoint = AWS_SERVICE_ENDPOINTS.get(service)
    ca_bundle = cast(str | None, ssl.get_default_verify_paths().cafile)
    if endpoint is None or ca_bundle is None or not Path(ca_bundle).is_file():
        raise AdoptionError("AWS identity endpoint is unavailable")
    if any(
        name == "AWS_ENDPOINT_URL"
        or name.startswith("AWS_ENDPOINT_URL_")
        or name
        in {
            "AWS_CA_BUNDLE",
            "SSL_CERT_FILE",
            "SSL_CERT_DIR",
            "REQUESTS_CA_BUNDLE",
            "CURL_CA_BUNDLE",
        }
        for name in os.environ
    ):
        raise AdoptionError("AWS endpoint or CA override is not allowed")
    environment = dict(os.environ)
    # Config-file endpoint_url settings are ignored by the AWS CLI. Explicit
    # endpoint and CA arguments below also override config-file settings.
    environment["AWS_IGNORE_CONFIGURED_ENDPOINT_URLS"] = "true"
    try:
        result = subprocess.run(
            [
                "aws",
                "--region",
                REGION,
                "--endpoint-url",
                endpoint,
                "--ca-bundle",
                ca_bundle,
                *args,
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            env=environment,
        )
    except subprocess.TimeoutExpired as error:
        raise AdoptionError("required AWS identity check failed") from error
    except OSError as error:
        raise AdoptionError("required AWS identity check failed") from error
    if result.returncode != 0:
        raise AdoptionError("required AWS identity check failed")
    return result.stdout.strip()


def _rds_identity() -> RdsIdentity:
    account = _capture(
        "sts", "get-caller-identity", "--query", "Account", "--output", "text"
    )
    if account != ACCOUNT_ID:
        raise AdoptionError("AWS account identity is not the fixed production account")
    try:
        raw_value: object = json.loads(
            _capture(
                "rds",
                "describe-db-instances",
                "--db-instance-identifier",
                DB_INSTANCE_IDENTIFIER,
                "--query",
                "DBInstances",
                "--output",
                "json",
            )
        )
        if not isinstance(raw_value, list):
            raise ValueError
        raw_items: list[object] = cast(list[object], raw_value)
        if len(raw_items) != 1 or not isinstance(raw_items[0], dict):
            raise ValueError
        instance = cast(dict[str, object], raw_items[0])
        endpoint = cast(dict[str, object], instance["Endpoint"])
        secret = cast(dict[str, object], instance["MasterUserSecret"])
        address = endpoint["Address"]
        port = endpoint["Port"]
        secret_arn = secret["SecretArn"]
        if (
            instance.get("DBInstanceIdentifier") != DB_INSTANCE_IDENTIFIER
            or instance.get("DBInstanceStatus") != "available"
            or instance.get("PubliclyAccessible") is not False
            or not isinstance(address, str)
            or RDS_ENDPOINT_PATTERN.fullmatch(address) is None
            or not isinstance(port, int)
            or not 0 < port < 65536
            or not isinstance(secret_arn, str)
            or SECRET_ARN_PATTERN.fullmatch(secret_arn) is None
        ):
            raise ValueError
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise AdoptionError(
            "RDS identity is not the fixed private production instance"
        ) from error
    expected = os.environ.get(EXPECTED_ENDPOINT_ENV, "").strip().strip("[]").lower()
    if expected != address.lower():
        raise AdoptionError(
            "verified RDS endpoint is required and did not match metadata"
        )
    return RdsIdentity(address.lower(), port, secret_arn)


def _admin_url(endpoint: str) -> tuple[str, int | None, str]:
    value = os.environ.get(ADMIN_URL_ENV, "")
    if not value:
        raise AdoptionError("managed-secret TLS administrative URL is required")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as error:
        raise AdoptionError("administrative URL is invalid") from error
    if (
        parsed.scheme not in ("postgres", "postgresql")
        or parsed.hostname is None
        or parsed.hostname.lower() != endpoint
        or parsed.username not in (None, ADMIN_ROLE)
        or parsed.password is not None
        or parsed.path not in ("", f"/{DATABASE}")
        or "#" in value
        or not parsed.query
    ):
        raise AdoptionError("administrative URL is not bound to the fixed TLS endpoint")
    query: dict[str, str] = {}
    for pair in parsed.query.split("&"):
        if not pair or "=" not in pair:
            raise AdoptionError("administrative URL TLS settings are invalid")
        key, raw_value = pair.split("=", 1)
        try:
            key = unquote(key, errors="strict")
            raw_value = unquote(raw_value, errors="strict")
        except UnicodeDecodeError as error:
            raise AdoptionError(
                "administrative URL TLS settings are invalid"
            ) from error
        if key in query or key not in {"sslmode", "sslrootcert"} or not raw_value:
            raise AdoptionError("administrative URL TLS settings are invalid")
        query[key] = raw_value
    rootcert = query.get("sslrootcert")
    if query.get("sslmode") != "verify-full" or rootcert is None:
        raise AdoptionError(
            "administrative URL requires verify-full TLS and an explicit CA"
        )
    ca = Path(rootcert)
    if not ca.is_file() or ca.is_symlink():
        raise AdoptionError("administrative URL CA bundle is unavailable")
    try:
        ca_digest = hashlib.sha256(ca.read_bytes()).hexdigest()
    except OSError as error:
        raise AdoptionError("administrative URL CA bundle is unavailable") from error
    if ca_digest != APPROVED_CA_SHA256:
        raise AdoptionError("administrative URL CA bundle is not approved")
    return parsed.hostname.lower(), port, rootcert


def _admin_secret(secret_arn: str) -> AdminSecret:
    try:
        raw_value: object = json.loads(
            _capture(
                "secretsmanager",
                "get-secret-value",
                "--secret-id",
                secret_arn,
                "--query",
                "SecretString",
                "--output",
                "text",
            )
        )
        if not isinstance(raw_value, dict):
            raise ValueError
        raw = cast(dict[str, object], raw_value)
        username: object = raw.get("username")
        password: object = raw.get("password")
        if username != ADMIN_ROLE or not isinstance(password, str) or not password:
            raise ValueError
    except (ValueError, TypeError, json.JSONDecodeError) as error:
        raise AdoptionError("managed administrative secret is invalid") from error
    return AdminSecret(ADMIN_ROLE, password)


def _psql_environment(
    identity: RdsIdentity, secret: AdminSecret, port: int | None, rootcert: str
) -> dict[str, str]:
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("PG")
    }
    environment.update(
        {
            "PGHOST": identity.endpoint,
            "PGUSER": secret.username,
            "PGPASSWORD": secret.password,
            "PGDATABASE": DATABASE,
            "PGSSLMODE": "verify-full",
            "PGSSLROOTCERT": rootcert,
        }
    )
    if port is not None:
        environment["PGPORT"] = str(port)
    return environment


def run() -> dict[str, str]:
    if os.environ.get(APPROVAL_ENV) != APPROVAL_TOKEN:
        raise AdoptionError("explicit production adoption approval is required")
    identity = _rds_identity()
    endpoint, url_port, rootcert = _admin_url(identity.endpoint)
    secret = _admin_secret(identity.secret_arn)
    if endpoint != identity.endpoint or (
        url_port is not None and url_port != identity.port
    ):
        raise AdoptionError("administrative endpoint identity changed")
    sql = adoption_sql()
    environment = _psql_environment(identity, secret, identity.port, rootcert)
    try:
        result = subprocess.run(
            ["psql", "-X", "--no-psqlrc", "--set", "ON_ERROR_STOP=1", "--quiet"],
            input=sql,
            text=True,
            capture_output=True,
            env=environment,
            cwd=ROOT,
            timeout=90,
            check=False,
        )
    except OSError as error:
        raise AdoptionError("production adoption SQL execution failed") from error
    finally:
        del environment, secret
    if (
        result.returncode != 0
        or result.stdout.splitlines().count("TOLLCHAT_PRODUCTION_BASELINE_ADOPTED") != 1
    ):
        raise AdoptionError(
            "production adoption outcome is unknown; recheck read-only state before retry"
        )
    return {"database": DATABASE, "status": "adopted", "evidence": ADOPTION_EVIDENCE}


def main() -> int:
    if len(sys.argv) != 1:
        print(f"usage: {Path(sys.argv[0]).name}", file=sys.stderr)
        return 2
    try:
        print(json.dumps(run(), sort_keys=True, separators=(",", ":")))
    except (AdoptionError, OSError, ValueError, subprocess.SubprocessError):
        print("production baseline adoption failed", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
