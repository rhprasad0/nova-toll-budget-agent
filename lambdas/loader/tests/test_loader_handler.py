import sys

import pytest
from conftest import loader_handler as handler
from parse_csv import I95Row
from parse_xml import I66Row


def test_handler_module_imports_without_psycopg():
    # psycopg only ships in the deployed zip, not this dev venv — handler.py
    # must not import it at module scope, only lazily inside _connect().
    assert "psycopg" not in sys.modules


def test_upsert_i95_sql_conflict_key_matches_spec():
    assert (
        "ON CONFLICT (interval_end_at, start_zone_id, end_zone_id, od_pair_id) DO UPDATE"
        in handler.UPSERT_I95_SQL
    )


def test_upsert_i95_sql_does_not_update_key_columns():
    set_clause = handler.UPSERT_I95_SQL.split("DO UPDATE")[1]
    for key_column in (
        "interval_end_at = ",
        "start_zone_id = ",
        "end_zone_id = ",
        "od_pair_id = ",
    ):
        assert key_column not in set_clause


def test_upsert_i66_sql_conflict_key_matches_spec():
    assert (
        "ON CONFLICT (interval_end_at, start_zone_id, end_zone_id) DO UPDATE"
        in handler.UPSERT_I66_SQL
    )


def test_upsert_i66_sql_does_not_update_key_columns():
    set_clause = handler.UPSERT_I66_SQL.split("DO UPDATE")[1]
    for key_column in (
        "interval_end_at = ",
        "start_zone_id = ",
        "end_zone_id = ",
    ):
        assert key_column not in set_clause


@pytest.mark.parametrize(
    ("key", "feed"),
    [
        ("raw/feed=i95/date=2026-07-21/1440Z.csv", "i95"),
        ("raw/feed=i66/date=2026-07-21/1440Z.xml", "i66"),
        (
            "raw/feed=i66/date=2026-07-21/1440Z-0123456789abcdef.xml",
            "i66",
        ),
    ],
)
def test_feed_from_key(key, feed):
    assert handler._feed_from_key(key) == feed


def test_feed_from_key_raises_without_feed_segment():
    with pytest.raises(ValueError, match="unsupported raw object key"):
        handler._feed_from_key("raw/date=2026-07-21/1440Z.csv")


@pytest.mark.parametrize(
    "key",
    [
        "raw/feed=i95-live/date=2026-07-21/1440Z.csv",
        "raw/feed=i95/date=2026-07-21/not-a-time.csv",
        "raw/feed=other/date=2026-07-21/1440Z.csv",
        "raw/feed=i95/date=2026-07-21/1440Z-not-a-drill-id.csv",
        "raw/feed=i95/date=2026-07-21/1440Z.csv/extra",
    ],
)
def test_feed_from_key_rejects_untrusted_shapes(key):
    with pytest.raises(
        ValueError, match=r"unsupported raw object key|unexpected extension"
    ):
        handler._feed_from_key(key)


def test_validate_record_rejects_wrong_bucket(monkeypatch):
    monkeypatch.setenv("RAW_BUCKET", "expected-bucket")
    with pytest.raises(ValueError, match="unexpected source bucket"):
        handler._validate_record(
            "attacker-bucket", "raw/feed=i95/date=2026-07-21/1440Z.csv", 1
        )


def test_validate_record_rejects_oversized_event(monkeypatch):
    monkeypatch.setenv("RAW_BUCKET", "expected-bucket")
    with pytest.raises(ValueError, match="outside allowed range"):
        handler._validate_record(
            "expected-bucket",
            "raw/feed=i95/date=2026-07-21/1440Z.csv",
            handler.MAX_RAW_OBJECT_BYTES + 1,
        )


def test_row_params_includes_s3_key_and_all_row_fields_i95():
    row = I95Row(
        interval_end_at=None,  # type: ignore[arg-type]
        current_at=None,  # type: ignore[arg-type]
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
    assert params["corridor_id"] == 951
    assert "feed" not in params


def test_row_params_includes_s3_key_and_all_row_fields_i66():
    row = I66Row(
        interval_start_at=None,  # type: ignore[arg-type]
        interval_end_at=None,  # type: ignore[arg-type]
        calculated_at=None,  # type: ignore[arg-type]
        corridor_id=1100,
        corridor_name="I-66 EB",
        start_zone_id=100,
        start_zone_name=None,
        end_zone_id=200,
        end_zone_name="B",
        zone_toll_rate_usd=None,  # type: ignore[arg-type]
    )
    params = handler._row_params(row, s3_key="raw/feed=i66/date=2026-07-21/1440Z.xml")
    assert params["s3_key"] == "raw/feed=i66/date=2026-07-21/1440Z.xml"
    assert params["corridor_id"] == 1100
    assert "feed" not in params
