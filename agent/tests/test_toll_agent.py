"""Prompt-content assertions only -- no AWS calls, no network. Constructing
a BedrockModel touches boto3.Session() before any network call, so
build_agent() is deliberately not exercised here; see
tests/test_toll_agent_live.py for the real end-to-end check.
"""

from toll_agent import build_system_prompt


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
