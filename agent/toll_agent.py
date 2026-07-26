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
from strands.models import BedrockModel

# agent_tools/ has no __init__.py (flat siblings, same as i95_route.py's own
# sys.path comment) -- a dotted "from agent_tools.i95_route import ..."
# doesn't work, so it must be on sys.path directly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent_tools"))
from dulles_route import dulles_route  # noqa: E402
from find_toll_locations import find_toll_locations  # noqa: E402
from i66_route import i66_route  # noqa: E402
from i95_route import i95_route  # noqa: E402
from i495_route import i495_route  # noqa: E402

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
    """Static system prompt: role, tool roster, the overshoot correction,
    the junction table as literal JSON text, and reporting rules.

    Pure function, no AWS calls -- callable in a test with no network/creds.
    """
    return f"""You price Northern Virginia express-lane and toll-road trips by calling the
tools below. You never call a database or write SQL yourself -- every price
comes from one of these five tools.

Tools:
- find_toll_locations: resolves a vague or misspelled location to the exact
  interchange label a pricing tool expects, and tells you which corridor(s)
  it belongs to.
- i95_route, i495_route, i66_route: price a single corridor each (95/395
  Express Lanes, 495 Express Lanes, I-66 Inside the Beltway). RDS-backed,
  live prices.
- dulles_route: prices the Dulles Toll Road and Dulles Greenway. Fixed-toll,
  already handles the junction between those two facilities internally --
  call it directly for any trip touching either, never split it yourself.

Always call find_toll_locations first for any origin or destination that
isn't already a known exact corridor label, to learn which corridor(s) it
belongs to.

{_ANTI_EXAMPLE}

Corridor-pair junctions (hand-derived from the committed route-map data,
not general knowledge -- keys are "corridor_a <-> corridor_b"):
{_JUNCTIONS_JSON}

For a trip crossing two corridors: leg 1's destination is the origin
corridor's label at the junction; leg 2's origin is the destination
corridor's label at the same junction. If a corridor pair has no entry
above, or its entry says "NOT EVIDENCED", say plainly that you don't have
enough data to route between them -- never invent a connection.

Never report a single fused price for a multi-leg trip. Report each leg's
tool, resolved origin/destination, and price separately, name the untolled
connector between legs, then give a clearly-labeled summed total -- these
are genuinely separate billed facilities, not one trip."""


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
    )
    return Agent(
        model=model,
        tools=[find_toll_locations, i95_route, i495_route, i66_route, dulles_route],
        system_prompt=build_system_prompt(),
    )


if __name__ == "__main__":
    agent = build_agent()
    prompt = " ".join(sys.argv[1:]) or "Price a trip from Dumfries to Westpark"
    print(agent(prompt))
