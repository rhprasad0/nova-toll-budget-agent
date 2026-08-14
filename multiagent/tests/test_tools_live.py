from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from orchestrator import routing
from orchestrator.schemas import RoutePlan

pytestmark = pytest.mark.live


def test_live_i95_direction_access_route_chain():
    requested_at = datetime.now(ZoneInfo("America/New_York")).isoformat()
    direction = routing.i95_direction(requested_at)
    assert direction["status"] == "supported", direction

    origin, destination = (
        ("US-1", "I-395 Near Edsall Road")
        if direction["open_direction"] == "Northbound"
        else ("I-395 Near Edsall Road", "US-1")
    )
    access = routing.i95_access_options("i95", origin, "i95", destination, direction)
    assert access["status"] == "supported", access

    plan = routing.plan_toll_route(
        "i95",
        origin,
        "i95",
        destination,
        direction["requested_at"],
        direction,
        access,
    )
    assert RoutePlan.model_validate(plan).status == "ready"


def test_live_universal_route_without_i95():
    plan = routing.plan_toll_route(
        "i66_itb",
        "I-66 West",
        "i66_itb",
        "Westmoreland St",
        datetime.now(ZoneInfo("America/New_York")).isoformat(),
    )
    assert RoutePlan.model_validate(plan).status == "ready"
