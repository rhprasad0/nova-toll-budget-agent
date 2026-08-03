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
    facility: str
    label: str
    lat: float
    lon: float
    nodeIds: list[str]


def _embedded_json(script_id: str) -> object:
    page = SITE.read_text()
    match = re.search(
        rf'<script id="{script_id}" type="application/json">\s*(.*?)\s*</script>',
        page,
        re.DOTALL,
    )
    assert match, f"the page must embed {script_id} (no runtime data request)"
    return json.loads(match.group(1))


def _coverage_data() -> list[CoveragePin]:
    return cast(list[CoveragePin], _embedded_json("coverage-data"))


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


def test_map_uses_token_free_pinned_maplibre_and_stays_accessible() -> None:
    page = SITE.read_text()
    assert 'id="coverage-map"' in page
    assert 'aria-label="Interactive TollChat coverage map"' in page
    assert "144 supported entry and exit nodes" in page
    assert "maplibre-gl@6.0.0/dist/maplibre-gl.css" in page
    assert "maplibre-gl@6.0.0/dist/maplibre-gl.mjs" in page
    assert "https://tiles.openfreemap.org/styles/dark" in page
    assert "OpenStreetMap contributors" in page
    assert "mapbox" not in page.lower()
    assert "leaflet" not in page.lower()
    assert "access_token" not in page.lower()
    assert "api_key" not in page.lower()


def test_map_embeds_road_following_geojson_for_every_facility() -> None:
    route_data = cast(dict[str, object], _embedded_json("route-data"))
    assert route_data["type"] == "FeatureCollection"
    assert route_data["source"] == "U.S. Census Bureau TIGER/Line 2019"
    assert route_data["sourceArchive"] == "tl_2019_51_prisecroads.zip"
    features = cast(list[dict[str, object]], route_data["features"])
    assert {
        cast(dict[str, str], feature["properties"])["facility"] for feature in features
    } == {"i66", "i95", "i495", "dulles", "greenway"}
    for feature in features:
        geometry = cast(dict[str, object], feature["geometry"])
        assert geometry["type"] == "MultiLineString"
        lines = cast(list[list[list[float]]], geometry["coordinates"])
        assert lines
        assert sum(len(line) for line in lines) >= 8


def test_map_exposes_native_filters_reset_and_details() -> None:
    page = SITE.read_text()
    assert 'id="route-filters"' in page
    for facility in ("all", "i66", "i95", "i495", "dulles", "greenway"):
        assert f'data-facility="{facility}"' in page
    assert 'id="reset-map"' in page
    assert 'aria-live="polite"' in page
    assert 'className = "map-pin"' in page
    assert 'markerButton.type = "button"' in page
    assert 'id="map-loading"' in page
    assert 'id="map-error"' in page


def test_rendered_pins_snap_to_fixed_positions_on_their_routes() -> None:
    page = SITE.read_text()
    assert ".map-pin, .junction-pin { position: absolute;" in page
    assert "const snapToRoute = (pin) =>" in page
    assert ".setLngLat(snapToRoute(pin))" in page
    assert ".setLngLat([pin.lon,pin.lat])" not in page


def test_map_marks_the_i95_i495_junction_as_unpriced() -> None:
    page = SITE.read_text()
    assert "Coverage, with one honest gap." in page
    assert "95/495 junction price unavailable" in page
    assert 'dataset.junction = "true"' in page
    assert 'aria-label", "I-95 to I-495 junction: price unavailable"' in page
    assert "Edsall or Franconia-Springfield" in page
    assert "I-495 pricing begins or ends at Braddock" in page
    assert "no complete trip total is available" in page


def test_footer_states_ai_support_and_vdot_independence() -> None:
    page = SITE.read_text()
    assert "We support American AI innovation" in page
    assert "TollChat is not affiliated with VDOT" in page
    assert "We use VDOT\u2019s public toll pricing data—and we\u2019re fans." in page
