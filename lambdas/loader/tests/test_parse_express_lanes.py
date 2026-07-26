import json
from decimal import Decimal

import pytest
from conftest import SAMPLE_DATA_DIR
from parse_express_lanes import parse_express_lanes_live_json

SAMPLE_JSON = (SAMPLE_DATA_DIR / "expresslanes_live_sample.json").read_text()


def test_null_price_rows_are_skipped():
    rows = parse_express_lanes_live_json(SAMPLE_JSON)
    assert not any(r.od_pair_id == 1083 for r in rows)


def test_null_road_direction_status_become_none():
    rows = parse_express_lanes_live_json(SAMPLE_JSON)
    row = next(r for r in rows if r.od_pair_id == 1000)
    assert row.road is None
    assert row.direction is None
    assert row.status is None


def test_closed_rows_with_a_real_price_are_still_stored():
    # A future maintainer might "helpfully" filter these out as placeholders --
    # availability is status's job, never price's; store faithfully.
    rows = parse_express_lanes_live_json(SAMPLE_JSON)
    row = next(r for r in rows if r.od_pair_id == 1380)
    assert row.status == "closed"
    assert row.price_usd == Decimal("2.45")


def test_shared_time_field_parsed_as_eastern_and_converted_to_utc():
    rows = parse_express_lanes_live_json(SAMPLE_JSON)
    # 2026-07-25 is EDT (UTC-4): 18:00 ET -> 22:00 UTC.
    assert all(r.observed_at.isoformat() == "2026-07-25T22:00:00+00:00" for r in rows)


def test_dst_fall_back_resolves_with_fold_zero():
    # 2026-11-01 is the US fall-back date: 01:30 local occurs twice.
    # fold=0 must pick the first (pre-transition, EDT/UTC-4) occurrence.
    payload = {
        "response": [
            {
                "od": "od_1",
                "price": "1.00",
                "road": "95",
                "ratetype": "null",
                "time": "2026-11-01 01:30:00",
                "direction": "N",
                "status": "open",
            }
        ]
    }
    rows = parse_express_lanes_live_json(json.dumps(payload))
    assert rows[0].observed_at.isoformat() == "2026-11-01T05:30:00+00:00"


def test_no_response_key_fails_loudly():
    with pytest.raises(ValueError, match="no 'response' rows"):
        parse_express_lanes_live_json(json.dumps({"error": "0"}))


def test_all_null_price_response_fails_loudly():
    payload = {
        "response": [
            {
                "od": "od_1",
                "price": "null",
                "road": "null",
                "ratetype": "null",
                "time": "2026-07-25 18:00:00",
                "direction": "null",
                "status": "null",
            }
        ]
    }
    with pytest.raises(ValueError, match="no priced rows parsed"):
        parse_express_lanes_live_json(json.dumps(payload))


def test_shape_has_no_link_status_or_feed_field():
    rows = parse_express_lanes_live_json(SAMPLE_JSON)
    assert not hasattr(rows[0], "link_status")
    assert not hasattr(rows[0], "feed")


def test_mixed_observation_times_are_rejected():
    payload = json.loads(SAMPLE_JSON)
    payload["response"][1]["time"] = "2026-07-25 19:00:00"
    with pytest.raises(ValueError, match="mixed observation times"):
        parse_express_lanes_live_json(json.dumps(payload))


def test_out_of_range_price_is_rejected():
    payload = json.loads(SAMPLE_JSON)
    payload["response"][0]["price"] = "9999.99"
    with pytest.raises(ValueError, match="outside allowed range"):
        parse_express_lanes_live_json(json.dumps(payload))
