"""Dashboard end to end: fake Anthropic API, then ingest, then HTTP GET against a real database."""

import json
import re
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from collections.abc import Callable, Generator
from datetime import UTC, datetime
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, urlsplit

import pytest

from dashboard.fake_client import FakeAnalytics

if TYPE_CHECKING:
    from dashboard.ingest import IngestResult

REPOSITORY = Path(__file__).resolve().parents[2]
DATABASE = "nova_toll_dashboard_test"
DATABASE_URL = f"postgresql:///{DATABASE}"
NOW = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)
WORKSPACE = "wrkspc_01FDNWCYNuxbxcZhFsD76VoQ"
WORKER = "agent_01Y8aT4NryjgTqtipBqBssyY"
REVIEWER = "agent_011ssC4G41v97wCzCAjg8iQU"
UNMAPPED = "agent_01ZZunmapped"
OPUS = "claude-opus-4-7"
SONNET = "claude-sonnet-4-6"
DAY_A = "2026-11-20"
DAY_B = "2026-11-21"


def usage_row(
    day: str,
    agent: str | None,
    session: str | None,
    model: str | None,
    uncached: int,
    cache_1h: int,
    cache_5m: int,
    read: int,
    output: int,
) -> dict[str, Any]:
    return {
        "starting_at": f"{day}T00:00:00Z",
        "ending_at": f"{day}T00:00:00Z",
        "group": {"agent_id": agent, "session_id": session, "model": model},
        "usage": {
            "uncached_input_tokens": uncached,
            "cache_creation": {
                "ephemeral_1h_input_tokens": cache_1h,
                "ephemeral_5m_input_tokens": cache_5m,
            },
            "cache_read_input_tokens": read,
            "output_tokens": output,
            "total_tokens": uncached + cache_1h + cache_5m + read + output,
            "requests": 3,
            "server_tool_use": {"web_search_requests": 0},
        },
    }


def cost_row(
    day: str,
    agent: str | None,
    session: str | None,
    cost_type: str,
    cents: str,
    model: str | None = OPUS,
    token_type: str | None = None,
) -> dict[str, Any]:
    return {
        "starting_at": f"{day}T00:00:00Z",
        "ending_at": f"{day}T00:00:00Z",
        "group": {
            "agent_id": agent,
            "session_id": session,
            "model": model,
            "cost_type": cost_type,
            "token_type": token_type,
        },
        "cost": {
            "amount": cents,
            "list_amount": cents,
            "currency": "USD",
            "requests": 1,
        },
    }


def usage_rows() -> list[dict[str, Any]]:
    return [
        usage_row(DAY_A, WORKER, "s1", OPUS, 1000, 0, 1000, 8000, 500),
        usage_row(DAY_B, WORKER, "s2", OPUS, 2000, 0, 0, 2000, 1000),
        usage_row(DAY_B, WORKER, "s3", SONNET, 1000, 0, 0, 0, 100),
        usage_row(DAY_B, REVIEWER, "s4", OPUS, 500, 500, 0, 4000, 200),
        usage_row(DAY_A, UNMAPPED, "s5", SONNET, 100, 0, 0, 0, 10),
        usage_row(DAY_A, None, None, None, 50, 0, 0, 0, 5),
    ]


def cost_rows() -> list[dict[str, Any]]:
    return [
        cost_row(DAY_A, WORKER, "s1", "tokens", "4120.000000", token_type="output"),
        cost_row(DAY_A, WORKER, "s1", "session_usage", "80.000000", None),
        cost_row(DAY_B, WORKER, "s2", "tokens", "1000.000000"),
        cost_row(DAY_B, WORKER, "s3", "tokens", "300.000000", SONNET),
        cost_row(DAY_B, WORKER, "s3", "web_search", "50.000000", SONNET),
        cost_row(DAY_B, REVIEWER, "s4", "tokens", "2500.000000"),
        cost_row(DAY_B, REVIEWER, "s4", "code_execution", "25.000000", None),
        cost_row(DAY_A, UNMAPPED, "s5", "tokens", "10.000000", SONNET),
        cost_row(DAY_A, None, None, "tokens", "5.000000", None),
    ]


@pytest.fixture
def database() -> Generator[str]:
    import psycopg

    with psycopg.connect(dbname="postgres", autocommit=True) as admin:
        admin.execute(f"DROP DATABASE IF EXISTS {DATABASE} WITH (FORCE)")
        admin.execute(f"CREATE DATABASE {DATABASE}")
        try:
            yield DATABASE_URL
        finally:
            admin.execute(f"DROP DATABASE IF EXISTS {DATABASE} WITH (FORCE)")


def ingest(
    database: str,
    fake: FakeAnalytics,
    *,
    now: datetime = NOW,
    days: int = 45,
) -> "IngestResult":
    import psycopg

    from dashboard import ingest as ingest_module
    from dashboard import migrate

    with psycopg.connect(database) as connection:
        migrate.apply(connection)
        return ingest_module.run(
            fake, connection, now=now, days=days, workspace_id=WORKSPACE
        )


def make_fake(
    *, page_size: int = 1000, expire_cursor_once: bool = False
) -> FakeAnalytics:
    return FakeAnalytics(
        usage_rows(),
        cost_rows(),
        usage_refreshed_at="2026-11-23T08:00:00Z",
        cost_refreshed_at="2026-11-23T07:30:00Z",
        page_size=page_size,
        expire_cursor_once=expire_cursor_once,
    )


@pytest.fixture
def get(database: str) -> Generator[Callable[[str], tuple[int, str]]]:
    from dashboard import web

    server = web.make_server(database, "127.0.0.1", 0, now=lambda: NOW)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]

    def fetch(path: str) -> tuple[int, str]:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}") as response:
                return response.status, response.read().decode()
        except urllib.error.HTTPError as error:
            return error.code, error.read().decode()

    try:
        yield fetch
    finally:
        server.shutdown()
        server.server_close()


def cells(page: str) -> dict[str, str]:
    found = re.findall(r'data-k="([^"]+)"[^>]*>([^<]*)<', page)
    values = {key: text.strip() for key, text in found}
    assert len(values) == len(found), "duplicate data-k keys"
    return values


@pytest.mark.live
def test_ingest_then_page_shows_every_number(
    database: str, get: Callable[[str], tuple[int, str]]
) -> None:
    fake = make_fake(page_size=2, expire_cursor_once=True)
    ingest(database, fake)

    status, page = get("/")
    assert status == 200
    assert page.lower().count("<script") == 1
    assert "<script src" not in page.lower()
    assert 'name="viewport"' in page
    values = cells(page)

    assert values["total-cost"] == "$80.90"
    assert values["total-tokens"] == "21,965"
    assert values["cost:worker"] == "$55.50"
    assert values["cost:reviewer"] == "$25.25"
    assert values["cost:docs"] == "$0.00"
    assert values[f"cost:{UNMAPPED}"] == "$0.10"
    assert values["cost:other"] == "$0.05"
    assert values["tokens:worker"] == "16,600"
    assert values["tokens:reviewer"] == "5,200"
    assert values["tokens:other"] == "55"
    assert values["cost-share:worker"] == "68.6%"
    assert values["token-share:worker"] == "75.6%"

    assert values[f"daily:{DAY_A}:worker"] == "$42.00"
    assert values[f"daily:{DAY_B}:worker"] == "$13.50"
    assert values[f"daily:{DAY_B}:reviewer"] == "$25.25"
    assert values[f"daily:{DAY_A}:other"] == "$0.05"

    assert values[f"sessions:{DAY_A}:worker"] == "1"
    assert values[f"sessions:{DAY_B}:worker"] == "2"
    assert values[f"sessions:{DAY_B}:reviewer"] == "1"
    assert values[f"sessions:{DAY_A}:other"] == "0"
    assert values["session-cost:worker:median"] == "$10.00"
    assert values["session-cost:worker:p90"] == "$35.60"
    assert values["session-cost:worker:max"] == "$42.00"
    assert values["session-cost:reviewer:median"] == "$25.25"
    assert values["session-cost:docs:max"] == "n/a"

    assert values[f"cache:{DAY_A}:worker"] == "80.0%"
    assert values[f"cache:{DAY_B}:worker"] == "40.0%"
    assert values[f"cache:{DAY_B}:reviewer"] == "80.0%"
    assert values[f"cache:{DAY_B}:docs"] == "n/a"

    assert values["cost-type:tokens"] == "$79.35"
    assert values["cost-type:session_usage"] == "$0.80"
    assert values["cost-type:web_search"] == "$0.50"
    assert values["cost-type:code_execution"] == "$0.25"

    assert values[f"model:{OPUS}"] == "20,700"
    assert values[f"model:{SONNET}"] == "1,210"
    assert values["model:(none)"] == "55"

    top = [(values[f"top:{n}:session"], values[f"top:{n}:cost"]) for n in range(1, 6)]
    assert top == [
        ("s1", "$42.00"),
        ("s4", "$25.25"),
        ("s2", "$10.00"),
        ("s3", "$3.50"),
        ("s5", "$0.10"),
    ]
    assert values["top:1:agent"] == "worker"
    assert values["top:1:date"] == DAY_A
    assert values["top:1:tokens"] == "10,500"
    assert values["top:2:agent"] == "reviewer"
    assert values["top:2:date"] == DAY_B
    assert "top:6:session" not in values

    assert values["refreshed-at"] == "2026-11-23 07:30 UTC"


@pytest.mark.live
def test_ingest_requests_are_filtered_chunked_and_survive_expired_cursor(
    database: str,
) -> None:
    fake = make_fake(page_size=2, expire_cursor_once=True)
    ingest(database, fake)

    assert fake.requests
    spans: set[tuple[str, str]] = set()
    for path, params in fake.requests:
        assert params["workspace_ids[]"] == [WORKSPACE]
        assert params["time_bucket_width"] == ["1d"]
        start = datetime.fromisoformat(params["starting_at"][0])
        end = datetime.fromisoformat(params["ending_at"][0])
        assert (end - start).days <= 31
        assert start >= datetime(2026, 1, 1, tzinfo=UTC)
        spans.add((params["starting_at"][0], params["ending_at"][0]))
        assert path.rsplit("/", 1)[1] in {"usage", "cost"}
    assert len(spans) == 2
    assert fake.cursor_expirations == 1


@pytest.mark.live
def test_rerun_replaces_revised_values_and_keeps_history_outside_window(
    database: str, get: Callable[[str], tuple[int, str]]
) -> None:
    import psycopg

    history = [
        usage_row("2026-09-01", WORKER, "old", OPUS, 0, 0, 0, 0, 7),
    ]
    old_cost = [cost_row("2026-09-01", WORKER, "old", "tokens", "100.000000")]
    ingest(
        database,
        FakeAnalytics(history, old_cost),
        now=datetime(2026, 10, 5, tzinfo=UTC),
    )

    ingest(database, make_fake())
    ingest(database, make_fake())
    first = cells(get("/")[1])
    assert first["total-cost"] == "$80.90"

    revised_usage = usage_rows()
    revised_usage[0] = usage_row(DAY_A, WORKER, "s1", OPUS, 1000, 0, 1000, 8000, 900)
    revised_cost = cost_rows()
    revised_cost[0] = cost_row(
        DAY_A, WORKER, "s1", "tokens", "5120.000000", token_type="output"
    )
    ingest(database, FakeAnalytics(revised_usage, revised_cost))

    second = cells(get("/")[1])
    assert second["total-cost"] == "$90.90"
    assert second["total-tokens"] == "22,365"
    assert second["cost:worker"] == "$65.50"

    everything = cells(get("/?range=all")[1])
    assert everything["total-cost"] == "$91.90"
    assert everything["total-tokens"] == "22,372"

    with psycopg.connect(database) as connection:
        count = connection.execute(
            "SELECT count(*) FROM dashboard.cost_daily"
        ).fetchone()
    assert count == (len(cost_rows()) + 1,)


@pytest.mark.live
def test_load_fixtures_command_matches_the_recorded_files(
    database: str, get: Callable[[str], tuple[int, str]]
) -> None:
    import psycopg

    from dashboard import load_fixtures, migrate

    with psycopg.connect(database) as connection:
        migrate.apply(connection)
        load_fixtures.run(connection, now=NOW, keep_dates=True)

    recorded = json.loads(
        (REPOSITORY / "dashboard/fixtures/cost.json").read_text(encoding="utf-8")
    )
    expected_cents = sum(Decimal(row["cost"]["amount"]) for row in recorded["data"])
    recorded_usage = json.loads(
        (REPOSITORY / "dashboard/fixtures/usage.json").read_text(encoding="utf-8")
    )
    expected_tokens = sum(
        row["usage"]["total_tokens"] for row in recorded_usage["data"]
    )

    values = cells(get("/?range=all")[1])
    assert values["total-cost"] == f"${expected_cents / 100:,.2f}"
    assert values["total-tokens"] == f"{expected_tokens:,}"
    assert values["cost:worker"] != "$0.00"
    assert values["cost:reviewer"] != "$0.00"
    assert values["cost:docs"] != "$0.00"
    assert [
        key for key in values if key.startswith("top:") and key.endswith(":cost")
    ] == [f"top:{n}:cost" for n in range(1, 11)]


@pytest.mark.live
def test_page_without_data_and_unknown_range(
    database: str, get: Callable[[str], tuple[int, str]]
) -> None:
    import psycopg

    from dashboard import migrate

    with psycopg.connect(database) as connection:
        migrate.apply(connection)
    status, page = get("/")
    assert status == 200
    assert cells(page)["total-cost"] == "$0.00"
    assert cells(page)["refreshed-at"] == "never"
    assert get("/?range=bogus")[0] == 400
    assert get("/healthz")[0] == 200
    assert get("/nope")[0] == 404


def test_http_client_sends_the_documented_request_and_maps_410() -> None:
    from dashboard.analytics import CursorExpired, HttpAnalyticsClient

    seen: list[tuple[str, dict[str, str]]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            seen.append((self.path, dict(self.headers)))
            if "page=stale" in self.path:
                self.send_response(410)
                self.end_headers()
                return
            body = json.dumps({"data": [], "has_more": False}).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        client = HttpAnalyticsClient(
            "test-key", base_url=f"http://127.0.0.1:{server.server_address[1]}"
        )
        assert client.get(
            "/v1/organizations/analytics/usage",
            [("group_by[]", "agent_id"), ("group_by[]", "model"), ("limit", "1000")],
        ) == {"data": [], "has_more": False}
        with pytest.raises(CursorExpired):
            client.get("/v1/organizations/analytics/cost", [("page", "stale")])
    finally:
        server.shutdown()
        server.server_close()

    path, headers = seen[0]
    parts = urlsplit(path)
    assert parts.path == "/v1/organizations/analytics/usage"
    assert parse_qs(parts.query) == {
        "group_by[]": ["agent_id", "model"],
        "limit": ["1000"],
    }
    lowered = {key.lower(): value for key, value in headers.items()}
    assert lowered["x-api-key"] == "test-key"
    assert lowered["anthropic-version"] == "2026-10-21"
    assert lowered["anthropic-beta"] == "analytics-usage-cost-2026-08-24"


def test_agent_names_cover_mapped_unmapped_and_missing() -> None:
    from dashboard.agents import agent_label

    assert agent_label(WORKER) == "worker"
    assert agent_label(REVIEWER) == "reviewer"
    assert agent_label("agent_01N8SxzRnREt1Rzsu6LCRzPD") == "docs"
    assert agent_label(UNMAPPED) == UNMAPPED
    assert agent_label("") == "other"


@pytest.mark.parametrize("command", ["migrate", "ingest", "load_fixtures", "serve"])
def test_every_command_documents_itself(command: str) -> None:
    result = subprocess.run(
        [sys.executable, "-m", f"dashboard.{command}", "--help"],
        cwd=REPOSITORY,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout
