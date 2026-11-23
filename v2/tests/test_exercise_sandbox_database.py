import os
import shutil
import subprocess
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "exercise_sandbox_database.py"
SCHEMA = "issue_868"


def psql(url_or_db: str, sql_text: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["psql", "-X", "-v", "ON_ERROR_STOP=1", "-At", "-d", url_or_db, "-c", sql_text],
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture
def sandbox_url() -> Iterator[str]:
    if shutil.which("psql") is None:
        pytest.skip("needs the PostgreSQL client")
    host = os.environ.get("PGHOST", "localhost")
    port = os.environ.get("PGPORT", "5432")
    admin = os.environ.get("PGUSER", "postgres")
    root = f"postgresql://{admin}@{host}:{port}/postgres"
    if psql(root, "SELECT 1").returncode != 0:
        pytest.skip("no disposable PostgreSQL reachable")
    suffix = uuid.uuid4().hex[:8]
    role, database = f"sandbox_role_{suffix}", f"sandbox_db_{suffix}"
    password = uuid.uuid4().hex
    for statement in (
        f"CREATE ROLE {role} LOGIN PASSWORD '{password}'",
        f"CREATE DATABASE {database} OWNER {role}",
    ):
        assert psql(root, statement).returncode == 0
    try:
        yield f"postgresql://{role}:{password}@{host}:{port}/{database}"
    finally:
        psql(root, f"DROP DATABASE {database} WITH (FORCE)")
        psql(root, f"DROP ROLE {role}")


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

    relations = psql(
        sandbox_url,
        "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace"
        f" WHERE n.nspname = '{SCHEMA}' ORDER BY 1",
    )
    assert relations.stdout.split() == ["review_check", "review_check_pkey"]
    rows = psql(
        sandbox_url, f"SELECT id, label, value FROM {SCHEMA}.review_check ORDER BY id"
    )
    assert rows.stdout.split() == ["1|alpha|11", "2|bravo|22", "3|charlie|33"]
    extensions = psql(
        sandbox_url, "SELECT extname FROM pg_extension WHERE extname = 'pgcrypto'"
    )
    assert extensions.stdout.strip() == ""
