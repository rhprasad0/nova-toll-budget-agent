"""Guards the schema contract that today's data-loss bug slipped through:
each table's UNIQUE/PRIMARY KEY and its loader's ON CONFLICT key must agree,
every column the upsert inserts actually exists on that table, every
NOT-NULL-without-default column is covered by the upsert, and the schema
version is valid semver kept in sync between db/schema.sql and the spec.

Pure stdlib; runs in the existing `uv run pytest` CI step.
"""

import re

from conftest import REPO_ROOT, loader_handler

SCHEMA_SQL = (REPO_ROOT / "db" / "schema.sql").read_text()
SPEC_MD = (REPO_ROOT / "docs" / "poller-spec.md").read_text()

SEMVER = r"\d+\.\d+\.\d+"

EXPECTED_TABLES = {"trip_pricing_i95", "trip_pricing_i66", "trip_pricing_i95_live"}


def _cols(paren_body: str) -> list[str]:
    return [c.strip() for c in paren_body.split(",") if c.strip()]


def _table_bodies() -> dict[str, str]:
    return {
        m.group(1): m.group(2)
        for m in re.finditer(
            r"CREATE TABLE (\w+)\s*\((.*?)\n\);", SCHEMA_SQL, re.DOTALL
        )
    }


def _schema_key_cols_by_table() -> dict[str, list[str]]:
    tables: dict[str, list[str]] = {}
    for table, body in _table_bodies().items():
        key_match = re.search(
            r"(?:PRIMARY KEY|UNIQUE(?:\s+NULLS\s+NOT\s+DISTINCT)?)\s*\(([^)]*)\)",
            body,
            re.IGNORECASE,
        )
        assert key_match, f"no PRIMARY KEY/UNIQUE constraint found for {table}"
        tables[table] = _cols(key_match.group(1))
    return tables


def _schema_columns_by_table() -> dict[str, dict[str, bool]]:
    """table -> {column_name: is_required (NOT NULL, no DEFAULT)}."""
    tables: dict[str, dict[str, bool]] = {}
    for table, body in _table_bodies().items():
        columns: dict[str, bool] = {}
        for line in body.splitlines():
            line = line.split("--", 1)[0].strip().rstrip(",")
            if not line or line.upper().startswith(("PRIMARY KEY", "UNIQUE")):
                continue
            name = line.split()[0]
            is_required = "NOT NULL" in line.upper() and "DEFAULT" not in line.upper()
            columns[name] = is_required
        tables[table] = columns
    return tables


def _upsert_sql_by_table() -> dict[str, str]:
    return {
        m.group(1): sql
        for sql in (
            loader_handler.UPSERT_I95_SQL,
            loader_handler.UPSERT_I66_SQL,
            loader_handler.UPSERT_I95_LIVE_SQL,
        )
        for m in [re.search(r"INSERT INTO (\w+)", sql)]
        if m
    }


def _on_conflict_cols_by_table() -> dict[str, list[str]]:
    upserts: dict[str, list[str]] = {}
    for table, sql in _upsert_sql_by_table().items():
        conflict_match = re.search(r"ON CONFLICT\s*\(([^)]*)\)", sql, re.IGNORECASE)
        assert conflict_match, f"no ON CONFLICT clause found for {table}"
        upserts[table] = _cols(conflict_match.group(1))
    return upserts


def _insert_cols_by_table() -> dict[str, list[str]]:
    inserts: dict[str, list[str]] = {}
    for table, sql in _upsert_sql_by_table().items():
        insert_match = re.search(
            rf"INSERT INTO {table}\s*\((.*?)\)\s*VALUES", sql, re.DOTALL
        )
        assert insert_match, f"no INSERT column list found for {table}"
        inserts[table] = _cols(insert_match.group(1))
    return inserts


def test_both_tables_and_both_upserts_are_present():
    assert _schema_key_cols_by_table().keys() == EXPECTED_TABLES
    assert _on_conflict_cols_by_table().keys() == EXPECTED_TABLES


def test_upsert_key_matches_schema_key_per_table():
    # The exact drift that silently dropped 30 i95 rows/poll. Order matters:
    # ON CONFLICT inference must line up with the table's key columns.
    schema_keys = _schema_key_cols_by_table()
    upsert_keys = _on_conflict_cols_by_table()
    for table in EXPECTED_TABLES:
        assert upsert_keys[table] == schema_keys[table], table


def test_insert_columns_exist_on_their_table():
    schema_columns = _schema_columns_by_table()
    insert_columns = _insert_cols_by_table()
    for table in EXPECTED_TABLES:
        unknown = set(insert_columns[table]) - schema_columns[table].keys()
        assert not unknown, f"{table}: INSERT references unknown columns {unknown}"


def test_insert_covers_every_required_column():
    # A NOT-NULL-without-default column missing from the INSERT list fails
    # at insert time in prod, not at plan time -- catch it here instead.
    schema_columns = _schema_columns_by_table()
    insert_columns = _insert_cols_by_table()
    for table in EXPECTED_TABLES:
        required = {c for c, req in schema_columns[table].items() if req}
        missing = required - set(insert_columns[table])
        assert not missing, f"{table}: INSERT omits required columns {missing}"


def test_schema_version_is_semver_and_matches_spec():
    schema_v = re.search(rf"schema version:\s*({SEMVER})", SCHEMA_SQL, re.IGNORECASE)
    spec_v = re.search(rf"Schema version:\s*({SEMVER})", SPEC_MD, re.IGNORECASE)
    assert schema_v, "db/schema.sql missing a `-- schema version: X.Y.Z` line"
    assert spec_v, "docs/poller-spec.md missing a `Schema version: X.Y.Z` line"
    assert schema_v.group(1) == spec_v.group(1), (
        f"schema.sql version {schema_v.group(1)} != spec version {spec_v.group(1)}"
    )
