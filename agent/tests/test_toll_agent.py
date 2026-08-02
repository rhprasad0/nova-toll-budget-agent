"""Prompt-content and request-shape assertions only -- no AWS calls/network."""

import hashlib
import json
import re
from collections import deque
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from strands.models.openai_responses import OpenAIResponsesModel

from agent import toll_agent as toll_agent_module
from agent.toll_agent import (
    _DIRECT_PAIR_ORACLES,
    _LOCATION_ALIASES,
    _PRICED_LOCATION_ORACLE_JSON,
    NETWORK_TRANSFERS,
    build_agent,
    build_system_prompt,
    plan_toll_route,
)
from agent_tools.dulles_route import _lookup as _dulles_lookup
from agent_tools.dulles_route import dulles_route
from agent_tools.i66_route import _lookup as _i66_lookup
from agent_tools.i66_route import i66_route
from agent_tools.i95_route import _lookup as _i95_lookup
from agent_tools.i95_route import i95_junction_leg, i95_route
from agent_tools.i495_route import _lookup as _i495_lookup
from agent_tools.i495_route import i495_route
from scripts.check_agent_contract_versions import validate_manifest_update

_DULLES_CORRIDORS = {"dulles_toll_road", "dulles_greenway"}
_CONTRACT_MANIFEST_PATH = Path(__file__).resolve().parents[1] / "contract-manifest.json"
_SEMVER = re.compile(r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)")
_LOOKUPS = {
    "i95": _i95_lookup,
    "i495": _i495_lookup,
    "i66_itb": _i66_lookup,
}


def _contract_manifest():
    return json.loads(_CONTRACT_MANIFEST_PATH.read_text())


def _sha256(value):
    return hashlib.sha256(value.encode()).hexdigest()


def _same_location(corridor, query, node_id):
    nodes, _ = _DIRECT_PAIR_ORACLES[corridor]
    return query == node_id or (
        node_id in nodes and nodes[node_id]["label"].casefold() == query.casefold()
    )


def _can_price(origin_corridor, origin, destination_corridor, destination):
    if {origin_corridor, destination_corridor} <= _DULLES_CORRIDORS:
        return "error" not in _dulles_lookup(origin, destination)
    return origin_corridor == destination_corridor and "error" not in _LOOKUPS[
        origin_corridor
    ](origin, destination)


def _reference_reachable(origin_corridor, origin, destination_corridor, destination):
    frontier = deque([(origin_corridor, origin)])
    visited = {(origin_corridor, origin)}
    while frontier:
        corridor, point = frontier.popleft()
        if (
            corridor == destination_corridor
            and _same_location(corridor, destination, point)
        ) or _can_price(corridor, point, destination_corridor, destination):
            return True
        if corridor == "i95" and destination_corridor != "i95":
            state = ("i495", "191NO")
            if state not in visited:
                visited.add(state)
                frontier.append(state)
            continue
        if corridor == "i495" and destination_corridor == "i95":
            return True
        for transfer in NETWORK_TRANSFERS:
            source = transfer["from"]
            if not (
                (
                    corridor == source["corridor"]
                    and _same_location(corridor, point, source["node_id"])
                )
                or _can_price(corridor, point, source["corridor"], source["node_id"])
            ):
                continue
            target = transfer["to"]
            state = (target["corridor"], target["node_id"])
            if state not in visited:
                visited.add(state)
                frontier.append(state)
    return False


def _assert_plan_is_continuous(
    origin_corridor, origin, destination_corridor, destination, plan
):
    corridor, point = origin_corridor, origin
    for index, step in enumerate(plan["steps"]):
        if step["kind"] == "priced":
            assert (step["corridor"], step["origin"]) == (corridor, point)
            if corridor in _DULLES_CORRIDORS:
                result = _dulles_lookup(step["origin"], step["destination"])
                assert "error" not in result
                corridor, pair = result["legs"][-1]
                point = pair["exit"]
            else:
                result = _LOOKUPS[corridor](step["origin"], step["destination"])
                assert "error" not in result
                point = result["exit"]["node_id"]
        elif step["kind"] == "junction":
            if step["movement"] == "i95_to_i495":
                assert corridor == "i95"
                assert step["location"] == point
                corridor, point = "i495", "191NO"
            else:
                assert corridor == "i495"
                corridor, point = "i95", destination
        elif step["kind"] == "unpriced":
            continue
        else:
            transfers = [
                transfer
                for transfer in NETWORK_TRANSFERS
                if transfer["connector"] == step["label"]
                and transfer["from"]["corridor"] == corridor
                and _same_location(corridor, point, transfer["from"]["node_id"])
            ]
            if len(transfers) > 1:
                targets = {
                    (transfer["to"]["corridor"], transfer["to"]["node_id"])
                    for transfer in transfers
                }
                if len(targets) == 1 or index == len(plan["steps"]) - 1:
                    transfers = transfers[:1]
                else:
                    next_step = plan["steps"][index + 1]
                    transfers = [
                        transfer
                        for transfer in transfers
                        if next_step.get("corridor") == transfer["to"]["corridor"]
                        and _same_location(
                            transfer["to"]["corridor"],
                            next_step.get("origin"),
                            transfer["to"]["node_id"],
                        )
                    ]
            assert len(transfers) == 1
            target = transfers[0]["to"]
            corridor, point = target["corridor"], target["node_id"]
    if (
        destination_corridor == "i495"
        and plan["steps"]
        and any(step.get("kind") == "junction" for step in plan["steps"])
        and plan["steps"][-1].get("kind") == "unpriced"
    ):
        return
    assert corridor == destination_corridor or (
        {corridor, destination_corridor} <= _DULLES_CORRIDORS
        and _same_location(corridor, destination, point)
    )
    assert _same_location(corridor, destination, point)


def test_system_prompt_contains_i95_i495_junction():
    prompt = build_system_prompt()
    assert "Edsall" in prompt
    assert "Franconia-Springfield Parkway" in prompt
    assert "I-495 Near Braddock Road" in prompt
    assert "unpriced junction" in prompt.casefold()


def test_system_prompt_describes_curated_network_transfers():
    prompt = build_system_prompt()
    assert '"connector": "I-66/I-495 interchange"' in prompt
    assert '"connector": "Dulles Airport Access Highway"' in prompt
    assert '"connector": "I-495/Route 267 interchange"' in prompt
    assert "explicitly labeled curated connector" in prompt
    assert "Do not infer a reverse edge" in prompt
    assert "Dulles Connector Road" not in prompt
    assert "explicitly call it a Route 267 detour" in prompt
    assert "never describe it as a direct I-66/I-495 connection" in prompt
    assert "Route 267 detour; not a direct I-66/I-495" in prompt
    assert "Copy the planner result's `at_time` unchanged" in prompt
    assert "Resolve from travel direction and endpoint role" in prompt
    assert "call each step exactly once" in prompt
    assert "without asking the user to confirm it" in prompt


def test_network_transfers_have_directed_entry_and_exit_roles():
    oracle_dir = Path(__file__).resolve().parents[2] / "oracles"
    filenames = {
        "i95": "i95.json",
        "i495": "i95.json",
        "i66_itb": "i66.json",
        "dulles_toll_road": "dulles_toll_road.json",
    }
    for transfer in NETWORK_TRANSFERS:
        source = transfer["from"]
        target = transfer["to"]
        source_oracle = json.loads(
            (oracle_dir / filenames[source["corridor"]]).read_text()
        )
        target_oracle = json.loads(
            (oracle_dir / filenames[target["corridor"]]).read_text()
        )
        assert source_oracle["nodes"][source["node_id"]]["label"] == source["exit"]
        assert target_oracle["nodes"][target["node_id"]]["label"] == target["entry"]
        assert any(pair["exit"] == source["node_id"] for pair in source_oracle["pairs"])
        assert any(
            pair["entry"] == target["node_id"] for pair in target_oracle["pairs"]
        )


@pytest.mark.parametrize(
    (
        "origin_corridor",
        "origin",
        "destination_corridor",
        "destination",
        "expected",
        "routing_note",
    ),
    [
        (
            "i66_itb",
            "Lee Highway - Scott Street",
            "i495",
            "Braddock Road",
            [
                ("priced", "i66_itb", "Lee Highway - Scott Street", "5"),
                ("connector", "I-66/I-495 interchange"),
                ("priced", "i495", "187SO", "Braddock Road"),
            ],
            None,
        ),
        (
            "i495",
            "Braddock Road",
            "i66_itb",
            "Westmoreland St",
            [
                ("priced", "i495", "Braddock Road", "187ND"),
                ("connector", "I-66/I-495 interchange"),
                ("priced", "i66_itb", "3", "Westmoreland St"),
            ],
            None,
        ),
        (
            "i66_itb",
            "Lee Highway - Scott Street",
            "i495",
            "495 Express Lanes End/George Wash. Mem. Pkwy.",
            [
                ("priced", "i66_itb", "Lee Highway - Scott Street", "6"),
                ("connector", "Dulles Airport Access Highway"),
                ("connector", "I-495/Route 267 interchange"),
                (
                    "priced",
                    "i495",
                    "182NO",
                    "495 Express Lanes End/George Wash. Mem. Pkwy.",
                ),
            ],
            "Route 267 detour; not a direct I-66/I-495 connection",
        ),
        (
            "i495",
            "495 Express Lanes Start/Georg Wash. Mem. Pkwy.",
            "i66_itb",
            "Westmoreland St",
            [
                (
                    "priced",
                    "i495",
                    "495 Express Lanes Start/Georg Wash. Mem. Pkwy.",
                    "182SD",
                ),
                ("connector", "I-495/Route 267 interchange"),
                ("connector", "Dulles Airport Access Highway"),
                ("priced", "i66_itb", "6", "Westmoreland St"),
            ],
            "Route 267 detour; not a direct I-66/I-495 connection",
        ),
    ],
    ids=(
        "i66-west-to-i495-south-direct",
        "i495-north-to-i66-east-direct",
        "i66-west-to-i495-north-route-267-detour",
        "i495-south-to-i66-east-route-267-detour",
    ),
)
def test_planner_covers_every_i66_i495_direction(
    origin_corridor,
    origin,
    destination_corridor,
    destination,
    expected,
    routing_note,
):
    plan = plan_toll_route(origin_corridor, origin, destination_corridor, destination)

    actual = []
    for step in plan["steps"]:
        if step["kind"] == "priced":
            actual.append(
                (
                    "priced",
                    step["corridor"],
                    step["origin"],
                    step["destination"],
                )
            )
        else:
            actual.append((step["kind"], step["label"]))
    assert actual == expected
    assert plan.get("routing_note") == routing_note


def test_planner_defaults_to_one_timezone_aware_timestamp():
    plan = plan_toll_route(
        "i66_itb", "Lee Highway - Scott Street", "i495", "Braddock Road"
    )

    assert datetime.fromisoformat(plan["at_time"]).tzinfo is not None


def test_planner_preserves_an_explicit_historical_timestamp():
    at_time = "2026-07-30T12:34:56-04:00"

    plan = plan_toll_route(
        "i66_itb",
        "Lee Highway - Scott Street",
        "i495",
        "Braddock Road",
        at_time,
    )

    assert plan["at_time"] == at_time


def test_planner_rejects_a_malformed_timestamp_before_planning():
    plan = plan_toll_route(
        "i66_itb",
        "Lee Highway - Scott Street",
        "i495",
        "Braddock Road",
        "not-a-time",
    )

    assert plan.keys() == {"error"}
    assert plan["error"].startswith("invalid at_time 'not-a-time':")


@pytest.mark.parametrize(
    ("origin_corridor", "origin", "destination_corridor", "destination", "boundary"),
    [
        (
            "dulles_toll_road",
            "Exit 12 - SR 602 (Reston Pkwy)",
            "i495",
            "Braddock Road",
            ("1819", "182SO"),
        ),
        (
            "dulles_toll_road",
            "Exit 12 - SR 602 (Reston Pkwy)",
            "i495",
            "495 Express Lanes End/George Wash. Mem. Pkwy.",
            ("1819", "182NO"),
        ),
        (
            "i495",
            "Braddock Road",
            "dulles_toll_road",
            "Exit 12 - SR 602 (Reston Pkwy)",
            ("182ND", "1819"),
        ),
        (
            "i495",
            "495 Express Lanes Start/Georg Wash. Mem. Pkwy.",
            "dulles_toll_road",
            "Exit 12 - SR 602 (Reston Pkwy)",
            ("182SD", "1819"),
        ),
    ],
    ids=(
        "dulles-east-to-i495-south",
        "dulles-east-to-i495-north",
        "i495-north-to-dulles-west",
        "i495-south-to-dulles-west",
    ),
)
def test_planner_covers_every_dulles_i495_direction(
    origin_corridor, origin, destination_corridor, destination, boundary
):
    plan = plan_toll_route(origin_corridor, origin, destination_corridor, destination)

    assert [step["kind"] for step in plan["steps"]] == [
        "priced",
        "connector",
        "priced",
    ]
    assert plan["steps"][1] == {
        "kind": "connector",
        "label": "I-495/Route 267 interchange",
        "price_usd": "0.00",
    }
    first, last = plan["steps"][0], plan["steps"][-1]
    assert first["destination"] == boundary[0]
    assert last["origin"] == boundary[1]


def test_planner_uses_unpriced_directional_i95_i495_junction_both_ways():
    outbound = plan_toll_route("i95", "US-1", "i495", "Westpark Drive")
    assert outbound["steps"] == [
        {
            "kind": "junction",
            "tool": "i95_junction_leg",
            "movement": "i95_to_i495",
            "location": "US-1",
            "i495_boundary": {
                "label": "I-495 Near Braddock Road",
                "node_id": "191NO",
            },
            "pricing": "unpriced between the selected 95 boundary and Braddock",
        },
        {
            "kind": "priced",
            "corridor": "i495",
            "tool": "i495_route",
            "origin": "191NO",
            "destination": "Westpark Drive",
        },
    ]

    inbound = plan_toll_route("i495", "Westpark Drive", "i95", "US-1")
    assert inbound["steps"] == [
        {
            "kind": "priced",
            "corridor": "i495",
            "tool": "i495_route",
            "origin": "Westpark Drive",
            "destination": "191SD",
        },
        {
            "kind": "junction",
            "tool": "i95_junction_leg",
            "movement": "i495_to_i95",
            "location": "US-1",
            "i495_boundary": {
                "label": "I-495 Near Braddock Road",
                "node_id": "191SD",
            },
            "pricing": "unpriced between the selected 95 boundary and Braddock",
        },
    ]


def test_planner_omits_495_price_for_an_endpoint_inside_the_gap():
    plan = plan_toll_route("i95", "US-1", "i495", "I-495/I-95 Near Van Dorn Street")
    assert [step["kind"] for step in plan["steps"]] == ["junction", "unpriced"]
    assert "do not call i495_route" in plan["steps"][-1]["reason"]


def test_planner_uses_the_curated_i66_dulles_handoff():
    plan = plan_toll_route(
        "i66_itb",
        "Fairfax Drive",
        "dulles_toll_road",
        "Exit 12 - SR 602 (Reston Pkwy)",
    )
    assert plan["steps"] == [
        {
            "kind": "priced",
            "corridor": "i66_itb",
            "tool": "i66_route",
            "origin": "Fairfax Drive",
            "destination": "6",
        },
        {
            "kind": "connector",
            "label": "Dulles Airport Access Highway",
            "price_usd": "0.00",
        },
        {
            "kind": "priced",
            "corridor": "dulles_toll_road",
            "tool": "dulles_route",
            "origin": "1819",
            "destination": "Exit 12 - SR 602 (Reston Pkwy)",
        },
    ]


def test_planner_routes_leesburg_to_reagan_without_an_i66_leg():
    plan = plan_toll_route(
        "dulles_greenway",
        "Exit 1 - US 15/SR 7 (Leesburg Bypass)",
        "i95",
        "Pentagon/Eads Street",
    )
    assert plan["steps"] == [
        {
            "kind": "priced",
            "corridor": "dulles_greenway",
            "tool": "dulles_route",
            "origin": "Exit 1 - US 15/SR 7 (Leesburg Bypass)",
            "destination": "1819",
        },
        {
            "kind": "connector",
            "label": "I-495/Route 267 interchange",
            "price_usd": "0.00",
        },
        {
            "kind": "priced",
            "corridor": "i495",
            "tool": "i495_route",
            "origin": "182SO",
            "destination": "191SD",
        },
        {
            "kind": "junction",
            "tool": "i95_junction_leg",
            "movement": "i495_to_i95",
            "location": "Pentagon/Eads Street",
            "i495_boundary": {
                "label": "I-495 Near Braddock Road",
                "node_id": "191SD",
            },
            "pricing": "unpriced between the selected 95 boundary and Braddock",
        },
    ]


def test_planner_refuses_an_unsupported_interchange_leg():
    plan = plan_toll_route(
        "dulles_toll_road",
        "Exit 18/19 - I-495 / SR 123 (Capital Beltway)",
        "i66_itb",
        "I-495 S",
    )
    assert plan == {
        "error": "no oracle-supported directed route connects "
        "'Exit 18/19 - I-495 / SR 123 (Capital Beltway)' on "
        "dulles_toll_road to 'I-495 S' on i66_itb"
    }


def test_planner_reaches_the_greenway_from_i495():
    plan = plan_toll_route(
        "i495",
        "Westpark Drive",
        "dulles_greenway",
        "Exit 3 - SR 653 (Shreve Mill Rd)",
    )
    assert [step["kind"] for step in plan["steps"]] == [
        "priced",
        "connector",
        "priced",
    ]
    assert plan["steps"][-1] == {
        "kind": "priced",
        "corridor": "dulles_toll_road",
        "tool": "dulles_route",
        "origin": "1819",
        "destination": "Exit 3 - SR 653 (Shreve Mill Rd)",
    }


def test_planner_uses_route_267_when_direct_i495_south_to_i66_east_is_unsupported():
    plan = plan_toll_route(
        "i495",
        "495 Express Lanes Start/Georg Wash. Mem. Pkwy.",
        "i66_itb",
        "Fairfax Drive",
    )
    assert [step["label"] for step in plan["steps"] if step["kind"] == "connector"] == [
        "I-495/Route 267 interchange",
        "Dulles Airport Access Highway",
    ]
    assert all(step.get("label") != "I-66/I-495 interchange" for step in plan["steps"])
    assert plan["routing_note"] == (
        "Route 267 detour; not a direct I-66/I-495 connection"
    )


def test_planner_matches_exhaustive_directed_oracle_reachability():
    oracle = json.loads(_PRICED_LOCATION_ORACLE_JSON)
    checked = 0
    for origin_corridor, origin_data in oracle.items():
        for origin in (
            location["label"]
            for location in origin_data["locations"]
            if location["entry"]
        ):
            for destination_corridor, destination_data in oracle.items():
                for destination in (
                    location["label"]
                    for location in destination_data["locations"]
                    if location["exit"]
                ):
                    if (
                        origin_corridor == destination_corridor
                        and origin == destination
                    ):
                        continue
                    expected = _reference_reachable(
                        origin_corridor,
                        origin,
                        destination_corridor,
                        destination,
                    )
                    plan = plan_toll_route(
                        origin_corridor,
                        origin,
                        destination_corridor,
                        destination,
                    )
                    assert ("error" not in plan) is expected, (
                        origin_corridor,
                        origin,
                        destination_corridor,
                        destination,
                        plan,
                    )
                    if expected:
                        _assert_plan_is_continuous(
                            origin_corridor,
                            origin,
                            destination_corridor,
                            destination,
                            plan,
                        )
                    checked += 1
    assert checked > 0


def test_system_prompt_states_the_overshoot_anti_example():
    prompt = build_system_prompt()
    assert "Washington D.C." in prompt
    assert "I-495 Near Braddock Road" in prompt
    assert "NOT evidence the leg boundary is correct" in prompt
    assert "assign it $0.00" in prompt
    assert "**Known segment prices**" in prompt
    assert "**Unpriced junction**" in prompt
    assert "**Complete price unavailable**" in prompt
    assert "Never calculate a subtotal or complete total" in prompt
    assert "requires exactly one" in prompt
    assert "Never skip it" in prompt


def test_system_prompt_embeds_only_priced_location_labels():
    prompt = build_system_prompt()
    assert '"i95"' in prompt
    assert '"i495"' in prompt
    assert '"i66_itb"' in prompt
    assert '"dulles_toll_road"' in prompt
    assert '"dulles_greenway"' in prompt
    assert "Vaden Drive" not in prompt


def test_system_prompt_refuses_unmatched_or_uncovered_locations():
    prompt = build_system_prompt()
    assert "Match vague, partial, or misspelled locations" in prompt
    assert "ask a concise clarifying question instead of guessing" in prompt
    assert "no clear match in the priced location oracle" in prompt
    assert "Never substitute a nearby listed road or ramp" in prompt
    assert "I-66 Outside the Beltway" in prompt


def test_location_aliases_only_point_to_priced_labels():
    prompt = build_system_prompt()
    priced_labels = {
        location["label"]
        for corridor in json.loads(_PRICED_LOCATION_ORACLE_JSON).values()
        for location in corridor["locations"]
    }
    assert "Tysons" in prompt
    assert "Gainesville" not in _LOCATION_ALIASES
    assert _LOCATION_ALIASES["Dulles Airport"] == [
        "Route 28 (Dulles Toll Road / Dulles Greenway)"
    ]
    assert {
        label for labels in _LOCATION_ALIASES.values() for label in labels
    } <= priced_labels


def test_system_prompt_is_an_agent_sop():
    prompt = build_system_prompt()
    for heading in (
        "# Nova Toll Pricing Assistant",
        "## Overview",
        "## Parameters",
        "## Steps",
        "### 1. Resolve locations",
        "### 2. Plan the route",
        "### 3. Price each leg",
        "### 4. Report the result",
        "## Examples",
        "## Troubleshooting",
    ):
        assert heading in prompt
    assert "**Constraints for parameter acquisition:**" in prompt
    assert "**Constraints:**" in prompt
    assert "MUST NOT ask the user to supply an at_time when it was omitted" in prompt
    assert "relative or ambiguous at_time" in prompt
    assert prompt.count("### Example ") == 3
    assert "You MUST" in prompt


def test_system_prompt_has_no_unresolved_placeholders():
    prompt = build_system_prompt()
    assert re.findall(r"\{[A-Z_]+\}", prompt) == []


def test_system_prompt_requires_auditable_price_reporting():
    prompt = build_system_prompt()
    assert "**Route and fares**" in prompt
    assert "**Calculation**" in prompt
    assert "**Final price**" in prompt
    assert "VDOT observed at: <observed_at>" in prompt
    assert "exact decimal addition" in prompt
    assert "returned toll items" in prompt
    assert "Rate period: <rate_period>" in prompt
    assert "calculated Dulles total" in prompt
    assert "empty dulles_route tolls list means no toll applies" in prompt
    assert "private reasoning or narrate tool-call deliberation" in prompt


def test_system_prompt_suggests_general_purpose_lanes_when_i95_is_closed():
    prompt = build_system_prompt()
    assert "i95_route" in prompt and "link_status=CLOSED" in prompt
    assert "i95_junction_leg" in prompt and "closed lane" in prompt
    assert re.search(r"Suggest the\s+I-95 general-purpose lanes", prompt)
    assert re.search(
        r"Do not call a pricing\s+tool or quote a fare for those lanes", prompt
    )
    assert re.search(
        r"Continue pricing every remaining\s+planner-returned step", prompt
    )


def test_agent_contract_manifest_versions_are_semver():
    manifest = _contract_manifest()
    versions = {
        "system_prompt": toll_agent_module.SYSTEM_PROMPT_VERSION,
        "toolset": toll_agent_module.TOOLSET_VERSION,
    }

    for contract, version in versions.items():
        assert _SEMVER.fullmatch(version)
        assert manifest[contract]["current"] == version
        assert version in manifest[contract]["releases"]
        assert all(_SEMVER.fullmatch(v) for v in manifest[contract]["releases"])
        assert all(
            re.fullmatch(r"[0-9a-f]{64}", digest)
            for digest in manifest[contract]["releases"].values()
        )


def test_agent_contract_manifest_releases_are_append_only_and_monotonic():
    previous = _contract_manifest()
    rewritten = deepcopy(previous)
    rewritten["system_prompt"]["releases"]["1.0.0"] = "0" * 64
    with pytest.raises(ValueError, match=r"rewrites system_prompt release 1\.0\.0"):
        validate_manifest_update(previous, rewritten)

    advanced = deepcopy(previous)
    advanced["system_prompt"]["current"] = "1.2.0"
    advanced["system_prompt"]["releases"]["1.2.0"] = "0" * 64
    validate_manifest_update(previous, advanced)

    advanced["system_prompt"]["current"] = "1.0.0"
    with pytest.raises(ValueError, match=r"must advance beyond 1\.1\.0"):
        validate_manifest_update(previous, advanced)


def test_rendered_system_prompt_matches_its_versioned_digest():
    manifest = _contract_manifest()["system_prompt"]
    assert _sha256(build_system_prompt()) == manifest["releases"][manifest["current"]]


def test_registered_toolset_matches_its_versioned_digest():
    manifest = _contract_manifest()["toolset"]
    canonical_specs = json.dumps(
        [tool.tool_spec for tool in toll_agent_module._AGENT_TOOLS],
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    assert _sha256(canonical_specs) == manifest["releases"][manifest["current"]]


def test_agent_tool_specs_are_concise_and_preserve_their_contracts():
    expected = {
        "plan_toll_route": (
            plan_toll_route,
            {"origin_corridor", "origin", "destination_corridor", "destination"},
            ("cross-corridor", "ordered steps", "On error"),
        ),
        "i95_junction_leg": (
            i95_junction_leg,
            {"location", "movement"},
            ("junction", "pricing_status", "unavailable"),
        ),
        "i95_route": (
            i95_route,
            {"origin", "destination"},
            ("I-95/395", "total_usd", "Failure"),
        ),
        "i495_route": (
            i495_route,
            {"origin", "destination"},
            ("I-495", "total_usd", "Failure"),
        ),
        "i66_route": (
            i66_route,
            {"origin", "destination"},
            ("I-66", "total_usd", "Failure"),
        ),
        "dulles_route": (
            dulles_route,
            {"origin", "destination"},
            ("Route 28", "toll items", "Failure"),
        ),
    }
    for name, (tool, required, cues) in expected.items():
        spec = tool.tool_spec
        schema = spec["inputSchema"]["json"]

        assert spec["name"] == name
        assert set(schema["required"]) == required
        assert all(field["type"] == "string" for field in schema["properties"].values())
        assert len(spec["description"]) < 900
        assert all(cue in spec["description"] for cue in cues)
        assert "America/New_York" in schema["properties"]["at_time"]["description"]

    assert set(
        plan_toll_route.tool_spec["inputSchema"]["json"]["properties"][
            "origin_corridor"
        ]["enum"]
    ) == {
        "i95",
        "i495",
        "i66_itb",
        "dulles_toll_road",
        "dulles_greenway",
    }
    assert set(
        i95_junction_leg.tool_spec["inputSchema"]["json"]["properties"]["movement"][
            "enum"
        ]
    ) == {
        "i95_to_i495",
        "i495_to_i95",
    }


def test_agent_uses_direct_openai_luna_with_an_explicit_prompt_cache(monkeypatch):
    calls = []

    class Ssm:
        def get_parameter(self, **kwargs):
            calls.append(kwargs)
            return {"Parameter": {"Value": "test-openai-key"}}

    def client(service_name, *, region_name):
        assert service_name == "ssm"
        assert region_name == "us-east-1"
        return Ssm()

    monkeypatch.delenv("TOLLCHAT_MODEL_BACKEND", raising=False)
    monkeypatch.setattr(toll_agent_module.boto3, "client", client)
    agent = build_agent(
        trace_attributes={
            "tollchat.session_id": "test",
            "tollchat.system_prompt_version": "wrong",
            "tollchat.toolset_version": "wrong",
        }
    )
    assert isinstance(agent.model, OpenAIResponsesModel)
    assert agent.trace_attributes == {
        "tollchat.session_id": "test",
        "tollchat.system_prompt_version": toll_agent_module.SYSTEM_PROMPT_VERSION,
        "tollchat.toolset_version": toll_agent_module.TOOLSET_VERSION,
    }
    assert calls == [{"Name": "/nova-toll/openai_api_key", "WithDecryption": True}]
    assert agent.model.client_args == {"api_key": "test-openai-key"}

    request = agent.model._format_request(
        messages=[
            {"role": "user", "content": [{"text": "Price Dumfries to Westpark"}]}
        ],
        tool_specs=agent.tool_registry.get_all_tool_specs(),
        system_prompt=agent.system_prompt,
    )

    assert request["model"] == "gpt-5.6-luna"
    assert request["reasoning"] == {"effort": "low"}
    assert request["max_output_tokens"] == 2048
    assert request["prompt_cache_key"] == "tollchat-agent-v1"
    assert request["prompt_cache_options"] == {"mode": "explicit", "ttl": "30m"}
    assert request["store"] is True
    assert "temperature" not in request
    assert "instructions" not in request
    assert "test-openai-key" not in json.dumps(request)
    assert request["input"][0] == {
        "type": "message",
        "role": "developer",
        "content": [
            {
                "type": "input_text",
                "text": build_system_prompt(),
                "prompt_cache_breakpoint": {"mode": "explicit"},
            }
        ],
    }
    assert request["input"][1] == {
        "role": "user",
        "content": [{"type": "input_text", "text": "Price Dumfries to Westpark"}],
    }
    assert [tool["name"] for tool in request["tools"]] == [
        "plan_toll_route",
        "i95_junction_leg",
        "i95_route",
        "i495_route",
        "i66_route",
        "dulles_route",
    ]

    continued = agent.model._format_request(
        messages=[], model_state={"response_id": "resp_test"}
    )
    assert continued["previous_response_id"] == "resp_test"


def test_agent_reports_prompt_cache_reads_and_writes(monkeypatch):
    monkeypatch.setattr(toll_agent_module, "_load_openai_api_key", lambda: "test-key")
    model = toll_agent_module._build_model()
    chunk = model._format_chunk(
        {
            "chunk_type": "metadata",
            "data": SimpleNamespace(
                input_tokens=100,
                output_tokens=10,
                total_tokens=110,
                input_tokens_details=SimpleNamespace(
                    cached_tokens=80, cache_write_tokens=0
                ),
            ),
        }
    )

    assert chunk["metadata"]["usage"]["cacheReadInputTokens"] == 80
    assert chunk["metadata"]["usage"]["cacheWriteInputTokens"] == 0


def test_agent_keeps_the_bedrock_mantle_backend_ready(monkeypatch):
    monkeypatch.setenv("TOLLCHAT_MODEL_BACKEND", "bedrock-mantle")

    def fail_if_called():
        raise AssertionError("Bedrock Mantle must not read the OpenAI API key")

    monkeypatch.setattr(toll_agent_module, "_load_openai_api_key", fail_if_called)
    agent = build_agent()

    assert agent.model.get_config()["model_id"] == "openai.gpt-5.6-luna"
    assert agent.model.stateful is True
    assert agent.model.client_args == {}
    assert agent.model._bedrock_mantle_config == {"region": "us-east-1"}


def test_agent_rejects_an_unknown_model_backend(monkeypatch):
    monkeypatch.setenv("TOLLCHAT_MODEL_BACKEND", "surprise")

    with pytest.raises(ValueError, match="must be 'openai' or 'bedrock-mantle'"):
        build_agent()
