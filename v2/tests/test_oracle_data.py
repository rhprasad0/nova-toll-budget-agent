from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import replace

import pytest

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
