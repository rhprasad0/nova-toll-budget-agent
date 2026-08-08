"""toll_agent: a Strands GPT-5.6 Luna agent that prices NoVA trips
by calling the route and junction tools in agent_tools/*.py. It never touches RDS or issues SQL
itself; every price comes from one of those tools (the same
constraint that led to lambdas/agent/* being deleted -- see README.md and
db/drop_agent_surface.sql).

Each of those tools deliberately refuses to resolve a cross-corridor trip
(docs/oracle-findings.md section 8) -- a caller wanting Dumfries (I-95) to
Westpark Drive (I-495) gets independently priced segments around an explicitly
unpriced junction, not one combined trip. A manual smoke test proved a Haiku
agent left to figure out the split on its own will happily overshoot.
NETWORK_TRANSFERS turns committed
oracle nodes and pair roles, plus explicitly curated connector facts, into the
small directed handoff graph the agent may use; every absent handoff is
intentionally unsupported.

strands.Agent's system_prompt accepts str | list[SystemContentBlock], and
SystemContentBlock only has text/cachePoint keys (strands/types/content.py)
-- there's no structured-knowledge field. The priced location oracle and
NETWORK_TRANSFERS therefore go in as literal json.dumps(...) text inside the prompt
string, not any special mechanism.

build_system_prompt() reads its template from
agent-sops/nova-toll-pricing-assistant.sop.md, a sibling file at the repo
root -- that file must ship alongside this module in any deployment of this
agent. The AgentCore package builder copies it into the same relative path.

See docs/oracle-tools-spec.md for the tool contract this builds on.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal, cast, override
from zoneinfo import ZoneInfo

import boto3
from strands import Agent, tool  # pyright: ignore[reportUnknownVariableType]
from strands.models.openai_responses import OpenAIResponsesModel
from strands.types.content import Messages
from strands.types.streaming import StreamEvent
from strands.types.tools import ToolChoice, ToolSpec

from agent_tools import _oracle_route
from agent_tools.dulles_route import (
    _lookup as _dulles_lookup,  # pyright: ignore[reportPrivateUsage]
)
from agent_tools.dulles_route import dulles_route
from agent_tools.i66_route import (
    _lookup as _i66_lookup,  # pyright: ignore[reportPrivateUsage]
)
from agent_tools.i66_route import i66_route
from agent_tools.i95_route import (
    i95_access_options,
    i95_endpoint_access_options,
    i95_junction_leg,
    i95_route,
)
from agent_tools.i495_route import (
    _lookup as _i495_lookup,  # pyright: ignore[reportPrivateUsage]
)
from agent_tools.i495_route import i495_route

_ORACLE_DIR = Path(__file__).resolve().parent.parent / "oracles"
_ORACLES: dict[str, _oracle_route.JsonObject] = {
    name: json.loads((_ORACLE_DIR / f"{name}.json").read_text())
    for name in ("i95", "i66", "dulles_toll_road", "dulles_greenway")
}


def _locations(
    nodes: _oracle_route.Nodes,
    pairs: _oracle_route.Pairs,
    *,
    directional: bool = False,
) -> list[dict[str, object]]:
    """Return the labels and roles a route tool can actually resolve."""
    entry_ids = {pair["entry"] for pair in pairs}
    exit_ids = {pair["exit"] for pair in pairs}
    locations: list[dict[str, object]] = []
    for label in sorted({nodes[node_id]["label"] for node_id in entry_ids | exit_ids}):
        location: dict[str, object] = {
            "label": label,
            "entry": any(nodes[node_id]["label"] == label for node_id in entry_ids),
            "exit": any(nodes[node_id]["label"] == label for node_id in exit_ids),
        }
        if directional:
            location["entry_directions"] = sorted(
                {
                    pair["direction"]
                    for pair in pairs
                    if nodes[pair["entry"]]["label"] == label
                }
            )
            location["exit_directions"] = sorted(
                {
                    pair["direction"]
                    for pair in pairs
                    if nodes[pair["exit"]]["label"] == label
                }
            )
        locations.append(location)
    return locations


def _load_priced_location_oracle() -> dict[str, _oracle_route.JsonObject]:
    """Prompt knowledge only; route tools remain the pricing source of truth."""
    i95 = _ORACLES["i95"]
    i66 = _ORACLES["i66"]

    def is_495(node_id: str) -> bool:
        return i95["nodes"][node_id]["path"].startswith("495")

    i95_pairs = [
        pair
        for pair in i95["pairs"]
        if not is_495(pair["entry"]) and not is_495(pair["exit"])
    ]
    i495_pairs = [
        pair for pair in i95["pairs"] if is_495(pair["entry"]) and is_495(pair["exit"])
    ]
    dulles_toll_road = _ORACLES["dulles_toll_road"]
    dulles_greenway = _ORACLES["dulles_greenway"]
    return {
        "i95": {
            "tool": "i95_route",
            "locations": _locations(i95["nodes"], i95_pairs, directional=True),
        },
        "i495": {
            "tool": "i495_route",
            "locations": _locations(i95["nodes"], i495_pairs, directional=True),
        },
        "i66_itb": {
            "tool": "i66_route",
            "locations": _locations(i66["nodes"], i66["pairs"], directional=True),
        },
        "dulles_toll_road": {
            "tool": "dulles_route",
            "locations": _locations(
                dulles_toll_road["nodes"], dulles_toll_road["pairs"], directional=True
            ),
        },
        "dulles_greenway": {
            "tool": "dulles_route",
            "locations": _locations(
                dulles_greenway["nodes"], dulles_greenway["pairs"], directional=True
            ),
        },
    }


_PRICED_LOCATION_ORACLE = _load_priced_location_oracle()
_PRICED_LOCATION_ORACLE_JSON = json.dumps(_PRICED_LOCATION_ORACLE, indent=2)

# User-facing locality hints retained from the deleted discovery tool. Every
# candidate is an exact label in the priced oracle; unpriced I-66 OTB hints
# deliberately stay out.
_LOCATION_ALIASES = {
    "Tysons": [
        "Jones Branch Drive/Route 123",
        "Route 123 - Dolley Madison Blvd",
        "I-495 Express Lanes N",
        "Westpark Drive",
    ],
    "McLean": ["Route 123 - Dolley Madison Blvd", "Jones Branch Drive/Route 123"],
    "Washington": ["Washington", "Washington D.C."],
    "Arlington": [
        "Exit 73 - Rosslyn",
        "Exit 75 - Pentagon/Alexandria",
        "Fairfax Drive",
        "Glebe Road",
        "Washington Blvd",
        "Shirlington Circle",
    ],
    "Ballston": ["Fairfax Drive", "Glebe Road"],
    "Vienna": ["Route 123 - Dolley Madison Blvd", "Fairfax Drive"],
    "Herndon": [
        "Exit 14 - SR 674 (Hunter Mill Rd)",
        "Exit 15 - SR 676 (Wolf Trap)",
    ],
}
_LOCATION_ALIASES_JSON = json.dumps(_LOCATION_ALIASES, indent=2)
_AIRPORT_ENDPOINTS = {
    "airport_iad": "Dulles International Airport (IAD)",
    "airport_dca": "Ronald Reagan Washington National Airport (DCA)",
}
_AIRPORT_ALIASES = {
    "IAD": "airport_iad",
    "Dulles": "airport_iad",
    "Dulles Airport": "airport_iad",
    "Dulles International Airport": "airport_iad",
    "DCA": "airport_dca",
    "Reagan": "airport_dca",
    "Reagan Airport": "airport_dca",
    "National Airport": "airport_dca",
    "Ronald Reagan Washington National Airport": "airport_dca",
}
_AIRPORT_ENDPOINTS_JSON = json.dumps(_AIRPORT_ENDPOINTS, indent=2)
_AIRPORT_ALIASES_JSON = json.dumps(_AIRPORT_ALIASES, indent=2)

_AWS_REGION = "us-east-1"
_OPENAI_API_KEY_PARAMETER = "/nova-toll/openai_api_key"
_OPENAI_BASE_URL = "https://api.openai.com/v1"
_MODEL_BACKEND_ENV = "TOLLCHAT_MODEL_BACKEND"
SYSTEM_PROMPT_VERSION = "1.26.0"
TOOLSET_VERSION = "1.7.0"
_EASTERN = ZoneInfo("America/New_York")


class _CachedResponsesModel(OpenAIResponsesModel):
    """Cache the unchanged developer prompt before variable conversation input."""

    @override
    def _format_request(
        self,
        messages: Messages,
        tool_specs: list[ToolSpec] | None = None,
        system_prompt: str | None = None,
        tool_choice: ToolChoice | None = None,
        model_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        request = super()._format_request(
            messages, tool_specs, None, tool_choice, model_state
        )
        if system_prompt:
            cast(list[dict[str, Any]], request["input"]).insert(
                0,
                {
                    "type": "message",
                    "role": "developer",
                    "content": [
                        {
                            "type": "input_text",
                            "text": system_prompt,
                            "prompt_cache_breakpoint": {"mode": "explicit"},
                        }
                    ],
                },
            )
        return request

    @override
    def _format_chunk(self, event: dict[str, Any]) -> StreamEvent:
        chunk = super()._format_chunk(event)
        if event["chunk_type"] == "metadata":
            details = getattr(event["data"], "input_tokens_details", None)
            written = getattr(details, "cache_write_tokens", None)
            if isinstance(written, int):
                cast(Any, chunk)["metadata"]["usage"]["cacheWriteInputTokens"] = written
        return chunk


def load_openai_api_key() -> str:
    ssm = cast(
        Any,
        boto3.client(  # pyright: ignore[reportUnknownMemberType]
            "ssm", region_name=_AWS_REGION
        ),
    )
    value = ssm.get_parameter(
        Name=_OPENAI_API_KEY_PARAMETER,
        WithDecryption=True,
    )["Parameter"]["Value"]
    if not isinstance(value, str) or not value:
        raise ValueError(f"{_OPENAI_API_KEY_PARAMETER} is empty")
    return value


_load_openai_api_key = load_openai_api_key


def _build_model() -> _CachedResponsesModel:
    backend = os.environ.get(_MODEL_BACKEND_ENV, "openai")
    params = {
        "max_output_tokens": 2048,
        "reasoning": {"effort": "low"},
        "prompt_cache_key": "tollchat-agent-v1",
        "prompt_cache_options": {"mode": "explicit", "ttl": "30m"},
    }
    if backend == "openai":
        return _CachedResponsesModel(
            model_id="gpt-5.6-luna",
            client_args={
                "api_key": _load_openai_api_key(),
                "base_url": _OPENAI_BASE_URL,
            },
            params=params,
            stateful=True,
        )
    if backend == "bedrock-mantle":
        return _CachedResponsesModel(
            model_id="openai.gpt-5.6-luna",
            bedrock_mantle_config={"region": _AWS_REGION},
            params=params,
            stateful=True,
        )
    raise ValueError(
        f"{_MODEL_BACKEND_ENV} must be 'openai' or 'bedrock-mantle', got {backend!r}"
    )


NETWORK_TRANSFERS: list[_oracle_route.JsonObject] = [
    {
        "id": "iad_to_i66",
        "from": {
            "corridor": "airport_iad",
            "exit": _AIRPORT_ENDPOINTS["airport_iad"],
            "node_id": _AIRPORT_ENDPOINTS["airport_iad"],
        },
        "to": {
            "corridor": "i66_itb",
            "entry": "Route 267 - Dulles Toll Road",
            "node_id": "6",
        },
        "connector": "Dulles Airport Access Highway",
        "evidence": "airport-only untolled access confirmed by the user; I-66 node 6 is its priced-network handoff",
    },
    {
        "id": "i66_to_iad",
        "from": {
            "corridor": "i66_itb",
            "exit": "Route 267 - Dulles Toll Road",
            "node_id": "6",
        },
        "to": {
            "corridor": "airport_iad",
            "entry": _AIRPORT_ENDPOINTS["airport_iad"],
            "node_id": _AIRPORT_ENDPOINTS["airport_iad"],
        },
        "connector": "Dulles Airport Access Highway",
        "evidence": "airport-only untolled access confirmed by the user; I-66 node 6 is its priced-network handoff",
    },
    {
        "id": "dca_to_i95",
        "from": {
            "corridor": "airport_dca",
            "exit": _AIRPORT_ENDPOINTS["airport_dca"],
            "node_id": _AIRPORT_ENDPOINTS["airport_dca"],
        },
        "to": {
            "corridor": "i95",
            "entry": "Pentagon/Eads Street",
            "node_id": "2233SO",
        },
        "connector": "Reagan airport access",
        "evidence": "curated airport endpoint confirmed by the user; I-95 node 2233SO is the southbound entry",
    },
    {
        "id": "i95_to_dca_northbound",
        "from": {
            "corridor": "i95",
            "exit": "Pentagon/Eads Street",
            "node_id": "223ND",
        },
        "to": {
            "corridor": "airport_dca",
            "entry": _AIRPORT_ENDPOINTS["airport_dca"],
            "node_id": _AIRPORT_ENDPOINTS["airport_dca"],
        },
        "connector": "Reagan airport access",
        "evidence": "curated airport endpoint confirmed by the user; I-95 node 223ND is the northbound exit",
    },
    {
        "id": "i95_to_dca_southbound",
        "from": {
            "corridor": "i95",
            "exit": "Pentagon/Eads Street",
            "node_id": "2239ND",
        },
        "to": {
            "corridor": "airport_dca",
            "entry": _AIRPORT_ENDPOINTS["airport_dca"],
            "node_id": _AIRPORT_ENDPOINTS["airport_dca"],
        },
        "connector": "Reagan airport access",
        "evidence": "curated airport endpoint confirmed by the user; I-95 node 2239ND is the southbound exit",
    },
    {
        "id": "i66_to_i495",
        "from": {"corridor": "i66_itb", "exit": "I-495 S", "node_id": "5"},
        "to": {"corridor": "i495", "entry": "Interstate 66", "node_id": "187SO"},
        "connector": "I-66/I-495 interchange",
        "evidence": "oracles/i66.json node 5 and oracles/i95.json node 187SO pair roles",
    },
    {
        "id": "i66_to_i495_north",
        "from": {"corridor": "i66_itb", "exit": "I-495 S", "node_id": "5"},
        "to": {"corridor": "i495", "entry": "Interstate 66", "node_id": "187NO"},
        "connector": "I-66/I-495 interchange",
        "evidence": "curated connector confirmed by the user; oracle endpoints are nodes 5 and 187NO",
    },
    {
        "id": "i495_to_i66",
        "from": {"corridor": "i495", "exit": "Interstate 66", "node_id": "187ND"},
        "to": {
            "corridor": "i66_itb",
            "entry": "I-495 Express Lanes N",
            "node_id": "3",
        },
        "connector": "I-66/I-495 interchange",
        "evidence": "oracles/i95.json node 187ND and oracles/i66.json node 3 pair roles",
    },
    {
        "id": "i495_south_to_i66",
        "from": {"corridor": "i495", "exit": "Interstate 66", "node_id": "187SD"},
        "to": {"corridor": "i66_itb", "entry": "I-495 S", "node_id": "5"},
        "connector": "I-66/I-495 interchange",
        "evidence": "curated connector confirmed by the user; oracle endpoints are nodes 187SD and 5",
    },
    {
        "id": "dulles_toll_road_to_i495",
        "from": {
            "corridor": "dulles_toll_road",
            "exit": "Exit 18/19 - I-495 / SR 123 (Capital Beltway)",
            "node_id": "1819",
        },
        "to": {"corridor": "i495", "entry": "Route 267", "node_id": "182SO"},
        "connector": "I-495/Route 267 interchange",
        "evidence": "curated connector confirmed by the user; oracle endpoints are nodes 1819 and 182SO",
    },
    {
        "id": "dulles_toll_road_to_i495_north",
        "from": {
            "corridor": "dulles_toll_road",
            "exit": "Exit 18/19 - I-495 / SR 123 (Capital Beltway)",
            "node_id": "1819",
        },
        "to": {"corridor": "i495", "entry": "Route 267", "node_id": "182NO"},
        "connector": "I-495/Route 267 interchange",
        "evidence": "curated connector confirmed by the user; oracle endpoints are nodes 1819 and 182NO",
    },
    {
        "id": "i495_to_dulles_toll_road",
        "from": {"corridor": "i495", "exit": "Route 267", "node_id": "182ND"},
        "to": {
            "corridor": "dulles_toll_road",
            "entry": "Exit 18/19 - I-495 / SR 123 (Capital Beltway)",
            "node_id": "1819",
        },
        "connector": "I-495/Route 267 interchange",
        "evidence": "curated connector confirmed by the user; oracle endpoints are nodes 182ND and 1819",
    },
    {
        "id": "i495_south_to_dulles_toll_road",
        "from": {"corridor": "i495", "exit": "Route 267", "node_id": "182SD"},
        "to": {
            "corridor": "dulles_toll_road",
            "entry": "Exit 18/19 - I-495 / SR 123 (Capital Beltway)",
            "node_id": "1819",
        },
        "connector": "I-495/Route 267 interchange",
        "evidence": "curated connector confirmed by the user; oracle endpoints are nodes 182SD and 1819",
    },
    {
        "id": "i66_to_dulles_toll_road",
        "from": {
            "corridor": "i66_itb",
            "exit": "Route 267 - Dulles Toll Road",
            "node_id": "6",
        },
        "to": {
            "corridor": "dulles_toll_road",
            "entry": "I-66 / Dulles Toll Road junction",
            "node_id": "66",
        },
        "connector": "I-66 / Dulles Toll Road junction",
        "evidence": "curated shared boundary confirmed by the user; oracle endpoints are nodes 6 and 66",
    },
    {
        "id": "dulles_toll_road_to_i66",
        "from": {
            "corridor": "dulles_toll_road",
            "exit": "I-66 / Dulles Toll Road junction",
            "node_id": "66",
        },
        "to": {
            "corridor": "i66_itb",
            "entry": "Route 267 - Dulles Toll Road",
            "node_id": "6",
        },
        "connector": "I-66 / Dulles Toll Road junction",
        "evidence": "curated shared boundary confirmed by the user; oracle endpoints are nodes 66 and 6",
    },
]

_NETWORK_TRANSFERS_JSON = json.dumps(NETWORK_TRANSFERS, indent=2)
_LOCATION_BY_CORRIDOR = {
    corridor: {location["label"]: location for location in data["locations"]}
    for corridor, data in _PRICED_LOCATION_ORACLE.items()
}
_LOCATION_BY_CORRIDOR.update(
    {
        corridor: {label: {"label": label, "entry": True, "exit": True}}
        for corridor, label in _AIRPORT_ENDPOINTS.items()
    }
)
_DULLES_CORRIDORS = {"dulles_toll_road", "dulles_greenway"}
_CROSS_I95_HANDOFF = "Franconia-Springfield Parkway/Route 289"
_I495_JUNCTION_ENTRY = "191NO"
_I495_JUNCTION_EXIT = "191SD"
_DCA_I95_HANDOFF = "Pentagon/Eads Street"
_ROUTE_267_DETOUR_CONNECTORS = {
    "I-66 / Dulles Toll Road junction",
    "I-495/Route 267 interchange",
}


def _load_direct_pair_oracles() -> dict[
    str, tuple[_oracle_route.Nodes, _oracle_route.Pairs]
]:
    """Committed pair data used to prove each planned priced step exists."""
    i95 = _ORACLES["i95"]
    i66 = _ORACLES["i66"]
    dulles_toll_road = _ORACLES["dulles_toll_road"]
    dulles_greenway = _ORACLES["dulles_greenway"]

    def is_495(node_id: str) -> bool:
        return i95["nodes"][node_id]["path"].startswith("495")

    return {
        "i95": (
            i95["nodes"],
            [
                pair
                for pair in i95["pairs"]
                if not is_495(pair["entry"]) and not is_495(pair["exit"])
            ],
        ),
        "i495": (
            i95["nodes"],
            [
                pair
                for pair in i95["pairs"]
                if is_495(pair["entry"]) and is_495(pair["exit"])
            ],
        ),
        "i66_itb": (i66["nodes"], i66["pairs"]),
        "dulles_toll_road": (
            dulles_toll_road["nodes"],
            dulles_toll_road["pairs"],
        ),
        "dulles_greenway": (dulles_greenway["nodes"], dulles_greenway["pairs"]),
    }


_DIRECT_PAIR_ORACLES = _load_direct_pair_oracles()


def _has_direct_pair(corridor: str, origin: str, destination: str) -> bool:
    """Match the lookup rule of the VDOT tools without querying for a price."""
    nodes, pairs = _DIRECT_PAIR_ORACLES[corridor]
    origin_ids = (
        [origin]
        if origin in nodes
        else [
            node_id
            for node_id, node in nodes.items()
            if node["label"].casefold() == origin.casefold()
        ]
    )
    destination_ids = (
        [destination]
        if destination in nodes
        else [
            node_id
            for node_id, node in nodes.items()
            if node["label"].casefold() == destination.casefold()
        ]
    )
    return any(
        pair["entry"] in origin_ids and pair["exit"] in destination_ids
        for pair in pairs
    )


def _validate_location(
    corridor: str, label: str, role: str, *, check_role: bool = True
) -> _oracle_route.JsonObject | None:
    location = _LOCATION_BY_CORRIDOR.get(corridor, {}).get(label)
    if location is None:
        return {
            "error": f"unknown {role} {label!r} on {corridor}",
            "valid_options": sorted(_LOCATION_BY_CORRIDOR.get(corridor, {})),
        }
    if check_role and not location[role]:
        return {
            "error": f"{label!r} is not a valid {role} on {corridor}",
            "valid_options": sorted(
                name
                for name, candidate in _LOCATION_BY_CORRIDOR[corridor].items()
                if candidate[role]
            ),
        }
    return None


def _same_location(corridor: str, query: str, node_id: str) -> bool:
    if corridor in _AIRPORT_ENDPOINTS:
        return query.casefold() == node_id.casefold()
    nodes, _ = _DIRECT_PAIR_ORACLES[corridor]
    return query == node_id or (
        node_id in nodes and nodes[node_id]["label"].casefold() == query.casefold()
    )


def _can_price(
    origin_corridor: str,
    origin: str,
    destination_corridor: str,
    destination: str,
) -> bool:
    result = _route_lookup(origin_corridor, origin, destination_corridor, destination)
    return (
        "error" not in result
        and result.get("status") != "one_way_mismatch"
        and result.get("ok", True)
    )


def _route_lookup(
    origin_corridor: str,
    origin: str,
    destination_corridor: str,
    destination: str,
) -> _oracle_route.JsonObject:
    if (
        origin_corridor in _AIRPORT_ENDPOINTS
        or destination_corridor in _AIRPORT_ENDPOINTS
    ):
        return {"error": "airport endpoints require a documented connector"}
    if {origin_corridor, destination_corridor} <= _DULLES_CORRIDORS:
        return _dulles_lookup(origin, destination)
    if origin_corridor != destination_corridor:
        return {"error": "different corridors"}
    if origin_corridor == "i66_itb":
        return _i66_lookup(origin, destination)
    if origin_corridor == "i495":
        return _i495_lookup(origin, destination)
    return {"ok": _has_direct_pair(origin_corridor, origin, destination)}


def _priced_step(
    corridor: str, origin: str, destination: str
) -> _oracle_route.JsonObject:
    return {
        "kind": "priced",
        "corridor": corridor,
        "tool": _PRICED_LOCATION_ORACLE[corridor]["tool"],
        "origin": origin,
        "destination": destination,
    }


def _junction_step(movement: str, location: str) -> _oracle_route.JsonObject:
    return {
        "kind": "junction",
        "tool": "i95_junction_leg",
        "movement": movement,
        "location": location,
        "i495_boundary": {
            "label": "I-495 Near Braddock Road",
            "node_id": (
                _I495_JUNCTION_ENTRY
                if movement == "i95_to_i495"
                else _I495_JUNCTION_EXIT
            ),
        },
        "pricing": "unpriced between the selected 95 boundary and Braddock",
    }


def _requested_endpoint_mismatch(
    result: _oracle_route.JsonObject,
    leg_origin: tuple[str, str],
    leg_destination: tuple[str, str],
    requested_origin: tuple[str, str],
    requested_destination: tuple[str, str],
) -> _oracle_route.JsonObject | None:
    constraints = [
        constraint
        for constraint in result.get("constraints", [])
        if (
            constraint.get("role") == "entry"
            and leg_origin[0] == requested_origin[0]
            and _same_location(
                leg_origin[0], constraint.get("location", ""), requested_origin[1]
            )
        )
        or (
            constraint.get("role") == "exit"
            and leg_destination[0] == requested_destination[0]
            and _same_location(
                leg_destination[0],
                constraint.get("location", ""),
                requested_destination[1],
            )
        )
    ]
    if not constraints:
        return None
    return {
        "status": "one_way_mismatch",
        "direction": result["direction"],
        "constraints": constraints,
    }


def _planned_steps(
    origin_corridor: str,
    origin: str,
    destination_corridor: str,
    destination: str,
) -> list[_oracle_route.JsonObject] | _oracle_route.JsonObject | None:
    frontier: list[tuple[str, str, list[_oracle_route.JsonObject]]] = [
        (origin_corridor, origin, [])
    ]
    visited = {(origin_corridor, origin)}
    mismatch: _oracle_route.JsonObject | None = None
    while frontier:
        corridor, point, steps = frontier.pop(0)
        if (
            corridor == destination_corridor
            and _same_location(corridor, destination, point)
            and _LOCATION_BY_CORRIDOR[corridor][destination]["exit"]
        ):
            return steps
        direct = _route_lookup(corridor, point, destination_corridor, destination)
        if direct.get("status") == "one_way_mismatch":
            if requested := _requested_endpoint_mismatch(
                direct,
                (corridor, point),
                (destination_corridor, destination),
                (origin_corridor, origin),
                (destination_corridor, destination),
            ):
                mismatch = requested
        elif "error" not in direct and direct.get("ok", True):
            return [*steps, _priced_step(corridor, point, destination)]
        if (
            corridor == destination_corridor == "i495"
            and steps
            and steps[-1].get("kind") == "junction"
        ):
            # The requested I-495 endpoint is at or inside the unpriced gap,
            # before a Braddock-originating 495 leg can be formed.
            return [
                *steps,
                {
                    "kind": "unpriced",
                    "corridor": "i495",
                    "reason": (
                        "the I-495 endpoint is inside the unpriced junction "
                        "before Braddock; do not call i495_route"
                    ),
                },
            ]

        if corridor == "i95" and destination_corridor not in {"i95", "airport_dca"}:
            state = ("i495", _I495_JUNCTION_ENTRY)
            if state not in visited:
                visited.add(state)
                frontier.append(
                    (
                        *state,
                        [*steps, _junction_step("i95_to_i495", point)],
                    )
                )
            continue

        if corridor == "i495" and destination_corridor in {"i95", "airport_dca"}:
            priced_steps = (
                [_priced_step("i495", point, _I495_JUNCTION_EXIT)]
                if _can_price("i495", point, "i495", _I495_JUNCTION_EXIT)
                else []
            )
            steps_to_i95 = [
                *steps,
                *priced_steps,
                _junction_step(
                    "i495_to_i95",
                    _DCA_I95_HANDOFF
                    if destination_corridor == "airport_dca"
                    else destination,
                ),
            ]
            if destination_corridor == "airport_dca":
                return [
                    *steps_to_i95,
                    {
                        "kind": "connector",
                        "transfer_id": "i95_to_dca_northbound",
                        "label": "Reagan airport access",
                        "price_usd": "0.00",
                    },
                ]
            return steps_to_i95

        for transfer in NETWORK_TRANSFERS:
            if any(
                step.get("kind") == "connector"
                and step.get("label") == transfer["connector"]
                for step in steps
            ):
                continue
            source = transfer["from"]
            if corridor == source["corridor"] and _same_location(
                corridor, point, source["node_id"]
            ):
                priced_steps = []
            else:
                source_route = _route_lookup(
                    corridor, point, source["corridor"], source["node_id"]
                )
                if source_route.get("status") == "one_way_mismatch":
                    requested = _requested_endpoint_mismatch(
                        source_route,
                        (corridor, point),
                        (source["corridor"], source["node_id"]),
                        (origin_corridor, origin),
                        (destination_corridor, destination),
                    )
                    mismatch = mismatch or requested
                    continue
                if "error" in source_route or not source_route.get("ok", True):
                    continue
                priced_steps = [_priced_step(corridor, point, source["node_id"])]

            target = transfer["to"]
            state = (target["corridor"], target["node_id"])
            if state in visited:
                continue
            visited.add(state)
            frontier.append(
                (
                    *state,
                    [
                        *steps,
                        *priced_steps,
                        {
                            "kind": "connector",
                            "transfer_id": transfer["id"],
                            "label": transfer["connector"],
                            "price_usd": "0.00",
                        },
                    ],
                )
            )
    return mismatch


@tool
def plan_toll_route(
    origin_corridor: Literal[
        "i95",
        "i495",
        "i66_itb",
        "dulles_toll_road",
        "dulles_greenway",
        "airport_iad",
        "airport_dca",
    ],
    origin: str,
    destination_corridor: Literal[
        "i95",
        "i495",
        "i66_itb",
        "dulles_toll_road",
        "dulles_greenway",
        "airport_iad",
        "airport_dca",
    ],
    destination: str,
    at_time: str | None = None,
) -> _oracle_route.JsonObject:
    """Plan a supported cross-corridor trip before pricing either leg.

    Use exact corridor IDs and oracle labels or node IDs. Returns normalized
    ``at_time`` and ordered steps: call each ``priced`` or ``junction`` step
    once with its returned arguments, use each connector step's
    ``transfer_id`` to identify its directed transfer, and do not call a tool
    for ``connector`` or ``unpriced`` steps. A connector's ``price_usd`` is an
    untolled planning sentinel, not a billed fare. On error, no supported
    directed route exists and no pricing tool should be called.

    Args:
        origin_corridor: Exact origin corridor ID or airport endpoint ID.
        origin: Exact origin oracle label, node ID, or canonical airport name.
        destination_corridor: Exact destination corridor ID or airport endpoint ID.
        destination: Exact destination oracle label, node ID, or canonical airport name.
        at_time: Optional ISO-8601 travel time; offset-less values use
            America/New_York. Omit for the current VDOT view.

    Returns:
        dict: ``{"at_time", "steps"}``, optionally with ``routing_note``;
        each step has a ``kind`` and its documented tool arguments. A
        directionally invalid endpoint returns the shared structured
        ``one_way_mismatch`` result; other failures return ``{"error": str}``.
    """
    try:
        planned_at_time = _oracle_route.resolve_at_time(at_time).isoformat()
    except (TypeError, ValueError) as e:
        return {"error": f"invalid at_time {at_time!r}: {e}"}

    if origin_corridor not in _LOCATION_BY_CORRIDOR:
        return {"error": f"unknown origin corridor {origin_corridor!r}"}
    if destination_corridor not in _LOCATION_BY_CORRIDOR:
        return {"error": f"unknown destination corridor {destination_corridor!r}"}
    if (
        origin_corridor == "i95"
        and destination_corridor != "i95"
        and origin in _LOCATION_BY_CORRIDOR["i95"]
    ):
        access = i95_endpoint_access_options(origin, "entry", _CROSS_I95_HANDOFF)
        if access["status"] == "one_way_mismatch":
            return access
    if (
        destination_corridor == "i95"
        and origin_corridor != "i95"
        and destination in _LOCATION_BY_CORRIDOR["i95"]
    ):
        access = i95_endpoint_access_options(destination, "exit", _CROSS_I95_HANDOFF)
        if access["status"] == "one_way_mismatch":
            return access
    if error := _validate_location(
        origin_corridor, origin, "entry", check_role=origin_corridor == "i95"
    ):
        return error
    if error := _validate_location(
        destination_corridor,
        destination,
        "exit",
        check_role=destination_corridor == "i95",
    ):
        return error

    steps = _planned_steps(origin_corridor, origin, destination_corridor, destination)
    if steps is None:
        return {
            "error": (
                "no oracle-supported directed route connects "
                f"{origin!r} on {origin_corridor} to "
                f"{destination!r} on {destination_corridor}"
            )
        }
    if isinstance(steps, dict):
        return steps
    connector_labels = {step["label"] for step in steps if step["kind"] == "connector"}
    if connector_labels >= _ROUTE_267_DETOUR_CONNECTORS:
        return {
            "at_time": planned_at_time,
            "steps": steps,
            "routing_note": "Route 267 detour; not a direct I-66/I-495 connection",
        }
    return {"at_time": planned_at_time, "steps": steps}


_AGENT_TOOLS = (
    plan_toll_route,
    i95_access_options,
    i95_junction_leg,
    i95_route,
    i495_route,
    i66_route,
    dulles_route,
)


def build_system_prompt(*, current_date: date | None = None) -> str:
    """System prompt loaded from the Nova Toll Pricing Assistant Agent SOP.

    The SOP at agent-sops/nova-toll-pricing-assistant.sop.md is the literal
    source of the runtime prompt text; the oracle blocks and current New York
    date are filled in dynamically. No AWS calls -- callable in a test with
    no network/creds.
    """
    sop_path = (
        Path(__file__).resolve().parent.parent
        / "agent-sops"
        / "nova-toll-pricing-assistant.sop.md"
    )
    return sop_path.read_text().format(
        PRICED_LOCATION_ORACLE_JSON=_PRICED_LOCATION_ORACLE_JSON,
        LOCATION_ALIASES_JSON=_LOCATION_ALIASES_JSON,
        AIRPORT_ENDPOINTS_JSON=_AIRPORT_ENDPOINTS_JSON,
        AIRPORT_ALIASES_JSON=_AIRPORT_ALIASES_JSON,
        NETWORK_TRANSFERS_JSON=_NETWORK_TRANSFERS_JSON,
        CURRENT_DATE=(current_date or datetime.now(_EASTERN).date()).strftime(
            "%-m/%-d/%Y"
        ),
    )


def build_agent(
    *,
    trace_attributes: dict[str, str] | None = None,
    hooks: list[object] | None = None,
) -> Agent:
    trace_attributes = {
        **(trace_attributes or {}),
        "tollchat.system_prompt_version": SYSTEM_PROMPT_VERSION,
        "tollchat.toolset_version": TOOLSET_VERSION,
    }
    return Agent(
        model=_build_model(),
        tools=list(_AGENT_TOOLS),
        system_prompt=build_system_prompt(),
        callback_handler=None,
        trace_attributes=trace_attributes,
        hooks=cast(Any, hooks),
    )


if __name__ == "__main__":
    agent = build_agent()
    prompt = " ".join(sys.argv[1:]) or "Price a trip from Dumfries to Westpark"
    print(agent(prompt))
