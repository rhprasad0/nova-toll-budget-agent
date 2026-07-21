import sys

import pytest
from conftest import loader_handler as handler
from parse_csv import TripPricingRow


def test_handler_module_imports_without_psycopg():
    # psycopg only ships in the deployed zip, not this dev venv — handler.py
    # must not import it at module scope, only lazily inside _connect().
    assert "psycopg" not in sys.modules


def test_upsert_sql_conflict_key_matches_spec():
    assert (
        "ON CONFLICT (feed, interval_end_at, start_zone_id, end_zone_id, od_pair_id) DO UPDATE"
        in handler.UPSERT_SQL
    )


def test_upsert_sql_does_not_update_key_columns():
    # feed/interval_end_at/start_zone_id/end_zone_id are the conflict key —
    # they must not also appear on the left of a SET clause.
    set_clause = handler.UPSERT_SQL.split("DO UPDATE")[1]
    for key_column in (
        "feed = ",
        "interval_end_at = ",
        "start_zone_id = ",
        "end_zone_id = ",
        "od_pair_id = ",
    ):
        assert key_column not in set_clause


@pytest.mark.parametrize(
    ("key", "feed"),
    [
        ("raw/feed=i95/date=2026-07-21/1440Z.csv", "i95"),
        ("raw/feed=i66/date=2026-07-21/1440Z.xml", "i66"),
    ],
)
def test_feed_from_key(key, feed):
    assert handler._feed_from_key(key) == feed


def test_feed_from_key_raises_without_feed_segment():
    with pytest.raises(ValueError, match="cannot determine feed"):
        handler._feed_from_key("raw/date=2026-07-21/1440Z.csv")


def test_row_params_includes_s3_key_and_all_row_fields():
    row = TripPricingRow(
        feed="i95",
        interval_start_at=None,
        interval_end_at=None,  # type: ignore[arg-type]
        current_at=None,
        calculated_at=None,  # type: ignore[arg-type]
        corridor_id=951,
        corridor_name="I-95-NB",
        od_pair_id=1,
        od_pair_name="A TO B",
        start_zone_id=100,
        start_zone_name=None,
        end_zone_id=200,
        end_zone_name="B",
        zone_toll_rate_usd=None,  # type: ignore[arg-type]
        link_status="CLOSED",
    )
    params = handler._row_params(row, s3_key="raw/feed=i95/date=2026-07-21/1440Z.csv")
    assert params["s3_key"] == "raw/feed=i95/date=2026-07-21/1440Z.csv"
    assert params["feed"] == "i95"
    assert params["corridor_id"] == 951
