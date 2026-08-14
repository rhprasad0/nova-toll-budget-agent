from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from orchestrator import routing
from orchestrator.schemas import I95DirectionResult
from tests.conftest import FakeConnection

EASTERN = ZoneInfo("America/New_York")
REQUESTED_AT = "2026-08-13T08:00:00-04:00"
EFFECTIVE_AT = datetime(2026, 8, 13, 7, 55, tzinfo=EASTERN)
OBSERVED_AT = datetime(2026, 8, 13, 7, 50, tzinfo=EASTERN)


def row(
    od_pair_id: int,
    corridor: str,
    status: str,
    *,
    effective_at: datetime = EFFECTIVE_AT,
) -> tuple[object, ...]:
    return od_pair_id, corridor, effective_at, OBSERVED_AT, status


def test_direction_returns_one_open_observed_direction(monkeypatch):
    conn = FakeConnection(
        [
            row(1132, "I-95-NB", "NORTHBOUND_OPEN"),
            row(1151, "I-95-SB", "CLOSED"),
        ]
    )
    monkeypatch.setattr(routing, "_connect", lambda: conn)

    result = routing.i95_direction(REQUESTED_AT)

    assert I95DirectionResult.model_validate(result).open_direction == "Northbound"
    assert result["status"] == "supported"
    assert result["source_kind"] == "observed"
    assert {item["link_status"] for item in result["observations"]} == {
        "NORTHBOUND_OPEN",
        "CLOSED",
    }
    assert conn.closed
    assert len(conn.cur.queries) == 2
    assert all("zone_toll_rate_usd" not in query for query, _ in conn.cur.queries)
    assert all("trip_pricing_i95" in query for query, _ in conn.cur.queries)


def test_direction_supports_southbound(monkeypatch):
    monkeypatch.setattr(
        routing,
        "_connect",
        lambda: FakeConnection(
            [
                row(1132, "I-95-NB", "CLOSED"),
                row(1151, "I-95-SB", "SOUTHBOUND_OPEN"),
            ]
        ),
    )

    result = routing.i95_direction(REQUESTED_AT)

    assert result["status"] == "supported"
    assert result["open_direction"] == "Southbound"


@pytest.mark.parametrize(
    "rows,reason_code",
    [
        (
            [
                row(1132, "I-95-NB", "CLOSED"),
                row(1151, "I-95-SB", "CLOSED"),
            ],
            "direction_indeterminate",
        ),
        ([None, row(1151, "I-95-SB", "SOUTHBOUND_OPEN")], "missing_observation"),
        (
            [
                row(1132, "I-95-NB", "NORTHBOUND_OPEN"),
                row(
                    1151,
                    "I-95-SB",
                    "CLOSED",
                    effective_at=datetime(2026, 8, 13, 7, 50, tzinfo=EASTERN),
                ),
            ],
            "mismatched_intervals",
        ),
    ],
)
def test_direction_fails_closed_for_unusable_evidence(monkeypatch, rows, reason_code):
    monkeypatch.setattr(routing, "_connect", lambda: FakeConnection(rows))

    result = routing.i95_direction(REQUESTED_AT)

    assert I95DirectionResult.model_validate(result).status == "unavailable"
    assert result["reason_code"] == reason_code
    assert result["open_direction"] is None


@pytest.mark.parametrize(
    "requested_at,reason_code",
    [
        ("not-a-time", "invalid_time"),
        ("2026-08-13T08:00:00", "invalid_time"),
        ("2999-01-01T08:00:00-05:00", "future_direction_unavailable"),
    ],
)
def test_direction_rejects_invalid_naive_and_future_times(
    monkeypatch, requested_at, reason_code
):
    monkeypatch.setattr(
        routing,
        "_connect",
        lambda: pytest.fail("invalid requests must not connect to RDS"),
    )

    result = routing.i95_direction(requested_at)

    assert result["status"] == "unavailable"
    assert result["reason_code"] == reason_code


def test_direction_tool_schema_requires_requested_at():
    spec = routing.i95_direction.tool_spec
    assert spec["name"] == "i95_direction"
    assert spec["inputSchema"]["json"]["required"] == ["requested_at"]
