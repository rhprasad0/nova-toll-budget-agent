from pathlib import Path
from tomllib import load


def test_angry_math_nerd_agent_contract() -> None:
    path = Path(__file__).parents[2] / ".codex/agents/angry_math_nerd.toml"
    with path.open("rb") as definition:
        config = load(definition)

    assert config["name"] == "angry_math_nerd"
    assert config["model"] == "gpt-5.6-sol"
    assert config["model_reasoning_effort"] == "medium"
    assert config["sandbox_mode"] == "read-only"

    instructions = config["developer_instructions"]
    for required in (
        "#164",
        "#165",
        "Not placated",
        "Grudgingly placated",
        "Cannot audit",
        "serially correlated",
        "unpriced",
        "independent statistical review",
    ):
        assert required in instructions
