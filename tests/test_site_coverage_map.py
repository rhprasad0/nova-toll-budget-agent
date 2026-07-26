"""Regression checks for the self-contained coming-soon coverage map."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import TypedDict, cast


ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site" / "index.html"
ORACLES = ROOT / "oracles"


class CoveragePin(TypedDict):
    source: str
    label: str
    nodeIds: list[str]


def _coverage_data() -> list[CoveragePin]:
    page = SITE.read_text()
    match = re.search(
        r'<script id="coverage-data" type="application/json">\s*(.*?)\s*</script>',
        page,
        re.DOTALL,
    )
    assert match, "the page must embed its coverage data (no runtime map request)"
    return cast(list[CoveragePin], json.loads(match.group(1)))


def test_embedded_map_data_covers_every_active_oracle_node() -> None:
    """Every supported entry/exit stays represented when the oracles refresh."""
    pins_by_source: dict[str, dict[str, str]] = defaultdict(dict)
    for pin in _coverage_data():
        source = pin["source"]
        for node_id in pin["nodeIds"]:
            assert node_id not in pins_by_source[source]
            pins_by_source[source][node_id] = pin["label"]

    for filename, source in (
        ("i66.json", "i66"),
        ("i95.json", "i95"),
        ("dulles_toll_road.json", "dulles_toll_road"),
        ("dulles_greenway.json", "dulles_greenway"),
    ):
        oracle = json.loads((ORACLES / filename).read_text())
        expected = {node_id: node["label"] for node_id, node in oracle["nodes"].items()}
        assert pins_by_source[source] == expected


def test_map_stays_self_contained_and_accessible() -> None:
    page = SITE.read_text()
    assert 'id="coverage-map"' in page
    assert 'role="img"' in page
    assert "144 supported entry and exit nodes" in page
    assert "mapbox" not in page.lower()
    assert "leaflet" not in page.lower()
    assert "maplibre" not in page.lower()
    assert not re.search(r"<script[^>]+\bsrc=", page, re.IGNORECASE)
