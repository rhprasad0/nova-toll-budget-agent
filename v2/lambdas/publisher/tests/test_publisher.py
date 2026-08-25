from datetime import UTC, datetime
from decimal import Decimal

import pytest
import report_publisher_handler as publisher

EVALUATED_AT = datetime(2026, 8, 25, 16, 5, tzinfo=UTC)
WATERMARK = datetime(2026, 8, 25, 16, 0, tzinfo=UTC)


def _endpoint(point_id, role):
    return {
        "point_id": point_id,
        "label": point_id,
        "place_name": "Newington",
        "region": "Virginia",
        "country_code": "US",
        "aliases": [point_id],
        "nearby_landmarks": ["Ronald Reagan Washington National Airport"],
        "direction": "southbound",
        "role": role,
        "display_name": f"Newington, Virginia - {point_id}",
        "location": {"type": "Point", "coordinates": [-77.1, 38.8]},
    }


def _report_row(index=0, *, available=True, evaluated_at=EVALUATED_AT):
    origin_id = f"i95:{index}SO"
    destination_id = f"i95:{index}SD"
    route_key = f"Southbound:{index}SO:{index}SD"
    observed_at = WATERMARK if available else WATERMARK.replace(hour=15)
    return {
        "snapshot_evaluated_at": evaluated_at,
        "origin": _endpoint(origin_id, "entry"),
        "destination": _endpoint(destination_id, "exit"),
        "structural_facility_legs": [
            {
                "route_step_id": "step-1",
                "facility": "i95_i495",
                "point_ids": [origin_id, destination_id],
                "connection_ids": [f"source:i95_shared:{route_key}"],
                "pricing_key": {"source_route_key": route_key, "od_pair_id": index + 1},
            }
        ],
        "status": "valid",
        "reason": None,
        "point_ids": [origin_id, destination_id],
        "connection_ids": [f"source:i95_shared:{route_key}"],
        "connection_types": ["within_facility"],
        "general_purpose_gaps": [],
        "i95_evidence": {
            "availability": "southbound",
            "northbound_corridor_name": "Northbound",
            "northbound_link_status": "CLOSED",
            "northbound_interval_end_at": WATERMARK.isoformat(),
            "northbound_calculated_at": observed_at.isoformat(),
            "southbound_corridor_name": "Southbound",
            "southbound_link_status": "OPEN",
            "southbound_interval_end_at": WATERMARK.isoformat(),
            "southbound_calculated_at": observed_at.isoformat(),
        },
        "facility_legs": [
            {
                "route_step_id": "step-1",
                "facility": "i95_i495",
                "point_ids": [origin_id, destination_id],
                "connection_ids": [f"source:i95_shared:{route_key}"],
                "pricing_key": {"source_route_key": route_key, "od_pair_id": index + 1},
            }
        ],
        "route_step_id": "step-1",
        "comparison_kind": "current",
        "comparison_offset": 0,
        "bin_start_at": observed_at,
        "bin_end_at": observed_at.replace(minute=10),
        "interval_end_at": observed_at,
        "observed_at": observed_at,
        "price_usd": Decimal("1.23"),
        "available": available,
        "availability_reason": None if available else "stale_observation",
        "source_kind": "observed",
        "pricing_method": "source_observation",
        "od_pair_id": index + 1,
        "proxy_od_pair_id": None,
        "source_status": "OPEN",
    }


def _report_rows():
    return [_report_row(index) for index in range(685)]


def _load_event(watermark=WATERMARK):
    return {
        "source": "tollchat.pricing-loader",
        "detail-type": "I95 Pricing Load Committed",
        "detail": {
            "schema_version": 1,
            "facility": "i95_i495",
            "source_watermark": watermark.isoformat().replace("+00:00", "Z"),
            "source_key": "raw/feed=i95/date=2026-08-25/1600Z.csv",
            "row_count": 317,
        },
    }


def test_watchdog_builds_one_complete_generation(monkeypatch, caplog):
    monkeypatch.setattr(publisher, "_read_report_rows", _report_rows)

    with caplog.at_level("INFO"):
        result = publisher.handler({"trigger": "watchdog"}, None)

    assert result == {
        "status": "generated",
        "facility": "i95_i495",
        "generation_id": "2026-08-25T16:05:00Z",
        "source_watermark": "2026-08-25T16:00:00Z",
        "route_count": 685,
    }
    assert "V2_REPORT_GENERATION_OK i95_i495 2026-08-25T16:05:00Z 685" in caplog.text
    generation = publisher.build_generation(_report_rows())
    assert generation.routes[0].structural_facility_legs[0]["facility"] == "i95_i495"


def test_expected_watermark_matrix():
    assert publisher._expected_watermark_action(WATERMARK, WATERMARK) == "build"
    assert (
        publisher._expected_watermark_action(
            WATERMARK.replace(minute=50, hour=15), WATERMARK
        )
        == "superseded"
    )
    with pytest.raises(RuntimeError, match="not visible"):
        publisher._expected_watermark_action(WATERMARK.replace(minute=10), WATERMARK)
    with pytest.raises(RuntimeError, match="not visible"):
        publisher._expected_watermark_action(WATERMARK, None)


def test_duplicate_load_events_are_safe(monkeypatch):
    rows = _report_rows()
    monkeypatch.setattr(publisher, "_read_report_rows", lambda: rows)

    first = publisher.handler(_load_event(), None)
    second = publisher.handler(_load_event(), None)

    assert first == second
    assert first["status"] == "generated"


def test_delayed_load_event_is_a_noop(monkeypatch):
    monkeypatch.setattr(publisher, "_read_report_rows", _report_rows)
    result = publisher.handler(_load_event(WATERMARK.replace(hour=15, minute=50)), None)
    assert result["status"] == "superseded"
    assert result["source_watermark"] == "2026-08-25T16:00:00Z"


def test_unknown_event_fails_before_database_access(monkeypatch):
    monkeypatch.setattr(
        publisher,
        "_read_report_rows",
        lambda: pytest.fail("database should not be read"),
    )
    with pytest.raises(ValueError, match="unsupported publisher event"):
        publisher.handler({"source": "not-the-loader"}, None)


def test_generation_rejects_inconsistent_snapshot_times():
    rows = _report_rows()
    rows[-1] = _report_row(684, evaluated_at=EVALUATED_AT.replace(minute=6))
    with pytest.raises(ValueError, match="evaluation timestamp"):
        publisher.build_generation(rows)


def test_stale_watchdog_result_stays_unavailable(monkeypatch):
    rows = _report_rows()
    rows[0] = _report_row(0, available=False)
    monkeypatch.setattr(publisher, "_read_report_rows", lambda: rows)

    result = publisher.handler({"trigger": "watchdog"}, None)

    assert result["status"] == "generated"
    generation = publisher.build_generation(rows)
    assert generation.routes[0].current_price["reason"] == "incomplete_route_price"
    assert (
        generation.routes[0].current_price["unavailable_components"][0]["reason"]
        == "stale_observation"
    )


def test_report_read_uses_one_bounded_repeatable_read(monkeypatch):
    calls = []

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, sql):
            calls.append(sql)

        def fetchall(self):
            return []

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
            calls.append("close")

    monkeypatch.setattr(publisher, "_connect", lambda: Connection())
    assert publisher._read_report_rows() == []
    assert calls == [
        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY",
        "SET LOCAL statement_timeout = '180s'",
        "SELECT * FROM oracle.get_i95_i495_report_inputs()",
        "close",
    ]
