"""Tests for i495_route.

Route resolution is pure local JSON lookup, no network, no RDS. Pricing
hits RDS via _env_connect(), which every success-path test here replaces
with a FakeConnection (conftest.py) -- no real DB, no psycopg import.

i495_route covers only the within-495 subset of oracles/i95.json (78 of
685 pairs); cross-corridor trips are out of scope (see i95_route.py and
docs/oracle-findings.md section 8). Real-data fixtures are verified
directly against that subset (see the inline values below); the
ambiguous-match branch is exercised with synthetic data since the real
oracle has no such case today.
"""

import logging
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import i495_route as i495_mod
from conftest import FakeConnection, connect_returning as _connect_returning
from i495_route import i495_route

_EASTERN = ZoneInfo("America/New_York")
_PRICED_AS_OF = datetime(2026, 7, 26, 14, 20, tzinfo=_EASTERN)

# (od_pair_id, corridor_name, zone_toll_rate_usd, interval_end_at)
_ROUTE267_TO_495END_ROW = (1038, "I-495-NB", Decimal("2.60"), _PRICED_AS_OF)
_I66_TO_495END_ROW = (1034, "I-495-NB", Decimal("3.10"), _PRICED_AS_OF)


def test_single_leg_lookup(monkeypatch):
    monkeypatch.setattr(
        i495_mod, "_env_connect", _connect_returning(_ROUTE267_TO_495END_ROW)
    )
    result = i495_route("Route 267", "495 Express Lanes End/George Wash. Mem. Pkwy.")
    assert result["direction"] == "Northbound"
    assert result["entry"] == {"node_id": "182NO", "label": "Route 267"}
    assert result["legs"] == [
        {
            "od_pair_id": 1038,
            "price_usd": "2.60",
            "corridor_name": "I-495-NB",
            "priced_as_of": _PRICED_AS_OF.isoformat(),
        }
    ]
    assert result["total_usd"] == "2.60"
    assert "at_time" in result


def test_label_lookup_is_case_insensitive(monkeypatch):
    monkeypatch.setattr(
        i495_mod, "_env_connect", _connect_returning(_ROUTE267_TO_495END_ROW)
    )
    result = i495_route("route 267", "495 express lanes end/george wash. mem. pkwy.")
    assert result["legs"][0]["od_pair_id"] == 1038


def test_node_id_fallback_matches_label_lookup(monkeypatch):
    def env_connect():
        return FakeConnection([_ROUTE267_TO_495END_ROW])

    monkeypatch.setattr(i495_mod, "_env_connect", env_connect)
    by_id = i495_route("182NO", "181ND")
    by_label = i495_route("Route 267", "495 Express Lanes End/George Wash. Mem. Pkwy.")
    # origin/destination echo the caller's raw input, so they legitimately
    # differ between the two forms -- everything resolved must match.
    for key in ("direction", "entry", "exit", "legs", "total_usd"):
        assert by_id[key] == by_label[key]


def test_price_not_found_is_a_hard_error(monkeypatch):
    monkeypatch.setattr(i495_mod, "_env_connect", _connect_returning(None))
    result = i495_route("Route 267", "495 Express Lanes End/George Wash. Mem. Pkwy.")
    assert "error" in result
    assert result["valid_options"] == []
    assert "trip_pricing_i95" in result["error"]
    assert "1038" in result["error"]


def test_at_time_is_passed_through_and_echoed(monkeypatch):
    monkeypatch.setattr(
        i495_mod, "_env_connect", _connect_returning(_ROUTE267_TO_495END_ROW)
    )
    result = i495_route(
        "Route 267",
        "495 Express Lanes End/George Wash. Mem. Pkwy.",
        at_time="2026-01-15T09:00:00-05:00",
    )
    assert result["at_time"] == "2026-01-15T09:00:00-05:00"


def test_invalid_at_time_is_a_hard_error_before_any_db_call(monkeypatch):
    def env_connect():
        raise AssertionError("must not connect to the DB for a malformed at_time")

    monkeypatch.setattr(i495_mod, "_env_connect", env_connect)
    result = i495_route(
        "Route 267",
        "495 Express Lanes End/George Wash. Mem. Pkwy.",
        at_time="not-a-timestamp",
    )
    assert "error" in result
    assert result["valid_options"] == []
    assert "not-a-timestamp" in result["error"]


def test_unknown_origin_returns_only_origin_capable_labels():
    result = i495_route("Not A Real Place", "Route 267")
    assert "error" in result
    assert "Route 267" in result["valid_options"]
    # Exit-only ramp -- suggesting it as an origin would guarantee a second
    # dead-end miss.
    assert (
        "495 Express Lanes End/George Wash. Mem. Pkwy." not in result["valid_options"]
    )


def test_unknown_destination_returns_only_destination_capable_labels():
    result = i495_route("Route 267", "Not A Real Place")
    assert "error" in result
    assert "495 Express Lanes End/George Wash. Mem. Pkwy." in result["valid_options"]
    # Entry-only ramp -- suggesting it as a destination would guarantee a
    # second dead-end miss.
    assert (
        "495 Express Lanes Start/Georg Wash. Mem. Pkwy." not in result["valid_options"]
    )


def test_known_but_unconnected_pair_returns_reachable_only():
    # "495 Express Lanes Start" (the entry-only ramp at one end) never
    # reaches "495 Express Lanes End" (the exit-only ramp at the other) --
    # verified against the real oracle.
    result = i495_route(
        "495 Express Lanes Start/Georg Wash. Mem. Pkwy.",
        "495 Express Lanes End/George Wash. Mem. Pkwy.",
    )
    assert "error" in result
    assert result["valid_options"] == [
        "Braddock Road",
        "Gallows Road",
        "I-495 Near Braddock Road",
        "I-495/I-95 Near Van Dorn Street",
        "Interstate 66",
        "Jones Branch Drive/Route 123",
        "Route 267",
        "Westpark Drive",
    ]
    assert (
        "495 Express Lanes End/George Wash. Mem. Pkwy." not in result["valid_options"]
    )


def test_ambiguous_match_is_guarded_with_synthetic_data(monkeypatch):
    # Unreachable via the real oracle; hand-built to prove the guard fires
    # if that invariant ever breaks.
    monkeypatch.setattr(
        i495_mod,
        "_NODES",
        {
            "a": {
                "label": "Origin",
                "direction": "Northbound",
                "side": "entries",
                "path": "495North",
            },
            "b": {
                "label": "Origin",
                "direction": "Northbound",
                "side": "entries",
                "path": "495North",
            },
            "c": {
                "label": "Dest",
                "direction": "Northbound",
                "side": "exits",
                "path": "495North",
            },
        },
    )
    monkeypatch.setattr(
        i495_mod,
        "_PAIRS",
        [
            {"direction": "Northbound", "entry": "a", "exit": "c", "ods": [1]},
            {"direction": "Northbound", "entry": "b", "exit": "c", "ods": [2]},
        ],
    )
    monkeypatch.setattr(i495_mod, "_LABEL_INDEX", {"origin": ["a", "b"], "dest": ["c"]})
    result = i495_mod._lookup("Origin", "Dest")
    assert "error" in result
    assert "ambiguous" in result["error"]


def test_label_shared_by_multiple_node_ids_still_resolves_unambiguously(monkeypatch):
    # "Interstate 66" maps to 4 distinct node ids in the real oracle; the
    # (entry_label, exit_label) pair is still unique.
    monkeypatch.setattr(
        i495_mod, "_env_connect", _connect_returning(_I66_TO_495END_ROW)
    )
    result = i495_route(
        "Interstate 66", "495 Express Lanes End/George Wash. Mem. Pkwy."
    )
    assert result["entry"]["node_id"] == "187NO"
    assert result["legs"][0]["od_pair_id"] == 1034


def test_resolve_at_time_defaults_to_now_eastern():
    sentinel = datetime(2026, 7, 26, 12, 0, tzinfo=_EASTERN)
    assert i495_mod._resolve_at_time(None, now=lambda: sentinel) == sentinel


def test_resolve_at_time_assumes_eastern_for_a_naive_string():
    result = i495_mod._resolve_at_time("2026-07-26T12:00:00")
    assert result == datetime(2026, 7, 26, 12, 0, tzinfo=_EASTERN)


def test_resolve_at_time_keeps_an_explicit_offset():
    result = i495_mod._resolve_at_time("2026-07-26T12:00:00+00:00")
    assert result.utcoffset() == timedelta(0)


def test_tool_spec_matches_signature():
    assert i495_route.tool_spec["name"] == "i495_route"
    assert set(i495_route.tool_spec["inputSchema"]["json"]["required"]) == {
        "origin",
        "destination",
    }


def test_logs_successful_lookup(monkeypatch, caplog):
    monkeypatch.setattr(
        i495_mod, "_env_connect", _connect_returning(_ROUTE267_TO_495END_ROW)
    )
    caplog.set_level(logging.INFO)
    i495_route("Route 267", "495 Express Lanes End/George Wash. Mem. Pkwy.")
    assert "i495_route ok" in caplog.text
    assert "1038" in caplog.text


def test_failure_log_omits_the_option_list(caplog):
    caplog.set_level(logging.INFO)
    i495_route("Not A Real Place", "Route 267")
    assert "i495_route miss" in caplog.text
    # An unrelated valid_options entry must not leak into the audit line.
    assert "Interstate 66" not in caplog.text
