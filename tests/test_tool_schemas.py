"""Structural guard on schemas/tools/*.json -- the JSON Schema contract of
record for i66_route/i95_route (docs/oracle-tools-spec.md).

Stdlib-only: no jsonschema validator here (deliberately dropped as an
orphaned dependency, commit 44ef7c9) -- output-shape correctness is asserted
with plain dict equality in agent_tools/tests/, which is simpler than
round-tripping through a validator library for two known-small shapes. This
file only guards that the contract files exist, are well-formed, and are
versioned -- a schema round-trip through psycopg or Strands is out of scope.

No network, no RDS.
"""

import json
import re

from conftest import REPO_ROOT

SCHEMA_DIR = REPO_ROOT / "schemas" / "tools"
TOOLS = ("i66_route", "i95_route")


def _schema(tool: str) -> dict:
    return json.loads((SCHEMA_DIR / f"{tool}.json").read_text())


def test_every_tool_has_exactly_one_schema_file():
    assert {p.stem for p in SCHEMA_DIR.glob("*.json")} == set(TOOLS)


def test_schema_version_is_semver():
    for tool in TOOLS:
        assert re.fullmatch(r"\d+\.\d+\.\d+", _schema(tool)["version"]), tool


def test_schema_has_input_and_output_shapes():
    for tool in TOOLS:
        doc = _schema(tool)
        assert doc["title"] == tool
        assert "properties" in doc["input"]
        assert set(doc["input"]["required"]) == {"origin", "destination"}
        assert "oneOf" in doc["output"]
