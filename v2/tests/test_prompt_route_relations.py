"""Prompt topology preserves the catalog and matches the canonical directed pairs."""

import json
from copy import deepcopy
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from agent import toll_agent

_V2 = Path(__file__).resolve().parents[1]
_RELATION = "same_facility_exit_point_ids"


def _render(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    values = toll_agent._render_system_prompt_values(
        points, current_date=date(2026, 9, 27)
    )
    return json.loads(values["PROMPT_POINTS_JSON"])


def test_catalog_records_fields_and_order_are_preserved() -> None:
    points = json.loads(
        (_V2 / "eval/archive/development-3.3.28/prompt-points.json").read_text()
    )
    original = deepcopy(points)
    rendered = _render(points)
    assert points == original
    assert rendered == _render(points)
    assert len(rendered) == 220
    assert [
        {key: value for key, value in point.items() if key != _RELATION}
        for point in rendered
    ] == original
    by_id = {point["point_id"]: point for point in rendered}
    for entry in rendered:
        if _RELATION not in entry:
            continue
        assert entry["network_id"] in {"dtr", "greenway"}
        assert entry["point_type"] == "entry"
        assert entry["direction"] in {"EB", "WB"}
        assert len(entry[_RELATION]) == len(set(entry[_RELATION]))
        for exit_id in entry[_RELATION]:
            exit_point = by_id[exit_id]
            assert exit_point["network_id"] == entry["network_id"]
            assert exit_point["direction"] == entry["direction"]
            assert exit_point["point_type"] == "exit"


@pytest.mark.parametrize(
    ("network", "source", "pair_count"),
    [("dtr", "dulles_toll_road", 110), ("greenway", "dulles_greenway", 79)],
)
def test_relations_equal_every_canonical_pair(
    network: str, source: str, pair_count: int
) -> None:
    catalog = json.loads(
        (_V2 / "eval/archive/development-3.3.28/prompt-points.json").read_text()
    )
    graph = json.loads((_V2 / f"oracle/sources/{source}.json").read_text())
    expected = {
        (
            f"{network}:{pair['entry']}:entry:{pair['direction']}",
            f"{network}:{pair['exit']}:exit:{pair['direction']}",
        )
        for pair in graph["pairs"]
    }
    actual = {
        (point["point_id"], exit_id)
        for point in _render(catalog)
        if point["network_id"] == network
        for exit_id in point.get(_RELATION, [])
    }
    assert len(expected) == pair_count
    assert actual == expected


def test_partial_catalog_unknown_nodes_and_unavailable_roles_are_preserved() -> None:
    def point(
        network: str, node: str, role: str = "entry", direction: str = "EB"
    ) -> dict[str, Any]:
        return {
            "point_id": f"{network}:{node}:{role}:{direction}",
            "network_id": network,
            "source_node_id": node,
            "point_type": role,
            "direction": direction,
            "label": "Synthetic endpoint",
            "aliases": ["Unchanged alias"],
            "location": {"type": "Point", "coordinates": [-77.5, 39.0]},
        }

    points = sorted(
        [
            point("greenway", "1"),
            point("greenway", "1", "exit"),  # Valid ID, wrong role for departure.
            point("greenway", "2A"),  # Exit role absent: do not fabricate its ID.
            point("greenway", "2B", "exit", "WB"),
            point("greenway", "3", "exit"),
            point("greenway", "3", "exit", "WB"),
            point("greenway", "28"),  # No downstream exit in this catalog.
            point("greenway", "unknown"),
            point("greenway", "unknown", "exit"),
            point("dtr", "10", "exit"),
            point("dtr", "28", direction="NB"),
            point("i66", "1"),
        ],
        key=lambda value: value["point_id"],
    )
    original = deepcopy(points)
    rendered = _render(points)
    assert points == original
    assert [
        {key: value for key, value in item.items() if key != _RELATION}
        for item in rendered
    ] == original
    relations = {
        item["point_id"]: item[_RELATION] for item in rendered if _RELATION in item
    }
    assert relations == {
        "greenway:1:entry:EB": ["greenway:3:exit:EB"],
        "greenway:2A:entry:EB": ["greenway:3:exit:EB"],
        "greenway:28:entry:EB": [],
    }
