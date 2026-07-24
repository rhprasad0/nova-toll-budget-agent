"""execute_sql tool: free-form read-only SQL against the poller's database.

psycopg is only present in the deployed zip, not the dev/test venv, so the
connection is built with a lazy import inside _connect() — everything else
here must stay importable without it. See docs/agent-tools-spec.md §2/§4.
"""

from __future__ import annotations

import os
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

import boto3
from strands import tool

# ponytail: connect recipe duplicated from lambdas/loader/handler.py; share a
# db.py if a third DB tool appears.
CA_BUNDLE_PATH = os.path.join(os.path.dirname(__file__), "rds-ca-bundle.pem")

ROW_CAP = 500


def _preflight(sql: str) -> str | None:
    """UX-only guard — the agent_readonly role + prepared statement are the
    real enforcement (spec §4). Returns an error message, or None if OK."""
    stripped = sql.strip()
    if not stripped:
        return "sql must not be empty"
    if ";" in stripped.rstrip(";"):
        return "only one statement is allowed (no embedded semicolons)"
    if not stripped.upper().startswith(("SELECT", "WITH")):
        return "only SELECT or WITH ... SELECT statements are allowed"
    return None


def _serialize(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    return value


def _connect(*, host: str, port: int, dbname: str):
    import psycopg  # type: ignore[import-not-found]  # deployed-zip-only dependency; see module docstring.

    token = boto3.client("rds").generate_db_auth_token(
        DBHostname=host, Port=port, DBUsername="agent_readonly"
    )
    return psycopg.connect(
        host=host,
        port=port,
        dbname=dbname,
        user="agent_readonly",
        password=token,
        sslmode="verify-full",
        sslrootcert=CA_BUNDLE_PATH,
    )


@tool
def execute_sql(sql: str) -> dict:
    """Run exactly one read-only SQL statement against the toll database.

    Accepts a single SELECT (or WITH ... SELECT) statement — no semicolon-
    separated statement lists. Results are capped at 500 rows; use LIMIT and
    aggregates rather than pulling raw rows. Errors (validation or Postgres)
    are returned in the result, not raised, so read the error and retry.

    Args:
        sql: Exactly one SQL SELECT (or WITH ... SELECT) statement.
    """
    error = _preflight(sql)
    if error:
        return {"sql": sql, "error": error}

    conn = None
    try:
        conn = _connect(
            host=os.environ["DB_HOST"],
            port=int(os.environ["DB_PORT"]),
            dbname=os.environ["DB_NAME"],
        )
        with conn.cursor() as cur:
            # Dynamic (model-written) SQL is the point of this tool, so the
            # stubs' LiteralString requirement can't hold here.
            cur.execute(sql, prepare=True)  # pyright: ignore[reportCallIssue, reportArgumentType]
            fetched = cur.fetchmany(ROW_CAP + 1)
            truncated = len(fetched) > ROW_CAP
            fetched = fetched[:ROW_CAP]
            columns = [c.name for c in cur.description or []]
            rows = [[_serialize(v) for v in row] for row in fetched]
        return {
            "sql": sql,
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
            "truncated": truncated,
        }
    except Exception as exc:  # noqa: BLE001 — surfaced to the model, never raised
        return {"sql": sql, "error": str(exc)[:500]}
    finally:
        if conn is not None:
            conn.close()
