import json

import pytest
from conftest import SCHEMAS_DIR
from jsonschema import Draft202012Validator

from catalog import describe_table, list_tables

TABLES = ("trip_pricing", "graph_node", "graph_edge")


def _output_schema(tool: str) -> dict:
    return json.loads((SCHEMAS_DIR / f"{tool}.json").read_text())["output"]


def test_list_tables_matches_schema():
    Draft202012Validator(_output_schema("list_tables")).validate(list_tables())


@pytest.mark.parametrize("table", TABLES)
def test_describe_table_matches_schema(table):
    Draft202012Validator(_output_schema("describe_table")).validate(
        describe_table(table)
    )


def test_describe_table_unknown_raises():
    with pytest.raises(ValueError, match="unknown table"):
        describe_table("not_a_table")


def _column(table: str, name: str) -> dict:
    cols = describe_table(table)["columns"]
    return next(c for c in cols if c["name"] == name)


def test_nullability_spot_checks():
    assert _column("trip_pricing", "od_pair_id")["nullable"] is True
    assert _column("graph_node", "node_id")["nullable"] is False
    assert _column("graph_edge", "feed")["nullable"] is True


def test_trip_pricing_notes_mention_link_status():
    notes = " ".join(describe_table("trip_pricing")["notes"])
    assert "link_status" in notes
