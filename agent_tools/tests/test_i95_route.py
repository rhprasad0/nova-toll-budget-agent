"""Tests for the behaviour unique to i95_route: the link_status
availability gate.

Everything i95_route shares with i66_route/i495_route -- resolution,
at_time handling, error envelopes, logging -- is covered once, table-driven,
in test_route_tools.py. Only the gate lives here, because i95 is the one
corridor whose lanes are reversible and whose feed publishes a real
open/closed signal (i495's never does; see i495_route.py's docstring).

Row tuples are (od_pair_id, corridor_name, rate, interval_end_at,
calculated_at, link_status).
"""

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import i95_route as i95_mod
import pytest
from conftest import FakeConnection
from conftest import connect_returning as _connect_returning
from i95_route import i95_route

_EASTERN = ZoneInfo("America/New_York")
_PRICED_AS_OF = datetime(2026, 7, 26, 14, 20, tzinfo=_EASTERN)
_OBSERVED_AT = datetime(2026, 7, 26, 14, 10, tzinfo=_EASTERN)
_EDSALL_TO_SEMINARY_ROW = (
    1266,
    "I-95-NB",
    Decimal("2.10"),
    _PRICED_AS_OF,
    _OBSERVED_AT,
    "NORTHBOUND_OPEN",
)


def test_unrecognized_corridor_name_is_a_hard_error(monkeypatch):
    bad_row = (
        1132,
        "I-395-NEW-EXTENSION",
        Decimal("7.20"),
        _PRICED_AS_OF,
        _OBSERVED_AT,
        "OPEN",
    )
    monkeypatch.setattr(i95_mod, "_env_connect", _connect_returning(bad_row))
    result = i95_route("US-1", "I-395 Near Edsall Road")
    assert "error" in result
    assert "I-395-NEW-EXTENSION" in result["error"]
    assert "1132" in result["error"]


@pytest.mark.parametrize(
    ("origin", "destination", "od_pair_id", "corridor_name", "link_status"),
    [
        ("US-1", "I-395 Near Edsall Road", 1132, "I-95-NB", "CLOSED"),
        ("I-395 Near Edsall Road", "US-1", 1151, "I-95-SB", "CLOSED"),
        (
            "US-1",
            "I-395 Near Edsall Road",
            1132,
            "I-95-NB",
            "NORTHBOUND_CLOSING",
        ),
    ],
)
def test_unavailable_primary_row_is_a_hard_error(
    monkeypatch, origin, destination, od_pair_id, corridor_name, link_status
):
    unavailable_row = (
        od_pair_id,
        corridor_name,
        Decimal("6.75"),
        _PRICED_AS_OF,
        _OBSERVED_AT,
        link_status,
    )
    monkeypatch.setattr(i95_mod, "_env_connect", _connect_returning(unavailable_row))
    result = i95_route(origin, destination)
    assert "error" in result
    assert result["valid_options"] == []
    assert str(od_pair_id) in result["error"]
    assert link_status in result["error"]
    assert "legs" not in result


def test_historical_northbound_closure_is_a_hard_error(monkeypatch):
    at_time = "2026-07-29T15:40:00-04:00"
    conn = FakeConnection(
        [
            (
                1132,
                "I-95-NB",
                Decimal("6.75"),
                datetime.fromisoformat(at_time),
                datetime.fromisoformat(at_time),
                "CLOSED",
            )
        ]
    )
    monkeypatch.setattr(i95_mod, "_env_connect", lambda: conn)

    result = i95_route("US-1", "I-395 Near Edsall Road", at_time=at_time)

    assert "error" in result
    assert result["valid_options"] == []
    assert "1132" in result["error"]
    assert "CLOSED" in result["error"]
    assert "legs" not in result
    sql, params = conn.cur.queries[0]
    assert "FROM trip_pricing_i95" in sql
    assert params is not None
    assert params["at_time"].isoformat() == at_time


def test_historical_southbound_closure_is_a_hard_error(monkeypatch):
    at_time = "2026-07-29T10:10:00-04:00"
    conn = FakeConnection(
        [
            (
                1151,
                "I-95-SB",
                Decimal("6.75"),
                datetime.fromisoformat(at_time),
                datetime.fromisoformat(at_time),
                "CLOSED",
            )
        ]
    )
    monkeypatch.setattr(i95_mod, "_env_connect", lambda: conn)

    result = i95_route("I-395 Near Edsall Road", "US-1", at_time=at_time)

    assert "error" in result
    assert result["valid_options"] == []
    assert "1151" in result["error"]
    assert "CLOSED" in result["error"]
    assert "legs" not in result
    sql, params = conn.cur.queries[0]
    assert "FROM trip_pricing_i95" in sql
    assert params is not None
    assert params["at_time"].isoformat() == at_time


def test_historical_both_lanes_closure_is_a_hard_error(monkeypatch):
    at_time = "2026-07-29T10:50:00-04:00"
    northbound_conn = FakeConnection(
        [
            (
                1132,
                "I-95-NB",
                Decimal("6.75"),
                datetime.fromisoformat(at_time),
                datetime.fromisoformat(at_time),
                "CLOSED",
            )
        ]
    )
    southbound_conn = FakeConnection(
        [
            (
                1151,
                "I-95-SB",
                Decimal("6.75"),
                datetime.fromisoformat(at_time),
                datetime.fromisoformat(at_time),
                "CLOSED",
            )
        ]
    )
    connections = iter((northbound_conn, southbound_conn))
    monkeypatch.setattr(i95_mod, "_env_connect", lambda: next(connections))

    northbound = i95_route("US-1", "I-395 Near Edsall Road", at_time=at_time)
    southbound = i95_route("I-395 Near Edsall Road", "US-1", at_time=at_time)

    for result, od_pair_id in ((northbound, 1132), (southbound, 1151)):
        assert "error" in result
        assert result["valid_options"] == []
        assert str(od_pair_id) in result["error"]
        assert "CLOSED" in result["error"]
        assert "legs" not in result
    for conn in (northbound_conn, southbound_conn):
        sql, params = conn.cur.queries[0]
        assert "FROM trip_pricing_i95" in sql
        assert params is not None
        assert params["at_time"].isoformat() == at_time


def test_wrong_direction_open_primary_row_is_a_hard_error(monkeypatch):
    # A real, valid *_OPEN status, but for the wrong direction of this
    # corridor -- pins the exact-match rule against a sloppy "OPEN in
    # status" implementation.
    wrong_direction_row = (
        1151,
        "I-95-SB",
        Decimal("6.75"),
        _PRICED_AS_OF,
        _OBSERVED_AT,
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
