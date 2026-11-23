import os
import shutil
import subprocess
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from psycopg import sql

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "exercise_sandbox_database.py"
SCHEMA = "issue_868"


@pytest.fixture
def sandbox_url() -> Iterator[str]:
    host = os.environ.get("PGHOST", "localhost")
    port = os.environ.get("PGPORT", "5432")
    admin = os.environ.get("PGUSER", "postgres")
    try:
        root = psycopg.connect(
            host=host, port=port, user=admin, dbname="postgres", autocommit=True
        )
    except psycopg.Error:
        pytest.skip("no disposable PostgreSQL reachable")
    suffix = uuid.uuid4().hex[:8]
    role, database = f"sandbox_role_{suffix}", f"sandbox_db_{suffix}"
    password = uuid.uuid4().hex
    with root:
        root.execute(
            sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                sql.Identifier(role), sql.Literal(password)
            )
        )
        root.execute(
            sql.SQL("CREATE DATABASE {} OWNER {}").format(
                sql.Identifier(database), sql.Identifier(role)
            )
        )
        try:
            yield f"postgresql://{role}:{password}@{host}:{port}/{database}"
        finally:
            root.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(
                    sql.Identifier(database)
                )
            )
            root.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))


@pytest.mark.skipif(shutil.which("psql") is None, reason="needs the PostgreSQL client")
def test_script_exercises_database_and_leaves_only_review_check(
    sandbox_url: str,
) -> None:
    run = subprocess.run(
        [sys.executable, str(SCRIPT), sandbox_url, "--schema", SCHEMA],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert run.returncode == 0, run.stdout + run.stderr
    assert "FAIL:" not in run.stdout
    assert "postgis refused" in run.stdout
    assert "a rolled-back transaction left nothing behind" in run.stdout
    assert "connections attempted = 20, completed = 20, failed = 0" in run.stdout

    with psycopg.connect(sandbox_url) as conn:
        relations = conn.execute(
            "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace"
            " WHERE n.nspname = %s ORDER BY 1",
            (SCHEMA,),
        ).fetchall()
        assert relations == [("review_check",), ("review_check_pkey",)]
        rows = conn.execute(
            sql.SQL("SELECT id, label, value FROM {}.review_check ORDER BY id").format(
                sql.Identifier(SCHEMA)
            )
        ).fetchall()
        assert rows == [(1, "alpha", 11), (2, "bravo", 22), (3, "charlie", 33)]
        extensions = conn.execute(
            "SELECT extname FROM pg_extension WHERE extname = 'pgcrypto'"
        ).fetchall()
        assert extensions == []
