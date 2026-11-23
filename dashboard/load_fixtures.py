import argparse
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg

from dashboard import ingest
from dashboard.fake_client import FakeAnalytics

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load(name: str) -> tuple[list[dict[str, Any]], str]:
    document = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return document["data"], document["data_refreshed_at"]


def run(
    connection: psycopg.Connection, *, now: datetime, keep_dates: bool = False
) -> ingest.IngestResult:
    usage, usage_refreshed = _load("usage.json")
    cost, cost_refreshed = _load("cost.json")
    shift = 0
    if not keep_dates:
        newest = max(datetime.fromisoformat(row["starting_at"]) for row in usage)
        yesterday = now.astimezone(UTC).replace(
            hour=0, minute=0, second=0, microsecond=0
        ) - timedelta(days=1)
        shift = (yesterday - newest).days
    fake = FakeAnalytics(
        usage,
        cost,
        usage_refreshed_at=usage_refreshed,
        cost_refreshed_at=cost_refreshed,
        shift_days=shift,
    )
    return ingest.run(fake, connection, now=now)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m dashboard.load_fixtures",
        description=(
            "Load the recorded-style fixture data (a fake Anthropic API served through "
            "the real ingest code) into the database named by DATABASE_URL, so the "
            "page can be tried locally without an Admin key. Run "
            "python -m dashboard.migrate first. Dates move so the newest fixture "
            "day is yesterday."
        ),
        epilog="Example: DATABASE_URL=postgresql:///dashboard uv run --project v2 python -m dashboard.load_fixtures",
    )
    parser.add_argument(
        "--keep-dates",
        action="store_true",
        help="keep the recorded dates (2026-10-23 to 2026-11-22) instead of moving them",
    )
    args = parser.parse_args(argv)
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL is required", file=sys.stderr)
        return 2
    with psycopg.connect(url) as connection:
        result = run(connection, now=datetime.now(UTC), keep_dates=args.keep_dates)
    print(f"loaded {result.usage_rows} usage rows and {result.cost_rows} cost rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
