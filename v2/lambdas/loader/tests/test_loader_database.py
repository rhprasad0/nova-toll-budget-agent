"""The real loader upserts into the disposable database that the agent then reads."""

import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from lambdas.loader import handler as handler
else:
    import pricing_loader_handler as handler
import pytest
from parse_csv import I95Row
from parse_xml import I66Row

from agent_tools import current_price_domain as pricing_tool
from agent_tools import validate_toll_route as route_validation

pytestmark = pytest.mark.live

DATABASE = "nova_toll_v2_bootstrap_test"  # built by scripts/run_db_tests.sh
OD_PAIR = 1089  # I-495 northbound 192NO -> 185ND; I-495 rows skip the direction check


def _connect(user: str) -> object:
    import psycopg  # lazy: test_loader asserts the handler module imports without it
    from psycopg.rows import dict_row

    # libpq PG* variables select the cluster (5432, or 5433 for the retained run).
    return psycopg.connect(dbname=DATABASE, user=user, row_factory=cast(Any, dict_row))


def _i95(interval_end: datetime, calculated: datetime, rate: str) -> I95Row:
    return I95Row(
        interval_end_at=interval_end,
        current_at=calculated,
        calculated_at=calculated,
        corridor_id=495,
        corridor_name="I-495-NB",
        od_pair_id=OD_PAIR,
        od_pair_name="192NO TO 185ND",
        start_zone_id=192,
        start_zone_name="192NO",
        end_zone_id=185,
        end_zone_name="185ND",
        zone_toll_rate_usd=Decimal(rate),
        link_status="OPEN",
    )


def _i66(interval_end: datetime, calculated: datetime, rate: str) -> I66Row:
    return I66Row(
        interval_start_at=interval_end - timedelta(minutes=6),
        interval_end_at=interval_end,
        calculated_at=calculated,
        corridor_id=66,
        corridor_name="E2E synthetic",
        start_zone_id=10,
        start_zone_name="E2E 10",
        end_zone_id=20,
        end_zone_name="E2E 20",
        zone_toll_rate_usd=Decimal(rate),
    )


def test_loader_upserts_monotonically_for_agent_reads(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def loader_connect(*, host: str, port: int, dbname: str, user: str) -> object:
        assert (dbname, user) == (DATABASE, "pricing_loader_writer")
        return _connect(user)

    published: list[int] = []

    def publish(*, watermark: str, s3_key: str, row_count: int) -> None:
        published.append(row_count)

    monkeypatch.setattr(handler, "_connect", loader_connect)
    monkeypatch.setattr(handler, "_publish_i95_success", publish)
    monkeypatch.setattr(route_validation, "_connect_to_database", _connect)
    monkeypatch.setenv("DB_HOST", os.environ.get("PGHOST", "localhost"))
    monkeypatch.setenv("DB_PORT", os.environ.get("PGPORT", "5432"))
    monkeypatch.setenv("DB_NAME", DATABASE)
    monkeypatch.setenv("DB_USER", "pricing_loader_writer")
    monkeypatch.delenv("TOLLCHAT_ENVIRONMENT", raising=False)
    caplog.set_level("INFO")

    now = datetime.now(UTC).replace(second=0, microsecond=0)
    current, earlier = now - timedelta(minutes=1), now - timedelta(hours=1)
    first, second = "raw/feed=i95/e2e/1200Z.csv", "raw/feed=i95/e2e/1210Z.csv"

    handler._load(
        "i95", [_i95(current, now - timedelta(minutes=2), "5.00")], s3_key=first
    )
    # An older calculation loses even with a later key.
    handler._load(
        "i95", [_i95(current, now - timedelta(minutes=3), "1.00")], s3_key=second
    )
    # The same calculation with a later key wins.
    handler._load(
        "i95", [_i95(current, now - timedelta(minutes=2), "6.00")], s3_key=second
    )
    caplog.clear()
    # The same revision tuple is a no-op.
    handler._load(
        "i95", [_i95(current, now - timedelta(minutes=2), "7.00")], s3_key=second
    )
    assert "V2_LOAD_ROWS i95 0" in caplog.text
    assert "V2_LOAD_OK i95" in caplog.text
    # An older interval is history, not a replacement.
    handler._load("i95", [_i95(earlier, earlier, "4.00")], s3_key=first)
    assert published == [1, 1, 1, 1, 1]

    handler._load(
        "i66", [_i66(current, now - timedelta(minutes=2), "2.00")], s3_key=first
    )
    handler._load(
        "i66", [_i66(current, now - timedelta(minutes=3), "1.00")], s3_key=second
    )
    handler._load(
        "i66", [_i66(current, now - timedelta(minutes=2), "3.00")], s3_key=second
    )
    caplog.clear()
    handler._load(
        "i66", [_i66(current, now - timedelta(minutes=2), "9.00")], s3_key=second
    )
    assert "V2_LOAD_ROWS i66 0" in caplog.text

    with cast(Any, _connect("postgres")) as connection:
        i95 = connection.execute(
            "SELECT zone_toll_rate_usd FROM pricing.trip_pricing_i95"
            " WHERE od_pair_id = %s AND interval_end_at IN (%s, %s)"
            " ORDER BY interval_end_at",
            (OD_PAIR, earlier, current),
        ).fetchall()
        i66 = connection.execute(
            "SELECT zone_toll_rate_usd FROM pricing.trip_pricing_i66"
            " WHERE start_zone_id = 10 AND end_zone_id = 20 AND interval_end_at = %s",
            (current,),
        ).fetchall()
    assert [row["zone_toll_rate_usd"] for row in i95] == [
        Decimal("4.00"),
        Decimal("6.00"),
    ]
    assert [row["zone_toll_rate_usd"] for row in i66] == [Decimal("3.00")]

    comparisons = pricing_tool._fetch_i95_i495_comparisons(OD_PAIR)
    latest = next(row for row in comparisons if row.comparison_kind == "current")
    assert latest.available, latest
    assert latest.price_usd == Decimal("6.00")
    assert latest.source_kind == "observed"
