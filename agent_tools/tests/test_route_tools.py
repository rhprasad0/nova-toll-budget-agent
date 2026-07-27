"""Shared behaviour of the three RDS-backed route tools (i66_route,
i95_route, i495_route).

These tools differ only in which oracle subset they resolve against and how
they price a leg -- everything else runs through _oracle_route.run(), so it
is tested once here, table-driven over CASES, rather than in three
near-identical copies. Tool-specific behaviour keeps its own file:
test_i95_route.py (the link_status availability gate) and
test_dulles_route.py (fixed-toll, two facilities, composite legs).

Route resolution is pure local JSON lookup, no network, no RDS. Pricing hits
RDS via each module's _env_connect(), which every success-path test replaces
with a FakeConnection (conftest.py) -- no real DB, no psycopg import.

Every fixture value below is verified directly against the committed oracle
each tool loads.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import i66_route as i66_mod
import i95_route as i95_mod
import i495_route as i495_mod
import pytest
from conftest import FakeConnection, connect_returning as _connect_returning

_EASTERN = ZoneInfo("America/New_York")
_PRICED_AS_OF = datetime(2026, 7, 26, 14, 20, tzinfo=_EASTERN)


@dataclass(frozen=True)
class Case:
    """One tool's real-oracle fixtures. Field-for-field, the only things
    that ever differed between the three original test modules.
    """

    module: Any
    origin: str
    destination: str
    origin_id: str
    destination_id: str
    row: tuple  # the priced DB row for origin -> destination
    leg: dict  # the priced leg that row must produce
    entry: dict
    direction: str
    price_table: str
    # Substrings that must appear in a "no price found" error -- the leg key
    # the tool looked up, so the message names what actually missed.
    price_key_fragments: tuple[str, ...]
    # Entry-capable-only and exit-capable-only labels: each must be
    # suggestable for its own role and never for the other, or the caller's
    # next call is guaranteed to miss too.
    entry_only: str
    exit_only: str
    # A real, resolvable origin/destination pair with no direct trip between
    # them -- the "both labels exist, this trip doesn't" branch.
    unconnected_origin: str
    unconnected_destination: str
    unconnected_option_count: int
    unconnected_options: list[str] | None  # exact list where it's short enough to pin

    @property
    def tool(self):
        return getattr(self.module, self.module.__name__)

    @property
    def name(self) -> str:
        return self.module.__name__


CASES = [
    Case(
        module=i66_mod,
        origin="I-66 West",
        destination="Westmoreland St",
        origin_id="1",
        destination_id="10",
        # (start_zone_id, end_zone_id, corridor_name, rate, interval_end_at)
        row=(3100, 3110, "I-66-EB", Decimal("4.50"), _PRICED_AS_OF),
        leg={
            "start_zone_id": 3100,
            "end_zone_id": 3110,
            "price_usd": "4.50",
            "corridor_name": "I-66-EB",
            "priced_as_of": _PRICED_AS_OF.isoformat(),
        },
        entry={"node_id": "1", "label": "I-66 West"},
        direction="EB",
        price_table="trip_pricing_i66",
        price_key_fragments=("3100", "3110"),
        entry_only="I-495 N",
        exit_only="Westmoreland St",
        unconnected_origin="I-66 West",
        unconnected_destination="Glebe Road",
        unconnected_option_count=8,
        unconnected_options=[
            "Exit 73 - Rosslyn",
            "Exit 75 - Pentagon/Alexandria",
            "Fairfax Drive",
            "Lee Highway - Spout Run Parkway",
            "Route 7 - Leesburg Pike",
            "Washington",
            "Washington Blvd",
            "Westmoreland St",
        ],
    ),
    Case(
        module=i95_mod,
        origin="US-1",
        destination="I-395 Near Edsall Road",
        origin_id="210NO",
        destination_id="201ND",
        # (od_pair_id, corridor_name, rate, interval_end_at, link_status)
        row=(1132, "I-95-NB", Decimal("7.20"), _PRICED_AS_OF, "NORTHBOUND_OPEN"),
        leg={
            "od_pair_id": 1132,
            "price_usd": "7.20",
            "corridor_name": "I-95-NB",
            "priced_as_of": _PRICED_AS_OF.isoformat(),
        },
        entry={"node_id": "210NO", "label": "US-1"},
        direction="Northbound",
        price_table="trip_pricing_i95",
        price_key_fragments=("1132",),
        entry_only="Heller Road",
        exit_only="I-95 Near Backlick Road",
        unconnected_origin="US-1",
        unconnected_destination="Courthouse Road/Route 630",
        unconnected_option_count=9,
        unconnected_options=None,  # 9 ramp labels; the count is the useful pin
    ),
    Case(
        module=i495_mod,
        origin="Route 267",
        destination="495 Express Lanes End/George Wash. Mem. Pkwy.",
        origin_id="182NO",
        destination_id="181ND",
        # (od_pair_id, corridor_name, rate, interval_end_at)
        row=(1038, "I-495-NB", Decimal("2.60"), _PRICED_AS_OF),
        leg={
            "od_pair_id": 1038,
            "price_usd": "2.60",
            "corridor_name": "I-495-NB",
            "priced_as_of": _PRICED_AS_OF.isoformat(),
        },
        entry={"node_id": "182NO", "label": "Route 267"},
        direction="Northbound",
        price_table="trip_pricing_i95",
        price_key_fragments=("1038",),
        entry_only="495 Express Lanes Start/Georg Wash. Mem. Pkwy.",
        exit_only="495 Express Lanes End/George Wash. Mem. Pkwy.",
        # The entry-only ramp at one end never reaches the exit-only ramp at
        # the other -- verified against the real oracle.
        unconnected_origin="495 Express Lanes Start/Georg Wash. Mem. Pkwy.",
        unconnected_destination="495 Express Lanes End/George Wash. Mem. Pkwy.",
        unconnected_option_count=8,
        unconnected_options=[
            "Braddock Road",
            "Gallows Road",
            "I-495 Near Braddock Road",
            "I-495/I-95 Near Van Dorn Street",
            "Interstate 66",
            "Jones Branch Drive/Route 123",
            "Route 267",
            "Westpark Drive",
        ],
    ),
]

pytestmark = pytest.mark.parametrize("case", CASES, ids=lambda c: c.name)


def _priced(monkeypatch, case: Case) -> None:
    monkeypatch.setattr(case.module, "_env_connect", _connect_returning(case.row))


def test_single_leg_lookup(monkeypatch, case: Case):
    _priced(monkeypatch, case)
    result = case.tool(case.origin, case.destination)
    assert result["direction"] == case.direction
    assert result["entry"] == case.entry
    assert result["legs"] == [case.leg]
    assert result["total_usd"] == case.leg["price_usd"]
    assert "at_time" in result


def test_label_lookup_is_case_insensitive(monkeypatch, case: Case):
    _priced(monkeypatch, case)
    result = case.tool(case.origin.lower(), case.destination.lower())
    assert result["legs"] == [case.leg]


def test_node_id_fallback_matches_label_lookup(monkeypatch, case: Case):
    monkeypatch.setattr(case.module, "_env_connect", lambda: FakeConnection([case.row]))
    by_id = case.tool(case.origin_id, case.destination_id)
    by_label = case.tool(case.origin, case.destination)
    # origin/destination echo the caller's raw input, so they legitimately
    # differ between the two forms -- everything resolved must match.
    for key in ("direction", "entry", "exit", "legs", "total_usd"):
        assert by_id[key] == by_label[key]


def test_price_not_found_is_a_hard_error(monkeypatch, case: Case):
    monkeypatch.setattr(case.module, "_env_connect", _connect_returning(None))
    result = case.tool(case.origin, case.destination)
    assert "error" in result
    assert result["valid_options"] == []
    assert case.price_table in result["error"]
    for fragment in case.price_key_fragments:
        assert fragment in result["error"]
    assert "legs" not in result


def test_at_time_is_passed_through_and_echoed(monkeypatch, case: Case):
    _priced(monkeypatch, case)
    result = case.tool(
        case.origin, case.destination, at_time="2026-01-15T09:00:00-05:00"
    )
    assert result["at_time"] == "2026-01-15T09:00:00-05:00"


def test_invalid_at_time_is_a_hard_error_before_any_db_call(monkeypatch, case: Case):
    def env_connect():
        raise AssertionError("must not connect to the DB for a malformed at_time")

    monkeypatch.setattr(case.module, "_env_connect", env_connect)
    result = case.tool(case.origin, case.destination, at_time="not-a-timestamp")
    assert "error" in result
    assert result["valid_options"] == []
    assert "not-a-timestamp" in result["error"]


def test_unknown_origin_returns_only_origin_capable_labels(case: Case):
    result = case.tool("Not A Real Place", case.destination)
    assert "error" in result
    assert case.entry_only in result["valid_options"]
    # An exit-only ramp as a suggested origin would guarantee a second
    # dead-end miss on the caller's retry.
    assert case.exit_only not in result["valid_options"]


def test_unknown_destination_returns_only_destination_capable_labels(case: Case):
    result = case.tool(case.origin, "Not A Real Place")
    assert "error" in result
    assert case.exit_only in result["valid_options"]
    assert case.entry_only not in result["valid_options"]


def test_known_but_unconnected_pair_returns_reachable_only(case: Case):
    result = case.tool(case.unconnected_origin, case.unconnected_destination)
    assert "error" in result
    assert case.unconnected_destination not in result["valid_options"]
    assert len(result["valid_options"]) == case.unconnected_option_count
    if case.unconnected_options is not None:
        assert result["valid_options"] == case.unconnected_options


def test_ambiguous_match_is_guarded_with_synthetic_data(monkeypatch, case: Case):
    # Unreachable via any real oracle (every committed pair is unique on
    # (entry, exit)); hand-built to prove the guard fires if that invariant
    # ever breaks. Pairs carry every tool's leg key so one fixture covers
    # all three -- build_legs is never reached on the ambiguous branch.
    monkeypatch.setattr(
        case.module,
        "_NODES",
        {
            "a": {"label": "Origin"},
            "b": {"label": "Origin"},
            "c": {"label": "Dest"},
        },
    )
    monkeypatch.setattr(
        case.module,
        "_PAIRS",
        [
            {
                "direction": "EB",
                "entry": e,
                "exit": "c",
                "ods": [n],
                "start_zone": n,
                "end_zone": n + 1,
            }
            for n, e in ((1, "a"), (2, "b"))
        ],
    )
    monkeypatch.setattr(
        case.module, "_LABEL_INDEX", {"origin": ["a", "b"], "dest": ["c"]}
    )
    result = case.module._lookup("Origin", "Dest")
    assert "error" in result
    assert "ambiguous" in result["error"]


def test_tool_spec_matches_signature(case: Case):
    assert case.tool.tool_spec["name"] == case.name
    assert set(case.tool.tool_spec["inputSchema"]["json"]["required"]) == {
        "origin",
        "destination",
    }


def test_logs_successful_lookup(monkeypatch, caplog, case: Case):
    _priced(monkeypatch, case)
    caplog.set_level(logging.INFO)
    case.tool(case.origin, case.destination)
    assert f"{case.name} ok" in caplog.text
    assert case.leg["price_usd"] in caplog.text
    for fragment in case.price_key_fragments:
        assert fragment in caplog.text


def test_failure_log_omits_the_option_list(caplog, case: Case):
    caplog.set_level(logging.INFO)
    case.tool("Not A Real Place", case.destination)
    assert f"{case.name} miss" in caplog.text
    # entry_only is one of the valid_options entries on this failure -- it
    # must not leak into the audit line, which is noise, not signal.
    assert case.entry_only not in caplog.text
