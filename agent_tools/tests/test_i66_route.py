"""Tests for i66_route.

Route resolution is pure local JSON lookup, no network, no RDS. Pricing
hits RDS via _env_connect(), which every success-path test here replaces
with a FakeConnection (conftest.py) -- no real DB, no psycopg import.

Real-data fixtures are verified directly against oracles/i66.json (see the
inline values below); the ambiguous-match branch is exercised with synthetic
data since the real oracle has no such case today (verified 96/96 pairs
unique on (entry, exit)).
"""

import logging
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import i66_route as i66_mod
from conftest import FakeConnection, connect_returning as _connect_returning
from i66_route import i66_route

_EASTERN = ZoneInfo("America/New_York")
_PRICED_AS_OF = datetime(2026, 7, 26, 14, 20, tzinfo=_EASTERN)

# (start_zone_id, end_zone_id, corridor_name, zone_toll_rate_usd, interval_end_at)
_I66_WEST_TO_WESTMORELAND_ROW = (3100, 3110, "I-66-EB", Decimal("4.50"), _PRICED_AS_OF)


def test_label_lookup(monkeypatch):
    monkeypatch.setattr(
        i66_mod, "_env_connect", _connect_returning(_I66_WEST_TO_WESTMORELAND_ROW)
    )
    result = i66_route("I-66 West", "Westmoreland St")
    assert result["direction"] == "EB"
    assert result["entry"] == {"node_id": "1", "label": "I-66 West"}
    assert result["exit"] == {"node_id": "10", "label": "Westmoreland St"}
    assert result["legs"] == [
        {
            "start_zone_id": 3100,
            "end_zone_id": 3110,
            "price_usd": "4.50",
            "corridor_name": "I-66-EB",
            "priced_as_of": _PRICED_AS_OF.isoformat(),
        }
    ]
    assert result["total_usd"] == "4.50"
    assert "at_time" in result


def test_label_lookup_is_case_insensitive(monkeypatch):
    monkeypatch.setattr(
        i66_mod, "_env_connect", _connect_returning(_I66_WEST_TO_WESTMORELAND_ROW)
    )
    result = i66_route("i-66 west", "westmoreland st")
    assert result["legs"][0]["start_zone_id"] == 3100
    assert result["legs"][0]["end_zone_id"] == 3110
    assert result["total_usd"] == "4.50"


def test_node_id_fallback_matches_label_lookup(monkeypatch):
    def env_connect():
        return FakeConnection([_I66_WEST_TO_WESTMORELAND_ROW])

    monkeypatch.setattr(i66_mod, "_env_connect", env_connect)
    by_id = i66_route("1", "10")
    by_label = i66_route("I-66 West", "Westmoreland St")
    # origin/destination echo the caller's raw input, so they legitimately
    # differ between the two forms -- everything resolved must match.
    for key in ("direction", "entry", "exit", "legs", "total_usd"):
        assert by_id[key] == by_label[key]


def test_price_not_found_is_a_hard_error(monkeypatch):
    monkeypatch.setattr(i66_mod, "_env_connect", _connect_returning(None))
    result = i66_route("I-66 West", "Westmoreland St")
    assert "error" in result
    assert result["valid_options"] == []
    assert "trip_pricing_i66" in result["error"]
    assert "3100" in result["error"] and "3110" in result["error"]


def test_at_time_is_passed_through_and_echoed(monkeypatch):
    monkeypatch.setattr(
        i66_mod, "_env_connect", _connect_returning(_I66_WEST_TO_WESTMORELAND_ROW)
    )
    result = i66_route(
        "I-66 West", "Westmoreland St", at_time="2026-01-15T09:00:00-05:00"
    )
    assert result["at_time"] == "2026-01-15T09:00:00-05:00"


def test_invalid_at_time_is_a_hard_error_before_any_db_call(monkeypatch):
    def env_connect():
        raise AssertionError("must not connect to the DB for a malformed at_time")

    monkeypatch.setattr(i66_mod, "_env_connect", env_connect)
    result = i66_route("I-66 West", "Westmoreland St", at_time="not-a-timestamp")
    assert "error" in result
    assert result["valid_options"] == []
    assert "not-a-timestamp" in result["error"]


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


def test_resolve_at_time_defaults_to_now_eastern():
    sentinel = datetime(2026, 7, 26, 12, 0, tzinfo=_EASTERN)
    assert i66_mod._resolve_at_time(None, now=lambda: sentinel) == sentinel


def test_resolve_at_time_assumes_eastern_for_a_naive_string():
    result = i66_mod._resolve_at_time("2026-07-26T12:00:00")
    assert result == datetime(2026, 7, 26, 12, 0, tzinfo=_EASTERN)


def test_resolve_at_time_keeps_an_explicit_offset():
    result = i66_mod._resolve_at_time("2026-07-26T12:00:00+00:00")
    assert result.utcoffset() == timedelta(0)


def test_tool_spec_matches_signature():
    assert i66_route.tool_spec["name"] == "i66_route"
    assert set(i66_route.tool_spec["inputSchema"]["json"]["required"]) == {
        "origin",
        "destination",
    }


def test_logs_successful_lookup(monkeypatch, caplog):
    monkeypatch.setattr(
        i66_mod, "_env_connect", _connect_returning(_I66_WEST_TO_WESTMORELAND_ROW)
    )
    caplog.set_level(logging.INFO)
    i66_route("I-66 West", "Westmoreland St")
    assert "i66_route ok" in caplog.text
    assert "3100" in caplog.text
    assert "4.50" in caplog.text


def test_failure_log_omits_the_option_list(caplog):
    caplog.set_level(logging.INFO)
    i66_route("Not A Real Place", "Westmoreland St")
    assert "i66_route miss" in caplog.text
    # "Fairfax Drive" is one of the valid_options entries on this failure --
    # it must not leak into the audit line, which is noise, not signal.
    assert "Fairfax Drive" not in caplog.text
