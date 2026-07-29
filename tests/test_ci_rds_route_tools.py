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

import json
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

from dulles_route import dulles_route
from i66_route import i66_route
from i95_route import i95_route
from i495_route import i495_route

pytestmark = pytest.mark.live

_I95_ORACLE = json.loads((REPO_ROOT / "oracles" / "i95.json").read_text())
_I95_REQUIRED_STATUS = {
    "I-95-NB": "NORTHBOUND_OPEN",
    "I-95-SB": "SOUTHBOUND_OPEN",
}


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


def _assert_price_at(
    result: dict,
    expected_rate: Decimal,
    expected_as_of: datetime,
    requested_at: datetime,
):
    """Assert a tool's source row and this test's shared requested time."""
    assert "error" not in result, result
    assert len(result["legs"]) == 1
    assert result["legs"][0]["price_usd"] == str(expected_rate)
    assert result["legs"][0]["priced_as_of"] == expected_as_of.isoformat()
    assert result["total_usd"] == str(expected_rate)
    assert result["at_time"] == requested_at.isoformat()


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
    "i95_origin, i95_destination, i95_od_pair_id, i95_status, i495_origin, i495_destination, i495_od_pair_id",
    [
        (
            "US-1",
            "Franconia-Springfield Parkway/Route 289",
            1130,
            "NORTHBOUND_OPEN",
            "I-495/I-95 Near Van Dorn Street",
            "Westpark Drive",
            1089,
        ),
        (
            "Franconia-Springfield Parkway/Route 289",
            "US-1",
            1168,
            "SOUTHBOUND_OPEN",
            "Westpark Drive",
            "I-495/I-95 Near Van Dorn Street",
            1062,
        ),
    ],
)
def test_i95_i495_junction_tools_match_shared_requested_time(
    i95_origin,
    i95_destination,
    i95_od_pair_id,
    i95_status,
    i495_origin,
    i495_destination,
    i495_od_pair_id,
):
    row = _fetchone(
        """
        WITH requested AS (
            SELECT LEAST(
                (SELECT interval_end_at FROM trip_pricing_i95
                 WHERE od_pair_id = %s AND link_status = %s
                   AND interval_end_at <= CURRENT_TIMESTAMP
                 ORDER BY interval_end_at DESC LIMIT 1),
                (SELECT interval_end_at FROM trip_pricing_i95
                 WHERE od_pair_id = %s AND interval_end_at <= CURRENT_TIMESTAMP
                 ORDER BY interval_end_at DESC LIMIT 1)
            ) AS at_time
        )
        SELECT
            requested.at_time,
            i95.od_pair_id, i95.corridor_name, i95.zone_toll_rate_usd, i95.interval_end_at,
            i495.od_pair_id, i495.corridor_name, i495.zone_toll_rate_usd, i495.interval_end_at
        FROM requested
        CROSS JOIN LATERAL (
            SELECT od_pair_id, corridor_name, zone_toll_rate_usd, interval_end_at
            FROM trip_pricing_i95
            WHERE od_pair_id = %s AND link_status = %s
              AND interval_end_at <= requested.at_time
            ORDER BY interval_end_at DESC LIMIT 1
        ) AS i95
        CROSS JOIN LATERAL (
            SELECT od_pair_id, corridor_name, zone_toll_rate_usd, interval_end_at
            FROM trip_pricing_i95
            WHERE od_pair_id = %s AND interval_end_at <= requested.at_time
            ORDER BY interval_end_at DESC LIMIT 1
        ) AS i495
        """,
        (
            i95_od_pair_id,
            i95_status,
            i495_od_pair_id,
            i95_od_pair_id,
            i95_status,
            i495_od_pair_id,
        ),
    )
    (
        at_time,
        i95_od,
        i95_corridor,
        i95_rate,
        i95_as_of,
        i495_od,
        i495_corridor,
        i495_rate,
        i495_as_of,
    ) = row

    i95_result = i95_route(i95_origin, i95_destination, at_time=at_time.isoformat())
    i495_result = i495_route(i495_origin, i495_destination, at_time=at_time.isoformat())

    _assert_price_at(i95_result, i95_rate, i95_as_of, at_time)
    assert i95_result["legs"][0]["od_pair_id"] == i95_od
    assert i95_result["legs"][0]["corridor_name"] == i95_corridor
    assert i95_result["entry"]["label"] == i95_origin
    assert i95_result["exit"]["label"] == i95_destination

    _assert_price_at(i495_result, i495_rate, i495_as_of, at_time)
    assert i495_result["legs"][0]["od_pair_id"] == i495_od
    assert i495_result["legs"][0]["corridor_name"] == i495_corridor
    assert i495_result["entry"]["label"] == i495_origin
    assert i495_result["exit"]["label"] == i495_destination


@pytest.mark.parametrize(
    "i66_origin, i66_destination, i66_start_zone, i66_end_zone, i495_origin, i495_destination, i495_od_pair_id",
    [
        ("I-495 N", "Washington", 3100, 3130, "Route 267", "Interstate 66", 1052),
        ("Washington", "I-495 S", 3200, 3230, "Interstate 66", "Route 267", 1033),
    ],
)
def test_i66_i495_junction_tools_match_shared_requested_time(
    i66_origin,
    i66_destination,
    i66_start_zone,
    i66_end_zone,
    i495_origin,
    i495_destination,
    i495_od_pair_id,
):
    row = _fetchone(
        """
        WITH requested AS (
            SELECT LEAST(
                (SELECT interval_end_at FROM trip_pricing_i66
                 WHERE start_zone_id = %s AND end_zone_id = %s
                   AND interval_end_at <= CURRENT_TIMESTAMP
                 ORDER BY interval_end_at DESC LIMIT 1),
                (SELECT interval_end_at FROM trip_pricing_i95
                 WHERE od_pair_id = %s AND interval_end_at <= CURRENT_TIMESTAMP
                 ORDER BY interval_end_at DESC LIMIT 1)
            ) AS at_time
        )
        SELECT
            requested.at_time,
            i66.start_zone_id, i66.end_zone_id, i66.corridor_name, i66.zone_toll_rate_usd,
            i66.interval_end_at,
            i495.od_pair_id, i495.corridor_name, i495.zone_toll_rate_usd, i495.interval_end_at
        FROM requested
        CROSS JOIN LATERAL (
            SELECT start_zone_id, end_zone_id, corridor_name, zone_toll_rate_usd, interval_end_at
            FROM trip_pricing_i66
            WHERE start_zone_id = %s AND end_zone_id = %s
              AND interval_end_at <= requested.at_time
            ORDER BY interval_end_at DESC LIMIT 1
        ) AS i66
        CROSS JOIN LATERAL (
            SELECT od_pair_id, corridor_name, zone_toll_rate_usd, interval_end_at
            FROM trip_pricing_i95
            WHERE od_pair_id = %s AND interval_end_at <= requested.at_time
            ORDER BY interval_end_at DESC LIMIT 1
        ) AS i495
        """,
        (
            i66_start_zone,
            i66_end_zone,
            i495_od_pair_id,
            i66_start_zone,
            i66_end_zone,
            i495_od_pair_id,
        ),
    )
    (
        at_time,
        i66_start,
        i66_end,
        i66_corridor,
        i66_rate,
        i66_as_of,
        i495_od,
        i495_corridor,
        i495_rate,
        i495_as_of,
    ) = row

    i66_result = i66_route(i66_origin, i66_destination, at_time=at_time.isoformat())
    i495_result = i495_route(i495_origin, i495_destination, at_time=at_time.isoformat())

    _assert_price_at(i66_result, i66_rate, i66_as_of, at_time)
    assert i66_result["legs"][0]["start_zone_id"] == i66_start
    assert i66_result["legs"][0]["end_zone_id"] == i66_end
    assert i66_result["legs"][0]["corridor_name"] == i66_corridor
    assert i66_result["entry"]["label"] == i66_origin
    assert i66_result["exit"]["label"] == i66_destination

    _assert_price_at(i495_result, i495_rate, i495_as_of, at_time)
    assert i495_result["legs"][0]["od_pair_id"] == i495_od
    assert i495_result["legs"][0]["corridor_name"] == i495_corridor
    assert i495_result["entry"]["label"] == i495_origin
    assert i495_result["exit"]["label"] == i495_destination


@pytest.mark.parametrize(
    "i495_origin, i495_destination, od_pair_id, dulles_origin, dulles_destination",
    [
        (
            "Westpark Drive",
            "Route 267",
            1036,
            "Exit 18/19 - I-495 / SR 123 (Capital Beltway)",
            "Exit 12 - SR 602 (Reston Pkwy)",
        ),
        (
            "Route 267",
            "Westpark Drive",
            1053,
            "Exit 12 - SR 602 (Reston Pkwy)",
            "Exit 18/19 - I-495 / SR 123 (Capital Beltway)",
        ),
    ],
)
def test_i495_dulles_toll_road_junction_tools_match_shared_requested_time(
    i495_origin,
    i495_destination,
    od_pair_id,
    dulles_origin,
    dulles_destination,
):
    row = _fetchone(
        """
        SELECT od_pair_id, corridor_name, zone_toll_rate_usd, interval_end_at
        FROM trip_pricing_i95
        WHERE od_pair_id = %s AND interval_end_at <= CURRENT_TIMESTAMP
        ORDER BY interval_end_at DESC
        LIMIT 1
        """,
        (od_pair_id,),
    )
    resolved_od_pair_id, corridor_name, rate, at_time = row

    i495_result = i495_route(i495_origin, i495_destination, at_time=at_time.isoformat())
    dulles_result = dulles_route(
        dulles_origin, dulles_destination, at_time=at_time.isoformat()
    )

    _assert_price_at(i495_result, rate, at_time, at_time)
    assert i495_result["legs"][0]["od_pair_id"] == resolved_od_pair_id
    assert i495_result["legs"][0]["corridor_name"] == corridor_name
    assert i495_result["entry"]["label"] == i495_origin
    assert i495_result["exit"]["label"] == i495_destination
    [dulles_leg] = dulles_result["legs"]
    assert dulles_leg["facility"] == "dulles_toll_road"
    assert dulles_leg["entry"]["label"] == dulles_origin
    assert dulles_leg["exit"]["label"] == dulles_destination


@pytest.mark.parametrize(
    ("od_pair_id", "origin", "destination"),
    [
        (1038, "Route 267", "495 Express Lanes End/George Wash. Mem. Pkwy."),
        (
            1040,
            "495 Express Lanes Start/Georg Wash. Mem. Pkwy.",
            "I-495/I-95 Near Van Dorn Street",
        ),
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
