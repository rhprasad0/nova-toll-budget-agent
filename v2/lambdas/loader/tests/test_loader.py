import io
import json
import sys
from dataclasses import replace
from datetime import UTC, datetime

import pricing_loader_handler as handler
import pytest
from parse_csv import parse_trip_pricing_csv
from parse_xml import parse_trip_pricing_xml


def test_module_imports_without_psycopg():
    assert "psycopg" not in sys.modules


def test_upserts_are_schema_qualified_and_idempotent():
    assert "INSERT INTO pricing.trip_pricing_i95" in handler.UPSERT_I95_SQL
    assert "INSERT INTO pricing.trip_pricing_i66" in handler.UPSERT_I66_SQL
    assert (
        "ON CONFLICT (interval_end_at, start_zone_id, end_zone_id, od_pair_id)"
        in handler.UPSERT_I95_SQL
    )
    assert (
        "ON CONFLICT (interval_end_at, start_zone_id, end_zone_id)"
        in handler.UPSERT_I66_SQL
    )
    assert (
        "(trip_pricing_i95.calculated_at, trip_pricing_i95.s3_key)"
        in handler.UPSERT_I95_SQL
    )
    assert (
        "(trip_pricing_i66.calculated_at, trip_pricing_i66.s3_key)"
        in handler.UPSERT_I66_SQL
    )


def test_eventbridge_object_is_normalized():
    event = {
        "source": "aws.s3",
        "detail-type": "Object Created",
        "detail": {
            "bucket": {"name": "raw-bucket"},
            "object": {
                "key": "raw/feed=i95/date=2026-08-16/1200Z.csv",
                "size": 42,
            },
        },
    }
    assert list(handler._event_objects(event)) == [
        (
            "raw-bucket",
            "raw/feed=i95/date=2026-08-16/1200Z.csv",
            42,
        )
    ]


def test_direct_s3_object_remains_replayable():
    event = {
        "Records": [
            {
                "s3": {
                    "bucket": {"name": "raw-bucket"},
                    "object": {
                        "key": "raw%2Ffeed%3Di66%2Fdate%3D2026-08-16%2F1200Z.xml",
                        "size": 42,
                    },
                }
            }
        ]
    }
    assert next(iter(handler._event_objects(event)))[1].endswith("1200Z.xml")


def test_handler_reads_and_loads_eventbridge_object(monkeypatch):
    key = "raw/feed=i66/date=2026-08-16/1200Z.xml"
    payload = (
        b'<root><opt IntervalDateTime="2026-08-16T11:55:00Z" '
        b'IntervalEndDateTime="2026-08-16T12:00:00Z" '
        b'CalculatedDateTime="2026-08-16T11:54:00Z" CorridorID="66" '
        b'CorridorName="I-66" StartZoneID="1" StartZoneName="A" '
        b'EndZoneID="2" EndZoneName="B" ZoneTollRate="3.50" /></root>'
    )

    class S3:
        def get_object(self, **kwargs):
            assert kwargs == {"Bucket": "raw-bucket", "Key": key}
            return {"Body": io.BytesIO(payload), "ContentLength": len(payload)}

    loaded = []
    monkeypatch.setenv("RAW_BUCKET", "raw-bucket")
    monkeypatch.setattr(handler.boto3, "client", lambda service: S3())
    monkeypatch.setattr(
        handler,
        "_load",
        lambda feed, rows, *, s3_key: loaded.append((feed, rows, s3_key)),
    )
    handler.handler(
        {
            "source": "aws.s3",
            "detail-type": "Object Created",
            "detail": {
                "bucket": {"name": "raw-bucket"},
                "object": {"key": key, "size": len(payload)},
            },
        },
        None,
    )
    assert loaded[0][0] == "i66"
    assert loaded[0][2] == key
    assert len(loaded[0][1]) == 1


def test_empty_event_fails_closed(monkeypatch):
    monkeypatch.setattr(handler.boto3, "client", lambda service: object())
    with pytest.raises(ValueError, match="no supported S3 objects"):
        handler.handler({}, None)


def test_i95_parser_contract():
    csv_text = """ZONETOLLRATE,ODPAIRNAME,ODPAIRID,STARTZONENAME,STARTZONEID,INTERVALENDDATETI,CURRENTDATETIME,ENDZONENAME,ENDZONEID,CORRIDORN,CORRIDORID,CALULCATEDDATETIM,LINKSTATUS
2.50,A TO B,1,A,10,16/08/26 12:00:00,16/08/26 11:59:00,B,20,I-95,95,16/08/26 11:58:00,OPEN
"""
    rows = parse_trip_pricing_csv(csv_text)
    assert len(rows) == 1
    assert str(rows[0].zone_toll_rate_usd) == "2.50"


def test_i66_parser_contract():
    xml = '<root><opt IntervalDateTime="2026-08-16T11:55:00Z" IntervalEndDateTime="2026-08-16T12:00:00Z" CalculatedDateTime="2026-08-16T11:54:00Z" CorridorID="66" CorridorName="I-66" StartZoneID="1" StartZoneName="A" EndZoneID="2" EndZoneName="B" ZoneTollRate="3.50" /></root>'
    rows = parse_trip_pricing_xml(xml)
    assert len(rows) == 1
    assert str(rows[0].zone_toll_rate_usd) == "3.50"


def test_load_batches_rows_and_keeps_success_markers_on_noop(monkeypatch, caplog):
    class Cursor:
        def __init__(self):
            self.rowcount = 0
            self.calls = []

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def executemany(self, sql, params):
            self.calls.append((sql, params))

    class Connection:
        cursor_instance = Cursor()

        def transaction(self):
            return self

        def cursor(self):
            return self.cursor_instance

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def close(self):
            return None

    xml = '<root><opt IntervalDateTime="2026-08-16T11:55:00Z" IntervalEndDateTime="2026-08-16T12:00:00Z" CalculatedDateTime="2026-08-16T11:54:00Z" CorridorID="66" CorridorName="I-66" StartZoneID="1" StartZoneName="A" EndZoneID="2" EndZoneName="B" ZoneTollRate="3.50" /></root>'
    rows = parse_trip_pricing_xml(xml)
    monkeypatch.setattr(handler, "_connect", lambda **_kwargs: Connection())
    for name in ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER"):
        monkeypatch.setenv(name, "5432" if name == "DB_PORT" else "test")

    with caplog.at_level("INFO"):
        handler._load("i66", rows, s3_key="raw/feed=i66/date=2026-08-17/1200Z.xml")

    assert len(Connection.cursor_instance.calls) == 1
    assert "V2_LOAD_ROWS i66 0" in caplog.text
    assert "V2_LOAD_OK i66" in caplog.text
    assert "V2_LOAD_OBJECT_OK i66" in caplog.text


def _i95_rows():
    return parse_trip_pricing_csv(
        """ZONETOLLRATE,ODPAIRNAME,ODPAIRID,STARTZONENAME,STARTZONEID,INTERVALENDDATETI,CURRENTDATETIME,ENDZONENAME,ENDZONEID,CORRIDORN,CORRIDORID,CALULCATEDDATETIM,LINKSTATUS
2.50,A TO B,1,A,10,16/08/26 12:00:00,16/08/26 11:59:00,B,20,I-95,95,16/08/26 11:58:00,OPEN
"""
    )


def test_i95_success_event_is_emitted_after_commit(monkeypatch):
    calls = []

    class Cursor:
        rowcount = 1

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def executemany(self, *_args):
            calls.append("write")

    class Transaction:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            calls.append("commit")

    class Connection:
        def transaction(self):
            return Transaction()

        def cursor(self):
            return Cursor()

        def close(self):
            calls.append("close")

    class Events:
        def put_events(self, **kwargs):
            calls.append(("event", kwargs))
            return {"FailedEntryCount": 0, "Entries": [{"EventId": "event-1"}]}

    monkeypatch.setattr(handler, "_connect", lambda **_kwargs: Connection())
    monkeypatch.setattr(handler.boto3, "client", lambda service: Events())
    for name in ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER"):
        monkeypatch.setenv(name, "5432" if name == "DB_PORT" else "test")

    handler._load(
        "i95",
        _i95_rows(),
        s3_key="raw/feed=i95/date=2026-08-16/1200Z.csv",
    )

    assert calls[:3] == ["write", "commit", "close"]
    detail = json.loads(calls[3][1]["Entries"][0]["Detail"])
    assert detail["environment"] == "production"
    event = calls[3][1]["Entries"][0]
    assert event["Source"] == "tollchat.pricing-loader"
    assert event["DetailType"] == "I95 Pricing Load Committed"
    assert '"source_watermark":"2026-08-16T16:00:00Z"' in event["Detail"]
    assert '"row_count":1' in event["Detail"]


def test_i95_mixed_intervals_fail_before_writing(monkeypatch):
    rows = _i95_rows()
    rows.append(
        replace(rows[0], interval_end_at=datetime(2026, 8, 16, 16, 10, tzinfo=UTC))
    )
    monkeypatch.setattr(
        handler,
        "_connect",
        lambda **_kwargs: pytest.fail("database should not be opened"),
    )

    with pytest.raises(ValueError, match="one source interval"):
        handler._load(
            "i95",
            rows,
            s3_key="raw/feed=i95/date=2026-08-16/1200Z.csv",
        )


def test_i95_eventbridge_partial_failure_retries_the_loader(monkeypatch):
    class Cursor:
        rowcount = 1

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def executemany(self, *_args):
            return None

    class Connection:
        def transaction(self):
            return self

        def cursor(self):
            return Cursor()

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def close(self):
            return None

    class Events:
        def put_events(self, **_kwargs):
            return {
                "FailedEntryCount": 1,
                "Entries": [{"ErrorCode": "InternalFailure"}],
            }

    monkeypatch.setattr(handler, "_connect", lambda **_kwargs: Connection())
    monkeypatch.setattr(handler.boto3, "client", lambda service: Events())
    for name in ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER"):
        monkeypatch.setenv(name, "5432" if name == "DB_PORT" else "test")

    with pytest.raises(RuntimeError, match="load-success event"):
        handler._load(
            "i95",
            _i95_rows(),
            s3_key="raw/feed=i95/date=2026-08-16/1200Z.csv",
        )


def test_failed_i95_transaction_emits_no_event(monkeypatch):
    class Cursor:
        rowcount = 0

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def executemany(self, *_args):
            raise RuntimeError("database write failed")

    class Connection:
        def transaction(self):
            return self

        def cursor(self):
            return Cursor()

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def close(self):
            return None

    monkeypatch.setattr(handler, "_connect", lambda **_kwargs: Connection())
    monkeypatch.setattr(
        handler.boto3,
        "client",
        lambda service: pytest.fail("failed transaction emitted an event"),
    )
    for name in ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER"):
        monkeypatch.setenv(name, "5432" if name == "DB_PORT" else "test")

    with pytest.raises(RuntimeError, match="database write failed"):
        handler._load(
            "i95",
            _i95_rows(),
            s3_key="raw/feed=i95/date=2026-08-16/1200Z.csv",
        )
