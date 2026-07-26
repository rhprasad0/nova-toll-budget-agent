"""Structural guard on schemas/tools/*.json -- the JSON Schema contract of
record for i66_route/i95_route/i495_route/dulles_route/find_toll_locations
(docs/oracle-tools-spec.md).

Stdlib-only: no jsonschema validator here (deliberately dropped as an
orphaned dependency, commit 44ef7c9) -- output-shape correctness is asserted
with plain dict equality in agent_tools/tests/, which is simpler than
round-tripping through a validator library for a handful of known-small
shapes. This file only guards that the contract files exist, are
well-formed, and are versioned -- a schema round-trip through psycopg or
Strands is out of scope.

No network, no RDS.
"""

import json
import re

from conftest import REPO_ROOT

SCHEMA_DIR = REPO_ROOT / "schemas" / "tools"

# The four route tools all take {origin, destination, at_time?} and price a
# trip; find_toll_locations takes {query?, corridor?} and looks up labels --
# a genuinely different shape, not just a fourth entry in the same list (see
# docs/oracle-tools-spec.md's now-updated note on this). ROUTE_TOOLS keeps
# the origin/destination/at_time assertions that only apply to that shape;
# ALL_TOOLS is the complete file-existence/version guard.
ROUTE_TOOLS = ("i66_route", "i95_route", "i495_route", "dulles_route")
FINDER_TOOLS = ("find_toll_locations",)
ALL_TOOLS = ROUTE_TOOLS + FINDER_TOOLS


def _schema(tool: str) -> dict:
    return json.loads((SCHEMA_DIR / f"{tool}.json").read_text())


def test_every_tool_has_exactly_one_schema_file():
    assert {p.stem for p in SCHEMA_DIR.glob("*.json")} == set(ALL_TOOLS)


def test_schema_version_is_semver():
    for tool in ALL_TOOLS:
        assert re.fullmatch(r"\d+\.\d+\.\d+", _schema(tool)["version"]), tool


def test_schema_has_input_and_output_shapes():
    for tool in ALL_TOOLS:
        doc = _schema(tool)
        assert doc["title"] == tool
        assert "properties" in doc["input"]
        assert "oneOf" in doc["output"]


def test_route_tool_schema_requires_origin_and_destination():
    for tool in ROUTE_TOOLS:
        doc = _schema(tool)
        assert set(doc["input"]["required"]) == {"origin", "destination"}


def test_route_tool_schema_input_includes_optional_at_time():
    # at_time is optional (not in "required"), but must be a declared
    # property -- otherwise the schema silently drifts from the tool's
    # actual signature (agent_tools/i66_route.py, i95_route.py).
    for tool in ROUTE_TOOLS:
        doc = _schema(tool)
        assert "at_time" in doc["input"]["properties"], tool
        assert "at_time" not in doc["input"]["required"], tool


def test_finder_tool_schema_has_no_required_input():
    # find_toll_locations's query/corridor are both optional -- an empty
    # call is the level-0 corridor menu, not a malformed request.
    for tool in FINDER_TOOLS:
        doc = _schema(tool)
        assert doc["input"]["required"] == []
