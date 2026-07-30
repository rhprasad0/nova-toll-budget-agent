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

from agent_tools import dulles_route as dulles_mod
from agent_tools.dulles_route import dulles_route

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
    assert leg["rate_period"] is None
    assert result["tolls"] == [
        {
            "facility": "dulles_toll_road",
            "label": "Entrance ramp at Exit 12 - SR 602 (Reston Pkwy)",
            "price_usd": "2.00",
        },
        {
            "facility": "dulles_toll_road",
            "label": "Mainline plaza",
            "price_usd": "4.00",
        },
        {
            "facility": "dulles_toll_road",
            "label": "Exit ramp at Exit 17 - SR 684 (Spring Hill Rd)",
            "price_usd": "2.00",
        },
    ]
    assert "total_usd" not in result
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
    assert leg["rate_period"] == "peak"
    assert result["tolls"][0]["price_usd"] == "5.10"


def test_greenway_only_trip_prices_off_peak():
    result = dulles_route(
        "Exit 1 - US 15/SR 7 (Leesburg Bypass)",
        "Exit 8 - SR 606 (Ox Rd)",
        at_time=_WEEKDAY_OFF_PEAK,
    )
    leg = result["legs"][0]
    assert leg["rate_period"] == "off_peak"
    assert result["tolls"][0]["price_usd"] == "4.55"


def test_greenway_weekend_rush_hour_is_still_off_peak():
    # Peak windows are weekday-only -- a Saturday morning at the same clock
    # time as the weekday EB peak window must not classify as peak.
    result = dulles_route(
        "Exit 1 - US 15/SR 7 (Leesburg Bypass)",
        "Exit 8 - SR 606 (Ox Rd)",
        at_time=_WEEKEND_RUSH_HOUR_TIME,
    )
    assert result["legs"][0]["rate_period"] == "off_peak"


def test_composite_trip_splits_at_route_28_and_returns_each_charge():
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
    assert result["tolls"] == [
        {
            "facility": "dulles_toll_road",
            "label": "Entrance ramp at Exit 12 - SR 602 (Reston Pkwy)",
            "price_usd": "2.00",
        },
        {"facility": "dulles_greenway", "label": "Mainline plaza", "price_usd": "5.25"},
    ]


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
    assert [toll["price_usd"] for toll in result["tolls"]] == ["5.25", "4.00", "2.00"]


def test_composite_trip_uses_route_28_from_the_i495_side_in_both_directions():
    to_greenway = dulles_route(
        "Exit 18/19 - I-495 / SR 123 (Capital Beltway)",
        "Exit 1 - US 15/SR 7 (Leesburg Bypass)",
        at_time=_WEEKDAY_OFF_PEAK,
    )
    to_beltway = dulles_route(
        "Exit 1 - US 15/SR 7 (Leesburg Bypass)",
        "Exit 18/19 - I-495 / SR 123 (Capital Beltway)",
        at_time=_WEEKDAY_OFF_PEAK,
    )

    dtr_leg, greenway_leg = to_greenway["legs"]
    assert dtr_leg["facility"] == "dulles_toll_road"
    assert dtr_leg["exit"]["label"] == "Route 28 (Dulles Toll Road / Dulles Greenway)"
    assert greenway_leg["facility"] == "dulles_greenway"
    assert (
        greenway_leg["entry"]["label"]
        == "Route 28 (Dulles Toll Road / Dulles Greenway)"
    )

    greenway_leg, dtr_leg = to_beltway["legs"]
    assert greenway_leg["facility"] == "dulles_greenway"
    assert (
        greenway_leg["exit"]["label"] == "Route 28 (Dulles Toll Road / Dulles Greenway)"
    )
    assert dtr_leg["facility"] == "dulles_toll_road"
    assert dtr_leg["entry"]["label"] == "Route 28 (Dulles Toll Road / Dulles Greenway)"


def test_dtr_ramp_only_trip_omits_the_free_mainline():
    result = dulles_route(
        "Exit 12 - SR 602 (Reston Pkwy)", "Exit 13 - SR 828 (Wiehle Ave)"
    )
    assert [toll["price_usd"] for toll in result["tolls"]] == ["2.00", "2.00"]
    assert all(toll["label"] != "Mainline plaza" for toll in result["tolls"])


def test_dtr_mainline_only_trip_omits_free_ramps():
    result = dulles_route(
        "Exit 15 - SR 676 (Wolf Trap)",
        "Exit 18/19 - I-495 / SR 123 (Capital Beltway)",
    )
    assert result["tolls"] == [
        {"facility": "dulles_toll_road", "label": "Mainline plaza", "price_usd": "4.00"}
    ]


def test_dtr_toll_free_trip_returns_an_empty_charge_list():
    result = dulles_route(
        "Route 28 (Dulles Toll Road / Dulles Greenway)",
        "Exit 15 - SR 676 (Wolf Trap)",
    )
    assert result["tolls"] == []
    assert "total_usd" not in result


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
    assert "4.00" in caplog.text


def test_failure_log_omits_the_option_list(caplog):
    caplog.set_level(logging.INFO)
    dulles_route("Not A Real Place", "Exit 8 - SR 606 (Ox Rd)")
    assert "dulles_route miss" in caplog.text
    assert "Exit 12 - SR 602 (Reston Pkwy)" not in caplog.text
