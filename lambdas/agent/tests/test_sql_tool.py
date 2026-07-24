import json
import sys
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from conftest import SCHEMAS_DIR
from jsonschema import Draft202012Validator

import sql_tool


def test_module_imports_without_psycopg():
    # psycopg only ships in the deployed zip, not this dev venv — sql_tool.py
    # must not import it at module scope, only lazily inside _connect().
    assert "psycopg" not in sys.modules


OUTPUT_SCHEMA = json.loads((SCHEMAS_DIR / "execute_sql.json").read_text())["output"]
_validator = Draft202012Validator(OUTPUT_SCHEMA)


@pytest.mark.parametrize(
    ("sql", "should_error"),
    [
        ("", True),
        ("   ", True),
        ("SELECT 1; DROP TABLE x", True),
        ("UPDATE trip_pricing SET zone_toll_rate_usd = 0", True),
        ("select 1", False),
        ("SELECT 1;", False),
        ("WITH t AS (SELECT 1 AS x) SELECT * FROM t", False),
    ],
)
def test_preflight(sql, should_error):
    result = sql_tool._preflight(sql)
    assert (result is not None) == should_error


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Decimal("3.50"), "3.50"),
        (datetime(2026, 7, 21, 14, 40), "2026-07-21T14:40:00"),
        (None, None),
        (3, 3),
        ("x", "x"),
        (True, True),
    ],
)
def test_serialize(value, expected):
    assert sql_tool._serialize(value) == expected


class FakeCursor:
    def __init__(self, *, rows, raises=None):
        self._rows = rows
        self._raises = raises
        self.description = [SimpleNamespace(name="a"), SimpleNamespace(name="b")]

    def execute(self, sql, prepare=True):
        if self._raises:
            raise self._raises

    def fetchmany(self, n):
        return self._rows[:n]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor
        self.closed = False

    def cursor(self):
        return self._cursor

    def close(self):
        self.closed = True


@pytest.fixture(autouse=True)
def _db_env(monkeypatch):
    monkeypatch.setenv("DB_HOST", "db.example.internal")
    monkeypatch.setenv("DB_PORT", "5432")
    monkeypatch.setenv("DB_NAME", "va_tolling")


def test_execute_sql_success(monkeypatch):
    fake_conn = FakeConnection(FakeCursor(rows=[(1, "x"), (2, "y")]))
    monkeypatch.setattr(sql_tool, "_connect", lambda **kw: fake_conn)

    result = sql_tool.execute_sql("SELECT a, b FROM t")

    _validator.validate(result)
    assert result["columns"] == ["a", "b"]
    assert result["rows"] == [[1, "x"], [2, "y"]]
    assert result["row_count"] == 2
    assert result["truncated"] is False
    assert fake_conn.closed is True


def test_execute_sql_truncates_at_500(monkeypatch):
    rows = [(i, str(i)) for i in range(501)]
    fake_conn = FakeConnection(FakeCursor(rows=rows))
    monkeypatch.setattr(sql_tool, "_connect", lambda **kw: fake_conn)

    result = sql_tool.execute_sql("SELECT a, b FROM t")

    _validator.validate(result)
    assert result["truncated"] is True
    assert result["row_count"] == 500
    assert len(result["rows"]) == 500


def test_execute_sql_error_from_execute_is_caught_and_truncated(monkeypatch):
    fake_conn = FakeConnection(FakeCursor(rows=[], raises=Exception("x" * 700)))
    monkeypatch.setattr(sql_tool, "_connect", lambda **kw: fake_conn)

    result = sql_tool.execute_sql("SELECT a, b FROM t")

    _validator.validate(result)
    assert len(result["error"]) <= 500
    assert fake_conn.closed is True


def test_execute_sql_serializes_decimal_and_datetime(monkeypatch):
    fake_conn = FakeConnection(
        FakeCursor(rows=[(Decimal("3.50"), datetime(2026, 7, 21, 14, 40))])
    )
    monkeypatch.setattr(sql_tool, "_connect", lambda **kw: fake_conn)

    result = sql_tool.execute_sql("SELECT a, b FROM t")

    _validator.validate(result)
    assert result["rows"] == [["3.50", "2026-07-21T14:40:00"]]
