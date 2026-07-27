"""Tests for the behaviour unique to i95_route: the link_status
availability gate.

Everything i95_route shares with i66_route/i495_route -- resolution,
at_time handling, error envelopes, logging -- is covered once, table-driven,
in test_route_tools.py. Only the gate lives here, because i95 is the one
corridor whose lanes are reversible and whose feed publishes a real
open/closed signal (i495's never does; see i495_route.py's docstring).

Row tuples are (od_pair_id, corridor_name, rate, interval_end_at,
link_status).
"""

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import i95_route as i95_mod
from conftest import connect_returning as _connect_returning
from i95_route import i95_route

_EASTERN = ZoneInfo("America/New_York")
_PRICED_AS_OF = datetime(2026, 7, 26, 14, 20, tzinfo=_EASTERN)
_EDSALL_TO_SEMINARY_ROW = (
    1266,
    "I-95-NB",
    Decimal("2.10"),
    _PRICED_AS_OF,
    "NORTHBOUND_OPEN",
)


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
