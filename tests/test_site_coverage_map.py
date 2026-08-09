"""Regression checks for the self-contained open-beta coverage map."""

from __future__ import annotations

import json
from collections import defaultdict
from hashlib import sha256
from pathlib import Path
from typing import TypedDict, cast

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site" / "preview.html"
MAP_MODULE = ROOT / "site" / "assets" / "coverage-map-v1.mjs"
ORACLES = ROOT / "oracles"
ASSETS = ROOT / "site" / "assets"
MAPLIBRE_ASSETS = ASSETS / "maplibre-gl-6.0.0"
SITE_TERRAFORM = ROOT / "infra" / "site.tf"


class CoveragePin(TypedDict):
    source: str
    facility: str
    label: str
    lat: float
    lon: float
    nodeIds: list[str]


def _exported_json(name: str) -> object:
    source = MAP_MODULE.read_text().split(f"export const {name} = ", maxsplit=1)[1]
    return json.JSONDecoder().raw_decode(source)[0]


def _coverage_data() -> list[CoveragePin]:
    return cast(list[CoveragePin], _exported_json("coveragePins"))


def test_shared_map_data_covers_every_active_oracle_node() -> None:
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
    implementation = page + MAP_MODULE.read_text()
    assert 'id="coverage-map"' in page
    assert 'aria-label="Interactive TollChat coverage map.' in page
    assert 'href="/assets/maplibre-gl-6.0.0/maplibre-gl.css"' in page
    assert 'import("/assets/maplibre-gl-6.0.0/maplibre-gl.mjs")' in implementation
    assert "setWorkerUrl" not in implementation
    assert "https://tiles.openfreemap.org/styles/dark" in implementation
    assert "OpenStreetMap contributors" in implementation
    assert "mapbox" not in implementation.lower()
    assert "leaflet" not in implementation.lower()
    assert "access_token" not in implementation.lower()
    assert "api_key" not in implementation.lower()
    assert "unpkg.com" not in implementation


def test_maplibre_assets_are_pinned_and_published_by_terraform() -> None:
    expected_hashes = {
        "maplibre-gl.mjs": "a641b06ae13a7aecc688c2de315b6483353ff62ba8276367e19acf51394fd3b1",
        "maplibre-gl-shared.mjs": "ba5bae6a93301ad92b8466fce6b80f8299c5825c41ae76496293bde34db96713",
        "maplibre-gl-worker.mjs": "a55efc5d80ad1d6a286c1d0e82d4d59c9d50b4e7a7da1d17c44e7791b2325930",
        "maplibre-gl.css": "9467ecb10416776e4ec880d662c20bbc1d1ea4e439ac3aeda45901bdf124b609",
    }
    for filename, expected_hash in expected_hashes.items():
        assert (
            sha256((MAPLIBRE_ASSETS / filename).read_bytes()).hexdigest()
            == expected_hash
        )
    assert (
        (MAPLIBRE_ASSETS / "LICENSE.txt")
        .read_text()
        .startswith("Copyright (c) 2023, MapLibre contributors")
    )

    terraform = SITE_TERRAFORM.read_text()
    for filename in expected_hashes:
        assert f'"assets/maplibre-gl-6.0.0/{filename}"' in terraform
    assert 'cache_control = "public, max-age=31536000, immutable"' in terraform
    assert '"text/css"' in terraform
    assert '"text/javascript"' in terraform


def test_map_recovers_from_a_slow_load_and_preserves_mobile_attribution() -> None:
    page = SITE.read_text()
    assert "error.hidden = true;" in MAP_MODULE.read_text()
    assert "grid-template-rows:auto 20rem auto" in page
    assert ".map-detail { position:static;" in page


def test_map_embeds_road_following_geojson_for_every_facility() -> None:
    route_data = cast(dict[str, object], _exported_json("routeData"))
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
    module = MAP_MODULE.read_text()
    assert 'id="route-filters"' in page
    for facility in ("all", "i66", "i95", "i495", "dulles", "greenway"):
        assert f'data-facility="{facility}"' in page
    assert 'id="reset-map"' in page
    assert 'aria-live="polite"' in page
    assert '<aside id="map-detail" class="map-detail" aria-live="polite">' in page
    assert '"map-pin preview-map-pin" : "map-pin"' in module
    assert 'marker.type = "button"' in module
    assert 'id="map-loading"' in page
    assert 'id="map-error"' in page


def test_rendered_pins_use_precomputed_fixed_positions() -> None:
    page = SITE.read_text()
    module = MAP_MODULE.read_text()
    assert ".map-pin,.junction-pin { position:absolute;" in page
    assert "snapToRoute" not in page
    assert "mountMarker(marker, [pin.lon,pin.lat])" in module
    assert "move = true" not in module
    assert "if (move)" not in module


def test_map_marks_the_i95_i495_junction_as_unpriced() -> None:
    page = SITE.read_text()
    module = MAP_MODULE.read_text()
    assert "Coverage at a glance" in page
    assert "I-95 \u2194 I-495 junction price unavailable." in page
    assert 'dataset.junction = "true"' in module
    assert 'aria-label", "I-95 to I-495 junction: price unavailable"' in module
    assert "const showJunction = () => {" in module
    assert 'selectedMarker?.classList.remove("selected");' in module
    assert "selectedMarker = undefined;" in module
    assert "Edsall or Franconia-Springfield" in page
    assert "I-495 pricing begins or ends at Braddock" in page
    assert "We add known fares but exclude the unpriced gap" in page


def test_map_keeps_filtered_controls_and_responsive_camera_in_sync() -> None:
    module = MAP_MODULE.read_text()
    assert 'let activeFacility = "all";' in module
    assert "activeFacility = facility;" in module
    assert (
        'const junctionVisible = facility === "all" || facility === "i95" || facility === "i495";'
        in module
    )
    assert 'map.setLayoutProperty("junction-zone", "visibility"' in module
    assert 'map.setLayoutProperty("junction-outline", "visibility"' in module
    assert "junctionMarker.hidden = !junctionVisible;" in module
    assert (
        'activeFacility === "all" ? coverageBounds : facilityBounds(activeFacility);'
        in module
    )
    assert "map.fitBounds(bounds, { padding:padding(mode), duration:0 });" in module


def test_footer_states_ai_support_and_vdot_independence() -> None:
    page = SITE.read_text()
    assert "We support American AI innovation" in page
    assert "Virginia Department of Transportation (VDOT)" in page
    assert "TollChat uses VDOT\u2019s public toll pricing data." in page


def test_page_contains_an_accessible_chat() -> None:
    page = SITE.read_text()
    script = (ROOT / "site" / "preview.mjs").read_text()
    assert 'id="transcript"' in page
    assert 'id="message"' in page
    assert 'aria-live="polite"' in page
    assert 'maxlength="8000"' in page
    assert 'post("/api/chat"' in script
    assert 'post("/api/reset"' in script
    assert 'id="privacy-notice"' in page
    assert "Raw telemetry" not in page
