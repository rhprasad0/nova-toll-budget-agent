"""Tests for i95_route.

Route resolution is pure local JSON lookup, no network, no RDS. Pricing
hits RDS via _env_connect(), which every success-path test here replaces
with a FakeConnection (conftest.py) -- no real DB, no psycopg import.

i95_route now covers only the within-95/395 subset of oracles/i95.json
(cross-corridor trips, including every 495-anchored trip, are out of
scope -- see i495_route.py and docs/oracle-findings.md section 8), so
every trip resolves to exactly one leg. Real-data fixtures are verified
directly against that subset (see the inline values below).

Primary-query row tuples carry a trailing link_status, which must match the
row's own corridor's required "{DIR}_OPEN" (_REQUIRED_LINK_STATUS in
i95_route.py) or the availability gate in _price_i95_leg will reject them.
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

# (od_pair_id, corridor_name, zone_toll_rate_usd, interval_end_at, link_status)
_US1_TO_EDSALL_ROW = (
    1132,
    "I-95-NB",
    Decimal("7.20"),
    _PRICED_AS_OF,
    "NORTHBOUND_OPEN",
)
_EDSALL_TO_SEMINARY_ROW = (
    1266,
    "I-95-NB",
    Decimal("2.10"),
    _PRICED_AS_OF,
    "NORTHBOUND_OPEN",
)


def test_single_leg_lookup(monkeypatch):
    monkeypatch.setattr(i95_mod, "_env_connect", _connect_returning(_US1_TO_EDSALL_ROW))
    result = i95_route("US-1", "I-395 Near Edsall Road")
    assert result["direction"] == "Northbound"
    assert result["entry"] == {"node_id": "210NO", "label": "US-1"}
    assert result["legs"] == [
        {
            "od_pair_id": 1132,
            "price_usd": "7.20",
            "corridor_name": "I-95-NB",
            "priced_as_of": _PRICED_AS_OF.isoformat(),
        }
    ]
    assert result["total_usd"] == "7.20"


def test_no_price_anywhere_is_a_hard_error(monkeypatch):
    monkeypatch.setattr(i95_mod, "_env_connect", _connect_returning(None))
    result = i95_route("US-1", "I-395 Near Edsall Road")
    assert "error" in result
    assert result["valid_options"] == []
    assert "1132" in result["error"]
    assert "legs" not in result


def test_unrecognized_corridor_name_is_a_hard_error(monkeypatch):
    bad_row = (1132, "I-395-NEW-EXTENSION", Decimal("7.20"), _PRICED_AS_OF, "OPEN")
    monkeypatch.setattr(i95_mod, "_env_connect", _connect_returning(bad_row))
    result = i95_route("US-1", "I-395 Near Edsall Road")
    assert "error" in result
    assert "I-395-NEW-EXTENSION" in result["error"]
    assert "1132" in result["error"]


def test_closed_primary_row_is_a_hard_error(monkeypatch):
    # Reproduces the reported bug live: od_pair_id 1151 ("TURKEYCOCK TO
    # US-1", southbound, real corridor I-95-SB) is currently CLOSED in RDS,
    # and used to still price at $6.75.
    closed_row = (1151, "I-95-SB", Decimal("6.75"), _PRICED_AS_OF, "CLOSED")
    monkeypatch.setattr(i95_mod, "_env_connect", _connect_returning(closed_row))
    result = i95_route("I-395 Near Edsall Road", "US-1")
    assert "error" in result
    assert result["valid_options"] == []
    assert "1151" in result["error"]
    assert "CLOSED" in result["error"]
    assert "legs" not in result


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
        i95_mod, "_env_connect", _connect_returning(wrong_direction_row)
    )
    result = i95_route("I-395 Near Edsall Road", "US-1")
    assert "error" in result
    assert "1151" in result["error"]


def test_invalid_at_time_is_a_hard_error_before_any_db_call(monkeypatch):
    def env_connect():
        raise AssertionError("must not connect to the DB for a malformed at_time")

    monkeypatch.setattr(i95_mod, "_env_connect", env_connect)
    result = i95_route("US-1", "I-395 Near Edsall Road", at_time="garbage")
    assert "error" in result
    assert result["valid_options"] == []
    assert "garbage" in result["error"]


def test_label_lookup_is_case_insensitive(monkeypatch):
    monkeypatch.setattr(i95_mod, "_env_connect", _connect_returning(_US1_TO_EDSALL_ROW))
    result = i95_route("us-1", "i-395 near edsall road")
    assert result["legs"][0]["od_pair_id"] == 1132


def test_node_id_fallback_matches_label_lookup(monkeypatch):
    def env_connect():
        return FakeConnection([_US1_TO_EDSALL_ROW])

    monkeypatch.setattr(i95_mod, "_env_connect", env_connect)
    by_id = i95_route("210NO", "201ND")
    by_label = i95_route("US-1", "I-395 Near Edsall Road")
    # origin/destination echo the caller's raw input, so they legitimately
    # differ between the two forms -- everything resolved must match.
    for key in ("direction", "entry", "exit", "legs", "total_usd"):
        assert by_id[key] == by_label[key]


def test_unknown_origin_returns_only_origin_capable_labels():
    result = i95_route("Not A Real Place", "Seminary Road")
    assert "error" in result
    # Entry-only ramp -- must appear as a suggestable origin.
    assert "Heller Road" in result["valid_options"]
    # Exit-only ramp -- suggesting it as an origin would guarantee a second
    # dead-end miss.
    assert "I-95 Near Backlick Road" not in result["valid_options"]


def test_unknown_destination_returns_only_destination_capable_labels():
    result = i95_route("US-1", "Not A Real Place")
    assert "error" in result
    # Exit-only ramp -- must appear as a suggestable destination.
    assert "I-95 Near Backlick Road" in result["valid_options"]
    # Entry-only ramp -- suggesting it as a destination would guarantee a
    # second dead-end miss.
    assert "Heller Road" not in result["valid_options"]


def test_known_but_unconnected_pair_returns_reachable_only():
    result = i95_route("US-1", "Courthouse Road/Route 630")
    assert "error" in result
    assert "Courthouse Road/Route 630" not in result["valid_options"]
    assert len(result["valid_options"]) == 9


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


def test_label_shared_by_multiple_node_ids_still_resolves_unambiguously(monkeypatch):
    # "I-395 Near Edsall Road" maps to 4 distinct node ids in the real
    # oracle (entries and exits, both directions); the (entry_label,
    # exit_label) pair is still unique.
    monkeypatch.setattr(
        i95_mod, "_env_connect", _connect_returning(_EDSALL_TO_SEMINARY_ROW)
    )
    result = i95_route("I-395 Near Edsall Road", "Seminary Road")
    assert result["entry"]["node_id"] == "221NO"
    assert result["legs"][0]["od_pair_id"] == 1266


def test_tool_spec_matches_signature():
    assert i95_route.tool_spec["name"] == "i95_route"
    assert set(i95_route.tool_spec["inputSchema"]["json"]["required"]) == {
        "origin",
        "destination",
    }


def test_logs_successful_lookup(monkeypatch, caplog):
    monkeypatch.setattr(i95_mod, "_env_connect", _connect_returning(_US1_TO_EDSALL_ROW))
    caplog.set_level(logging.INFO)
    i95_route("US-1", "I-395 Near Edsall Road")
    assert "i95_route ok" in caplog.text
    assert "1132" in caplog.text


def test_failure_log_omits_the_option_list(caplog):
    caplog.set_level(logging.INFO)
    i95_route("Not A Real Place", "Seminary Road")
    assert "i95_route miss" in caplog.text
    # An unrelated valid_options entry must not leak into the audit line.
    assert "Heller Road" not in caplog.text
