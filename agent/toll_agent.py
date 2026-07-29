"""toll_agent: a strands.Agent (Bedrock Claude Haiku) that prices NoVA trips
by calling the four existing agent_tools/*.py pricing tools -- i95_route,
i495_route, i66_route, dulles_route. It never touches RDS or issues SQL
itself; every price comes from one of those tools (the same
constraint that led to lambdas/agent/* being deleted -- see README.md and
db/drop_agent_surface.sql).

Each of those tools deliberately refuses to resolve a cross-corridor trip
(docs/oracle-findings.md section 8) -- a caller wanting Dumfries (I-95) to
Westpark Drive (I-495) gets two independent single-corridor answers, not one
combined trip. A manual smoke test proved a Haiku agent left to figure out
the split on its own will happily overshoot. NETWORK_TRANSFERS turns committed
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
import sys
from pathlib import Path

from strands import Agent, tool
from strands.models import BedrockModel, CacheToolsConfig

# agent_tools/ has no __init__.py (flat siblings, same as i95_route.py's own
# sys.path comment) -- a dotted "from agent_tools.i95_route import ..."
# doesn't work, so it must be on sys.path directly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent_tools"))
from dulles_route import dulles_route
from i66_route import i66_route
from i95_route import i95_route
from i495_route import i495_route

_ORACLE_DIR = Path(__file__).resolve().parent.parent / "oracles"


def _locations(nodes: dict, pairs: list) -> list[dict[str, str | bool]]:
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


def _load_priced_location_oracle() -> dict[str, dict]:
    """Prompt knowledge only; route tools remain the pricing source of truth."""
    i95 = json.loads((_ORACLE_DIR / "i95.json").read_text())
    i66 = json.loads((_ORACLE_DIR / "i66.json").read_text())

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
    dulles_toll_road = json.loads((_ORACLE_DIR / "dulles_toll_road.json").read_text())
    dulles_greenway = json.loads((_ORACLE_DIR / "dulles_greenway.json").read_text())
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

NETWORK_TRANSFERS = [
    {
        "id": "i95_to_i495",
        "from": {
            "corridor": "i95",
            "exit": "Franconia-Springfield Parkway/Route 289",
            "node_id": "206ND",
        },
        "to": {
            "corridor": "i495",
            "entry": "I-495/I-95 Near Van Dorn Street",
            "node_id": "192NO",
        },
        "connector": "Springfield interchange",
        "evidence": "oracles/i95.json pair roles at nodes 206ND and 192NO",
    },
    {
        "id": "i495_to_i95",
        "from": {
            "corridor": "i495",
            "exit": "I-495/I-95 Near Van Dorn Street",
            "node_id": "192SD",
        },
        "to": {
            "corridor": "i95",
            "entry": "Franconia-Springfield Parkway/Route 289",
            "node_id": "206NO",
        },
        "connector": "Springfield interchange",
        "evidence": "oracles/i95.json pair roles at nodes 192SD and 206NO",
    },
    {
        "id": "i66_to_i495",
        "from": {"corridor": "i66_itb", "exit": "I-495 S", "node_id": "5"},
        "to": {"corridor": "i495", "entry": "Interstate 66", "node_id": "187NO"},
        "connector": "I-66/I-495 interchange",
        "evidence": "oracles/i66.json node 5 and oracles/i95.json node 187NO pair roles",
    },
    {
        "id": "i495_to_i66",
        "from": {"corridor": "i495", "exit": "Interstate 66", "node_id": "187SD"},
        "to": {"corridor": "i66_itb", "entry": "I-495 N", "node_id": "2"},
        "connector": "I-66/I-495 interchange",
        "evidence": "oracles/i95.json node 187SD and oracles/i66.json node 2 pair roles",
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
_DULLES_GATEWAY = "Exit 18/19 - I-495 / SR 123 (Capital Beltway)"


def _load_direct_pair_oracles() -> dict[str, tuple[dict, list]]:
    """The three single-corridor tools accept only a published direct pair."""
    i95 = json.loads((_ORACLE_DIR / "i95.json").read_text())
    i66 = json.loads((_ORACLE_DIR / "i66.json").read_text())

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
the real trip should stop earlier, at the Springfield interchange, and
continue on I-495. Before calling any pricing tool on a trip that might span
two corridors, check whether the origin and destination resolve to different
corridors. If they do, split the trip at the documented junction below and
price each leg separately -- never pass the far-corridor destination
straight to a single tool."""


def _validate_location(corridor: str, label: str, role: str) -> dict | None:
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


def _transfer_path(origin: str, destination: str) -> list[dict] | None:
    frontier = [(origin, [])]
    visited = {origin}
    while frontier:
        corridor, path = frontier.pop(0)
        if corridor == destination:
            return path
        for transfer in NETWORK_TRANSFERS:
            next_corridor = transfer["to"]["corridor"]
            if (
                transfer["from"]["corridor"] == corridor
                and next_corridor not in visited
            ):
                visited.add(next_corridor)
                frontier.append((next_corridor, [*path, transfer]))
    return None


def _priced_step(corridor: str, origin: str, destination: str) -> dict:
    return {
        "kind": "priced",
        "corridor": corridor,
        "tool": _PRICED_LOCATION_ORACLE[corridor]["tool"],
        "origin": origin,
        "destination": destination,
    }


@tool
def plan_toll_route(
    origin_corridor: str,
    origin: str,
    destination_corridor: str,
    destination: str,
) -> dict:
    """Return the only oracle-supported pricing and connector steps for a trip.

    Call after resolving the user's location to exact prompt-oracle labels and
    before any pricing tool on a cross-corridor trip. Inputs must be exact;
    this tool does not fuzzy-match or invent roads. Its `priced` steps are the
    only pricing-tool calls permitted for the trip. `connector` steps are $0
    in this pricing model and must never be sent to a pricing tool. Connector
    boundaries use oracle node IDs so their directed entry/exit roles are not
    lost to duplicate human-readable labels.
    """
    if origin_corridor not in _LOCATION_BY_CORRIDOR:
        return {"error": f"unknown origin corridor {origin_corridor!r}"}
    if destination_corridor not in _LOCATION_BY_CORRIDOR:
        return {"error": f"unknown destination corridor {destination_corridor!r}"}
    if error := _validate_location(origin_corridor, origin, "entry"):
        return error
    if error := _validate_location(destination_corridor, destination, "exit"):
        return error

    if (
        origin_corridor == destination_corridor
        or {
            origin_corridor,
            destination_corridor,
        }
        <= _DULLES_CORRIDORS
    ):
        if origin_corridor not in _DULLES_CORRIDORS and not _has_direct_pair(
            origin_corridor, origin, destination
        ):
            return {
                "error": (
                    "planner produced no oracle-supported direct trip from "
                    f"{origin!r} to {destination!r} on {origin_corridor}"
                )
            }
        return {"steps": [_priced_step(origin_corridor, origin, destination)]}

    steps: list[dict] = []
    if origin_corridor == "dulles_greenway":
        # dulles_route owns its Route 28 boundary and returns both tolls.
        steps.append(_priced_step(origin_corridor, origin, _DULLES_GATEWAY))
        origin_corridor, origin = "dulles_toll_road", _DULLES_GATEWAY

    transfers = _transfer_path(origin_corridor, destination_corridor)
    if transfers is None:
        return {
            "error": (
                "no oracle-supported directed transfer connects "
                f"{origin_corridor} to {destination_corridor}"
            )
        }

    current_corridor, current_point, current_label = origin_corridor, origin, origin
    for transfer in transfers:
        exit_label = transfer["from"]["exit"]
        if current_label != exit_label:
            steps.append(
                _priced_step(
                    current_corridor, current_point, transfer["from"]["node_id"]
                )
            )
        steps.append(
            {
                "kind": "connector",
                "label": transfer["connector"],
                "price_usd": "0.00",
            }
        )
        current_corridor, current_point, current_label = (
            transfer["to"]["corridor"],
            transfer["to"]["node_id"],
            transfer["to"]["entry"],
        )
    if current_label != destination:
        steps.append(_priced_step(current_corridor, current_point, destination))

    for step in steps:
        if (
            step["kind"] == "priced"
            and step["corridor"] not in _DULLES_CORRIDORS
            and not _has_direct_pair(
                step["corridor"], step["origin"], step["destination"]
            )
        ):
            return {
                "error": (
                    "planner produced no oracle-supported direct trip from "
                    f"{step['origin']!r} to {step['destination']!r} on "
                    f"{step['corridor']}"
                )
            }
    return {"steps": steps}


def build_system_prompt() -> str:
    """Static system prompt: tool-routing context and response contract.

    Pure function, no AWS calls -- callable in a test with no network/creds.
    """
    return f"""<role>
You are a Northern Virginia toll-pricing assistant. Give users accurate,
auditable toll estimates grounded only in the registered tools' results.
</role>

<tool_rules>
- Match vague, partial, or misspelled locations to the closest appropriate
  exact label in the priced location oracle below. Use that exact label in a
  pricing-tool call. If more than one listed label could reasonably mean the
  user's location, ask a concise clarifying question instead of guessing.
- If a location has no clear match in the priced location oracle, or is on an
  unlisted road, explain that it is outside coverage and do not call a pricing
  tool. Never substitute a nearby listed road or ramp for an uncovered one,
  including I-66 Outside the Beltway.
- Use i95_route, i495_route, and i66_route only for their respective single
  corridors. They return VDOT-derived dynamic prices.
- Use dulles_route directly for a trip touching the Dulles Toll Road or
  Dulles Greenway; it handles their Route 28 boundary internally.
- For a trip whose resolved endpoints are on different corridors, call
  plan_toll_route before any pricing tool. Call only the `priced` steps it
  returns, in order. Report each `connector` step as $0.00; never call a
  pricing tool for it. A planner-provided node ID is an exact tool argument,
  not a location to display to the user. If planning returns an error, explain that the
  repository has no oracle-supported combined route and do not price any leg.
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
**Route and fares**
- {{i95_entry}} → Franconia-Springfield Parkway/Route 289 — i95_route:
  ${{i95_price_usd}}
  - VDOT observed at: {{i95_observed_at}}
- Untolled connector: Springfield interchange.
- I-495/I-95 Near Van Dorn Street → {{i495_destination}} — i495_route:
  ${{i495_price_usd}}
  - VDOT observed at: {{i495_observed_at}}

**Calculation**
${{i95_price_usd}} + ${{i495_price_usd}} = ${{total_usd}}

**Final price**
${{total_usd}}
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
    model = BedrockModel(
        # Bedrock rejects the plain model id for on-demand throughput
        # (verified empirically: ValidationException, "Retry your request
        # with the ID or ARN of an inference profile") -- the "us." prefix
        # is the cross-region inference profile id, confirmed working.
        model_id="us.anthropic.claude-haiku-4-5-20251001-v1:0",
        region_name="us-east-1",
        temperature=0,  # deterministic tool routing, not creative prose
        streaming=False,
        max_tokens=2048,
        # Keep the fixed tool schema prefix in Bedrock's 5-minute cache.
        # The matching system-prompt cache point below extends that prefix.
        cache_tools=CacheToolsConfig(type="default", ttl="5m"),
    )
    return Agent(
        model=model,
        tools=[plan_toll_route, i95_route, i495_route, i66_route, dulles_route],
        system_prompt=[
            {"text": build_system_prompt()},
            # Cache the static instructions after the cached tool definitions.
            {"cachePoint": {"type": "default", "ttl": "5m"}},
        ],
        trace_attributes=trace_attributes,
    )


if __name__ == "__main__":
    agent = build_agent()
    prompt = " ".join(sys.argv[1:]) or "Price a trip from Dumfries to Westpark"
    print(agent(prompt))
