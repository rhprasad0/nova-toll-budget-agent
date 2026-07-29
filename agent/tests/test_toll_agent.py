"""Prompt-content and request-shape assertions only -- no AWS calls/network.

Constructing ``BedrockModel`` creates a boto3 session but does not invoke
Bedrock, so these tests can verify cache-point placement locally. See
tests/test_toll_agent_live.py for the real end-to-end check.
"""

import json

from strands.models import BedrockModel
from toll_agent import (
    _LOCATION_ALIASES,
    _PRICED_LOCATION_ORACLE_JSON,
    build_agent,
    build_system_prompt,
)


def test_system_prompt_contains_i95_i495_junction():
    prompt = build_system_prompt()
    assert "206ND" in prompt
    assert "Franconia-Springfield Parkway" in prompt
    assert "192NO" in prompt
    assert "Van Dorn Street" in prompt


def test_system_prompt_flags_unevidenced_junctions():
    prompt = build_system_prompt()
    # One JUNCTIONS entry carries the marker, plus the refusal rule names it.
    assert prompt.count("NOT EVIDENCED") == 2


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
        "junctions",
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
        "i95_route",
        "i495_route",
        "i66_route",
        "dulles_route",
    ]
