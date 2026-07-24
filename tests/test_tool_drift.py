"""Strands-generated tool specs must not drift from schemas/tools/*.json.

Compares property names and required lists (docstring wording is allowed to
differ from the contract's description fields).
"""

import json
import sys

import pytest
from conftest import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT / "lambdas" / "agent"))

from catalog import describe_table, list_tables  # noqa: E402
from route_tool import route  # noqa: E402
from sql_tool import execute_sql  # noqa: E402

TOOLS = {
    "list_tables": list_tables,
    "describe_table": describe_table,
    "execute_sql": execute_sql,
    "route": route,
}


@pytest.mark.parametrize("name", sorted(TOOLS))
def test_tool_spec_matches_contract(name):
    contract = json.loads(
        (REPO_ROOT / "schemas" / "tools" / f"{name}.json").read_text()
    )["input"]
    generated = TOOLS[name].tool_spec["inputSchema"]["json"]

    assert TOOLS[name].tool_spec["name"] == name
    assert set(generated.get("properties", {})) == set(contract.get("properties", {}))
    assert set(generated.get("required", [])) == set(contract.get("required", []))
