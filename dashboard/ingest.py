import argparse
import os
import sys
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, cast

import psycopg

from dashboard.analytics import (
    COST_PATH,
    DEFAULT_WORKSPACE_ID,
    USAGE_PATH,
    AnalyticsClient,
    AnalyticsError,
    CursorExpired,
    HttpAnalyticsClient,
)

EARLIEST = datetime(2026, 1, 1, tzinfo=UTC)
CHUNK = timedelta(days=31)
PAGE_LIMIT = 1000
MAX_RESTARTS = 5
USAGE_GROUPS = ("agent_id", "session_id", "model")
COST_GROUPS = (*USAGE_GROUPS, "cost_type", "token_type")


@dataclass(frozen=True)
class IngestResult:
    window_start: datetime
    window_end: datetime
    usage_rows: int
    cost_rows: int


def _timestamp(text: str) -> datetime:
    value = datetime.fromisoformat(text)
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def chunks(start: datetime, end: datetime) -> Iterator[tuple[datetime, datetime]]:
    cursor = start
    while cursor < end:
        yield cursor, min(cursor + CHUNK, end)
        cursor += CHUNK


def _rfc3339(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch_all(
    client: AnalyticsClient, path: str, params: Sequence[tuple[str, str]]
) -> tuple[list[dict[str, Any]], datetime | None]:
    for _ in range(MAX_RESTARTS + 1):
        rows: list[dict[str, Any]] = []
        page: str | None = None
        try:
            while True:
                query = [*params, ("page", page)] if page else list(params)
                body = client.get(path, query)
                rows.extend(body.get("data") or [])
                if not body.get("has_more"):
                    refreshed = body.get("data_refreshed_at")
                    return rows, _timestamp(refreshed) if refreshed else None
                page = body.get("next_page")
                if not page:
                    raise AnalyticsError(
                        f"{path} reported more pages without next_page"
                    )
        except CursorExpired:
            continue
    raise AnalyticsError(f"{path} cursor kept expiring after {MAX_RESTARTS} restarts")


def _obj(value: object) -> dict[str, Any]:
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


def _count(value: object) -> int:
    return int(value) if isinstance(value, (int, float, str)) else 0


def _usage_record(row: dict[str, Any]) -> tuple[tuple[Any, ...], tuple[Any, ...]]:
    group = _obj(row.get("group"))
    usage = _obj(row.get("usage"))
    creation = _obj(usage.get("cache_creation"))
    uncached = _count(usage.get("uncached_input_tokens"))
    cache_1h = _count(creation.get("ephemeral_1h_input_tokens"))
    cache_5m = _count(creation.get("ephemeral_5m_input_tokens"))
    read = _count(usage.get("cache_read_input_tokens"))
    output = _count(usage.get("output_tokens"))
    total = usage.get("total_tokens")
    total = (
        uncached + cache_1h + cache_5m + read + output if total is None else int(total)
    )
    key = (
        _timestamp(row["starting_at"]),
        group.get("agent_id") or "",
        group.get("session_id") or "",
        group.get("model") or "",
    )
    searches = _count(_obj(usage.get("server_tool_use")).get("web_search_requests"))
    values = (
        uncached,
        cache_1h,
        cache_5m,
        read,
        output,
        total,
        _count(usage.get("requests")),
        searches,
    )
    return key, values


def _cost_record(row: dict[str, Any]) -> tuple[tuple[Any, ...], tuple[Any, ...]]:
    group = _obj(row.get("group"))
    cost = _obj(row.get("cost"))
    listed = cost.get("list_amount")
    key = (
        _timestamp(row["starting_at"]),
        group.get("agent_id") or "",
        group.get("session_id") or "",
        group.get("model") or "",
        group.get("cost_type") or "",
        group.get("token_type") or "",
    )
    values = (
        Decimal(str(cost.get("amount") or "0")),
        None if listed is None else Decimal(str(listed)),
        cost.get("currency") or "USD",
        _count(cost.get("requests")),
    )
    return key, values


UPSERT_USAGE = """
INSERT INTO dashboard.usage_daily (
    bucket_start, agent_id, session_id, model, uncached_input_tokens,
    cache_creation_1h_input_tokens, cache_creation_5m_input_tokens,
    cache_read_input_tokens, output_tokens, total_tokens, requests,
    web_search_requests)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (bucket_start, agent_id, session_id, model) DO UPDATE SET
    uncached_input_tokens = EXCLUDED.uncached_input_tokens,
    cache_creation_1h_input_tokens = EXCLUDED.cache_creation_1h_input_tokens,
    cache_creation_5m_input_tokens = EXCLUDED.cache_creation_5m_input_tokens,
    cache_read_input_tokens = EXCLUDED.cache_read_input_tokens,
    output_tokens = EXCLUDED.output_tokens,
    total_tokens = EXCLUDED.total_tokens,
    requests = EXCLUDED.requests,
    web_search_requests = EXCLUDED.web_search_requests,
    ingested_at = now()
"""

UPSERT_COST = """
INSERT INTO dashboard.cost_daily (
    bucket_start, agent_id, session_id, model, cost_type, token_type,
    amount_cents, list_amount_cents, currency, requests)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (bucket_start, agent_id, session_id, model, cost_type, token_type)
DO UPDATE SET
    amount_cents = EXCLUDED.amount_cents,
    list_amount_cents = EXCLUDED.list_amount_cents,
    currency = EXCLUDED.currency,
    requests = EXCLUDED.requests,
    ingested_at = now()
"""


def run(
    client: AnalyticsClient,
    connection: psycopg.Connection,
    *,
    now: datetime,
    days: int = 45,
    workspace_id: str = DEFAULT_WORKSPACE_ID,
) -> IngestResult:
    end = now.astimezone(UTC).replace(microsecond=0)
    midnight = end.replace(hour=0, minute=0, second=0)
    start = max(midnight - timedelta(days=days), EARLIEST)
    if end <= start:
        raise AnalyticsError("the ingest window is empty")

    usage: dict[tuple[Any, ...], tuple[Any, ...]] = {}
    cost: dict[tuple[Any, ...], tuple[Any, ...]] = {}
    usage_refreshed: list[datetime] = []
    cost_refreshed: list[datetime] = []
    for chunk_start, chunk_end in chunks(start, end):
        window = [
            ("starting_at", _rfc3339(chunk_start)),
            ("ending_at", _rfc3339(chunk_end)),
            ("time_bucket_width", "1d"),
            ("workspace_ids[]", workspace_id),
            ("limit", str(PAGE_LIMIT)),
        ]
        for path, groups, rows, store, refreshed in (
            (USAGE_PATH, USAGE_GROUPS, usage, _usage_record, usage_refreshed),
            (COST_PATH, COST_GROUPS, cost, _cost_record, cost_refreshed),
        ):
            params = [*window, *(("group_by[]", name) for name in groups)]
            fetched, stamp = fetch_all(client, path, params)
            for row in fetched:
                key, values = store(row)
                rows[key] = values
            if stamp:
                refreshed.append(stamp)

    with connection.transaction(), connection.cursor() as cursor:
        cursor.executemany(
            UPSERT_USAGE, [(*key, *values) for key, values in usage.items()]
        )
        cursor.executemany(
            UPSERT_COST, [(*key, *values) for key, values in cost.items()]
        )
        cursor.execute(
            "INSERT INTO dashboard.ingest_run "
            "(window_start, window_end, usage_refreshed_at, cost_refreshed_at) "
            "VALUES (%s, %s, %s, %s)",
            (
                start,
                end,
                min(usage_refreshed, default=None),
                min(cost_refreshed, default=None),
            ),
        )
    return IngestResult(start, end, len(usage), len(cost))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m dashboard.ingest",
        description=(
            "Pull a trailing window of Anthropic usage and cost analytics for the "
            "factory workspace into Postgres. The window is cut into 31-day chunks. "
            "Rows are upserted by bucket and group, so reruns are idempotent, pick "
            "up revised values and never delete history outside the window. "
            "Needs DATABASE_URL and ANTHROPIC_ADMIN_KEY; FACTORY_WORKSPACE_ID "
            f"overrides the workspace (default {DEFAULT_WORKSPACE_ID})."
        ),
        epilog="Example: ANTHROPIC_ADMIN_KEY=sk-ant-admin... DATABASE_URL=postgresql:///dashboard uv run --project v2 python -m dashboard.ingest --days 45",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=45,
        help="trailing window in days, counted back from today 00:00 UTC (default 45)",
    )
    args = parser.parse_args(argv)
    url = os.environ.get("DATABASE_URL")
    key = os.environ.get("ANTHROPIC_ADMIN_KEY")
    if not url or not key:
        print("DATABASE_URL and ANTHROPIC_ADMIN_KEY are required", file=sys.stderr)
        return 2
    if args.days < 1:
        print("--days must be at least 1", file=sys.stderr)
        return 2
    workspace = os.environ.get("FACTORY_WORKSPACE_ID") or DEFAULT_WORKSPACE_ID
    try:
        with psycopg.connect(url) as connection:
            result = run(
                HttpAnalyticsClient(key),
                connection,
                now=datetime.now(UTC),
                days=args.days,
                workspace_id=workspace,
            )
    except AnalyticsError as error:
        print(f"ingest failed: {error}", file=sys.stderr)
        return 1
    print(
        f"ingested {result.usage_rows} usage rows and {result.cost_rows} cost rows "
        f"for {result.window_start:%Y-%m-%d} to {result.window_end:%Y-%m-%d %H:%M} UTC"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
