"""Tests for i95_route.

Route resolution is pure local JSON lookup, no network, no RDS. Pricing
hits RDS via _env_connect(), which every success-path test here replaces
with a FakeConnection (conftest.py) -- no real DB, no psycopg import.

Real-data fixtures are verified directly against oracles/i95.json (see the
inline values below); the ambiguous-match branch is exercised with synthetic
data since the real oracle has no such case today (verified 685/685 pairs
unique on (entry, exit) and on (entry_label, exit_label)).

Primary-query row tuples carry a trailing link_status; live-query row tuples
carry a trailing status. Both must be set consistently with the row's own
corridor/road or the availability gate in _price_i95_leg will reject them --
see _RESERVED_LANE_REQUIRED_STATUS in i95_route.py.
"""

import logging
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import i95_route as i95_mod
from conftest import FakeConnection, connect_returning as _connect_returning
from i95_route import i95_route

_EASTERN = ZoneInfo("America/New_York")
_PRICED_AS_OF = datetime(2026, 7, 26, 14, 20, tzinfo=_EASTERN)
_LIVE_OBSERVED_AT = datetime(2026, 7, 26, 14, 30, tzinfo=_EASTERN)

# (od_pair_id, corridor_name, zone_toll_rate_usd, interval_end_at, link_status)
# link_status must match the row's own corridor's required "{DIR}_OPEN" for
# I-95-NB/I-95-SB rows to price -- see _RESERVED_LANE_REQUIRED_STATUS. I-495
# rows are exempt from that check, so "NO_DETERMINATION" (their real-world
# value) is used there to prove the exemption rather than coincidentally
# passing a strict check.
_ROUTE267_TO_495END_ROW = (
    1038,
    "I-495-NB",
    Decimal("2.75"),
    _PRICED_AS_OF,
    "NO_DETERMINATION",
)
_OLDKEENE_LEG1_ROW = (
    1144,
    "I-95-NB",
    Decimal("3.25"),
    _PRICED_AS_OF,
    "NORTHBOUND_OPEN",
)
_OLDKEENE_LEG2_ROW = (
    1092,
    "I-495-NB",
    Decimal("6.10"),
    _PRICED_AS_OF,
    "NO_DETERMINATION",
)
_BRADDOCK_LEG1_ROW = (
    1083,
    "I-495-NB",
    Decimal("6.60"),
    _PRICED_AS_OF,
    "NO_DETERMINATION",
)
# (od_pair_id, price_usd, road, observed_at, status) -- trip_pricing_i95_live shape
_BRADDOCK_LEG2_LIVE_ROW = (1374, Decimal("3.45"), "495", _LIVE_OBSERVED_AT, "open")


def test_single_leg_lookup(monkeypatch):
    monkeypatch.setattr(
        i95_mod, "_env_connect", _connect_returning(_ROUTE267_TO_495END_ROW)
    )
    result = i95_route("Route 267", "495 Express Lanes End/George Wash. Mem. Pkwy.")
    assert result["direction"] == "Northbound"
    assert result["entry"] == {"node_id": "182NO", "label": "Route 267"}
    assert result["legs"] == [
        {
            "od_pair_id": 1038,
            "price_usd": "2.75",
            "source": "trip_pricing_i95",
            "facility_group": "495",
            "corridor_name": "I-495-NB",
            "priced_as_of": _PRICED_AS_OF.isoformat(),
        }
    ]
    assert result["facility_totals"] == {"495": "2.75", "95_395": "0.00"}
    assert result["total_usd"] == "2.75"


def test_composite_two_leg_lookup_preserves_order_and_facility_breakdown(monkeypatch):
    # Cross-corridor trip: 203NO -> 181ND, both od_pair_ids in the range VDOT
    # has actually priced (1000-1352), unlike the flagship gap case below.
    monkeypatch.setattr(
        i95_mod,
        "_env_connect",
        _connect_returning(_OLDKEENE_LEG1_ROW, _OLDKEENE_LEG2_ROW),
    )
    result = i95_route(
        "Old Keene Mill Road/Route 644", "495 Express Lanes End/George Wash. Mem. Pkwy."
    )
    assert result["direction"] == "Northbound"
    assert result["entry"]["node_id"] == "203NO"
    assert [leg["od_pair_id"] for leg in result["legs"]] == [1144, 1092]
    assert result["legs"][0]["facility_group"] == "95_395"
    assert result["legs"][1]["facility_group"] == "495"
    assert result["facility_totals"] == {"495": "6.10", "95_395": "3.25"}
    assert result["total_usd"] == "9.35"


def test_composite_leg_falls_back_to_live_source_for_the_known_vdot_pricing_gap(
    monkeypatch,
):
    # od_pair_id 1374 is real (published by Transurban) but has never had a
    # priced row in trip_pricing_i95 -- docs/oracle-findings.md section 2.
    # The primary query returns None for it, so the tool falls back to
    # trip_pricing_i95_live, which does have a row here.
    monkeypatch.setattr(
        i95_mod,
        "_env_connect",
        _connect_returning(_BRADDOCK_LEG1_ROW, None, _BRADDOCK_LEG2_LIVE_ROW),
    )
    result = i95_route("I-495 Near Braddock Road", "I-395 Near Edsall Road")
    assert [leg["od_pair_id"] for leg in result["legs"]] == [1083, 1374]
    gap_leg = result["legs"][1]
    assert gap_leg["source"] == "trip_pricing_i95_live"
    assert gap_leg["price_usd"] == "3.45"
    assert gap_leg["facility_group"] == "495"
    assert gap_leg["corridor_name"] is None
    assert result["facility_totals"] == {"495": "10.05", "95_395": "0.00"}
    assert result["total_usd"] == "10.05"


def test_gap_id_defaults_to_zero_when_even_live_source_has_no_row(monkeypatch):
    # Neither table has a row for 1374 here (e.g. an at_time before the live
    # table's own ingestion start) -- still a known gap id, so this prices
    # $0.00 flagged as a placeholder rather than hard-erroring the call.
    monkeypatch.setattr(
        i95_mod,
        "_env_connect",
        _connect_returning(_BRADDOCK_LEG1_ROW, None, None),
    )
    result = i95_route("I-495 Near Braddock Road", "I-395 Near Edsall Road")
    gap_leg = result["legs"][1]
    assert gap_leg == {
        "od_pair_id": 1374,
        "price_usd": "0.00",
        "source": "unpriced_gap",
        "facility_group": "495",
        "corridor_name": None,
        "priced_as_of": None,
    }
    assert result["total_usd"] == "6.60"


def test_non_gap_id_with_no_price_anywhere_is_a_hard_error_not_a_partial_result(
    monkeypatch,
):
    # 1092 is NOT one of the 16 known gap ids -- a miss for it in both tables
    # is a real problem, so the whole call errors, discarding leg 1's price
    # rather than returning a partial result.
    monkeypatch.setattr(
        i95_mod,
        "_env_connect",
        _connect_returning(_OLDKEENE_LEG1_ROW, None, None),
    )
    result = i95_route(
        "Old Keene Mill Road/Route 644", "495 Express Lanes End/George Wash. Mem. Pkwy."
    )
    assert "error" in result
    assert result["valid_options"] == []
    assert "1092" in result["error"]
    assert "legs" not in result


def test_unrecognized_corridor_name_is_a_hard_error(monkeypatch):
    bad_row = (
        1038,
        "I-395-NEW-EXTENSION",
        Decimal("2.75"),
        _PRICED_AS_OF,
        "NO_DETERMINATION",
    )
    monkeypatch.setattr(i95_mod, "_env_connect", _connect_returning(bad_row))
    result = i95_route("Route 267", "495 Express Lanes End/George Wash. Mem. Pkwy.")
    assert "error" in result
    assert "I-395-NEW-EXTENSION" in result["error"]
    assert "1038" in result["error"]


def test_unrecognized_road_is_a_hard_error(monkeypatch):
    bad_live_row = (1374, Decimal("3.45"), "895", _LIVE_OBSERVED_AT, "open")
    monkeypatch.setattr(
        i95_mod,
        "_env_connect",
        _connect_returning(_BRADDOCK_LEG1_ROW, None, bad_live_row),
    )
    result = i95_route("I-495 Near Braddock Road", "I-395 Near Edsall Road")
    assert "error" in result
    assert "895" in result["error"]
    assert "1374" in result["error"]


def test_closed_primary_row_is_a_hard_error_not_priced(monkeypatch):
    # Reproduces the reported bug live: od_pair_id 1151 ("TURKEYCOCK TO
    # US-1", southbound, real corridor I-95-SB) is currently CLOSED in RDS,
    # and used to still price at $6.75. No live-table row either.
    closed_row = (1151, "I-95-SB", Decimal("6.75"), _PRICED_AS_OF, "CLOSED")
    monkeypatch.setattr(i95_mod, "_env_connect", _connect_returning(closed_row, None))
    result = i95_route("I-395 Near Edsall Road", "US-1")
    assert "error" in result
    assert result["valid_options"] == []
    assert "1151" in result["error"]
    assert "CLOSED" in result["error"]
    assert "legs" not in result


def test_495_corridor_row_ignores_no_determination_status(monkeypatch):
    # I-495-NB/SB never report a real link_status (always NO_DETERMINATION/
    # UNKNOWN in production), so those corridors must bypass the gate --
    # otherwise every 495 trip would hard-error.
    row = (1038, "I-495-NB", Decimal("2.75"), _PRICED_AS_OF, "NO_DETERMINATION")
    monkeypatch.setattr(i95_mod, "_env_connect", _connect_returning(row))
    result = i95_route("Route 267", "495 Express Lanes End/George Wash. Mem. Pkwy.")
    assert result["legs"][0]["price_usd"] == "2.75"


def test_wrong_direction_open_primary_row_is_a_hard_error(monkeypatch):
    # A real, valid *_OPEN status, but for the wrong direction of this
    # corridor -- pins the exact-match rule against a sloppy "OPEN in
    # status" implementation.
    wrong_direction_row = (
        1151,
        "I-95-SB",
        Decimal("6.75"),
        _PRICED_AS_OF,
        "NORTHBOUND_OPEN",
    )
    monkeypatch.setattr(
        i95_mod, "_env_connect", _connect_returning(wrong_direction_row, None)
    )
    result = i95_route("I-395 Near Edsall Road", "US-1")
    assert "error" in result
    assert "1151" in result["error"]


def test_closed_primary_falls_through_to_open_live_row(monkeypatch):
    closed_row = (1151, "I-95-SB", Decimal("6.75"), _PRICED_AS_OF, "CLOSED")
    live_row = (1151, Decimal("6.50"), "95", _LIVE_OBSERVED_AT, "open")
    monkeypatch.setattr(
        i95_mod, "_env_connect", _connect_returning(closed_row, live_row)
    )
    result = i95_route("I-395 Near Edsall Road", "US-1")
    leg = result["legs"][0]
    assert leg["source"] == "trip_pricing_i95_live"
    assert leg["price_usd"] == "6.50"


def test_closed_live_status_falls_through_to_gap_placeholder(monkeypatch):
    live_row = (1374, Decimal("3.45"), "495", _LIVE_OBSERVED_AT, "closed")
    monkeypatch.setattr(
        i95_mod,
        "_env_connect",
        _connect_returning(_BRADDOCK_LEG1_ROW, None, live_row),
    )
    result = i95_route("I-495 Near Braddock Road", "I-395 Near Edsall Road")
    gap_leg = result["legs"][1]
    assert gap_leg["source"] == "unpriced_gap"
    assert gap_leg["price_usd"] == "0.00"


def test_classify_facility_group_covers_all_known_corridor_and_road_values():
    classify = i95_mod._classify_facility_group
    assert (
        classify("I-495-NB", i95_mod._CORRIDOR_TO_FACILITY, od_pair_id=1, source="x")
        == "495"
    )
    assert (
        classify("I-495-SB", i95_mod._CORRIDOR_TO_FACILITY, od_pair_id=1, source="x")
        == "495"
    )
    assert (
        classify("I-95-NB", i95_mod._CORRIDOR_TO_FACILITY, od_pair_id=1, source="x")
        == "95_395"
    )
    assert (
        classify("I-95-SB", i95_mod._CORRIDOR_TO_FACILITY, od_pair_id=1, source="x")
        == "95_395"
    )
    assert classify("495", i95_mod._ROAD_TO_FACILITY, od_pair_id=1, source="x") == "495"
    assert (
        classify("95", i95_mod._ROAD_TO_FACILITY, od_pair_id=1, source="x") == "95_395"
    )
    assert (
        classify("395", i95_mod._ROAD_TO_FACILITY, od_pair_id=1, source="x") == "95_395"
    )


def test_invalid_at_time_is_a_hard_error_before_any_db_call(monkeypatch):
    def env_connect():
        raise AssertionError("must not connect to the DB for a malformed at_time")

    monkeypatch.setattr(i95_mod, "_env_connect", env_connect)
    result = i95_route(
        "Route 267", "495 Express Lanes End/George Wash. Mem. Pkwy.", at_time="garbage"
    )
    assert "error" in result
    assert result["valid_options"] == []
    assert "garbage" in result["error"]


def test_resolve_at_time_defaults_to_now_eastern():
    sentinel = datetime(2026, 7, 26, 12, 0, tzinfo=_EASTERN)
    assert i95_mod._resolve_at_time(None, now=lambda: sentinel) == sentinel


def test_resolve_at_time_assumes_eastern_for_a_naive_string():
    result = i95_mod._resolve_at_time("2026-07-26T12:00:00")
    assert result == datetime(2026, 7, 26, 12, 0, tzinfo=_EASTERN)


def test_label_lookup_is_case_insensitive(monkeypatch):
    monkeypatch.setattr(
        i95_mod, "_env_connect", _connect_returning(_ROUTE267_TO_495END_ROW)
    )
    result = i95_route("route 267", "495 express lanes end/george wash. mem. pkwy.")
    assert result["legs"][0]["od_pair_id"] == 1038


def test_node_id_fallback_matches_label_lookup(monkeypatch):
    def env_connect():
        return FakeConnection([_ROUTE267_TO_495END_ROW])

    monkeypatch.setattr(i95_mod, "_env_connect", env_connect)
    by_id = i95_route("182NO", "181ND")
    by_label = i95_route("Route 267", "495 Express Lanes End/George Wash. Mem. Pkwy.")
    # origin/destination echo the caller's raw input, so they legitimately
    # differ between the two forms -- everything resolved must match.
    for key in ("direction", "entry", "exit", "legs", "total_usd"):
        assert by_id[key] == by_label[key]


def test_unknown_origin_returns_only_origin_capable_labels():
    result = i95_route("Not A Real Place", "Route 267")
    assert "error" in result
    assert "Route 267" in result["valid_options"]
    # This ramp is exit-only -- suggesting it as an origin would guarantee a
    # second dead-end miss.
    assert (
        "495 Express Lanes End/George Wash. Mem. Pkwy." not in result["valid_options"]
    )


def test_unknown_destination_returns_only_destination_capable_labels():
    result = i95_route("Route 267", "Not A Real Place")
    assert "error" in result
    assert "Route 267" in result["valid_options"]
    # This ramp is entry-only -- suggesting it as a destination would
    # guarantee a second dead-end miss.
    assert (
        "495 Express Lanes Start/Georg Wash. Mem. Pkwy." not in result["valid_options"]
    )


def test_known_but_unconnected_pair_returns_reachable_only():
    result = i95_route("Route 267", "Fairfax County Parkway/Route 286")
    assert "error" in result
    assert "Fairfax County Parkway/Route 286" not in result["valid_options"]
    assert len(result["valid_options"]) == 25


def test_ambiguous_match_is_guarded_with_synthetic_data(monkeypatch):
    # Unreachable via the real oracle; hand-built to prove the guard fires
    # if that invariant ever breaks.
    monkeypatch.setattr(
        i95_mod,
        "_NODES",
        {
            "a": {
                "label": "Origin",
                "direction": "Northbound",
                "side": "entries",
                "path": "95",
            },
            "b": {
                "label": "Origin",
                "direction": "Northbound",
                "side": "entries",
                "path": "95",
            },
            "c": {
                "label": "Dest",
                "direction": "Northbound",
                "side": "exits",
                "path": "95",
            },
        },
    )
    monkeypatch.setattr(
        i95_mod,
        "_PAIRS",
        [
            {"direction": "Northbound", "entry": "a", "exit": "c", "ods": [1]},
            {"direction": "Northbound", "entry": "b", "exit": "c", "ods": [2]},
        ],
    )
    monkeypatch.setattr(i95_mod, "_LABEL_INDEX", {"origin": ["a", "b"], "dest": ["c"]})
    result = i95_mod._lookup("Origin", "Dest")
    assert "error" in result
    assert "ambiguous" in result["error"]


def test_direction_comes_from_the_pair_never_the_node_id_suffix(monkeypatch):
    # Node 2229ND has direction "Southbound" despite the ND suffix, which
    # would misleadingly suggest Northbound if inferred from the id.
    # This is a two-leg composite trip in the real oracle: od_pair_id 1039
    # then 1263.
    rows = (
        (1039, "I-95-SB", Decimal("2.00"), _PRICED_AS_OF, "SOUTHBOUND_OPEN"),
        (1263, "I-95-SB", Decimal("1.50"), _PRICED_AS_OF, "SOUTHBOUND_OPEN"),
    )
    monkeypatch.setattr(i95_mod, "_env_connect", _connect_returning(*rows))
    result = i95_route(
        "495 Express Lanes Start/Georg Wash. Mem. Pkwy.", "Seminary Road"
    )
    assert result["direction"] == "Southbound"
    assert result["exit"]["node_id"] == "2229ND"


def test_label_shared_by_multiple_node_ids_still_resolves_unambiguously(monkeypatch):
    # "Westpark Drive" maps to 5 distinct node ids in the real oracle; the
    # (entry_label, exit_label) pair is still unique.
    row = (1037, "I-495-NB", Decimal("2.00"), _PRICED_AS_OF, "NO_DETERMINATION")
    monkeypatch.setattr(i95_mod, "_env_connect", _connect_returning(row))
    result = i95_route(
        "Westpark Drive", "495 Express Lanes End/George Wash. Mem. Pkwy."
    )
    assert result["entry"]["node_id"] == "185NO"
    assert result["legs"][0]["od_pair_id"] == 1037


def test_tool_spec_matches_signature():
    assert i95_route.tool_spec["name"] == "i95_route"
    assert set(i95_route.tool_spec["inputSchema"]["json"]["required"]) == {
        "origin",
        "destination",
    }


def test_logs_successful_lookup(monkeypatch, caplog):
    monkeypatch.setattr(
        i95_mod, "_env_connect", _connect_returning(_ROUTE267_TO_495END_ROW)
    )
    caplog.set_level(logging.INFO)
    i95_route("Route 267", "495 Express Lanes End/George Wash. Mem. Pkwy.")
    assert "i95_route ok" in caplog.text
    assert "1038" in caplog.text


def test_failure_log_omits_the_option_list(caplog):
    caplog.set_level(logging.INFO)
    i95_route("Not A Real Place", "Route 267")
    assert "i95_route miss" in caplog.text
    # An unrelated valid_options entry must not leak into the audit line.
    assert "Westpark Drive" not in caplog.text
