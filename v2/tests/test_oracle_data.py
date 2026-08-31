from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import replace
from pathlib import Path

import pytest

from oracle import build_oracle_data as oracle_builder
from oracle.build_oracle_data import (
    build_connections,
    build_points,
    build_sql,
    validate,
)


def test_oracle_source_contract() -> None:
    points = build_points()
    connections = build_connections(points)

    validate(points, connections)


def test_curated_provenance_uses_the_oracle_contract() -> None:
    sql = build_sql()

    assert "v2/docs/" not in sql
    assert sql.count('"basis":"v2/db/oracle/CONTRACT.md"') == 32


def test_all_route_points_have_coordinate_provenance() -> None:
    points = build_points()

    assert Counter(
        point.source_metadata["coordinate_quality"] for point in points.values()
    ) == {
        "provisional_generalized": 107,
        "approximate_interchange": 111,
        "official_reference_point": 2,
    }
    locations: dict[tuple[str, str], set[tuple[str | None, str | None]]] = defaultdict(
        set
    )
    for point in points.values():
        assert point.longitude is not None and point.latitude is not None
        locations[(point.network_id, point.source_node_id)].add(
            (point.longitude, point.latitude)
        )
    assert all(len(coordinates) == 1 for coordinates in locations.values())


def test_i95_i495_report_points_have_curated_geographic_context() -> None:
    points = build_points()
    report_points = [
        point for point in points.values() if point.network_id in {"i95", "i495"}
    ]

    assert len(report_points) == 107
    assert all(point.place_name for point in report_points)
    assert all(point.region for point in report_points)
    assert {point.country_code for point in report_points} == {"US"}
    assert all(point.aliases for point in report_points)
    assert all(len(point.aliases) == len(set(point.aliases)) for point in report_points)
    assert points["i95:218NO"].place_name == "Dumfries"
    assert {"Dumfries Road", "Route 234"} <= set(points["i95:218NO"].aliases)
    assert points["i495:185ND"].place_name == "Tysons"
    assert "Tysons Corner" in points["i495:185ND"].aliases
    assert all(
        "Tysons Corner" in point.aliases
        for point in report_points
        if point.place_name == "Tysons"
    )
    assert points["i95:208ND"].place_name == "Newington"
    assert {"Fairfax County Parkway", "Route 286"} <= set(points["i95:208ND"].aliases)
    assert points["i495:187NO"].place_name == "Idylwood"
    assert points["i495:187SD"].place_name == "Dunn Loring"
    assert points["i495:188SO"].place_name == "Merrifield"
    assert points["i95:2249ND"].place_name == "Arlington"
    assert points["i95:236SO"].place_name == "Dale City"
    assert points["i95:216SD"].place_name == "Potomac Mills"
    assert points["i95:223ND"].source_metadata["report_context"][
        "nearby_landmarks"
    ] == [
        "Pentagon",
        "Ronald Reagan Washington National Airport",
    ]
    assert points["i95:208ND"].source_metadata["report_context"][
        "nearby_landmarks"
    ] == ["Fort Belvoir"]

    assert "Reagan Airport" in points["airport_dca"].aliases
    assert "DCA" in points["airport_dca"].aliases
    assert "Dulles Airport" in points["airport_iad"].aliases
    assert "IAD" in points["airport_iad"].aliases
    assert all("Reagan Airport" not in point.aliases for point in report_points)

    non_report_points = [
        point for point in points.values() if point.network_id not in {"i95", "i495"}
    ]
    assert all(point.place_name is None for point in non_report_points)
    assert all(point.region is None for point in non_report_points)
    assert all(point.country_code is None for point in non_report_points)


def test_source_metadata_retains_future_pricing_keys() -> None:
    points = build_points()
    connections = build_connections(points)

    shared = connections["source:i95_shared:Northbound:182NO:181ND"]
    i66 = connections["source:i66:EB:1:4"]
    dtr = connections["source:dtr:EB:28:10"]
    greenway = connections["source:greenway:EB:1:2A"]

    assert shared.source_metadata["source_pair"]["ods"] == [1038]
    assert i66.source_metadata["source_pair"]["start_zone"] == 3100
    assert dtr.source_metadata["source_pair"]["charges"]
    assert greenway.source_metadata["source_pair"]["charges"]


def test_greenway_and_dtr_pricing_metadata_stays_discrete() -> None:
    connections = build_connections(build_points())

    mainline_charges = 0
    for connection in connections.values():
        if not connection.connection_id.startswith("source:greenway:"):
            continue
        charges = connection.source_metadata["source_pair"]["charges"]
        assert all("facility" not in charge for charge in charges)
        if charges == [
            {
                "label": "Mainline plaza",
                "price_off_peak_usd": "5.25",
                "price_peak_usd": "5.80",
            }
        ]:
            mainline_charges += 1
    assert mainline_charges == 17
    assert connections["source:greenway:EB:1:2A"].source_metadata["source_pair"][
        "charges"
    ] == [
        {
            "label": "Secondary plaza",
            "price_off_peak_usd": "4.55",
            "price_peak_usd": "5.10",
        }
    ]

    for connection_id in ("greenway_to_dtr", "dtr_to_greenway"):
        handoff = connections[connection_id]
        assert handoff.source_route_key == connection_id
        assert handoff.source_metadata == {
            "curated": True,
            "basis": "v2/db/oracle/CONTRACT.md",
            "pricing_facility": "dtr",
            "pricing_charge": {
                "label": "Dulles Toll Road connection",
                "price_off_peak_usd": "2.00",
                "price_peak_usd": "2.00",
            },
        }

    handoff = connections["i495_1829_to_dulles_toll_road"]
    assert handoff.from_point_id == "i495:1829ND"
    assert handoff.to_point_id == "dtr:1819:entry:WB"
    assert handoff.required_i95_direction is None
    assert handoff.source_route_key is None
    assert handoff.source_metadata == {
        "curated": True,
        "basis": "v2/db/oracle/CONTRACT.md",
    }


def test_boundary_points_and_i95_requirements_are_explicit() -> None:
    points = build_points()
    connections = build_connections(points)

    assert points["i495:192NO"].aliases[0] == "TP1NB"
    assert points["i495:192SD"].aliases[0] == "TP1SB"
    assert points["i95:234NO"].point_type == "entry"
    assert points["i95:235SD"].point_type == "exit"

    same_facility = connections["source:i95_shared:Northbound:234NO:201ND"]
    gp_prefix = connections["source:i95_shared:Northbound:234NO:185ND"]
    gp_suffix = connections["source:i95_shared:Southbound:185SO:235SD"]
    mixed_i495_i95 = connections["source:i95_shared:Southbound:182SO:2239ND"]
    dca_destination = connections["i95_north_to_dca"]
    mixed_dca_destination = connections["i95_north_to_dca_from_i495_south"]
    dca_north = connections["dca_to_i95_north"]
    dca_south = connections["dca_to_i95_south"]

    assert same_facility.required_i95_direction == "NB"
    assert gp_prefix.required_i95_direction is None
    assert gp_suffix.required_i95_direction is None
    assert gp_prefix.source_metadata["general_purpose_fallback"] == {
        "boundary_point_id": "i495:192NO",
        "i95_direction": "NB",
    }
    assert gp_suffix.source_metadata["general_purpose_fallback"] == {
        "boundary_point_id": "i495:192SD",
        "i95_direction": "SB",
    }
    assert mixed_i495_i95.source_metadata["general_purpose_fallback"] == {
        "boundary_point_id": "i495:192SD",
        "i95_direction": "NB",
    }
    assert dca_destination.required_i95_direction == "NB"
    assert mixed_dca_destination.from_point_id == "i95:2239ND"
    assert mixed_dca_destination.required_i95_direction == "NB"
    assert dca_north.to_point_id == "i95:224NO"
    assert dca_north.required_i95_direction == "NB"
    assert dca_south.to_point_id == "i95:2233SO"
    assert dca_south.required_i95_direction == "SB"


def test_shared_point_directions_follow_their_roadway_paths() -> None:
    points = build_points()
    corrected: list[str] = []

    for point in points.values():
        if point.network_id not in {"i95", "i495"}:
            continue
        source_node = point.source_metadata["source_node"]
        path = source_node["path"]
        expected = (
            "NB"
            if path.endswith("North")
            else "SB"
            if path.endswith("South")
            else {"Northbound": "NB", "Southbound": "SB"}[source_node["direction"]]
        )
        assert point.direction == expected
        if (
            source_node["direction"]
            != {"NB": "Northbound", "SB": "Southbound"}[expected]
        ):
            corrected.append(point.point_id)

    assert set(corrected) == {
        "i495:1819ND",
        "i495:1829ND",
        "i495:1839ND",
        "i495:1859ND",
        "i495:1869ND",
        "i495:1879ND",
        "i495:1889ND",
        "i495:1919ND",
        "i95:2229ND",
        "i95:2239ND",
        "i95:2249ND",
    }


def test_washington_points_have_route_qualified_labels_and_source_aliases() -> None:
    points = build_points()

    expected = {
        "i66:16:entry:WB": ("Washington D.C. I-66", "Washington"),
        "i66:16:exit:EB": ("Washington D.C. I-66", "Washington"),
        "i95:2232SO": ("Washington D.C. I-395 Southbound", "Washington D.C."),
        "i95:224ND": ("Washington D.C. I-95/I-395 Northbound", "Washington D.C."),
        "i95:2249ND": (
            "Washington D.C. from I-495 Southbound via I-395",
            "Washington D.C.",
        ),
    }

    for point_id, (label, source_alias) in expected.items():
        assert points[point_id].label == label
        assert source_alias in points[point_id].aliases
    assert {"Washington", "District of Columbia"} <= set(points["i95:224ND"].aliases)


def test_alternative_rankings_retain_only_reviewed_v1_rules() -> None:
    points = build_points()

    assert points["i66:17:entry:WB"].source_metadata["alternative_ranking"] == {
        "corridor_position": 8,
        "preferred_point_ids": ["i66:12:exit:EB", "i66:13:exit:EB"],
    }
    assert points["greenway:2B:exit:WB"].source_metadata["alternative_ranking"] == {
        "corridor_position": 1.1,
        "preferred_point_ids": ["greenway:2A:entry:EB"],
    }
    assert "alternative_ranking" not in points["dtr:10:entry:EB"].source_metadata


def test_both_dtr_approaches_reach_northbound_i495() -> None:
    connections = build_connections(build_points())

    assert connections["dulles_toll_road_to_i495_north"].from_point_id == (
        "dtr:1819:exit:EB"
    )
    assert (
        connections["dulles_toll_road_westbound_to_i495_north"].from_point_id
        == "dtr:1819:exit:WB"
    )


def test_generated_sql_is_deterministic() -> None:
    assert build_sql() == build_sql()
    assert "INSERT INTO oracle.toll_route_point" in build_sql()
    assert "INSERT INTO oracle.toll_connection" in build_sql()


def test_generated_coverage_locations_group_every_oracle_point() -> None:
    points = build_points()
    rendered = oracle_builder.render_coverage_locations(points)
    snapshot = json.loads(rendered)

    assert rendered == oracle_builder.render_coverage_locations(points)
    assert snapshot["schema_version"] == 1
    assert len(snapshot["locations"]) == 103
    records = [
        point for location in snapshot["locations"] for point in location["points"]
    ]
    assert len(records) == 220
    assert {point["point_id"] for point in records} == set(points)
    assert snapshot["locations"] == sorted(
        snapshot["locations"], key=lambda location: location["coordinates"]
    )

    tp1 = next(
        location
        for location in snapshot["locations"]
        if location["coordinates"] == [-77.15413222704926, 38.79347384215561]
    )
    assert tp1["points"] == [
        {
            "point_id": "i495:192NO",
            "facility": "i495",
            "label": "I-495 Express northbound start at I-95 (TP1NB)",
            "direction": "NB",
            "role": "entry",
        },
        {
            "point_id": "i495:192SD",
            "facility": "i495",
            "label": "I-495 Express southbound end at I-95 (TP1SB)",
            "direction": "SB",
            "role": "exit",
        },
    ]
    checked_in = (
        Path(__file__).parents[1] / "agent" / "assets" / "coverage-locations.json"
    )
    assert checked_in.read_text(encoding="utf-8") == rendered


def test_importer_rejects_cross_row_semantic_errors() -> None:
    points = build_points()
    connections = build_connections(points)
    handoff = connections["greenway_to_dtr"]
    invalid = replace(
        handoff,
        from_point_id="greenway:28:entry:WB",
        to_point_id="dtr:28:entry:EB",
    )
    broken_connections = {**connections, handoff.connection_id: invalid}

    with pytest.raises(ValueError, match="invalid toll handoff"):
        validate(points, broken_connections)
