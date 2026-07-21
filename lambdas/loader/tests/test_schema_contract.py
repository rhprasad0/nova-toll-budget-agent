"""Guards the schema contract that today's data-loss bug slipped through:
the DB UNIQUE key and the loader's ON CONFLICT key must agree, and the schema
version must be valid semver kept in sync between db/schema.sql and the spec.

Pure stdlib; runs in the existing `uv run pytest` CI step.
"""

import re

from conftest import REPO_ROOT, loader_handler

SCHEMA_SQL = (REPO_ROOT / "db" / "schema.sql").read_text()
SPEC_MD = (REPO_ROOT / "docs" / "poller-spec.md").read_text()

SEMVER = r"\d+\.\d+\.\d+"


def _cols(paren_body: str) -> list[str]:
    return [c.strip() for c in paren_body.split(",") if c.strip()]


def _schema_unique_cols() -> list[str]:
    m = re.search(
        r"UNIQUE(?:\s+NULLS\s+NOT\s+DISTINCT)?\s*\(([^)]*)\)", SCHEMA_SQL, re.IGNORECASE
    )
    assert m, "no UNIQUE constraint found in db/schema.sql"
    return _cols(m.group(1))


def _on_conflict_cols() -> list[str]:
    m = re.search(
        r"ON CONFLICT\s*\(([^)]*)\)", loader_handler.UPSERT_SQL, re.IGNORECASE
    )
    assert m, "no ON CONFLICT clause found in UPSERT_SQL"
    return _cols(m.group(1))


def test_upsert_key_matches_schema_unique_key():
    # The exact drift that silently dropped 30 i95 rows/poll. Order matters:
    # ON CONFLICT inference must line up with the UNIQUE index columns.
    assert _on_conflict_cols() == _schema_unique_cols()


def test_schema_version_is_semver_and_matches_spec():
    schema_v = re.search(rf"schema version:\s*({SEMVER})", SCHEMA_SQL, re.IGNORECASE)
    spec_v = re.search(rf"Schema version:\s*({SEMVER})", SPEC_MD, re.IGNORECASE)
    assert schema_v, "db/schema.sql missing a `-- schema version: X.Y.Z` line"
    assert spec_v, "docs/poller-spec.md missing a `Schema version: X.Y.Z` line"
    assert schema_v.group(1) == spec_v.group(1), (
        f"schema.sql version {schema_v.group(1)} != spec version {spec_v.group(1)}"
    )
