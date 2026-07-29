"""Prompt-content and request-shape assertions only -- no AWS calls/network.

Constructing ``BedrockModel`` creates a boto3 session but does not invoke
Bedrock, so these tests can verify cache-point placement locally. See
tests/test_toll_agent_live.py for the real end-to-end check.
"""

import json
import sys
from collections import deque
from pathlib import Path

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
    for step in plan["steps"]:
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
        else:
            transfers = [
                transfer
                for transfer in NETWORK_TRANSFERS
                if transfer["connector"] == step["label"]
                and transfer["from"]["corridor"] == corridor
                and _same_location(corridor, point, transfer["from"]["node_id"])
            ]
            assert len(transfers) == 1
            target = transfers[0]["to"]
            corridor, point = target["corridor"], target["node_id"]
    assert corridor == destination_corridor or (
        {corridor, destination_corridor} <= _DULLES_CORRIDORS
        and _same_location(corridor, destination, point)
    )
    assert _same_location(corridor, destination, point)


def test_system_prompt_contains_i95_i495_junction():
    prompt = build_system_prompt()
    assert "206ND" in prompt
    assert "Franconia-Springfield Parkway" in prompt
    assert "192NO" in prompt
    assert "Van Dorn Street" in prompt
    assert "Springfield interchange" in prompt


def test_system_prompt_describes_curated_network_transfers():
    prompt = build_system_prompt()
    assert '"connector": "I-66/I-495 interchange"' in prompt
    assert '"connector": "Dulles Airport Access Highway"' in prompt
    assert '"connector": "I-495/Route 267 interchange"' in prompt
    assert "explicitly labeled curated connector" in prompt
    assert "Do not infer a reverse edge" in prompt
    assert "Dulles Connector Road" not in prompt


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


def test_planner_uses_only_oracle_supported_i66_i495_steps():
    plan = plan_toll_route(
        "i66_itb", "Lee Highway - Scott Street", "i495", "Route 7 (Leesburg Pike)"
    )
    assert plan["steps"] == [
        {
            "kind": "priced",
            "corridor": "i66_itb",
            "tool": "i66_route",
            "origin": "Lee Highway - Scott Street",
            "destination": "5",
        },
        {"kind": "connector", "label": "I-66/I-495 interchange", "price_usd": "0.00"},
        {
            "kind": "priced",
            "corridor": "i495",
            "tool": "i495_route",
            "origin": "187NO",
            "destination": "Route 7 (Leesburg Pike)",
        },
    ]


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
            "destination": "192SD",
        },
        {
            "kind": "connector",
            "label": "Springfield interchange",
            "price_usd": "0.00",
        },
        {
            "kind": "priced",
            "corridor": "i95",
            "tool": "i95_route",
            "origin": "206NO",
            "destination": "Pentagon/Eads Street",
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


def test_planner_uses_an_alternate_handoff_when_the_short_path_is_unpriceable():
    plan = plan_toll_route(
        "i95",
        "Courthouse Road/Route 630",
        "i66_itb",
        "Fairfax Drive",
    )
    assert [step["label"] for step in plan["steps"] if step["kind"] == "connector"] == [
        "Springfield interchange",
        "I-495/Route 267 interchange",
        "Dulles Airport Access Highway",
    ]


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
    assert "Springfield interchange" in prompt
    assert "NOT evidence the leg boundary is correct" in prompt


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
        "i95_route",
        "i495_route",
        "i66_route",
        "dulles_route",
    ]
