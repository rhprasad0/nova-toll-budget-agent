import pytest

from orchestrator import routing
from orchestrator.schemas import RoutePlan
from tests.test_access_tool import REQUESTED_AT, direction
from tests.test_route_tool import access


@pytest.mark.parametrize(
    ("origin_corridor", "origin", "destination_corridor", "destination", "transfer"),
    [
        (
            "i66_itb",
            "Lee Highway - Scott Street",
            "i495",
            "Braddock Road",
            "i66_to_i495",
        ),
        (
            "i495",
            "Braddock Road",
            "i66_itb",
            "Westmoreland St",
            "i495_to_i66",
        ),
        (
            "i66_itb",
            "Route 7 - Leesburg Pike",
            "i495",
            "Westpark Drive",
            "i66_to_i495_north",
        ),
        (
            "i495",
            "495 Express Lanes Start/Georg Wash. Mem. Pkwy.",
            "i66_itb",
            "Westmoreland St",
            "i495_south_to_i66",
        ),
    ],
)
def test_universal_route_covers_all_i66_i495_movements(
    origin_corridor, origin, destination_corridor, destination, transfer
):
    plan = routing.plan_toll_route(
        origin_corridor,
        origin,
        destination_corridor,
        destination,
        REQUESTED_AT,
    )

    RoutePlan.model_validate(plan)
    assert [step["kind"] for step in plan["steps"]] == [
        "toll",
        "connector",
        "toll",
    ]
    assert plan["steps"][1]["transfer_id"] == transfer


@pytest.mark.parametrize(
    ("origin_corridor", "origin", "destination_corridor", "destination", "transfer"),
    [
        (
            "dulles_toll_road",
            "Exit 12 - SR 602 (Reston Pkwy)",
            "i495",
            "Braddock Road",
            "dulles_toll_road_to_i495",
        ),
        (
            "dulles_toll_road",
            "Exit 12 - SR 602 (Reston Pkwy)",
            "i495",
            "495 Express Lanes End/George Wash. Mem. Pkwy.",
            "dulles_toll_road_to_i495_north",
        ),
        (
            "i495",
            "Braddock Road",
            "dulles_toll_road",
            "Exit 12 - SR 602 (Reston Pkwy)",
            "i495_to_dulles_toll_road",
        ),
        (
            "i495",
            "495 Express Lanes Start/Georg Wash. Mem. Pkwy.",
            "dulles_toll_road",
            "Exit 12 - SR 602 (Reston Pkwy)",
            "i495_south_to_dulles_toll_road",
        ),
    ],
)
def test_universal_route_covers_all_dulles_i495_movements(
    origin_corridor, origin, destination_corridor, destination, transfer
):
    plan = routing.plan_toll_route(
        origin_corridor,
        origin,
        destination_corridor,
        destination,
        REQUESTED_AT,
    )

    assert plan["status"] == "ready"
    assert plan["steps"][1]["transfer_id"] == transfer


def test_non_i95_directional_mismatch_returns_recovery_without_a_plan():
    result = routing.plan_toll_route(
        "i495",
        "Westpark Drive",
        "i66_itb",
        "Lee Highway - Scott Street",
        REQUESTED_AT,
    )

    assert result["status"] == "one_way_mismatch"
    assert result["constraints"][0]["nearby_options"][0] == "Fairfax Drive"


def test_supported_i95_to_i495_plan_orders_toll_gap_toll():
    direction_result = direction("Northbound")
    access_result = access("i95", "US-1", "i495", "Westpark Drive", direction_result)

    plan = routing.plan_toll_route(
        "i95",
        "US-1",
        "i495",
        "Westpark Drive",
        REQUESTED_AT,
        direction_result,
        access_result,
    )

    assert [(step["kind"], step.get("facility")) for step in plan["steps"]] == [
        ("toll", "i95"),
        ("unpriced", None),
        ("toll", "i495"),
    ]


def test_supported_i495_to_i95_plan_orders_toll_gap_toll():
    direction_result = direction("Southbound")
    access_result = access("i495", "Westpark Drive", "i95", "US-1", direction_result)

    plan = routing.plan_toll_route(
        "i495",
        "Westpark Drive",
        "i95",
        "US-1",
        REQUESTED_AT,
        direction_result,
        access_result,
    )

    assert [(step["kind"], step.get("facility")) for step in plan["steps"]] == [
        ("toll", "i495"),
        ("unpriced", None),
        ("toll", "i95"),
    ]


def test_dca_to_i95_uses_direction_access_and_airport_connector():
    direction_result = direction("Southbound")
    access_result = routing.i95_access_options(
        "airport_dca",
        "Ronald Reagan Washington National Airport (DCA)",
        "i95",
        "US-1",
        direction_result,
    )
    assert access_result["status"] == "supported"
    assert access_result["entry_node_id"] == "2233SO"
    assert access_result["exit_node_id"] == "210SD"

    plan = routing.plan_toll_route(
        "airport_dca",
        "Ronald Reagan Washington National Airport (DCA)",
        "i95",
        "US-1",
        REQUESTED_AT,
        direction_result,
        access_result,
    )
    assert [step["kind"] for step in plan["steps"]] == ["connector", "toll"]
    assert plan["steps"][0]["transfer_id"] == "dca_to_i95"


def test_i95_to_dca_uses_direction_access_and_airport_connector():
    direction_result = direction("Northbound")
    access_result = routing.i95_access_options(
        "i95",
        "US-1",
        "airport_dca",
        "Ronald Reagan Washington National Airport (DCA)",
        direction_result,
    )
    assert access_result["status"] == "supported"
    assert access_result["entry_node_id"] == "210NO"
    assert access_result["exit_node_id"] == "223ND"

    plan = routing.plan_toll_route(
        "i95",
        "US-1",
        "airport_dca",
        "Ronald Reagan Washington National Airport (DCA)",
        REQUESTED_AT,
        direction_result,
        access_result,
    )
    assert [step["kind"] for step in plan["steps"]] == ["toll", "connector"]
    assert plan["steps"][-1]["transfer_id"] == "i95_to_dca_northbound"


def test_cross_corridor_route_to_dca_uses_the_i95_gates():
    direction_result = direction("Northbound")
    access_result = routing.i95_access_options(
        "dulles_greenway",
        "Exit 1 - US 15/SR 7 (Leesburg Bypass)",
        "airport_dca",
        "Ronald Reagan Washington National Airport (DCA)",
        direction_result,
    )
    assert access_result["status"] == "supported"
    assert access_result["movement"] == "i495_to_i95"

    plan = routing.plan_toll_route(
        "dulles_greenway",
        "Exit 1 - US 15/SR 7 (Leesburg Bypass)",
        "airport_dca",
        "Ronald Reagan Washington National Airport (DCA)",
        REQUESTED_AT,
        direction_result,
        access_result,
    )
    assert [step["kind"] for step in plan["steps"]] == [
        "toll",
        "toll",
        "connector",
        "toll",
        "unpriced",
        "toll",
        "connector",
    ]
