"""Guards the agent tool contracts in schemas/tools/: each must be valid
Draft 2020-12 JSON Schema, carry a semver version, describe every input
property (the schemas are model-facing -- an undescribed parameter is an
undocumented parameter), and validate its own examples. Design rationale
lives in docs/agent-tools-spec.md; runs in the existing `uv run pytest`
CI step.
"""

import json
import re

import pytest
from conftest import REPO_ROOT
from jsonschema import Draft202012Validator

TOOLS = ("list_tables", "describe_table", "execute_sql", "route")
SCHEMA_DIR = REPO_ROOT / "schemas" / "tools"


def _schema(tool: str) -> dict:
    return json.loads((SCHEMA_DIR / f"{tool}.json").read_text())


def test_every_tool_has_a_schema_and_nothing_else_does():
    assert sorted(p.stem for p in SCHEMA_DIR.glob("*.json")) == sorted(TOOLS)


@pytest.mark.parametrize("tool", TOOLS)
def test_input_and_output_are_valid_draft_2020_12(tool: str):
    doc = _schema(tool)
    for part in ("input", "output"):
        Draft202012Validator.check_schema(doc[part])


@pytest.mark.parametrize("tool", TOOLS)
def test_version_is_semver(tool: str):
    version = _schema(tool)["version"]
    assert re.fullmatch(r"\d+\.\d+\.\d+", version), (
        f"{tool}: version {version!r} is not semver"
    )


@pytest.mark.parametrize("tool", TOOLS)
def test_examples_exist_and_validate_against_their_schema(tool: str):
    doc = _schema(tool)
    for part in ("input", "output"):
        schema = doc[part]
        examples = schema.get("examples", [])
        if not schema.get("properties"):  # no-input tool: nothing to exemplify
            continue
        assert examples, f"{tool} {part} schema has no examples"
        validator = Draft202012Validator(schema)
        for example in examples:
            validator.validate(example)


@pytest.mark.parametrize("tool", TOOLS)
def test_input_is_closed_and_every_property_is_described(tool: str):
    inp = _schema(tool)["input"]
    assert inp.get("additionalProperties") is False, (
        f"{tool}: input must set additionalProperties: false"
    )
    for name, prop in inp.get("properties", {}).items():
        assert prop.get("description"), f"{tool}: input '{name}' lacks a description"
