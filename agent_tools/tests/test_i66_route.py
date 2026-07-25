"""Tests for i66_route -- pure local JSON lookup, no network, no RDS.

Real-data fixtures are verified directly against oracles/i66.json (see the
inline values below); the ambiguous-match branch is exercised with synthetic
data since the real oracle has no such case today (verified 96/96 pairs
unique on (entry, exit)).
"""

import logging

import i66_route as i66_mod
from i66_route import i66_route


def test_label_lookup():
    result = i66_route("I-66 West", "Westmoreland St")
    assert result["direction"] == "EB"
    assert result["entry"] == {"node_id": "1", "label": "I-66 West"}
    assert result["exit"] == {"node_id": "10", "label": "Westmoreland St"}
    assert result["legs"] == [{"start_zone_id": 3100, "end_zone_id": 3110}]


def test_label_lookup_is_case_insensitive():
    result = i66_route("i-66 west", "westmoreland st")
    assert result["legs"] == [{"start_zone_id": 3100, "end_zone_id": 3110}]


def test_node_id_fallback_matches_label_lookup():
    by_id = i66_route("1", "10")
    by_label = i66_route("I-66 West", "Westmoreland St")
    # origin/destination echo the caller's raw input, so they legitimately
    # differ between the two forms -- everything resolved must match.
    for key in ("direction", "entry", "exit", "legs"):
        assert by_id[key] == by_label[key]


def test_unknown_origin_returns_only_origin_capable_labels():
    result = i66_route("Not A Real Place", "Westmoreland St")
    assert "error" in result
    assert "I-66 West" in result["valid_options"]
    # Westmoreland St and Exit 73 - Rosslyn are exit-only interchanges --
    # suggesting either as an origin would guarantee a second dead-end miss.
    assert "Westmoreland St" not in result["valid_options"]
    assert "Exit 73 - Rosslyn" not in result["valid_options"]


def test_unknown_destination_returns_only_destination_capable_labels():
    result = i66_route("I-66 West", "Not A Real Place")
    assert "error" in result
    assert "I-66 West" in result["valid_options"]
    # I-495 N and Lee Highway - Scott Street are entry-only interchanges --
    # suggesting either as a destination would guarantee a second dead-end miss.
    assert "I-495 N" not in result["valid_options"]
    assert "Lee Highway - Scott Street" not in result["valid_options"]


def test_known_but_unconnected_pair_returns_reachable_only():
    # Both labels are real; there is no direct EB trip from I-66 West to
    # Glebe Road (which sits on the WB side only from this entry).
    result = i66_route("I-66 West", "Glebe Road")
    assert "error" in result
    assert result["valid_options"] == [
        "Exit 73 - Rosslyn",
        "Exit 75 - Pentagon/Alexandria",
        "Fairfax Drive",
        "Lee Highway - Spout Run Parkway",
        "Route 7 - Leesburg Pike",
        "Washington",
        "Washington Blvd",
        "Westmoreland St",
    ]
    assert "Glebe Road" not in result["valid_options"]


def test_ambiguous_match_is_guarded_with_synthetic_data(monkeypatch):
    # Unreachable via the real oracle (96/96 pairs unique on (entry, exit));
    # hand-built to prove the guard fires if that invariant ever breaks.
    monkeypatch.setattr(
        i66_mod,
        "_NODES",
        {
            "a": {"label": "Origin", "entry_in": ["EB"], "exit_in": []},
            "b": {"label": "Origin", "entry_in": ["EB"], "exit_in": []},
            "c": {"label": "Dest", "entry_in": [], "exit_in": ["EB"]},
        },
    )
    monkeypatch.setattr(
        i66_mod,
        "_PAIRS",
        [
            {
                "direction": "EB",
                "entry": "a",
                "exit": "c",
                "start_zone": 1,
                "end_zone": 2,
            },
            {
                "direction": "EB",
                "entry": "b",
                "exit": "c",
                "start_zone": 3,
                "end_zone": 4,
            },
        ],
    )
    monkeypatch.setattr(i66_mod, "_LABEL_INDEX", {"origin": ["a", "b"], "dest": ["c"]})
    result = i66_mod._lookup("Origin", "Dest")
    assert "error" in result
    assert "ambiguous" in result["error"]


def test_tool_spec_matches_signature():
    assert i66_route.tool_spec["name"] == "i66_route"
    assert set(i66_route.tool_spec["inputSchema"]["json"]["required"]) == {
        "origin",
        "destination",
    }


def test_logs_successful_lookup(caplog):
    caplog.set_level(logging.INFO)
    i66_route("I-66 West", "Westmoreland St")
    assert "i66_route ok" in caplog.text
    assert "3100" in caplog.text


def test_failure_log_omits_the_option_list(caplog):
    caplog.set_level(logging.INFO)
    i66_route("Not A Real Place", "Westmoreland St")
    assert "i66_route miss" in caplog.text
    # "Fairfax Drive" is one of the valid_options entries on this failure --
    # it must not leak into the audit line, which is noise, not signal.
    assert "Fairfax Drive" not in caplog.text
