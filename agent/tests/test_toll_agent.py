"""Prompt-content and request-shape assertions only -- no AWS calls/network.

Constructing ``BedrockModel`` creates a boto3 session but does not invoke
Bedrock, so these tests can verify cache-point placement locally. See
tests/test_toll_agent_live.py for the real end-to-end check.
"""

import json
import sys
from collections import deque
from pathlib import Path

import pytest
from strands.models import BedrockModel
from toll_agent import (
    _DIRECT_PAIR_ORACLES,
    _LOCATION_ALIASES,
    _PRICED_LOCATION_ORACLE_JSON,
    NETWORK_TRANSFERS,
    build_agent,
    build_system_prompt,
    plan_toll_route,
)

_DULLES_CORRIDORS = {"dulles_toll_road", "dulles_greenway"}
_dulles_lookup = sys.modules["dulles_route"]._lookup
_LOOKUPS = {
    "i95": sys.modules["i95_route"]._lookup,
    "i495": sys.modules["i495_route"]._lookup,
    "i66_itb": sys.modules["i66_route"]._lookup,
}


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
    ("origin_corridor", "origin", "destination_corridor", "destination", "expected"),
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
    origin_corridor, origin, destination_corridor, destination, expected
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


def test_system_prompt_uses_structured_claude_prompt_sections():
    prompt = build_system_prompt()
    for section in (
        "role",
        "tool_rules",
        "priced_location_oracle",
        "location_aliases",
        "routing_context",
        "network_transfers",
        "response_format",
        "examples",
    ):
        assert f"<{section}>" in prompt
        assert f"</{section}>" in prompt
    assert prompt.count("<example>") == 3


def test_system_prompt_requires_auditable_price_reporting():
    prompt = build_system_prompt()
    assert "**Route and fares**" in prompt
    assert "**Calculation**" in prompt
    assert "**Final price**" in prompt
    assert "VDOT observed at: <observed_at>" in prompt
    assert "exact decimal addition" in prompt
    assert "returned toll items" in prompt
    assert "calculated Dulles total" in prompt
    assert "empty dulles_route tolls list means no toll applies" in prompt
    assert "private reasoning or narrate tool-call deliberation" in prompt


def test_agent_caches_static_tools_and_system_prompt_for_five_minutes():
    agent = build_agent(trace_attributes={"tollchat.session_id": "test"})
    assert isinstance(agent.model, BedrockModel)
    assert agent.trace_attributes == {"tollchat.session_id": "test"}
    request = agent.model.format_request(
        messages=[
            {"role": "user", "content": [{"text": "Price Dumfries to Westpark"}]}
        ],
        tool_specs=agent.tool_registry.get_all_tool_specs(),
        system_prompt_content=agent.system_prompt_content,
    )

    assert request["system"] == [
        {"text": build_system_prompt()},
        {"cachePoint": {"type": "default", "ttl": "5m"}},
    ]
    assert request["toolConfig"]["tools"][-1] == {
        "cachePoint": {"type": "default", "ttl": "5m"}
    }
    assert [
        tool["toolSpec"]["name"] for tool in request["toolConfig"]["tools"][:-1]
    ] == [
        "plan_toll_route",
        "i95_junction_leg",
        "i95_route",
        "i495_route",
        "i66_route",
        "dulles_route",
    ]
