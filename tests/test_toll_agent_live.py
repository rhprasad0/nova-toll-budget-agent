"""End-to-end checks for direction-aware junction pricing.

Hits live OpenAI (and, via the tools it calls, live RDS) -- deliberately
marked `live` and excluded from the default `pytest` run (see
pyproject.toml addopts), same convention as
tests/test_route_tools_live_crosscheck.py. Run explicitly:

    AWS_PROFILE=nova-toll uv run pytest -m live tests/test_toll_agent_live.py -v

Deliberately does not assert on dollar amounts: `trip_pricing_i95` refreshes
every 10 minutes, so a hard-coded price fails
tomorrow and reads as an agent regression when it's just a stale rate.
Instead this walks the tool-call trace in the response metrics and asserts on
*leg boundaries* -- did the agent actually stop at the junction, not just
"did some price come back".
"""

import json
from pathlib import Path

import boto3
import pytest

from agent.toll_agent import build_agent

REPO_ROOT = Path(__file__).resolve().parent.parent

pytestmark = pytest.mark.live

AWS_PROFILE = "nova-toll"
AWS_REGION = "us-east-1"
DB_IDENTIFIER = "nova-toll-db"
CA_BUNDLE_PATH = REPO_ROOT / "infra" / "build" / "loader" / "rds-ca-bundle.pem"

_PRICING_TOOLS = {"i95_route", "i495_route", "i66_route", "dulles_route"}
_AGENT_TOOLS = _PRICING_TOOLS | {"i95_junction_leg"}

_BOUNDARY_CASES = [
    (
        "i95-to-i495",
        (
            "Price Courthouse Road/Route 630 on the I-95 Express Lanes to "
            "Westpark Drive on the I-495 Express Lanes."
        ),
        [],
    ),
    (
        "i495-to-i95",
        (
            "Price Westpark Drive on the I-495 Express Lanes to Pentagon/Eads "
            "Street on the I-95/395 Express Lanes."
        ),
        [],
    ),
    (
        "i66-west-to-i495-south-direct",
        (
            "Price Lee Highway - Scott Street on I-66 Inside the Beltway to "
            "Braddock Road on the I-495 Express Lanes."
        ),
        ["I-66/I-495 interchange"],
    ),
    (
        "i495-north-to-i66-east-direct",
        (
            "Price Braddock Road on the I-495 Express Lanes to Washington on "
            "I-66 Inside the Beltway."
        ),
        ["I-66/I-495 interchange"],
    ),
    (
        "i66-west-to-i495-north-detour",
        (
            "Price Lee Highway - Scott Street on I-66 Inside the Beltway to "
            "the 495 Express Lanes End at George Washington Memorial Parkway."
        ),
        [
            "Dulles Airport Access Highway",
            "I-495/Route 267 interchange",
        ],
    ),
    (
        "i495-south-to-i66-east-detour",
        (
            "Price the 495 Express Lanes Start at George Washington Memorial "
            "Parkway to Washington on I-66 Inside the Beltway."
        ),
        [
            "I-495/Route 267 interchange",
            "Dulles Airport Access Highway",
        ],
    ),
    (
        "dulles-east-to-i495-south",
        (
            "Price Exit 12 - SR 602 (Reston Pkwy) on the Dulles Toll Road to "
            "Braddock Road on the I-495 Express Lanes."
        ),
        ["I-495/Route 267 interchange"],
    ),
    (
        "dulles-east-to-i495-north",
        (
            "Price Exit 12 - SR 602 (Reston Pkwy) on the Dulles Toll Road to "
            "the 495 Express Lanes End at George Washington Memorial Parkway."
        ),
        ["I-495/Route 267 interchange"],
    ),
    (
        "i495-north-to-dulles-west",
        (
            "Price Braddock Road on the I-495 Express Lanes to Exit 12 - SR 602 "
            "(Reston Pkwy) on the Dulles Toll Road."
        ),
        ["I-495/Route 267 interchange"],
    ),
    (
        "i495-south-to-dulles-west",
        (
            "Price the 495 Express Lanes Start at George Washington Memorial "
            "Parkway to Exit 12 - SR 602 (Reston Pkwy) on the Dulles Toll Road."
        ),
        ["I-495/Route 267 interchange"],
    ),
    (
        "i66-west-to-i495-south-direct-paraphrase",
        (
            "How much is westbound I-66 from Lee Highway/Scott Street, then "
            "southbound 495 Express to Braddock Road?"
        ),
        ["I-66/I-495 interchange"],
    ),
    (
        "i495-north-to-i66-east-direct-paraphrase",
        (
            "What is the toll from Braddock Road northbound on 495 Express to "
            "Washington via eastbound I-66 Inside the Beltway?"
        ),
        ["I-66/I-495 interchange"],
    ),
    (
        "i66-west-to-i495-north-detour-paraphrase",
        (
            "Price Lee Highway/Scott Street westbound on I-66 to the north end "
            "of the 495 Express Lanes at George Washington Memorial Parkway."
        ),
        [
            "Dulles Airport Access Highway",
            "I-495/Route 267 interchange",
        ],
    ),
    (
        "i495-south-to-i66-east-detour-paraphrase",
        (
            "How much from the George Washington Parkway start of southbound "
            "495 Express to Washington on eastbound I-66?"
        ),
        [
            "I-495/Route 267 interchange",
            "Dulles Airport Access Highway",
        ],
    ),
    (
        "dulles-east-to-i495-south-paraphrase",
        (
            "Price Reston Parkway eastbound on the Dulles Toll Road to Braddock "
            "Road southbound on 495 Express."
        ),
        ["I-495/Route 267 interchange"],
    ),
    (
        "dulles-east-to-i495-north-paraphrase",
        (
            "How much from Reston Parkway eastbound on the Dulles Toll Road to "
            "the north end of 495 Express at GW Parkway?"
        ),
        ["I-495/Route 267 interchange"],
    ),
    (
        "i495-north-to-dulles-west-paraphrase",
        (
            "Price Braddock Road northbound on 495 Express to Reston Parkway "
            "westbound on the Dulles Toll Road."
        ),
        ["I-495/Route 267 interchange"],
    ),
    (
        "i495-south-to-dulles-west-paraphrase",
        (
            "What is the toll from the GW Parkway start of southbound 495 "
            "Express to Reston Parkway on the Dulles Toll Road?"
        ),
        ["I-495/Route 267 interchange"],
    ),
    (
        "i66-to-dulles",
        (
            "Price Fairfax Drive on I-66 Inside the Beltway to Exit 12 - SR 602 "
            "(Reston Pkwy) on the Dulles Toll Road."
        ),
        ["Dulles Airport Access Highway"],
    ),
    (
        "dulles-to-i66",
        (
            "Price Exit 12 - SR 602 (Reston Pkwy) on the Dulles Toll Road to "
            "Westmoreland St on I-66 Inside the Beltway."
        ),
        ["Dulles Airport Access Highway"],
    ),
    (
        "greenway-to-dulles",
        (
            "Price Exit 1 - US 15/SR 7 (Leesburg Bypass) on the Dulles Greenway "
            "to Exit 12 - SR 602 (Reston Pkwy) on the Dulles Toll Road."
        ),
        [],
    ),
    (
        "dulles-to-greenway",
        (
            "Price Exit 12 - SR 602 (Reston Pkwy) on the Dulles Toll Road to "
            "Exit 3 - SR 653 (Shreve Mill Rd) on the Dulles Greenway."
        ),
        [],
    ),
    (
        "i495-to-greenway",
        (
            "Price Westpark Drive on the I-495 Express Lanes to Exit 3 - SR 653 "
            "(Shreve Mill Rd) on the Dulles Greenway."
        ),
        ["I-495/Route 267 interchange"],
    ),
    (
        "i95-to-greenway",
        (
            "Price Courthouse Road/Route 630 on the I-95 Express Lanes to Exit 3 "
            "- SR 653 (Shreve Mill Rd) on the Dulles Greenway."
        ),
        ["I-495/Route 267 interchange"],
    ),
    (
        "i95-to-i66-via-direct-junction",
        (
            "Price Courthouse Road/Route 630 on the I-95 Express Lanes to Fairfax "
            "Drive on I-66 Inside the Beltway."
        ),
        ["I-66/I-495 interchange"],
    ),
]
_JUNCTION_MATRIX_CASES = {
    "i66-west-to-i495-south-direct",
    "i495-north-to-i66-east-direct",
    "i66-west-to-i495-north-detour",
    "i495-south-to-i66-east-detour",
    "dulles-east-to-i495-south",
    "dulles-east-to-i495-north",
    "i495-north-to-dulles-west",
    "i495-south-to-dulles-west",
}


def _trace_messages(response) -> list[dict]:
    def walk(trace):
        messages = [trace["message"]] if trace.get("message") else []
        for child in trace.get("children", []):
            messages.extend(walk(child))
        return messages

    return [
        message
        for trace in response.metrics.get_summary().get("traces", [])
        for message in walk(trace)
    ]


def _tool_uses(response, tool_name: str) -> list[dict]:
    uses = []
    for message in _trace_messages(response):
        for block in message.get("content", []):
            tool_use = block.get("toolUse")
            if tool_use and tool_use.get("name") == tool_name:
                uses.append(tool_use)
    return uses


def _tool_results(response, tool_name: str) -> list[dict]:
    tool_use_ids = {
        block["toolUse"]["toolUseId"]
        for message in _trace_messages(response)
        for block in message.get("content", [])
        if block.get("toolUse", {}).get("name") == tool_name
    }
    return [
        json.loads(result["content"][0]["text"])
        for message in _trace_messages(response)
        for block in message.get("content", [])
        if (result := block.get("toolResult"))
        and result["toolUseId"] in tool_use_ids
        and result["status"] == "success"
    ]


def _pricing_tool_uses(response) -> list[dict]:
    return [
        tool_use
        for message in _trace_messages(response)
        for block in message.get("content", [])
        if (tool_use := block.get("toolUse")) and tool_use.get("name") in _PRICING_TOOLS
    ]


def _route_tool_uses(response) -> list[dict]:
    return [
        tool_use
        for message in _trace_messages(response)
        for block in message.get("content", [])
        if (tool_use := block.get("toolUse")) and tool_use.get("name") in _AGENT_TOOLS
    ]


def _tool_result(response, tool_use_id: str) -> dict:
    [result] = [
        json.loads(tool_result["content"][0]["text"])
        for message in _trace_messages(response)
        for block in message.get("content", [])
        if (tool_result := block.get("toolResult"))
        and tool_result["toolUseId"] == tool_use_id
    ]
    return result


def _resolved_endpoints(result: dict) -> tuple[dict, dict]:
    if "entry" in result:
        return result["entry"], result["exit"]
    return result["legs"][0]["entry"], result["legs"][-1]["exit"]


def _same_endpoint(expected: str, actual_input: str, resolved: dict) -> bool:
    return (
        expected == actual_input
        or expected == resolved["node_id"]
        or expected.casefold() == resolved["label"].casefold()
    )


@pytest.fixture
def live_pricing_env(monkeypatch):
    """Configure the agent's VDOT route tools for read-only live RDS access."""
    if not CA_BUNDLE_PATH.exists():
        pytest.skip(f"{CA_BUNDLE_PATH} missing -- run scripts/build_zips.sh first")

    try:
        session = boto3.Session(profile_name=AWS_PROFILE)
        instance = session.client("rds", region_name=AWS_REGION).describe_db_instances(
            DBInstanceIdentifier=DB_IDENTIFIER
        )["DBInstances"][0]
    except Exception as e:  # noqa: BLE001 -- local credentials/network are optional
        pytest.skip(f"could not describe {DB_IDENTIFIER}: {e}")

    monkeypatch.setenv("AWS_PROFILE", AWS_PROFILE)
    monkeypatch.setenv("AWS_DEFAULT_REGION", AWS_REGION)
    monkeypatch.setenv("DB_HOST", instance["Endpoint"]["Address"])
    monkeypatch.setenv("DB_PORT", str(instance["Endpoint"]["Port"]))
    monkeypatch.setenv("DB_NAME", instance["DBName"])
    monkeypatch.setenv("DB_USER", "pricing_reader")
    monkeypatch.setenv("DB_CA_BUNDLE_PATH", str(CA_BUNDLE_PATH))


def test_agent_reuses_the_explicit_system_prompt_cache():
    warmup = build_agent()
    warmup("Reply with exactly CACHE_WARMUP_1. Do not call tools.")

    probe = build_agent()
    response = probe("Reply with exactly CACHE_WARMUP_2. Do not call tools.")

    assert response.metrics.accumulated_usage.get("cacheReadInputTokens", 0) > 0
    assert response.metrics.accumulated_usage.get("cacheWriteInputTokens", 0) == 0


def test_dumfries_to_westpark_uses_the_unpriced_braddock_junction(
    live_pricing_env,
):
    agent = build_agent()
    response = agent("Price a trip from Dumfries to Westpark")

    junction_calls = _tool_uses(response, "i95_junction_leg")
    i495_calls = _tool_uses(response, "i495_route")

    assert len(junction_calls) == 1
    assert i495_calls, "expected the agent to call i495_route for the Westpark leg"
    assert junction_calls[0]["input"]["movement"] == "i95_to_i495"
    i495_result = _tool_result(response, i495_calls[0]["toolUseId"])
    entry, _ = _resolved_endpoints(i495_result)
    assert entry["node_id"] == "191NO"
    assert not _tool_uses(response, "i95_route")


def test_i66_price_answer_shows_work_and_vdot_observed_time(live_pricing_env):
    agent = build_agent()
    response = agent("Price a trip from I-66 West to Westmoreland St")

    answer = str(response)
    assert "Route and fares" in answer
    assert "Calculation" in answer
    assert "Final price" in answer
    assert "VDOT observed at:" in answer

    [tool_result] = _tool_results(response, "i66_route")
    leg = tool_result["legs"][0]
    assert leg["observed_at"] in answer
    assert f"${leg['price_usd']} = ${tool_result['total_usd']}" in answer


def test_dulles_answer_itemizes_each_charge_and_shows_the_sum():
    agent = build_agent()
    response = agent(
        "Price a trip from Exit 12 - SR 602 (Reston Pkwy) to "
        "Exit 17 - SR 684 (Spring Hill Rd)"
    )

    answer = str(response)
    [tool_result] = _tool_results(response, "dulles_route")
    assert [toll["price_usd"] for toll in tool_result["tolls"]] == [
        "2.00",
        "4.00",
        "2.00",
    ]
    assert "$2.00 + $4.00 + $2.00 = $8.00" in answer


@pytest.mark.parametrize(
    "_case,prompt,expected_connectors",
    _BOUNDARY_CASES,
    ids=[case[0] for case in _BOUNDARY_CASES],
)
def test_agent_follows_every_network_boundary(
    live_pricing_env, _case, prompt, expected_connectors
):
    agent = build_agent()
    response = agent(prompt)

    plans = _tool_results(response, "plan_toll_route")
    actual_calls = _route_tool_uses(response)
    assert actual_calls
    if not plans:
        assert expected_connectors == []
        assert [call["name"] for call in actual_calls] == ["dulles_route"]
        assert "error" not in _tool_result(response, actual_calls[0]["toolUseId"])
        return

    [plan] = plans
    assert "error" not in plan, plan
    matrix_case = next(
        (
            case
            for case in _JUNCTION_MATRIX_CASES
            if _case in {case, f"{case}-paraphrase"}
        ),
        None,
    )
    assert [
        step["label"] for step in plan["steps"] if step["kind"] == "connector"
    ] == expected_connectors

    expected_steps = [
        step for step in plan["steps"] if step["kind"] in {"priced", "junction"}
    ]
    if matrix_case:
        assert len(actual_calls) == len(expected_steps), str(response)
    else:
        assert len(actual_calls) <= len(expected_steps)

    for call, step in zip(actual_calls, expected_steps, strict=False):
        assert call["name"] == step["tool"]
        result = _tool_result(response, call["toolUseId"])
        assert call["input"].get("at_time") == plan["at_time"]
        if "error" not in result:
            assert result["at_time"] == plan["at_time"]
        if matrix_case:
            assert "error" not in result, str(response)

        if step["kind"] == "junction":
            assert call["input"]["location"] == step["location"]
            assert call["input"]["movement"] == step["movement"]
            continue

        assert "error" not in result, result
        entry, exit_ = _resolved_endpoints(result)
        assert _same_endpoint(step["origin"], call["input"]["origin"], entry)
        assert _same_endpoint(
            step["destination"],
            call["input"]["destination"],
            exit_,
        )

    if not matrix_case and len(actual_calls) < len(expected_steps):
        last_result = _tool_result(response, actual_calls[-1]["toolUseId"])
        assert "error" in last_result, str(response)

    if matrix_case and matrix_case.endswith("-detour"):
        assert plan["routing_note"] in str(response)
        assert all(
            step.get("label") != "I-66/I-495 interchange" for step in plan["steps"]
        )


@pytest.mark.parametrize(
    "prompt",
    [
        "Price Gainesville to Washington.",
        "Price Tysons to Arlington.",
    ],
)
def test_agent_does_not_guess_uncovered_or_ambiguous_locations(prompt):
    agent = build_agent()
    response = agent(prompt)
    answer = str(response)

    assert not _pricing_tool_uses(response)
    assert "Final price" not in answer


def test_agent_resolves_dulles_airport_and_leesburg_aliases():
    agent = build_agent()
    response = agent("Price Dulles Airport to Leesburg on the Dulles Greenway.")

    [call] = _pricing_tool_uses(response)
    assert call["name"] == "dulles_route"
    result = _tool_result(response, call["toolUseId"])
    assert "error" not in result, str(response)
    assert result["legs"][0]["entry"]["label"] == (
        "Route 28 (Dulles Toll Road / Dulles Greenway)"
    )
    assert result["legs"][-1]["exit"]["label"] == (
        "Exit 1 - US 15/SR 7 (Leesburg Bypass)"
    )


def test_agent_does_not_ignore_a_malformed_time(live_pricing_env):
    agent = build_agent()
    response = agent(
        "Price I-66 West to Westmoreland St at definitely-not-an-ISO-8601-time."
    )
    answer = str(response)

    for call in _pricing_tool_uses(response):
        assert "error" in _tool_result(response, call["toolUseId"])
    assert "Final price" not in answer


@pytest.mark.parametrize(
    "prompt",
    [
        "Price US-1 to I-395 Near Edsall Road.",
        "Price I-395 Near Edsall Road to US-1.",
    ],
)
def test_agent_reports_reversible_lane_availability_without_inventing_a_fare(
    live_pricing_env, prompt
):
    agent = build_agent()
    response = agent(prompt)
    answer = str(response)

    [call] = _pricing_tool_uses(response)
    result = _tool_result(response, call["toolUseId"])
    if "error" in result:
        assert "Final price" not in answer
    else:
        assert "Final price" in answer
