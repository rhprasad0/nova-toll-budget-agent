"""toll_agent: a strands.Agent (Bedrock Claude Haiku) that prices NoVA trips
by calling the five existing agent_tools/*.py tools -- find_toll_locations,
i95_route, i495_route, i66_route, dulles_route. It never touches RDS or
issues SQL itself; every price comes from one of those tools (the same
constraint that led to lambdas/agent/* being deleted -- see README.md and
db/drop_agent_surface.sql).

Each of those tools deliberately refuses to resolve a cross-corridor trip
(docs/oracle-findings.md section 8) -- a caller wanting Dumfries (I-95) to
Westpark Drive (I-495) gets two independent single-corridor answers, not one
combined trip. A manual smoke test proved a Haiku agent left to figure out
the split on its own will happily overshoot: asked to price that exact trip,
it first ran the I-95 leg all the way to "Washington D.C." (past the real
junction) before being told to stop at the Springfield interchange. JUNCTIONS
below bakes that correction in up front instead of requiring it interactively
every time.

JUNCTIONS was hand-derived by reading the committed oracle node/label fields
directly (oracles/i95.json, i66.json, dulles_toll_road.json,
dulles_greenway.json, i66_otb.json) -- not general geography knowledge, not
published by any operator. Evidence strength varies per entry: "verbatim"
(identical label/shared key on both sides) is strongest, "route-number"
(a route-number correlation, not a verbatim match) is weaker but still
directional. Two negative entries are included deliberately (dulles_greenway
<-> i495, i66_otb <-> dulles_toll_road) so the agent says "not enough data"
instead of guessing when a pair was checked and found unevidenced.

strands.Agent's system_prompt accepts str | list[SystemContentBlock], and
SystemContentBlock only has text/cachePoint keys (strands/types/content.py)
-- there's no structured-knowledge field, so JUNCTIONS goes in as literal
json.dumps(...) text inside the prompt string, not any special mechanism.

See docs/oracle-tools-spec.md for the tool contract this builds on.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from strands import Agent
from strands.models import BedrockModel, CacheToolsConfig

# agent_tools/ has no __init__.py (flat siblings, same as i95_route.py's own
# sys.path comment) -- a dotted "from agent_tools.i95_route import ..."
# doesn't work, so it must be on sys.path directly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent_tools"))
from dulles_route import dulles_route
from find_toll_locations import find_toll_locations
from i66_route import i66_route
from i95_route import i95_route
from i495_route import i495_route

JUNCTIONS = {
    ("i95", "i495"): {
        "evidence": "verbatim label, same physical Springfield interchange",
        "source": "oracles/i95.json",
        "i95_side": {
            "node_ids": ["206ND", "206NO", "206SO", "206SD"],
            "label": "Franconia-Springfield Parkway/Route 289",
        },
        "i495_side": {
            "node_ids": ["192NO", "192SD"],
            "label": "I-495/I-95 Near Van Dorn Street",
        },
    },
    ("i66_itb", "i495"): {
        "evidence": (
            "label cross-reference (i66.json labels I-495 directly; "
            "i95.json's 495-path nodes are labeled Interstate 66)"
        ),
        "source": "oracles/i66.json, oracles/i95.json",
        "i66_itb_side": {
            "node_ids": ["2", "3", "5"],
            "label": "I-495 N / I-495 Express Lanes N / I-495 S",
        },
        "i495_side": {"node_ids": ["187NO", "187SD"], "label": "Interstate 66"},
    },
    ("i495", "dulles_toll_road"): {
        "evidence": (
            "route-number correlation (weaker), corroborated independently "
            "by oracles/i66.json node 6"
        ),
        "source": "oracles/i95.json, oracles/dulles_toll_road.json, oracles/i66.json",
        "i495_side": {"node_ids": ["182NO", "182SD"], "label": "Route 267"},
        "dulles_toll_road_side": {
            "node_ids": ["1819"],
            "label": "Exit 18/19 - I-495 / SR 123 (Capital Beltway)",
        },
    },
    ("dulles_toll_road", "dulles_greenway"): {
        "evidence": "verbatim label + shared node key '28' in both files -- strongest match",
        "source": "oracles/dulles_toll_road.json, oracles/dulles_greenway.json",
        "note": (
            "Do NOT split this pair manually -- dulles_route.py already "
            "resolves it as one composite two-leg call internally (see that "
            "module's own docstring). Call dulles_route(origin, destination) "
            "directly."
        ),
        "node_ids": ["28"],
        "label": "Route 28 (Dulles Toll Road / Dulles Greenway)",
    },
    # Negative results -- checked-and-absent, not just unmentioned.
    ("dulles_greenway", "i495"): {
        "evidence": (
            "NOT EVIDENCED -- no 495/Beltway label anywhere in "
            "oracles/dulles_greenway.json"
        ),
        "note": (
            "A Greenway<->495 trip has no direct junction; it must route "
            "through dulles_toll_road as an intermediate leg via the "
            "dulles_toll_road<->dulles_greenway junction above."
        ),
    },
    ("i66_otb", "dulles_toll_road"): {
        "evidence": (
            "NOT EVIDENCED -- no shared node id/label between "
            "oracles/i66_otb.json and the Dulles oracles despite geographic "
            "proximity"
        ),
        "note": (
            "Do not guess a junction here. Also: no pricing tool exists for "
            "I-66 OTB at all -- find_toll_locations can resolve a label on "
            "it, but no route tool can price it."
        ),
    },
}

# json.dumps requires string dict keys; JUNCTIONS' tuple keys are the
# ergonomic form to read/maintain above, converted once here for the prompt.
_JUNCTIONS_JSON = json.dumps(
    {" <-> ".join(pair): data for pair, data in JUNCTIONS.items()}, indent=2
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


def build_system_prompt() -> str:
    """Static system prompt: tool-routing context and response contract.

    Pure function, no AWS calls -- callable in a test with no network/creds.
    """
    return f"""<role>
You are a Northern Virginia toll-pricing assistant. Give users accurate,
auditable toll estimates grounded only in the registered tools' results.
</role>

<tool_rules>
- Use find_toll_locations before pricing an origin or destination that is not
  already a known exact corridor label. It resolves vague or misspelled
  locations and identifies their corridor.
- Use i95_route, i495_route, and i66_route only for their respective single
  corridors. They return VDOT-derived dynamic prices.
- Use dulles_route directly for a trip touching the Dulles Toll Road or
  Dulles Greenway; it handles their Route 28 boundary internally.
- Never call a database, write SQL, invent a route, invent a price, or infer
  a timestamp that a tool did not return.
</tool_rules>

<routing_context>
{_ANTI_EXAMPLE}

The following corridor-pair junctions were derived from committed route-map
data, not general geographic knowledge. Keys use "corridor_a <-> corridor_b".
<junctions>
{_JUNCTIONS_JSON}
</junctions>

For a trip crossing two corridors, end leg 1 at the origin corridor's
junction label and begin leg 2 at the destination corridor's junction label.
If no junction is listed, or its evidence says "NOT EVIDENCED", explain that
there is not enough documented data to route the trip. Do not guess.
</routing_context>

<response_format>
For every successful price answer, respond directly with these Markdown
sections:

**Route and fares**
- One bullet for each billed leg: resolved entry → resolved destination,
  route tool, corridor or facility, and dollar fare.
- For every leg whose tool result includes observed_at, add
  "VDOT observed at: <observed_at>". This is VDOT's source-calculated time,
  not the request time or an estimate of when the user will travel.
- For a multi-leg journey, name the untolled connector between billed legs.

**Calculation**
- Show the exact decimal addition of all billed leg fares, ending in the
  returned total_usd. A one-leg trip still shows its fare equaling total_usd.

**Final price**
- State the returned total_usd clearly.

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


def build_agent() -> Agent:
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
        tools=[find_toll_locations, i95_route, i495_route, i66_route, dulles_route],
        system_prompt=[
            {"text": build_system_prompt()},
            # Cache the static instructions after the cached tool definitions.
            {"cachePoint": {"type": "default", "ttl": "5m"}},
        ],
    )


if __name__ == "__main__":
    agent = build_agent()
    prompt = " ".join(sys.argv[1:]) or "Price a trip from Dumfries to Westpark"
    print(agent(prompt))
