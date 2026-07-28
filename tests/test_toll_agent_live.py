"""End-to-end check that agent/toll_agent.py's Haiku agent doesn't overshoot
a cross-corridor trip -- the exact regression a manual smoke test caught
(Dumfries -> Westpark priced the I-95 leg all the way to Washington D.C.
before the agent was told to stop at the Springfield interchange).

Hits live Bedrock (and, via the tools it calls, live RDS) -- deliberately
marked `live` and excluded from the default `pytest` run (see
pyproject.toml addopts), same convention as
tests/test_route_tools_live_crosscheck.py. Run explicitly:

    uv run pytest -m live tests/test_toll_agent_live.py -v

Deliberately does not assert on dollar amounts: trip_pricing_i95/
trip_pricing_i495 refresh every 10 minutes, so a hard-coded price fails
tomorrow and reads as an agent regression when it's just a stale rate.
Instead this walks the tool-call trace in agent.messages and asserts on
*leg boundaries* -- did the agent actually stop at the junction, not just
"did some price come back".
"""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "agent"))

from toll_agent import build_agent

pytestmark = pytest.mark.live

# The i95-side junction labels a correctly-bounded leg 1 must end at, and
# the i495-side junction labels a correctly-bounded leg 2 must start at --
# see agent/toll_agent.py's JUNCTIONS[("i95", "i495")].
_I95_JUNCTION_NODE_IDS = {"206ND", "206NO", "206SO", "206SD"}
_I495_JUNCTION_NODE_IDS = {"192NO", "192SD"}


def _tool_uses(agent, tool_name: str) -> list[dict]:
    uses = []
    for message in agent.messages:
        for block in message.get("content", []):
            tool_use = block.get("toolUse")
            if tool_use and tool_use.get("name") == tool_name:
                uses.append(tool_use)
    return uses


def test_dumfries_to_westpark_splits_at_springfield_not_dc():
    agent = build_agent()
    agent("Price a trip from Dumfries to Westpark")

    i95_calls = _tool_uses(agent, "i95_route")
    i495_calls = _tool_uses(agent, "i495_route")

    assert i95_calls, "expected the agent to call i95_route for the Dumfries leg"
    assert i495_calls, "expected the agent to call i495_route for the Westpark leg"

    # Every i95_route call in this trip must stop at the junction -- none may
    # overshoot to Washington D.C. or any other far-corridor destination.
    i95_junction_markers = _I95_JUNCTION_NODE_IDS | {"Franconia", "Springfield"}
    for call in i95_calls:
        destination = call["input"].get("destination", "")
        assert any(marker in destination for marker in i95_junction_markers), (
            f"i95_route destination {destination!r} does not resolve to the Springfield junction"
        )
        assert "Washington" not in destination

    # At least one i495_route call must start from the junction.
    i495_junction_markers = _I495_JUNCTION_NODE_IDS | {"Van Dorn"}
    assert any(
        marker in call["input"].get("origin", "")
        for call in i495_calls
        for marker in i495_junction_markers
    ), "expected an i495_route call originating at the Van Dorn Street junction"
