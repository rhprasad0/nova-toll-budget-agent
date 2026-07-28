"""Tests for dulles_route.

Unlike i66_route/i95_route, there's no RDS and no FakeConnection here --
both oracles are fixed-price, so pricing is a pure function of the resolved
pair and at_time (for Greenway's peak/off-peak classification only). No
monkeypatching needed for the happy paths; a couple of tests do patch
_FACILITIES to exercise the ambiguous-match guard with synthetic data, since
real data has no such case today (mirrors i66_route's own test for the same
reason).
"""

import logging
from zoneinfo import ZoneInfo

import dulles_route as dulles_mod
from dulles_route import dulles_route

_EASTERN = ZoneInfo("America/New_York")
_WEEKDAY_PEAK_EB = "2026-07-27T07:30:00-04:00"  # Monday
_WEEKDAY_OFF_PEAK = "2026-07-27T12:00:00-04:00"  # Monday, midday
_WEEKEND_RUSH_HOUR_TIME = "2026-08-01T07:30:00-04:00"  # Saturday


def test_dtr_only_trip_is_a_single_leg():
    result = dulles_route(
        "Exit 12 - SR 602 (Reston Pkwy)", "Exit 17 - SR 684 (Spring Hill Rd)"
    )
    assert len(result["legs"]) == 1
    leg = result["legs"][0]
    assert leg["facility"] == "dulles_toll_road"
    assert leg["direction"] == "EB"
    assert leg["price_usd"] == "8.00"
    assert leg["rate_period"] is None
    assert result["total_usd"] == "8.00"
    assert result["facility_totals"] == {
        "dulles_toll_road": "8.00",
        "dulles_greenway": "0.00",
    }
    assert "observed_at" not in leg


def test_dtr_label_lookup_is_case_insensitive():
    a = dulles_route(
        "exit 12 - sr 602 (reston pkwy)", "exit 17 - sr 684 (spring hill rd)"
    )
    b = dulles_route(
        "Exit 12 - SR 602 (Reston Pkwy)", "Exit 17 - SR 684 (Spring Hill Rd)"
    )
    assert a["legs"] == b["legs"]


def test_dtr_node_id_fallback_matches_label_lookup():
    by_id = dulles_route("12", "17")
    by_label = dulles_route(
        "Exit 12 - SR 602 (Reston Pkwy)", "Exit 17 - SR 684 (Spring Hill Rd)"
    )
    assert by_id["legs"] == by_label["legs"]


def test_greenway_only_trip_prices_peak():
    result = dulles_route(
        "Exit 1 - US 15/SR 7 (Leesburg Bypass)",
        "Exit 8 - SR 606 (Ox Rd)",
        at_time=_WEEKDAY_PEAK_EB,
    )
    assert len(result["legs"]) == 1
    leg = result["legs"][0]
    assert leg["facility"] == "dulles_greenway"
    assert leg["rate_period"] == "peak"
    assert leg["price_usd"] == "5.10"


def test_greenway_only_trip_prices_off_peak():
    result = dulles_route(
        "Exit 1 - US 15/SR 7 (Leesburg Bypass)",
        "Exit 8 - SR 606 (Ox Rd)",
        at_time=_WEEKDAY_OFF_PEAK,
    )
    leg = result["legs"][0]
    assert leg["rate_period"] == "off_peak"
    assert leg["price_usd"] == "4.55"


def test_greenway_weekend_rush_hour_is_still_off_peak():
    # Peak windows are weekday-only -- a Saturday morning at the same clock
    # time as the weekday EB peak window must not classify as peak.
    result = dulles_route(
        "Exit 1 - US 15/SR 7 (Leesburg Bypass)",
        "Exit 8 - SR 606 (Ox Rd)",
        at_time=_WEEKEND_RUSH_HOUR_TIME,
    )
    assert result["legs"][0]["rate_period"] == "off_peak"


def test_composite_trip_splits_at_route_28_and_sums():
    result = dulles_route(
        "Exit 12 - SR 602 (Reston Pkwy)",
        "Exit 1 - US 15/SR 7 (Leesburg Bypass)",
        at_time=_WEEKDAY_OFF_PEAK,
    )
    assert len(result["legs"]) == 2
    dtr_leg, gw_leg = result["legs"]
    assert dtr_leg["facility"] == "dulles_toll_road"
    assert dtr_leg["exit"]["label"] == "Route 28 (Dulles Toll Road / Dulles Greenway)"
    assert gw_leg["facility"] == "dulles_greenway"
    assert gw_leg["entry"]["label"] == "Route 28 (Dulles Toll Road / Dulles Greenway)"
    # The Greenway leg starts at Route 28, so it crosses that facility's own
    # mainline plaza too -- it prices at the mainline rate, not secondary.
    assert result["facility_totals"] == {
        "dulles_toll_road": "2.00",
        "dulles_greenway": "5.25",
    }
    assert result["total_usd"] == "7.25"


def test_composite_trip_reverse_direction():
    result = dulles_route(
        "Exit 1 - US 15/SR 7 (Leesburg Bypass)",
        "Exit 17 - SR 684 (Spring Hill Rd)",
        at_time=_WEEKDAY_OFF_PEAK,
    )
    assert [leg["facility"] for leg in result["legs"]] == [
        "dulles_greenway",
        "dulles_toll_road",
    ]
    assert result["total_usd"] == "11.25"


def test_unknown_origin_returns_combined_valid_options():
    result = dulles_route("Not A Real Place", "Exit 8 - SR 606 (Ox Rd)")
    assert "error" in result
    assert "Exit 1 - US 15/SR 7 (Leesburg Bypass)" in result["valid_options"]
    assert "Exit 12 - SR 602 (Reston Pkwy)" in result["valid_options"]


def test_unknown_destination_returns_combined_valid_options():
    result = dulles_route("Exit 8 - SR 606 (Ox Rd)", "Not A Real Place")
    assert "error" in result
    assert "Exit 17 - SR 684 (Spring Hill Rd)" in result["valid_options"]


def test_exit_only_ramp_is_never_a_valid_origin():
    result = dulles_route("Exit 2A - Battlefield Pkwy", "Exit 8 - SR 606 (Ox Rd)")
    assert "error" in result
    assert "Exit 2A - Battlefield Pkwy" not in result["valid_options"]


def test_invalid_at_time_is_a_hard_error():
    result = dulles_route(
        "Exit 12 - SR 602 (Reston Pkwy)",
        "Exit 17 - SR 684 (Spring Hill Rd)",
        at_time="not-a-time",
    )
    assert "error" in result
    assert result["valid_options"] == []
    assert "not-a-time" in result["error"]


def test_ambiguous_match_is_guarded_with_synthetic_data(monkeypatch):
    # Unreachable via real data -- hand-built to prove the guard fires if
    # a future oracle refresh ever produces overlapping labels.
    synthetic = {
        "nodes": {
            "a": {"label": "Origin", "entry_in": ["EB"], "exit_in": []},
            "b": {"label": "Origin", "entry_in": ["EB"], "exit_in": []},
            "c": {"label": "Dest", "entry_in": [], "exit_in": ["EB"]},
        },
        "pairs": [
            {
                "direction": "EB",
                "entry": "a",
                "exit": "c",
                "price_peak_usd": "1.00",
                "price_off_peak_usd": "1.00",
            },
            {
                "direction": "EB",
                "entry": "b",
                "exit": "c",
                "price_peak_usd": "2.00",
                "price_off_peak_usd": "2.00",
            },
        ],
        "label_index": {"origin": ["a", "b"], "dest": ["c"]},
        "boundary_id": "c",
    }
    monkeypatch.setitem(dulles_mod._FACILITIES, "dulles_toll_road", synthetic)
    result = dulles_mod._lookup("Origin", "Dest")
    assert "error" in result
    assert "ambiguous" in result["error"]


def test_tool_spec_matches_signature():
    assert dulles_route.tool_spec["name"] == "dulles_route"
    assert set(dulles_route.tool_spec["inputSchema"]["json"]["required"]) == {
        "origin",
        "destination",
    }


def test_logs_successful_lookup(caplog):
    caplog.set_level(logging.INFO)
    dulles_route("Exit 12 - SR 602 (Reston Pkwy)", "Exit 17 - SR 684 (Spring Hill Rd)")
    assert "dulles_route ok" in caplog.text
    assert "8.00" in caplog.text


def test_failure_log_omits_the_option_list(caplog):
    caplog.set_level(logging.INFO)
    dulles_route("Not A Real Place", "Exit 8 - SR 606 (Ox Rd)")
    assert "dulles_route miss" in caplog.text
    assert "Exit 12 - SR 602 (Reston Pkwy)" not in caplog.text
