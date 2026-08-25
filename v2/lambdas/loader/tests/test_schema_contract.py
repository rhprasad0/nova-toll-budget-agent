import re
from pathlib import Path

import pricing_loader_handler as loader_handler

V2_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_SQL = (V2_ROOT / "db" / "schema.sql").read_text()
EXPECTED_TABLES = {"trip_pricing_i95", "trip_pricing_i66"}


def _columns(value: str) -> list[str]:
    return [column.strip() for column in value.split(",") if column.strip()]


def _table_bodies() -> dict[str, str]:
    return {
        match.group(1): match.group(2)
        for match in re.finditer(
            r"CREATE TABLE pricing\.(\w+)\s*\((.*?)\n\);", SCHEMA_SQL, re.DOTALL
        )
        if match.group(1) in EXPECTED_TABLES
    }


def _upserts() -> dict[str, str]:
    result = {}
    for sql in (loader_handler.UPSERT_I95_SQL, loader_handler.UPSERT_I66_SQL):
        match = re.search(r"INSERT INTO pricing\.(\w+)", sql)
        assert match
        result[match.group(1)] = sql
    return result


def test_loader_columns_and_conflict_keys_match_pricing_schema():
    tables = _table_bodies()
    upserts = _upserts()
    assert tables.keys() == EXPECTED_TABLES
    assert upserts.keys() == EXPECTED_TABLES

    for table, body in tables.items():
        key = re.search(r"PRIMARY KEY\s*\(([^)]*)\)", body)
        insert = re.search(
            rf"INSERT INTO pricing\.{table}\s*\((.*?)\)\s*VALUES",
            upserts[table],
            re.DOTALL,
        )
        conflict = re.search(r"ON CONFLICT\s*\(([^)]*)\)", upserts[table])
        assert key and insert and conflict
        assert _columns(conflict.group(1)) == _columns(key.group(1))

        schema_columns = {}
        for line in body.splitlines():
            line = line.split("--", maxsplit=1)[0].strip().rstrip(",")
            if not line or line.startswith("PRIMARY KEY"):
                continue
            name = line.split()[0]
            schema_columns[name] = "NOT NULL" in line and "DEFAULT" not in line

        insert_columns = set(_columns(insert.group(1)))
        assert not insert_columns - schema_columns.keys()
        required = {name for name, is_required in schema_columns.items() if is_required}
        assert not required - insert_columns
