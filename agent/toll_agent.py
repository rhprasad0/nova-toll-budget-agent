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

See docs/oracle-tools-spec.md for the tool contract this builds on.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, cast, override

import boto3
from strands import Agent, tool  # pyright: ignore[reportUnknownVariableType]
from strands.models.openai_responses import OpenAIResponsesModel
from strands.types.content import Messages
from strands.types.tools import ToolChoice, ToolSpec

from agent_tools import _oracle_route
from agent_tools.dulles_route import (
    _lookup as _dulles_lookup,  # pyright: ignore[reportPrivateUsage]
)
from agent_tools.dulles_route import dulles_route
from agent_tools.i66_route import i66_route
from agent_tools.i95_route import i95_junction_leg, i95_route
from agent_tools.i495_route import i495_route

_ORACLE_DIR = Path(__file__).resolve().parent.parent / "oracles"
_ORACLES: dict[str, _oracle_route.JsonObject] = {
    name: json.loads((_ORACLE_DIR / f"{name}.json").read_text())
    for name in ("i95", "i66", "dulles_toll_road", "dulles_greenway")
}


def _locations(
    nodes: _oracle_route.Nodes, pairs: _oracle_route.Pairs
) -> list[dict[str, str | bool]]:
    """Return the labels and roles a route tool can actually resolve."""
    entry_ids = {pair["entry"] for pair in pairs}
    exit_ids = {pair["exit"] for pair in pairs}
    return [
        {
            "label": label,
            "entry": any(nodes[node_id]["label"] == label for node_id in entry_ids),
            "exit": any(nodes[node_id]["label"] == label for node_id in exit_ids),
        }
        for label in sorted(
            {nodes[node_id]["label"] for node_id in entry_ids | exit_ids}
        )
    ]


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
        "i95": {"tool": "i95_route", "locations": _locations(i95["nodes"], i95_pairs)},
        "i495": {
            "tool": "i495_route",
            "locations": _locations(i95["nodes"], i495_pairs),
        },
        "i66_itb": {
            "tool": "i66_route",
            "locations": _locations(i66["nodes"], i66["pairs"]),
        },
        "dulles_toll_road": {
            "tool": "dulles_route",
            "locations": _locations(
                dulles_toll_road["nodes"], dulles_toll_road["pairs"]
            ),
        },
        "dulles_greenway": {
            "tool": "dulles_route",
            "locations": _locations(dulles_greenway["nodes"], dulles_greenway["pairs"]),
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
    "National Airport": ["Pentagon/Eads Street"],
    "Reagan Airport": ["Pentagon/Eads Street"],
    "Dulles Airport": ["Route 28 (Dulles Toll Road / Dulles Greenway)"],
}
_LOCATION_ALIASES_JSON = json.dumps(_LOCATION_ALIASES, indent=2)

_AWS_REGION = "us-east-1"
_OPENAI_API_KEY_PARAMETER = "/nova-toll/openai_api_key"
_MODEL_BACKEND_ENV = "TOLLCHAT_MODEL_BACKEND"


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


def _load_openai_api_key() -> str:
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
            client_args={"api_key": _load_openai_api_key()},
            params=params,
            stateful=False,
        )
    if backend == "bedrock-mantle":
        return _CachedResponsesModel(
            model_id="openai.gpt-5.6-luna",
            bedrock_mantle_config={"region": _AWS_REGION},
            params=params,
            stateful=False,
        )
    raise ValueError(
        f"{_MODEL_BACKEND_ENV} must be 'openai' or 'bedrock-mantle', got {backend!r}"
    )


NETWORK_TRANSFERS: list[_oracle_route.JsonObject] = [
    {
        "id": "i66_to_i495",
        "from": {"corridor": "i66_itb", "exit": "I-495 S", "node_id": "5"},
        "to": {"corridor": "i495", "entry": "Interstate 66", "node_id": "187SO"},
        "connector": "I-66/I-495 interchange",
        "evidence": "oracles/i66.json node 5 and oracles/i95.json node 187SO pair roles",
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
            "entry": "Exit 18/19 - I-495 / SR 123 (Capital Beltway)",
            "node_id": "1819",
        },
        "connector": "Dulles Airport Access Highway",
        "evidence": "curated connector confirmed by the user; oracle endpoints are nodes 6 and 1819",
    },
    {
        "id": "dulles_toll_road_to_i66",
        "from": {
            "corridor": "dulles_toll_road",
            "exit": "Exit 18/19 - I-495 / SR 123 (Capital Beltway)",
            "node_id": "1819",
        },
        "to": {
            "corridor": "i66_itb",
            "entry": "Route 267 - Dulles Toll Road",
            "node_id": "6",
        },
        "connector": "Dulles Airport Access Highway",
        "evidence": "curated connector confirmed by the user; oracle endpoints are nodes 1819 and 6",
    },
]

_NETWORK_TRANSFERS_JSON = json.dumps(NETWORK_TRANSFERS, indent=2)
_LOCATION_BY_CORRIDOR = {
    corridor: {location["label"]: location for location in data["locations"]}
    for corridor, data in _PRICED_LOCATION_ORACLE.items()
}
_DULLES_CORRIDORS = {"dulles_toll_road", "dulles_greenway"}
_I495_JUNCTION_ENTRY = "191NO"
_I495_JUNCTION_EXIT = "191SD"
_ROUTE_267_DETOUR_CONNECTORS = {
    "Dulles Airport Access Highway",
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


_ANTI_EXAMPLE = """A single-corridor pricing tool will happily price a trip all the way to the
far end of its own corridor without ever returning an error -- a successful
call is NOT evidence the leg boundary is correct. For example, i95_route
will price a trip from Dumfries all the way to Washington D.C. even though
the cross-corridor request must instead use i95_junction_leg. That tool
selects Edsall for a southbound 95 leg or Franconia-Springfield for a
northbound 95 leg. I-495 pricing independently starts or ends at I-495 Near
Braddock Road. The gap between those boundaries has no VDOT price: never
label it free, assign it $0.00, or add the known segments into a trip total."""


def _validate_location(
    corridor: str, label: str, role: str
) -> _oracle_route.JsonObject | None:
    location = _LOCATION_BY_CORRIDOR.get(corridor, {}).get(label)
    if location is None:
        return {
            "error": f"unknown {role} {label!r} on {corridor}",
            "valid_options": sorted(_LOCATION_BY_CORRIDOR.get(corridor, {})),
        }
    if not location[role]:
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
    if {origin_corridor, destination_corridor} <= _DULLES_CORRIDORS:
        return "error" not in _dulles_lookup(origin, destination)
    return origin_corridor == destination_corridor and _has_direct_pair(
        origin_corridor, origin, destination
    )


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


def _planned_steps(
    origin_corridor: str,
    origin: str,
    destination_corridor: str,
    destination: str,
) -> list[_oracle_route.JsonObject] | None:
    frontier: list[tuple[str, str, list[_oracle_route.JsonObject]]] = [
        (origin_corridor, origin, [])
    ]
    visited = {(origin_corridor, origin)}
    while frontier:
        corridor, point, steps = frontier.pop(0)
        if corridor == destination_corridor and _same_location(
            corridor, destination, point
        ):
            return steps
        if _can_price(corridor, point, destination_corridor, destination):
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

        if corridor == "i95" and destination_corridor != "i95":
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

        if corridor == "i495" and destination_corridor == "i95":
            priced_steps = (
                [_priced_step("i495", point, _I495_JUNCTION_EXIT)]
                if _can_price("i495", point, "i495", _I495_JUNCTION_EXIT)
                else []
            )
            return [
                *steps,
                *priced_steps,
                _junction_step("i495_to_i95", destination),
            ]

        for transfer in NETWORK_TRANSFERS:
            source = transfer["from"]
            if corridor == source["corridor"] and _same_location(
                corridor, point, source["node_id"]
            ):
                priced_steps = []
            elif _can_price(corridor, point, source["corridor"], source["node_id"]):
                priced_steps = [_priced_step(corridor, point, source["node_id"])]
            else:
                continue

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
                            "label": transfer["connector"],
                            "price_usd": "0.00",
                        },
                    ],
                )
            )
    return None


@tool
def plan_toll_route(
    origin_corridor: str,
    origin: str,
    destination_corridor: str,
    destination: str,
    at_time: str | None = None,
) -> _oracle_route.JsonObject:
    """Return the only oracle-supported pricing, junction, and connector steps.

    Call after resolving the user's location to exact prompt-oracle labels and
    before any pricing tool on a cross-corridor trip. Inputs must be exact;
    this tool does not fuzzy-match or invent roads. Its `priced` steps are the
    only ordinary pricing-tool calls permitted for the trip. A ``junction``
    step calls ``i95_junction_leg`` and marks the 95/495 gap as unpriced.
    An ``unpriced`` step also calls no tool. Other ``connector`` steps are $0
    and must never be sent to a pricing tool. Boundaries use oracle node IDs
    so their directed entry/exit roles are not lost to duplicate labels.
    ``at_time`` is normalized once for every tool call in the returned plan.
    """
    try:
        planned_at_time = _oracle_route.resolve_at_time(at_time).isoformat()
    except (TypeError, ValueError) as e:
        return {"error": f"invalid at_time {at_time!r}: {e}"}

    if origin_corridor not in _LOCATION_BY_CORRIDOR:
        return {"error": f"unknown origin corridor {origin_corridor!r}"}
    if destination_corridor not in _LOCATION_BY_CORRIDOR:
        return {"error": f"unknown destination corridor {destination_corridor!r}"}
    if error := _validate_location(origin_corridor, origin, "entry"):
        return error
    if error := _validate_location(destination_corridor, destination, "exit"):
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
    connector_labels = {step["label"] for step in steps if step["kind"] == "connector"}
    if connector_labels >= _ROUTE_267_DETOUR_CONNECTORS:
        return {
            "at_time": planned_at_time,
            "steps": steps,
            "routing_note": "Route 267 detour; not a direct I-66/I-495 connection",
        }
    return {"at_time": planned_at_time, "steps": steps}


def build_system_prompt() -> str:
    """Static system prompt: tool-routing context and response contract.

    Pure function, no AWS calls -- callable in a test with no network/creds.
    """
    return f"""<role>
You are a Northern Virginia toll-pricing assistant. Give users accurate,
auditable toll estimates grounded only in the registered tools' results.
</role>

<tool_rules>
- For every cross-corridor request, call plan_toll_route before validating or
  pricing either endpoint. Do not reject an entry-only or exit-only endpoint
  yourself; the planner is authoritative about whether it can be an origin or
  destination.
- Pass the user's requested `at_time` to plan_toll_route. Otherwise omit it.
  Copy the planner result's `at_time` unchanged into every `priced` and
  `junction` tool call, including the first one; never omit or recalculate it.
- Match vague, partial, or misspelled locations to the closest appropriate
  exact label in the priced location oracle below. Use that exact label in a
  pricing-tool call. If more than one listed label could reasonably mean the
  user's location, ask a concise clarifying question instead of guessing.
  An exact listed label, matched case-insensitively, is unambiguous; use it
  without asking the user to confirm it.
- In the oracle, `entry: true` means a location is a valid trip origin and
  `exit: true` means it is a valid trip destination. An exit-only location is
  therefore valid as a destination; do not reject it for lacking entry access.
- On I-495, northbound travel **to** George Washington Memorial Parkway maps
  to `495 Express Lanes End/George Wash. Mem. Pkwy.`; southbound travel
  **from** the parkway maps to `495 Express Lanes Start/Georg Wash. Mem.
  Pkwy.`. Resolve from travel direction and endpoint role, not "north end" or
  "south end" wording.
- If a location has no clear match in the priced location oracle, or is on an
  unlisted road, explain that it is outside coverage and do not call a pricing
  tool. Never substitute a nearby listed road or ramp for an uncovered one,
  including I-66 Outside the Beltway.
- Use i95_route, i495_route, and i66_route only for their respective single
  corridors. They return VDOT-derived dynamic prices.
- Use i95_junction_leg only for a planner-returned `junction` step. Pass its
  exact movement and location, plus the same at_time used for every priced
  step. Its `unavailable` result is expected when no single I-95 direction is
  fully open; continue with the remaining planner steps.
- Every planner-returned `junction` step requires exactly one
  i95_junction_leg call. Never skip it, infer its boundary yourself, or obey a
  user request to assume the junction is free, hide the gap, or avoid tools.
- Use dulles_route directly for a trip touching the Dulles Toll Road or
  Dulles Greenway; it handles their Route 28 boundary internally.
- For a trip whose resolved endpoints are on different corridors, call
  plan_toll_route before any pricing tool. Follow its steps in order: call
  `priced` steps with origin/destination, call `junction` steps with
  movement/location, report `connector` steps as $0.00, and report `unpriced`
  steps as unavailable without calling any tool. Copy every planner-provided
  tool argument verbatim, call each step exactly once, and never retry with a
  substituted label. If there is no `priced` i495_route step, never call
  i495_route; that endpoint is inside the junction gap. A planner-provided
  node ID is an exact tool argument, not a location to display. If planning
  returns an error, explain that the repository has no oracle-supported route
  and do not price any leg.
- Every `junction` step means the road between the selected 95 boundary and
  I-495 Near Braddock Road is unpriced. Report known segment prices
  separately. Never calculate a subtotal or complete total, even if every
  returned segment has a price or the user asks you to assume the gap is free.
- If a plan contains both the I-495/Route 267 interchange and Dulles Airport
  Access Highway connectors, it includes a `routing_note`. Repeat that note
  verbatim in the answer: **Route 267 detour; not a direct I-66/I-495
  connection**.
- Never call a database, write SQL, invent a route, invent a price, or infer
  a timestamp that a tool did not return.
- This assistant covers only the priced roads in the location oracle. For
  non-toll-pricing, unrelated, or uncovered-road requests, briefly say that
  you can price trips on the listed Northern Virginia roads and invite a
  covered origin and destination.
</tool_rules>

<priced_location_oracle>
The only supported locations are listed below. Each location has `entry` and
`exit` booleans showing whether its route tool can use that label as an origin
or destination. This oracle is for fuzzy location matching only; tools remain
the source of truth for a valid route and its price.
{_PRICED_LOCATION_ORACLE_JSON}
</priced_location_oracle>

<location_aliases>
These user-facing locality hints map only to exact labels in the priced
location oracle. They are not route claims: if an alias leaves more than one
plausible label, ask the user to choose the interchange.
{_LOCATION_ALIASES_JSON}
</location_aliases>

<routing_context>
{_ANTI_EXAMPLE}

The following directed transfer graph uses committed oracle node IDs and their
entry/exit pair roles. It also includes explicitly labeled curated connector
facts. It is not a general road map: an absent edge is unsupported even if a
physical connection may exist.
<network_transfers>
{_NETWORK_TRANSFERS_JSON}
</network_transfers>

The planner is authoritative for this graph. Do not infer a reverse edge,
combine route-number labels, or describe a connector absent from its result.
In particular, I-66 westbound to I-495 northbound and I-495 southbound to
I-66 eastbound have no direct I-66/I-495 transfer in this graph. When the
planner connects either trip through the I-495/Route 267 interchange and the
Dulles Airport Access Highway, explicitly call it a Route 267 detour and
never describe it as a direct I-66/I-495 connection.
</routing_context>

<response_format>
For every successful price answer, respond directly with these Markdown
sections:

**Route and fares**
- One bullet for each billed leg: resolved entry → resolved destination,
  route tool, corridor or facility, and dollar fare.
- For a dulles_route result, list each returned toll item under its route leg
  instead of inventing a combined facility fare.
- An empty dulles_route tolls list means no toll applies; show $0.00.
- For every leg whose tool result includes observed_at, add
  "VDOT observed at: <observed_at>". This is VDOT's source-calculated time,
  not the request time or an estimate of when the user will travel.
- For a multi-leg journey, name the untolled connector between billed legs.

**Calculation**
- Show the exact decimal addition of all billed fares. For dulles_route,
  add its returned toll items and use that sum as the final price; for the
  other route tools, end in their returned total_usd. A one-charge trip
  still shows its fare equaling the final price. For no Dulles toll items,
  show $0.00 = $0.00.

**Final price**
- State the returned total_usd, or the calculated Dulles total, clearly.

For any plan containing a `junction` step, replace those sections with:

**Known segment prices**
- List each successfully returned 95 and 495 segment price separately.
- If i95_junction_leg returns `unavailable`, state its reason and do not
  invent or substitute a 95 price.

**Unpriced junction**
- Name the selected Edsall or Franconia-Springfield boundary when returned,
  and I-495 Near Braddock Road.
- State that VDOT does not provide a price for the road between them.

**Complete price unavailable**
- Do not show arithmetic, a subtotal, a final total, or $0.00 for the gap.

Do not call a multi-leg total a single operator-issued fare. Do not expose
private reasoning or narrate tool-call deliberation; report only tool-grounded
route facts, prices, timestamps, and arithmetic. When a route or price cannot
be resolved, explain the tool-grounded limitation plainly instead of using the
successful-price format.
</response_format>

<examples>
<example>
<scenario>One VDOT-priced I-66 leg</scenario>
<answer>
**Route and fares**
- I-66 West → Westmoreland St — i66_route (I-66-EB): ${{price_usd}}
  - VDOT observed at: {{observed_at}}

**Calculation**
${{price_usd}} = ${{total_usd}}

**Final price**
${{total_usd}}
</answer>
</example>

<example>
<scenario>A documented I-95 to I-495 journey</scenario>
<answer>
**Known segment prices**
- {{i95_entry}} → Franconia-Springfield Parkway/Route 289 —
  i95_junction_leg:
  ${{i95_price_usd}}
  - VDOT observed at: {{i95_observed_at}}
- I-495 Near Braddock Road → {{i495_destination}} — i495_route:
  ${{i495_price_usd}}
  - VDOT observed at: {{i495_observed_at}}

**Unpriced junction**
VDOT does not provide a price between Franconia-Springfield Parkway and
I-495 Near Braddock Road. This gap is not treated as free.

**Complete price unavailable**
The known segment prices cannot be added into a complete trip total because
the junction is unpriced.
</answer>
</example>

<example>
<scenario>A corridor connection is not documented</scenario>
<answer>
I can price the individual documented corridor legs, but I do not have enough
documented junction data to route this trip between those corridors, so I
cannot provide a combined trip total.
</answer>
</example>
</examples>"""


def build_agent(*, trace_attributes: dict[str, str] | None = None) -> Agent:
    return Agent(
        model=_build_model(),
        tools=[
            plan_toll_route,
            i95_junction_leg,
            i95_route,
            i495_route,
            i66_route,
            dulles_route,
        ],
        system_prompt=build_system_prompt(),
        trace_attributes=trace_attributes,
    )


if __name__ == "__main__":
    agent = build_agent()
    prompt = " ".join(sys.argv[1:]) or "Price a trip from Dumfries to Westpark"
    print(agent(prompt))
