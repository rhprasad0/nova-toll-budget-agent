"""Prompt-content and request-shape assertions only -- no AWS calls/network.

Constructing ``BedrockModel`` creates a boto3 session but does not invoke
Bedrock, so these tests can verify cache-point placement locally. See
tests/test_toll_agent_live.py for the real end-to-end check.
"""

from strands.models import BedrockModel
from toll_agent import build_agent, build_system_prompt


def test_system_prompt_contains_i95_i495_junction():
    prompt = build_system_prompt()
    assert "206ND" in prompt
    assert "Franconia-Springfield Parkway" in prompt
    assert "192NO" in prompt
    assert "Van Dorn Street" in prompt


def test_system_prompt_flags_unevidenced_junctions():
    prompt = build_system_prompt()
    # 2 JUNCTIONS entries carry the marker, plus the refusal rule names it.
    assert prompt.count("NOT EVIDENCED") == 3


def test_system_prompt_states_the_overshoot_anti_example():
    prompt = build_system_prompt()
    assert "Washington D.C." in prompt
    assert "Springfield interchange" in prompt
    assert "NOT evidence the leg boundary is correct" in prompt


def test_system_prompt_never_asserts_i66_otb_dulles_junction():
    prompt = build_system_prompt()
    assert "no pricing tool exists for I-66 OTB" in prompt


def test_system_prompt_uses_structured_claude_prompt_sections():
    prompt = build_system_prompt()
    for section in (
        "role",
        "tool_rules",
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
    agent = build_agent()
    assert isinstance(agent.model, BedrockModel)
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
        "find_toll_locations",
        "i95_route",
        "i495_route",
        "i66_route",
        "dulles_route",
    ]
