import argparse
import os
import sys
from pathlib import Path

import psycopg

MIGRATIONS = Path(__file__).resolve().parent / "migrations"


def apply(connection: psycopg.Connection) -> list[str]:
    connection.execute(
        "SELECT pg_advisory_xact_lock(hashtext('tollchat-dashboard-migrations'))"
    )
    connection.execute("CREATE SCHEMA IF NOT EXISTS dashboard")
    connection.execute(
        "CREATE TABLE IF NOT EXISTS dashboard.schema_migration ("
        "migration_id text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
    )
    done = {
        row[0]
        for row in connection.execute(
            "SELECT migration_id FROM dashboard.schema_migration"
        )
    }
    applied: list[str] = []
    for path in sorted(MIGRATIONS.glob("*.sql")):
        if path.name in done:
            continue
        connection.execute(path.read_text(encoding="utf-8").encode())
        connection.execute(
            "INSERT INTO dashboard.schema_migration (migration_id) VALUES (%s)",
            (path.name,),
        )
        applied.append(path.name)
    connection.commit()
    return applied


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m dashboard.migrate",
        description=(
            "Create or upgrade the dashboard schema in the database named by "
            "DATABASE_URL. Safe to rerun: applied migrations are skipped."
        ),
        epilog="Example: DATABASE_URL=postgresql:///dashboard uv run --project v2 python -m dashboard.migrate",
    )
    parser.parse_args(argv)
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL is required", file=sys.stderr)
        return 2
    with psycopg.connect(url) as connection:
        applied = apply(connection)
    print("applied: " + (", ".join(applied) if applied else "nothing to do"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
