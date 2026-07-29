"""Compare route-tool output to independently queried, current RDS rows.

This suite is deliberately CI-only: it requires the Tailscale route, the
``nova-toll-github-ci`` OIDC role, and the pricing_reader IAM database user.
It reads expected rows with its own SQL before invoking any tool, then pins
the tool's ``at_time`` to that row's ``interval_end_at``. That prevents the
ten-minute source refresh from racing an exact-value assertion.

Run explicitly (with the same environment as the CI integration job):

    uv run pytest -m live tests/test_ci_rds_route_tools.py -v
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import LiteralString

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from rds_ci_test_support import (
    configure_pricing_reader_rds_env,
    connect_as_pricing_reader,
)

sys.path.insert(0, str(REPO_ROOT / "agent_tools"))

from i66_route import i66_route
from i495_route import i495_route

pytestmark = pytest.mark.live


@pytest.fixture(scope="module", autouse=True)
def pricing_reader_rds_env():
    configure_pricing_reader_rds_env()


def _fetchone(sql: LiteralString, params: tuple | list | None = None) -> tuple:
    """Execute test-owned read-only SQL, independently from the route tools."""
    with connect_as_pricing_reader() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
    assert row is not None, "independent RDS query returned no expected toll row"
    return row


def _assert_common_price_fields(
    result: dict, expected_rate: Decimal, expected_at: datetime
):
    assert "error" not in result, result
    assert len(result["legs"]) == 1
    assert result["legs"][0]["price_usd"] == str(expected_rate)
    assert result["legs"][0]["priced_as_of"] == expected_at.isoformat()
    assert result["total_usd"] == str(expected_rate)
    assert result["at_time"] == expected_at.isoformat()


def _current_open_i95_case() -> tuple[dict, tuple]:
    """Return an oracle pair and its newest directionally-open RDS row.

    I-95's lanes reverse, so a fixed northbound or southbound example would
    make CI fail during the other direction's operating window. The route map
    is read directly here rather than through i95_route, keeping discovery
    independent from the tool under test.
    """
    nodes = _I95_ORACLE["nodes"]
    pairs = [
        pair
        for pair in _I95_ORACLE["pairs"]
        if not nodes[pair["entry"]]["path"].startswith("495")
        and not nodes[pair["exit"]]["path"].startswith("495")
    ]
    pairs_by_od = {pair["ods"][0]: pair for pair in pairs if len(pair["ods"]) == 1}
    # Fetch every candidate's newest row once. The status test stays in Python
    # because the expected open value depends on the row's corridor_name.
    now = datetime.now(UTC)
    with connect_as_pricing_reader() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT ON (od_pair_id)
                od_pair_id, corridor_name, zone_toll_rate_usd, interval_end_at, link_status
            FROM trip_pricing_i95
            WHERE od_pair_id = ANY(%s) AND interval_end_at <= %s
            ORDER BY od_pair_id, interval_end_at DESC
            """,
            (list(pairs_by_od), now),
        )
        candidates = cur.fetchall()

    for row in candidates:
        od_pair_id, corridor_name, _, _, link_status = row
        if link_status == _I95_REQUIRED_STATUS.get(corridor_name):
            return pairs_by_od[od_pair_id], row
    pytest.fail("RDS has no current, directionally-open oracle-supported I-95 toll row")


def test_i95_route_matches_independently_read_open_rds_price():
    pair, row = _current_open_i95_case()
    od_pair_id, corridor_name, rate, interval_end_at, _ = row
    nodes = _I95_ORACLE["nodes"]

    result = i95_route(
        nodes[pair["entry"]]["label"],
        nodes[pair["exit"]]["label"],
        at_time=interval_end_at.isoformat(),
    )

    _assert_common_price_fields(result, rate, interval_end_at)
    assert result["legs"][0]["od_pair_id"] == od_pair_id
    assert result["legs"][0]["corridor_name"] == corridor_name


def test_i95_route_refuses_historical_northbound_closure():
    at_time = "2026-07-29T15:40:00-04:00"
    row = _fetchone(
        """
        SELECT od_pair_id, corridor_name, link_status
        FROM trip_pricing_i95
        WHERE od_pair_id = %s AND interval_end_at = %s
        """,
        (1132, at_time),
    )
    assert row == (1132, "I-95-NB", "CLOSED")

    result = i95_route("US-1", "I-395 Near Edsall Road", at_time=at_time)

    assert "error" in result
    assert result["valid_options"] == []
    assert "1132" in result["error"]
    assert "CLOSED" in result["error"]
    assert "legs" not in result


def test_i95_route_refuses_historical_southbound_closure():
    at_time = "2026-07-29T10:10:00-04:00"
    row = _fetchone(
        """
        SELECT od_pair_id, corridor_name, link_status
        FROM trip_pricing_i95
        WHERE od_pair_id = %s AND interval_end_at = %s
        """,
        (1151, at_time),
    )
    assert row == (1151, "I-95-SB", "CLOSED")

    result = i95_route("I-395 Near Edsall Road", "US-1", at_time=at_time)

    assert "error" in result
    assert result["valid_options"] == []
    assert "1151" in result["error"]
    assert "CLOSED" in result["error"]
    assert "legs" not in result


def test_i95_route_refuses_historical_both_lanes_closure():
    at_time = "2026-07-29T10:50:00-04:00"
    northbound_row = _fetchone(
        """
        SELECT od_pair_id, corridor_name, link_status
        FROM trip_pricing_i95
        WHERE od_pair_id = %s AND interval_end_at = %s
        """,
        (1132, at_time),
    )
    southbound_row = _fetchone(
        """
        SELECT od_pair_id, corridor_name, link_status
        FROM trip_pricing_i95
        WHERE od_pair_id = %s AND interval_end_at = %s
        """,
        (1151, at_time),
    )
    assert northbound_row == (1132, "I-95-NB", "CLOSED")
    assert southbound_row == (1151, "I-95-SB", "CLOSED")

    northbound = i95_route("US-1", "I-395 Near Edsall Road", at_time=at_time)
    southbound = i95_route("I-395 Near Edsall Road", "US-1", at_time=at_time)

    for result, od_pair_id in ((northbound, 1132), (southbound, 1151)):
        assert "error" in result
        assert result["valid_options"] == []
        assert str(od_pair_id) in result["error"]
        assert "CLOSED" in result["error"]
        assert "legs" not in result


@pytest.mark.parametrize(
    ("od_pair_id", "origin", "destination"),
    [
        (1038, "Route 267", "495 Express Lanes End/George Wash. Mem. Pkwy."),
        (1040, "495 Express Lanes Start/Georg Wash. Mem. Pkwy.", "I-495/I-95 Near Van Dorn Street"),
    ],
    ids=("northbound", "southbound"),
)
def test_i495_route_matches_independently_read_latest_rds_price(
    od_pair_id, origin, destination
):
    row = _fetchone(
        """
        SELECT od_pair_id, corridor_name, zone_toll_rate_usd, interval_end_at
        FROM trip_pricing_i95
        WHERE od_pair_id = %s AND interval_end_at <= %s
        ORDER BY interval_end_at DESC
        LIMIT 1
        """,
        (od_pair_id, datetime.now(UTC)),
    )
    actual_od_pair_id, corridor_name, rate, interval_end_at = row

    result = i495_route(
        origin,
        destination,
        at_time=interval_end_at.isoformat(),
    )

    _assert_common_price_fields(result, rate, interval_end_at)
    assert actual_od_pair_id == od_pair_id
    assert result["legs"][0]["od_pair_id"] == actual_od_pair_id
    assert result["legs"][0]["corridor_name"] == corridor_name


def test_i66_route_matches_independently_read_latest_rds_price():
    row = _fetchone(
        """
        SELECT start_zone_id, end_zone_id, corridor_name, zone_toll_rate_usd, interval_end_at
        FROM trip_pricing_i66
        WHERE start_zone_id = %s AND end_zone_id = %s AND interval_end_at <= %s
        ORDER BY interval_end_at DESC
        LIMIT 1
        """,
        (3100, 3110, datetime.now(UTC)),
    )
    start_zone_id, end_zone_id, corridor_name, rate, interval_end_at = row

    result = i66_route(
        "I-66 West",
        "Westmoreland St",
        at_time=interval_end_at.isoformat(),
    )

    _assert_common_price_fields(result, rate, interval_end_at)
    assert result["legs"][0]["start_zone_id"] == start_zone_id
    assert result["legs"][0]["end_zone_id"] == end_zone_id
    assert result["legs"][0]["corridor_name"] == corridor_name
