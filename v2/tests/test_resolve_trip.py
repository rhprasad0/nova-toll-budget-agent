"""Deterministic place-to-point resolution over the frozen training catalog."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from agent_tools import resolve_trip
from agent_tools.route_pairs import REACHABLE_PAIRS
from eval import golden

TRAINING = golden.V2 / "eval/active/training"
CATALOG = json.loads((TRAINING / "prompt-points.json").read_text())


def test_route_pairs_module_matches_the_oracle_graph() -> None:
    from scripts.write_route_pairs import TARGET, reachable_pairs, render

    pairs = reachable_pairs()
    assert len(pairs) == 2853 == len(REACHABLE_PAIRS)
    assert frozenset(pairs) == REACHABLE_PAIRS
    assert Path(TARGET).read_text() == render()


@pytest.mark.parametrize(
    ("origin", "destination", "facility", "expected"),
    [
        # Cross-facility Greenway to Dulles Toll Road trip, named facility Greenway.
        (
            "Exit 2 - Battlefield Pkwy",
            "Exit 13 - SR 828 (Wiehle Ave)",
            "greenway",
            ("greenway:2A:entry:EB", "dtr:13:exit:EB"),
        ),
        # Approach variants: the northbound Edsall exit, not the southbound one.
        (
            "I-495 EB / I-95 NB",
            "I-395 Near Edsall Road",
            "i95",
            ("i95:202NO", "i95:201ND"),
        ),
        (
            "Pentagon/Eads Street",
            "I-395 Near Edsall Road",
            "i95",
            ("i95:2233SO", "i95:227SD"),
        ),
        # Return leg: same places swapped, different source codes.
        ("Seminary Road", "US-1", None, ("i95:226SO", "i95:210SD")),
        # Punctuation separates the I-66 label from the I-495 label.
        (
            "Route 7 - Leesburg Pike",
            "Exit 75 - Pentagon/Alexandria",
            None,
            ("i66:4:entry:EB", "i66:15:exit:EB"),
        ),
        # A named road is searched first, so a road alias does not cross facilities.
        ("Route 7", "Washington Blvd", "i66", ("i66:4:entry:EB", "i66:11:exit:EB")),
        # Exact label beats a neighbour's alias.
        (
            "Braddock Road",
            "Route 267 (from I-495 northbound or I-95/I-395 northbound)",
            "i495",
            ("i495:190NO", "i495:182ND"),
        ),
        # Word-order and airport aliases.
        (
            "Franconia-Springfield Parkway/Route 289",
            "Westpark Drive",
            None,
            ("i95:206NO", "i495:185ND"),
        ),
        ("Reagan Airport", "Westpark Drive", None, ("airport_dca", "i495:1859ND")),
    ],
)
def test_resolves_one_point_pair(
    origin: str,
    destination: str,
    facility: resolve_trip.Facility | None,
    expected: tuple[str, str],
) -> None:
    result = resolve_trip.resolve(CATALOG, origin, destination, facility)
    assert result["status"] == "resolved", result
    assert (result["origin_point_id"], result["destination_point_id"]) == expected
    assert result["origin_label"] and result["destination_label"]


def test_ambiguity_not_found_wrong_role_and_no_route_are_reported() -> None:
    for origin, destination in (
        ("Tysons", "Pentagon"),
        ("Springfield-Franconia", "Westpark Drive"),
    ):
        ambiguous = resolve_trip.resolve(CATALOG, origin, destination)
        assert ambiguous["status"] == "ambiguous", ambiguous
    assert 1 < len(ambiguous["candidates"]) <= resolve_trip._MAX_CANDIDATES
    assert resolve_trip.resolve(CATALOG, "Baltimore", "Westpark Drive") == {
        "status": "not_found",
        "places": ["Baltimore"],
    }
    wrong_role = resolve_trip.resolve(
        CATALOG, "Exit 2B - Compass Creek Pkwy", "Exit 6 - SR 772 (Ryan Rd)"
    )
    assert wrong_role["status"] == "wrong_role"
    assert [m["point_id"] for m in wrong_role["origin_matches"]] == [
        "greenway:2B:exit:WB"
    ]
    assert (
        resolve_trip.resolve(CATALOG, "Sycamore St", "Route 7 - Leesburg Pike", "i66")[
            "status"
        ]
        == "no_route"
    )


def test_every_training_fixture_leg_resolves_from_its_labels() -> None:
    """Fixture legs are the ground truth the resolver must reproduce."""
    labels = {point["point_id"]: point["label"] for point in CATALOG}
    for case in golden.load_cases(TRAINING):
        for step in case.steps:
            fixture = golden.load_fixture(step.fixture, TRAINING)
            legs = (
                [fixture.input["outbound"], fixture.input["return"]]
                if "outbound" in fixture.input
                else [fixture.input]
            )
            for leg in legs:
                origin, destination = (
                    str(leg["origin_point_id"]),
                    str(leg["destination_point_id"]),
                )
                if (origin, destination) not in REACHABLE_PAIRS:
                    continue  # the deliberate wrong-role validation call
                result = resolve_trip.resolve(
                    CATALOG, labels[origin], labels[destination]
                )
                assert result["status"] == "resolved", (case.id, leg, result)
                assert (result["origin_point_id"], result["destination_point_id"]) == (
                    origin,
                    destination,
                ), (case.id, result)


def test_tool_returns_recorder_shaped_results() -> None:
    tool = resolve_trip.make_resolve_trip_tool(CATALOG)
    assert tool.tool_spec["name"] == "resolve_trip"
    assert tool.tool_spec["inputSchema"]["json"]["additionalProperties"] is False

    class Context:
        def __init__(self, data: dict[str, Any]) -> None:
            self.tool_use = {"toolUseId": "t1", "name": "resolve_trip", "input": data}

    good = tool._tool_func(  # pyright: ignore[reportAttributeAccessIssue]
        tool_context=Context(
            {
                "origin": "Exit 10 - SR 657",
                "destination": "Exit 11 - SR 286 (Fairfax County Pkwy)",
            }
        )
    )
    assert good["status"] == "success"
    assert good["content"][0]["json"]["destination_point_id"] == "dtr:11:exit:EB"
    bad = tool._tool_func(  # pyright: ignore[reportAttributeAccessIssue]
        tool_context=Context({"origin": "", "destination": "x", "facility": "i99"})
    )
    assert bad["status"] == "error"
