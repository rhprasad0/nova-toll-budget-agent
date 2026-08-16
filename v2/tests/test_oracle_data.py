from __future__ import annotations

from collections import Counter
from dataclasses import replace

import pytest

from oracle.build_oracle_data import (
    EXPECTED_CONNECTIONS,
    EXPECTED_MAX_SHORTEST_PATH,
    EXPECTED_POINTS,
    EXPECTED_REACHABLE_PAIRS,
    build_connections,
    build_points,
    build_sql,
    graph_metrics,
    validate,
)


def test_oracle_source_contract() -> None:
    points = build_points()
    connections = build_connections(points)

    validate(points, connections)

    assert len(points) == EXPECTED_POINTS
    assert len(connections) == EXPECTED_CONNECTIONS
    assert Counter(
        connection.connection_type for connection in connections.values()
    ) == {
        "within_facility": 670,
        "general_purpose_gap": 300,
        "toll_handoff": 13,
        "airport_access": 11,
    }
    assert sum(point.longitude is not None for point in points.values()) == 107
    assert graph_metrics(points, connections) == (
        EXPECTED_REACHABLE_PAIRS,
        EXPECTED_MAX_SHORTEST_PATH,
    )


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
    dca_destination = connections["i95_north_to_dca"]
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
    assert dca_destination.required_i95_direction == "NB"
    assert dca_north.to_point_id == "i95:224NO"
    assert dca_north.required_i95_direction == "NB"
    assert dca_south.to_point_id == "i95:2233SO"
    assert dca_south.required_i95_direction == "SB"


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
