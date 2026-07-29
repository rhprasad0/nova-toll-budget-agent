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


@pytest.mark.parametrize(
    ("od_pair_id", "origin", "destination"),
    [
        (
            1038,
            "Route 267",
            "495 Express Lanes End/George Wash. Mem. Pkwy.",
        ),
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
