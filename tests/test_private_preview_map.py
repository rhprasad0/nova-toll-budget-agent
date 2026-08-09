"""Contracts for the directional map in the private preview."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAP_MODULE = ROOT / "site" / "assets" / "coverage-map-v1.mjs"
HANDLER = ROOT / "lambdas" / "chat_proxy" / "handler.mjs"
BUILD = ROOT / "scripts" / "build_zips.sh"
INFRA = ROOT / "infra" / "site.tf"


def _exported_json(name: str) -> object:
    source = MAP_MODULE.read_text().split(f"export const {name} = ", maxsplit=1)[1]
    return json.JSONDecoder().raw_decode(source)[0]


def test_one_way_badges_match_oracle_direction_and_role() -> None:
    pins = _exported_json("coveragePins")
    direction_labels = {
        "Northbound": "NB",
        "Southbound": "SB",
        "EB": "EB",
        "WB": "WB",
    }
    oracle_names = {
        "i95": "i95.json",
        "i66": "i66.json",
        "dulles_toll_road": "dulles_toll_road.json",
        "dulles_greenway": "dulles_greenway.json",
    }
    oracles = {
        source: json.loads((ROOT / "oracles" / filename).read_text())
        for source, filename in oracle_names.items()
    }

    directional = 0
    for pin in pins:
        node_ids = set(pin["nodeIds"])
        pairs = oracles[pin["source"]]["pairs"]
        directions = {
            pair["direction"]
            for pair in pairs
            if pair["entry"] in node_ids or pair["exit"] in node_ids
        }
        if len(directions) != 1:
            assert "oneWay" not in pin
            continue

        roles = {
            role.upper()
            for pair in pairs
            for role in ("entry", "exit")
            if pair[role] in node_ids
        }
        expected_role = "/".join(sorted(roles, key=("ENTRY", "EXIT").index))
        assert pin["oneWay"] == {
            "direction": direction_labels[directions.pop()],
            "role": expected_role,
        }
        directional += 1

    assert directional == 20


def test_private_bundle_serves_the_shared_pinned_map_assets() -> None:
    handler = HANDLER.read_text()
    build = BUILD.read_text()
    infra = INFRA.read_text()

    for asset in (
        "coverage-map-v1.mjs",
        "maplibre-gl.css",
        "maplibre-gl.mjs",
        "maplibre-gl-shared.mjs",
        "maplibre-gl-worker.mjs",
    ):
        assert asset in handler
    assert "site/assets/coverage-map-v1.mjs" in build
    assert "site/assets/maplibre-gl-6.0.0" in build
    assert '"assets/coverage-map-v1.mjs"' in infra
    assert 'path.endsWith(".css") ? "text/css; charset=utf-8"' in handler


def test_private_map_uses_mode_selected_route_geometry() -> None:
    module = MAP_MODULE.read_text()

    assert "const displayedRouteData = routeDataForMode(mode);" in module
    assert "displayedRouteData.features.map" in module
    assert "data:displayedRouteData" in module
