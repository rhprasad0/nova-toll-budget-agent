"""Tests for i95_route -- pure local JSON lookup, no network, no RDS.

Real-data fixtures are verified directly against oracles/i95.json (see the
inline values below); the ambiguous-match branch is exercised with synthetic
data since the real oracle has no such case today (verified 685/685 pairs
unique on (entry, exit) and on (entry_label, exit_label)).
"""

import logging

import i95_route as i95_mod
from i95_route import i95_route


def test_single_leg_lookup():
    result = i95_route("Route 267", "495 Express Lanes End/George Wash. Mem. Pkwy.")
    assert result["direction"] == "Northbound"
    assert result["entry"] == {"node_id": "182NO", "label": "Route 267"}
    assert result["legs"] == [{"od_pair_id": 1038}]


def test_composite_two_leg_lookup_preserves_order():
    # Cross-corridor trip: 203NO -> 181ND, both od_pair_ids in the range VDOT
    # has actually priced (1000-1352), unlike the flagship gap case below.
    result = i95_route(
        "Old Keene Mill Road/Route 644", "495 Express Lanes End/George Wash. Mem. Pkwy."
    )
    assert result["direction"] == "Northbound"
    assert result["entry"]["node_id"] == "203NO"
    assert result["legs"] == [{"od_pair_id": 1144}, {"od_pair_id": 1092}]


def test_composite_leg_includes_the_known_vdot_pricing_gap():
    # od_pair_id 1374 is real (published by Transurban) but has never had a
    # priced row in trip_pricing_i95 -- docs/oracle-findings.md section 2.
    # This tool still returns it: existence in the oracle, not priceability,
    # is the contract.
    result = i95_route("I-495 Near Braddock Road", "I-395 Near Edsall Road")
    assert result["legs"] == [{"od_pair_id": 1083}, {"od_pair_id": 1374}]


def test_label_lookup_is_case_insensitive():
    result = i95_route("route 267", "495 express lanes end/george wash. mem. pkwy.")
    assert result["legs"] == [{"od_pair_id": 1038}]


def test_node_id_fallback_matches_label_lookup():
    by_id = i95_route("182NO", "181ND")
    by_label = i95_route("Route 267", "495 Express Lanes End/George Wash. Mem. Pkwy.")
    # origin/destination echo the caller's raw input, so they legitimately
    # differ between the two forms -- everything resolved must match.
    for key in ("direction", "entry", "exit", "legs"):
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


def test_direction_comes_from_the_pair_never_the_node_id_suffix():
    # Node 2229ND has direction "Southbound" despite the ND suffix, which
    # would misleadingly suggest Northbound if inferred from the id.
    result = i95_route(
        "495 Express Lanes Start/Georg Wash. Mem. Pkwy.", "Seminary Road"
    )
    assert result["direction"] == "Southbound"
    assert result["exit"]["node_id"] == "2229ND"


def test_label_shared_by_multiple_node_ids_still_resolves_unambiguously():
    # "Westpark Drive" maps to 5 distinct node ids in the real oracle; the
    # (entry_label, exit_label) pair is still unique.
    result = i95_route(
        "Westpark Drive", "495 Express Lanes End/George Wash. Mem. Pkwy."
    )
    assert result["entry"]["node_id"] == "185NO"
    assert result["legs"] == [{"od_pair_id": 1037}]


def test_tool_spec_matches_signature():
    assert i95_route.tool_spec["name"] == "i95_route"
    assert set(i95_route.tool_spec["inputSchema"]["json"]["required"]) == {
        "origin",
        "destination",
    }


def test_logs_successful_lookup(caplog):
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
