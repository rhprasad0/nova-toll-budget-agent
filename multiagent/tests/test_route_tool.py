import pytest
from pydantic import ValidationError

from orchestrator import routing
from orchestrator.schemas import I95DirectionResult, RoutePlan
from tests.test_access_tool import REQUESTED_AT, direction


def access(
    origin_corridor: str,
    origin: str,
    destination_corridor: str,
    destination: str,
    direction_result: dict[str, object],
) -> dict[str, object]:
    result = routing.i95_access_options(
        origin_corridor,
        origin,
        destination_corridor,
        destination,
        direction_result,
    )
    assert result["status"] == "supported"
    return result


def test_route_tool_is_universal_for_single_corridor_trip():
    result = routing.plan_toll_route(
        "i66_itb", "I-66 West", "i66_itb", "Westmoreland St", REQUESTED_AT
    )

    plan = RoutePlan.model_validate(result)
    assert plan.status == "ready"
    assert [(step.kind, getattr(step, "facility", None)) for step in plan.steps] == [
        ("toll", "i66_itb")
    ]
    assert plan.steps[0].route_step_id == "step-1"


def test_route_tool_requires_i95_gate_evidence():
    result = routing.plan_toll_route(
        "i95", "US-1", "i95", "I-395 Near Edsall Road", REQUESTED_AT
    )

    assert result["status"] == "validation_failed"
    assert "direction" in result["reason"]


def test_route_tool_builds_direct_i95_plan_from_validated_evidence():
    direction_result = direction()
    access_result = access(
        "i95",
        "US-1",
        "i95",
        "I-395 Near Edsall Road",
        direction_result,
    )

    result = routing.plan_toll_route(
        "i95",
        "US-1",
        "i95",
        "I-395 Near Edsall Road",
        REQUESTED_AT,
        direction_result,
        access_result,
    )

    plan = RoutePlan.model_validate(result)
    assert plan.i95_validation is not None
    assert plan.steps[0].facility == "i95"
    assert plan.steps[0].entry_node_id == "210NO"
    assert plan.steps[0].exit_node_id == "201ND"


def test_route_tool_rejects_access_evidence_for_different_trip():
    direction_result = direction()
    access_result = access(
        "i95",
        "US-1",
        "i95",
        "I-395 Near Edsall Road",
        direction_result,
    )

    result = routing.plan_toll_route(
        "i95",
        "US-1",
        "i95",
        "Seminary Road",
        REQUESTED_AT,
        direction_result,
        access_result,
    )

    assert result["status"] == "validation_failed"


def test_cross_corridor_closure_keeps_supported_toll_leg_and_unpriced_remainder():
    unavailable_values = {
        "status": "unavailable",
        "requested_at": REQUESTED_AT,
        "source_kind": "observed",
        "open_direction": None,
        "observations": [
            {
                "direction": direction_name,
                "od_pair_id": od_pair_id,
                "corridor_name": corridor,
                "link_status": "CLOSED",
                "effective_at": "2026-08-13T07:55:00-04:00",
                "observed_at": "2026-08-13T07:50:00-04:00",
            }
            for direction_name, od_pair_id, corridor in (
                ("Northbound", 1132, "I-95-NB"),
                ("Southbound", 1151, "I-95-SB"),
            )
        ],
        "reason_code": "direction_indeterminate",
        "reason": "I-95 does not have exactly one fully open direction",
    }
    unavailable = routing._record_evidence(
        I95DirectionResult.model_validate(
            routing._register_evidence("direction", unavailable_values)
        )
    )

    result = routing.plan_toll_route(
        "i495", "Westpark Drive", "i95", "US-1", REQUESTED_AT, unavailable
    )

    plan = RoutePlan.model_validate(result)
    assert [step.kind for step in plan.steps] == ["toll", "unpriced"]
    assert plan.steps[0].facility == "i495"
    assert "general-purpose" in plan.steps[1].description.lower()


def test_closed_desired_direction_uses_cross_corridor_partial_route():
    direction_result = direction("Northbound")
    access_result = routing.i95_access_options(
        "i495", "Westpark Drive", "i95", "US-1", direction_result
    )
    assert access_result["status"] == "direction_closed"

    result = routing.plan_toll_route(
        "i495",
        "Westpark Drive",
        "i95",
        "US-1",
        REQUESTED_AT,
        direction_result,
        access_result,
    )

    plan = RoutePlan.model_validate(result)
    assert [(step.kind, getattr(step, "facility", None)) for step in plan.steps] == [
        ("toll", "i495"),
        ("unpriced", None),
    ]


def test_closed_direction_access_cannot_be_reused_for_another_cross_trip():
    direction_result = direction("Northbound")
    access_result = routing.i95_access_options(
        "i495", "Westpark Drive", "i95", "US-1", direction_result
    )
    assert access_result["status"] == "direction_closed"

    result = routing.plan_toll_route(
        "i495",
        "Route 267",
        "i95",
        "US-1",
        REQUESTED_AT,
        direction_result,
        access_result,
    )

    assert result["status"] == "validation_failed"
    assert "exact trip" in result["reason"]


def test_plan_identifier_is_content_stable_and_changes_with_trip_time():
    args = ("i66_itb", "I-66 West", "i66_itb", "Westmoreland St")
    first = routing.plan_toll_route(*args, REQUESTED_AT)
    again = routing.plan_toll_route(*args, REQUESTED_AT)
    changed = routing.plan_toll_route(*args, "2026-08-13T08:15:00-04:00")

    assert first["route_plan_id"] == again["route_plan_id"]
    assert first["route_plan_id"] != changed["route_plan_id"]


def test_route_plan_rejects_content_changed_after_issuance():
    result = routing.plan_toll_route(
        "i66_itb", "I-66 West", "i66_itb", "Westmoreland St", REQUESTED_AT
    )
    result["destination"]["label"] = "A model invented this"

    with pytest.raises(ValidationError, match="immutable plan contents"):
        RoutePlan.model_validate(result)


def test_route_tool_rejects_same_endpoint_without_crashing():
    result = routing.plan_toll_route(
        "i66_itb", "I-66 West", "i66_itb", "I-66 West", REQUESTED_AT
    )

    assert result["status"] == "invalid_request"
    assert "same endpoint" in result["reason"]


def test_connector_is_route_evidence_not_zero_dollar_pricing():
    result = routing.plan_toll_route(
        "i66_itb",
        "Fairfax Drive",
        "dulles_toll_road",
        "Exit 12 - SR 602 (Reston Pkwy)",
        REQUESTED_AT,
    )

    connector = next(step for step in result["steps"] if step["kind"] == "connector")
    assert connector["transfer_id"] == "i66_to_dulles_toll_road"
    assert "price_usd" not in connector


def test_airport_connector_is_preserved_without_becoming_a_toll():
    result = routing.plan_toll_route(
        "airport_iad",
        "Dulles International Airport (IAD)",
        "i66_itb",
        "Fairfax Drive",
        REQUESTED_AT,
    )

    assert [step["kind"] for step in result["steps"]] == ["connector", "toll"]
    assert result["steps"][0]["transfer_id"] == "iad_to_i66"


def test_route_tool_schema_allows_evidence_only_when_needed():
    schema = routing.plan_toll_route.tool_spec["inputSchema"]["json"]
    assert set(schema["required"]) == {
        "origin_corridor",
        "origin",
        "destination_corridor",
        "destination",
        "requested_at",
    }
    variants = schema["properties"]["i95_direction_result"]["anyOf"]
    assert {variant["type"] for variant in variants} == {"object", "null"}
