"""Shared route legs and observations for current-price tests."""

from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from agent_tools import current_price_domain as pricing_tool

_EASTERN = ZoneInfo("America/New_York")


def greenway_leg(
    *, direction: str = "EB", entry: str = "1", exit_: str = "28"
) -> pricing_tool.route_validation._GreenwayFacilityLeg:
    route_key = f"{direction}:{entry}:{exit_}"
    return pricing_tool.route_validation._GreenwayFacilityLeg.model_validate(
        {
            "route_step_id": "step-1",
            "facility": "greenway",
            "point_ids": [
                f"greenway:{entry}:entry:{direction}",
                f"greenway:{exit_}:exit:{direction}",
            ],
            "connection_ids": [f"source:greenway:{route_key}"],
            "pricing_key": {"source_route_key": route_key, "charge_index": 1},
        }
    )


def dtr_leg(
    *,
    route_step_id: str = "step-1",
    direction: str = "EB",
    entry: str = "10",
    exit_: str = "16",
    charge_index: int = 1,
) -> pricing_tool.route_validation._DtrFacilityLeg:
    route_key = f"{direction}:{entry}:{exit_}"
    return pricing_tool.route_validation._DtrFacilityLeg.model_validate(
        {
            "route_step_id": route_step_id,
            "facility": "dtr",
            "point_ids": [
                f"dtr:{entry}:entry:{direction}",
                f"dtr:{exit_}:exit:{direction}",
            ],
            "connection_ids": [f"source:dtr:{route_key}"],
            "pricing_key": {
                "source_route_key": route_key,
                "charge_index": charge_index,
            },
        }
    )


def dtr_handoff_leg(
    route_key: str, route_step_id: str
) -> pricing_tool.route_validation._DtrFacilityLeg:
    point_ids = {
        "greenway_to_dtr": ["greenway:28:exit:EB", "dtr:28:entry:EB"],
        "dtr_to_greenway": ["dtr:28:exit:WB", "greenway:28:entry:WB"],
    }[route_key]
    return pricing_tool.route_validation._DtrFacilityLeg.model_validate(
        {
            "route_step_id": route_step_id,
            "facility": "dtr",
            "point_ids": point_ids,
            "connection_ids": [route_key],
            "pricing_key": {"source_route_key": route_key, "charge_index": 1},
        }
    )


def i66_leg(
    *,
    route_step_id: str = "step-1",
    direction: str = "EB",
    entry: str = "6",
    exit_: str = "10",
    start_zone_id: int = 3110,
    end_zone_id: int = 3110,
) -> pricing_tool.route_validation._I66FacilityLeg:
    route_key = f"{direction}:{entry}:{exit_}"
    return pricing_tool.route_validation._I66FacilityLeg.model_validate(
        {
            "route_step_id": route_step_id,
            "facility": "i66",
            "point_ids": [
                f"i66:{entry}:entry:{direction}",
                f"i66:{exit_}:exit:{direction}",
            ],
            "connection_ids": [f"source:i66:{route_key}"],
            "pricing_key": {
                "source_route_key": route_key,
                "start_zone_id": start_zone_id,
                "end_zone_id": end_zone_id,
            },
        }
    )


def i66_rows(
    *, unavailable_reason: str | None = None
) -> list[pricing_tool._I66ComparisonRow]:
    evaluated_at = datetime(2026, 8, 13, 8, 32, 6, tzinfo=_EASTERN)
    bin_start = datetime(2026, 8, 13, 8, 24, tzinfo=_EASTERN)
    rows = [
        {
            "evaluated_at": evaluated_at,
            "comparison_kind": "current",
            "comparison_offset": 0,
            "bin_start_at": bin_start
            if unavailable_reason != "missing_observation"
            else None,
            "bin_end_at": bin_start.replace(minute=30)
            if unavailable_reason != "missing_observation"
            else None,
            "interval_end_at": bin_start.replace(minute=29)
            if unavailable_reason != "missing_observation"
            else None,
            "observed_at": (
                evaluated_at - timedelta(minutes=31)
                if unavailable_reason == "stale_observation"
                else bin_start.replace(minute=22)
                if unavailable_reason is None
                else None
            ),
            "price_usd": Decimal("7.20")
            if unavailable_reason != "missing_observation"
            else None,
            "available": unavailable_reason is None,
            "availability_reason": unavailable_reason,
            "source_kind": (
                None if unavailable_reason == "missing_observation" else "observed"
            ),
            "pricing_method": (
                None
                if unavailable_reason == "missing_observation"
                else "source_observation"
            ),
        }
    ]
    if unavailable_reason is None:
        rows.extend(
            {
                "evaluated_at": evaluated_at,
                "comparison_kind": kind,
                "comparison_offset": offset,
                "bin_start_at": bin_start,
                "bin_end_at": bin_start.replace(minute=30),
                "interval_end_at": bin_start.replace(minute=29),
                "observed_at": bin_start.replace(minute=22),
                "price_usd": Decimal(price),
                "available": True,
                "availability_reason": None,
                "source_kind": "observed",
                "pricing_method": "source_observation",
            }
            for kind, offset, price in [
                ("prior_cycle", 1, "6.20"),
                ("prior_cycle", 2, "5.10"),
                ("prior_week", 1, "5.20"),
                ("prior_week", 2, "5.00"),
                ("prior_week", 3, "4.10"),
            ]
        )
    return [pricing_tool._I66ComparisonRow.model_validate(row) for row in rows]


def i95_leg(
    *,
    route_step_id: str = "step-1",
    direction: str = "Northbound",
    entry: str = "203NO",
    exit_: str = "223ND",
    od_pair_id: int = 1261,
    point_ids: list[str] | None = None,
) -> pricing_tool.route_validation._I95FacilityLeg:
    route_key = f"{direction}:{entry}:{exit_}"
    return pricing_tool.route_validation._I95FacilityLeg.model_validate(
        {
            "route_step_id": route_step_id,
            "facility": "i95_i495",
            "point_ids": point_ids or [f"i95:{entry}", f"i95:{exit_}"],
            "connection_ids": [f"source:i95_shared:{route_key}"],
            "pricing_key": {
                "source_route_key": route_key,
                "od_pair_id": od_pair_id,
            },
        }
    )


def i95_rows(
    *,
    unavailable_reason: str | None = None,
    source_kind: str = "observed",
    od_pair_id: int | None = None,
) -> list[pricing_tool._I95ComparisonRow]:
    evaluated_at = datetime(2026, 8, 13, 8, 32, 6, tzinfo=_EASTERN)
    bin_start = datetime(2026, 8, 13, 8, 20, tzinfo=_EASTERN)
    missing = unavailable_reason == "missing_observation"
    stale = unavailable_reason == "stale_observation"
    modeled = source_kind == "modeled"
    provenance = {
        "source_kind": None if missing else source_kind,
        "pricing_method": (
            None
            if missing
            else "identity_proxy_v1"
            if modeled
            else "source_observation"
        ),
        "od_pair_id": None if missing else od_pair_id or (1374 if modeled else 1261),
        "proxy_od_pair_id": 1146 if modeled and not missing else None,
        "source_status": (
            None
            if missing
            else "CLOSED"
            if unavailable_reason == "exceptional_i95_schedule"
            else "NORTHBOUND_OPEN"
        ),
    }
    rows = [
        {
            "evaluated_at": evaluated_at,
            "comparison_kind": "current",
            "comparison_offset": 0,
            "bin_start_at": None if missing else bin_start,
            "bin_end_at": None if missing else bin_start.replace(minute=30),
            "interval_end_at": None if missing else bin_start.replace(minute=29),
            "observed_at": (
                None
                if missing
                else evaluated_at - timedelta(minutes=31)
                if stale
                else bin_start.replace(minute=22)
            ),
            "price_usd": (
                None
                if missing or unavailable_reason == "facility_unavailable"
                else Decimal("8.20")
            ),
            "available": unavailable_reason is None,
            "availability_reason": unavailable_reason,
            **provenance,
        }
    ]
    if unavailable_reason is None:
        rows.extend(
            {
                "evaluated_at": evaluated_at,
                "comparison_kind": kind,
                "comparison_offset": offset,
                "bin_start_at": bin_start,
                "bin_end_at": bin_start.replace(minute=30),
                "interval_end_at": bin_start.replace(minute=29),
                "observed_at": bin_start.replace(minute=22),
                "price_usd": Decimal(price),
                "available": True,
                "availability_reason": None,
                **provenance,
            }
            for kind, offset, price in [
                ("prior_cycle", 1, "7.20"),
                ("prior_cycle", 2, "6.10"),
                ("prior_week", 1, "6.20"),
                ("prior_week", 2, "6.00"),
                ("prior_week", 3, "5.10"),
            ]
        )
    return [pricing_tool._I95ComparisonRow.model_validate(row) for row in rows]
