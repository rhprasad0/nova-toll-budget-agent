from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

import psycopg

from dashboard.agents import agent_label, ordered_labels

SINCE = date(2026, 1, 1)
RANGES = {"30d": "Last 30 days", "all": "All data since 2026-01-01"}
TOP_SESSIONS = 10
ZERO = Decimal(0)


@dataclass(frozen=True)
class TopSession:
    session_id: str
    agent: str
    day: date
    tokens: int
    cents: Decimal


@dataclass(frozen=True)
class SessionStats:
    median: Decimal
    p90: Decimal
    maximum: Decimal


@dataclass(frozen=True)
class Report:
    range_key: str
    first_day: date
    last_day: date
    days: list[date]
    agents: list[str]
    cents_by_agent: dict[str, Decimal]
    tokens_by_agent: dict[str, int]
    daily_cents: dict[tuple[date, str], Decimal]
    sessions: dict[tuple[date, str], int]
    session_stats: dict[str, SessionStats]
    cache_efficiency: dict[tuple[date, str], Decimal | None]
    cents_by_cost_type: dict[str, Decimal]
    tokens_by_model: dict[str, int]
    top_sessions: list[TopSession]
    refreshed_at: datetime | None

    @property
    def total_cents(self) -> Decimal:
        return sum(self.cents_by_agent.values(), ZERO)

    @property
    def total_tokens(self) -> int:
        return sum(self.tokens_by_agent.values())


def percentile(values: list[Decimal], fraction: Decimal) -> Decimal:
    ordered = sorted(values)
    position = fraction * (len(ordered) - 1)
    below = int(position)
    above = min(below + 1, len(ordered) - 1)
    return ordered[below] + (ordered[above] - ordered[below]) * (position - below)


def _window(range_key: str, today: date) -> tuple[date, date]:
    if range_key == "30d":
        return today - timedelta(days=29), today
    return SINCE, today


def build(connection: psycopg.Connection, range_key: str, now: datetime) -> Report:
    today = now.astimezone(UTC).date()
    first, last = _window(range_key, today)
    start = datetime.combine(first, time(), tzinfo=UTC)
    end = datetime.combine(last + timedelta(days=1), time(), tzinfo=UTC)
    span = (start, end)
    day = "(bucket_start AT TIME ZONE 'UTC')::date"

    cents_by_agent: dict[str, Decimal] = defaultdict(lambda: ZERO)
    daily_cents: dict[tuple[date, str], Decimal] = defaultdict(lambda: ZERO)
    for agent_id, bucket, cents in connection.execute(
        f"SELECT agent_id, {day}, sum(amount_cents) FROM dashboard.cost_daily "
        "WHERE bucket_start >= %s AND bucket_start < %s GROUP BY 1, 2",
        span,
    ):
        label = agent_label(agent_id)
        cents_by_agent[label] += cents
        daily_cents[(bucket, label)] += cents

    tokens_by_agent: dict[str, int] = defaultdict(int)
    cache_parts: dict[tuple[date, str], list[int]] = defaultdict(lambda: [0, 0])
    for agent_id, bucket, tokens, uncached, created, read in connection.execute(
        f"SELECT agent_id, {day}, sum(total_tokens), sum(uncached_input_tokens), "
        "sum(cache_creation_1h_input_tokens + cache_creation_5m_input_tokens), "
        "sum(cache_read_input_tokens) FROM dashboard.usage_daily "
        "WHERE bucket_start >= %s AND bucket_start < %s GROUP BY 1, 2",
        span,
    ):
        label = agent_label(agent_id)
        tokens_by_agent[label] += int(tokens)
        parts = cache_parts[(bucket, label)]
        parts[0] += int(read)
        parts[1] += int(uncached) + int(created) + int(read)

    sessions: dict[tuple[date, str], int] = {}
    for agent_id, bucket, count in connection.execute(
        f"SELECT agent_id, {day}, count(DISTINCT session_id) FROM dashboard.usage_daily "
        "WHERE bucket_start >= %s AND bucket_start < %s AND session_id <> '' "
        "GROUP BY 1, 2",
        span,
    ):
        sessions[(bucket, agent_label(agent_id))] = int(count)

    per_session: dict[str, list[Decimal]] = defaultdict(list)
    for agent_id, cents in connection.execute(
        "SELECT agent_id, sum(amount_cents) FROM dashboard.cost_daily "
        "WHERE bucket_start >= %s AND bucket_start < %s AND session_id <> '' "
        "GROUP BY agent_id, session_id",
        span,
    ):
        per_session[agent_label(agent_id)].append(cents)
    session_stats = {
        label: SessionStats(
            percentile(values, Decimal("0.5")),
            percentile(values, Decimal("0.9")),
            max(values),
        )
        for label, values in per_session.items()
    }

    cents_by_cost_type = {
        cost_type or "unknown": cents
        for cost_type, cents in connection.execute(
            "SELECT cost_type, sum(amount_cents) FROM dashboard.cost_daily "
            "WHERE bucket_start >= %s AND bucket_start < %s GROUP BY 1 ORDER BY 2 DESC, 1",
            span,
        )
    }
    tokens_by_model = {
        model or "(none)": int(tokens)
        for model, tokens in connection.execute(
            "SELECT model, sum(total_tokens) FROM dashboard.usage_daily "
            "WHERE bucket_start >= %s AND bucket_start < %s GROUP BY 1 ORDER BY 2 DESC, 1",
            span,
        )
    }

    top_rows = connection.execute(
        f"SELECT session_id, agent_id, min({day}), sum(amount_cents) "
        "FROM dashboard.cost_daily "
        "WHERE bucket_start >= %s AND bucket_start < %s AND session_id <> '' "
        "GROUP BY session_id, agent_id ORDER BY 4 DESC, 1 LIMIT %s",
        (*span, TOP_SESSIONS),
    ).fetchall()
    session_tokens = dict(
        connection.execute(
            "SELECT session_id, sum(total_tokens) FROM dashboard.usage_daily "
            "WHERE bucket_start >= %s AND bucket_start < %s AND session_id = ANY(%s) "
            "GROUP BY session_id",
            (*span, [row[0] for row in top_rows]),
        )
    )
    top_sessions = [
        TopSession(
            session_id,
            agent_label(agent_id),
            first_day,
            int(session_tokens.get(session_id, 0)),
            cents,
        )
        for session_id, agent_id, first_day, cents in top_rows
    ]

    refreshed = connection.execute(
        "SELECT least(usage_refreshed_at, cost_refreshed_at) FROM dashboard.ingest_run "
        "ORDER BY run_id DESC LIMIT 1"
    ).fetchone()

    present = set(cents_by_agent) | set(tokens_by_agent)
    seen_days = {key[0] for key in daily_cents} | {key[0] for key in cache_parts}
    if range_key == "all" and seen_days:
        first = min(seen_days)
    days = [first + timedelta(days=offset) for offset in range((last - first).days + 1)]
    return Report(
        range_key=range_key,
        first_day=first,
        last_day=last,
        days=days,
        agents=ordered_labels(present),
        cents_by_agent=dict(cents_by_agent),
        tokens_by_agent=dict(tokens_by_agent),
        daily_cents=dict(daily_cents),
        sessions=sessions,
        session_stats=session_stats,
        cache_efficiency={
            key: (Decimal(read) / Decimal(total) if total else None)
            for key, (read, total) in cache_parts.items()
        },
        cents_by_cost_type=cents_by_cost_type,
        tokens_by_model=tokens_by_model,
        top_sessions=top_sessions,
        refreshed_at=refreshed[0] if refreshed else None,
    )
