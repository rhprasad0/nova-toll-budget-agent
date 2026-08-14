from orchestrator import routing, schemas

REQUESTED_AT = "2026-08-13T08:00:00-04:00"


def direction(open_direction: str = "Northbound") -> dict[str, object]:
    statuses = {
        "Northbound": "NORTHBOUND_OPEN" if open_direction == "Northbound" else "CLOSED",
        "Southbound": "SOUTHBOUND_OPEN" if open_direction == "Southbound" else "CLOSED",
    }
    result = {
        "status": "supported",
        "requested_at": REQUESTED_AT,
        "source_kind": "observed",
        "open_direction": open_direction,
        "observations": [
            {
                "direction": name,
                "od_pair_id": 1132 if name == "Northbound" else 1151,
                "corridor_name": "I-95-NB" if name == "Northbound" else "I-95-SB",
                "link_status": status,
                "effective_at": "2026-08-13T07:55:00-04:00",
                "observed_at": "2026-08-13T07:50:00-04:00",
            }
            for name, status in statuses.items()
        ],
    }
    return routing._record_evidence(
        schemas.I95DirectionResult.model_validate(
            routing._register_evidence("direction", result)
        )
    )


def test_access_supports_direct_trip_and_returns_canonical_nodes():
    result = routing.i95_access_options(
        "i95", "US-1", "i95", "I-395 Near Edsall Road", direction()
    )

    validated = schemas.I95AccessResult.model_validate(result)
    assert validated.status == "supported"
    assert result["required_direction"] == "Northbound"
    assert result["entry_node_id"] == "210NO"
    assert result["exit_node_id"] == "201ND"
    assert result["validation_id"].startswith("access-")


def test_access_reports_closed_desired_direction_before_routing():
    result = routing.i95_access_options(
        "i95", "US-1", "i95", "I-395 Near Edsall Road", direction("Southbound")
    )

    assert result["status"] == "direction_closed"
    assert result["required_direction"] == "Northbound"
    assert result["open_direction"] == "Southbound"


def test_access_returns_fixed_ramp_alternatives_only_when_direction_is_open():
    result = routing.i95_access_options(
        "i95",
        "Franconia-Springfield Parkway/Route 289",
        "i95",
        "I-95 Near Quantico",
        direction("Southbound"),
    )

    assert result["status"] == "one_way_mismatch"
    assert result["constraints"] == [
        {
            "location": "I-95 Near Quantico",
            "role": "exit",
            "required_direction": "Southbound",
            "available_directions": ["Northbound"],
            "nearby_options": [
                "I-95 Near Garrisonville Road/Route 610",
                "I-95 Near Joplin Road/Quantico",
            ],
        }
    ]


def test_access_supports_cross_corridor_handoff():
    result = routing.i95_access_options(
        "i95", "US-1", "i495", "Westpark Drive", direction()
    )

    assert result["status"] == "supported"
    assert result["movement"] == "i95_to_i495"
    assert result["entry_node_id"] == "210NO"
    assert result["exit_node_id"] == "206ND"


def test_access_rejects_malformed_direction_evidence():
    result = routing.i95_access_options(
        "i95", "US-1", "i95", "I-395 Near Edsall Road", {"status": "supported"}
    )

    assert result["status"] == "invalid_evidence"


def test_access_rejects_well_formed_but_unissued_direction_evidence():
    unissued = direction()
    unissued["validation_id"] = "direction-not-issued"

    result = routing.i95_access_options(
        "i95", "US-1", "i95", "I-395 Near Edsall Road", unissued
    )

    assert result["status"] == "invalid_evidence"


def test_access_rejects_semantically_fabricated_direction_evidence():
    fabricated = direction()
    fabricated["observations"][0]["link_status"] = "CLOSED"

    result = routing.i95_access_options(
        "i95", "US-1", "i95", "I-395 Near Edsall Road", fabricated
    )

    assert result["status"] == "invalid_evidence"


def test_access_tool_schema_carries_nested_direction_evidence():
    schema = routing.i95_access_options.tool_spec["inputSchema"]["json"]
    assert set(schema["required"]) == {
        "origin_corridor",
        "origin",
        "destination_corridor",
        "destination",
        "direction_result",
    }
    assert schema["properties"]["direction_result"]["type"] == "object"
