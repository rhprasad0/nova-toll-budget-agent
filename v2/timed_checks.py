"""Reusable freshness, route, and annual checks for timed invocations."""

from __future__ import annotations

import asyncio
import os
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from math import ceil
from typing import Any, cast
from zoneinfo import ZoneInfo

import boto3
from strands.types.tools import ToolResult, ToolUse

from agent_tools import get_annual_toll_ballpark as ballpark
from agent_tools import get_current_toll_price as pricing_tool

MAX_DELAY_SECONDS = 600
NEW_YORK = ZoneInfo("America/New_York")
WINDOW_IDS = (
    "i95_northbound",
    "i95_reversal",
    "i95_southbound",
    "greenway_eb_peak",
    "greenway_wb_peak",
)
type ScheduleWindowPair = tuple[str, str]
SCHEDULE_WINDOW_PAIRS: tuple[ScheduleWindowPair, ...] = (
    ("17 6 * * 1", "i95_northbound"),
    ("17 6 * * 2", "i95_northbound"),
    ("17 6 * * 3", "i95_northbound"),
    ("17 6 * * 4", "i95_northbound"),
    ("17 6 * * 5", "i95_northbound"),
    ("17 14 * * 1", "i95_southbound"),
    ("17 14 * * 2", "i95_southbound"),
    ("17 14 * * 3", "i95_southbound"),
    ("17 14 * * 4", "i95_southbound"),
    ("17 14 * * 5", "i95_southbound"),
    ("17 11 * * 1", "i95_reversal"),
    ("47 1 * * 2", "i95_reversal"),
    ("47 1 * * 3", "i95_reversal"),
    ("47 1 * * 4", "i95_reversal"),
    ("47 1 * * 5", "i95_reversal"),
    ("17 10 * * 6", "i95_southbound"),
    ("17 15 * * 6", "i95_reversal"),
    ("17 18 * * 6", "i95_northbound"),
    ("23 7 * * 1", "greenway_eb_peak"),
    ("23 7 * * 2", "greenway_eb_peak"),
    ("23 7 * * 3", "greenway_eb_peak"),
    ("23 7 * * 4", "greenway_eb_peak"),
    ("23 7 * * 5", "greenway_eb_peak"),
    ("23 17 * * 1", "greenway_wb_peak"),
    ("23 17 * * 2", "greenway_wb_peak"),
    ("23 17 * * 3", "greenway_wb_peak"),
    ("23 17 * * 4", "greenway_wb_peak"),
    ("23 17 * * 5", "greenway_wb_peak"),
)
_DB_IDENTIFIER = "nova-toll-db"
_WINDOW_EXPECTATIONS: dict[str, dict[str, Any]] = {
    "i95_northbound": {
        "availability": "northbound",
        "northbound_status": "valid",
        "northbound_reason": None,
        "southbound_status": "currently_unavailable",
        "southbound_reason": "i95_opposite_direction_open",
        "northbound_link_status": "NORTHBOUND_OPEN",
        "southbound_link_status": "CLOSED",
    },
    "i95_reversal": {
        "availability": "closed",
        "northbound_status": "currently_unavailable",
        "northbound_reason": "i95_fully_closed",
        "southbound_status": "currently_unavailable",
        "southbound_reason": "i95_fully_closed",
        "northbound_link_status": "CLOSED",
        "southbound_link_status": "CLOSED",
    },
    "i95_southbound": {
        "availability": "southbound",
        "northbound_status": "currently_unavailable",
        "northbound_reason": "i95_opposite_direction_open",
        "southbound_status": "valid",
        "southbound_reason": None,
        "northbound_link_status": "CLOSED",
        "southbound_link_status": "SOUTHBOUND_OPEN",
    },
}
_GREENWAY_PEAK_TRIPS = {
    "greenway_eb_peak": ("greenway:1:entry:EB", "greenway:28:exit:EB"),
    "greenway_wb_peak": ("greenway:28:entry:WB", "greenway:1:exit:WB"),
}
type _SampleLeg = tuple[str, int, int | None, str]


def scheduled_run_is_fresh(schedule: str, now: datetime) -> bool:
    """Return whether a scheduled run is within its inclusive 600-second window."""
    if not schedule:
        return True

    minute, hour, _, _, weekday = schedule.split()
    if now.isoweekday() != int(weekday):
        return False

    scheduled_at = now.replace(
        hour=int(hour), minute=int(minute), second=0, microsecond=0
    )
    return 0 <= (now - scheduled_at).total_seconds() <= MAX_DELAY_SECONDS


def _configure_rds_endpoint() -> None:
    rds = cast(
        Any,
        boto3.client("rds", region_name="us-east-1"),  # pyright: ignore[reportUnknownMemberType]
    )
    instance = cast(
        dict[str, Any],
        rds.describe_db_instances(DBInstanceIdentifier=_DB_IDENTIFIER)["DBInstances"][
            0
        ],
    )
    os.environ["DB_HOST"] = instance["Endpoint"]["Address"]
    os.environ["DB_PORT"] = str(instance["Endpoint"]["Port"])


def _tool_use(origin: str, destination: str, tool_use_id: str) -> ToolUse:
    return cast(
        ToolUse,
        {
            "toolUseId": tool_use_id,
            "name": "get_current_toll_price",
            "input": {
                "origin_point_id": origin,
                "destination_point_id": destination,
                "pricing_profile": {
                    "vehicle_class": "two_axle_passenger",
                    "payment_method": "e_zpass",
                    "transponder_mode": "toll",
                },
            },
        },
    )


def _run_pricing_tool(tool_use: ToolUse) -> ToolResult:
    async def invoke() -> ToolResult:
        result: ToolResult | None = None
        async for event in pricing_tool.get_current_toll_price.stream(
            tool_use, {"agent": object()}
        ):
            if event.get("type") == "tool_result":
                result = cast(ToolResult, event["tool_result"])
        assert result is not None
        return result

    return asyncio.run(invoke())


def _validate(origin: str, destination: str, tool_use_id: str) -> dict[str, Any]:
    result = _run_pricing_tool(_tool_use(origin, destination, tool_use_id))
    assert result["status"] == "success", result
    assert result["toolUseId"] == tool_use_id
    assert len(result["content"]) == 1
    content = cast(Any, result["content"])
    return cast(dict[str, Any], content[0]["json"])


def _assert_priced(payload: dict[str, Any], origin: str, destination: str) -> None:
    assert payload["origin_point_id"] == origin
    assert payload["destination_point_id"] == destination
    assert payload["method"] == "latest_complete_current_facility_prices"
    assert float(payload["total_usd"]) > 0
    assert any(
        component["facility"] == "i95_i495" for component in payload["components"]
    )


def _reason_code(route: dict[str, Any]) -> str | None:
    reason = route["reason"]
    return None if reason is None else cast(str, reason["code"])


def _assert_unavailable(
    payload: dict[str, Any],
    status: str | None,
    reason: str | None,
    expected: dict[str, Any],
) -> None:
    assert status is not None
    assert reason is not None
    assert payload["status"] == status
    assert _reason_code(payload) == reason
    evidence = payload["i95_evidence"]
    assert evidence["availability"] == expected["availability"]
    assert evidence["northbound_link_status"] == expected["northbound_link_status"]
    assert evidence["southbound_link_status"] == expected["southbound_link_status"]


def run_route_checks(window_id: str) -> dict[str, Any]:
    """Run the current-price assertions for one approved timed window."""
    if window_id not in WINDOW_IDS:
        raise ValueError("unknown timed window")
    _configure_rds_endpoint()

    if window_id in _WINDOW_EXPECTATIONS:
        expected = _WINDOW_EXPECTATIONS[window_id]
        northbound_origin, northbound_destination = "i95:203NO", "airport_dca"
        southbound_origin, southbound_destination = "i95:200SO", "i95:202SD"
        northbound = _validate(
            northbound_origin, northbound_destination, f"{window_id}-northbound"
        )
        southbound = _validate(
            southbound_origin, southbound_destination, f"{window_id}-southbound"
        )
        i66 = _validate(
            "i66:1:entry:EB", "i66:4:exit:EB", f"{window_id}-i66-pricing-route"
        )

        if expected["northbound_status"] == "valid":
            _assert_priced(northbound, northbound_origin, northbound_destination)
        else:
            _assert_unavailable(
                northbound,
                expected["northbound_status"],
                expected["northbound_reason"],
                expected,
            )
        if expected["southbound_status"] == "valid":
            _assert_priced(southbound, southbound_origin, southbound_destination)
        else:
            _assert_unavailable(
                southbound,
                expected["southbound_status"],
                expected["southbound_reason"],
                expected,
            )
        assert i66["method"] == "latest_complete_current_facility_prices"
        assert any(component["facility"] == "i66" for component in i66["components"])

        initial = _validate("i95:206NO", "i495:1859ND", f"{window_id}-restart-offer")
        assert initial == {
            "status": "invalid_origin",
            "reason": {
                "code": "i95_northbound_requires_i495_restart",
                "details": {
                    "point_id": "i95:206NO",
                    "point_type": "entry",
                    "suggested_restart_point_id": "i495:192NO",
                    "suggested_destination_point_id": "i495:185ND",
                },
            },
            "point_ids": [],
            "connection_ids": [],
            "connection_types": [],
            "general_purpose_gaps": [],
            "i95_evidence": None,
        }
        accepted = _validate(
            "i495:192NO", "i495:185ND", f"{window_id}-restart-accepted"
        )
        assert accepted["origin_point_id"] == "i495:192NO"
        assert accepted["destination_point_id"] == "i495:185ND"
        assert accepted["method"] == "latest_complete_current_facility_prices"
        assert "total_usd" in accepted
        assert any(
            component["facility"] == "i95_i495" for component in accepted["components"]
        )

        payload = _validate(
            "greenway:1:entry:EB", "airport_dca", f"{window_id}-greenway-to-dca"
        )
        if expected["northbound_status"] == "valid":
            _assert_priced(payload, "greenway:1:entry:EB", "airport_dca")
            assert [component["facility"] for component in payload["components"]] == [
                "greenway",
                "dtr",
                "dtr",
                "i95_i495",
                "i95_i495",
            ]
        else:
            _assert_unavailable(
                payload,
                expected["northbound_status"],
                expected["northbound_reason"],
                expected,
            )
            assert payload["point_ids"] == [
                "greenway:1:entry:EB",
                "greenway:28:exit:EB",
                "dtr:28:entry:EB",
                "dtr:1819:exit:EB",
                "i495:182SO",
                "i95:2239ND",
                "airport_dca",
            ]
            assert payload["connection_ids"] == [
                "source:greenway:EB:1:28",
                "greenway_to_dtr",
                "source:dtr:EB:28:1819",
                "dulles_toll_road_to_i495",
                "source:i95_shared:Southbound:182SO:2239ND",
                "i95_north_to_dca_from_i495_south",
            ]
            assert payload["connection_types"] == [
                "within_facility",
                "toll_handoff",
                "within_facility",
                "toll_handoff",
                "general_purpose_gap",
                "airport_access",
            ]
            assert payload["general_purpose_gaps"] == [
                {
                    "connection_id": "source:i95_shared:Southbound:182SO:2239ND",
                    "boundary_point_id": "i495:192SD",
                    "role": "suffix",
                    "i95_direction": "NB",
                    "fallback_required": window_id != "i95_northbound",
                }
            ]
        return {
            "status": "succeeded",
            "window_id": window_id,
            "checks": ["i95_state", "i95_restart", "greenway_to_dca"],
        }

    origin, destination = _GREENWAY_PEAK_TRIPS[window_id]
    result = _run_pricing_tool(_tool_use(origin, destination, window_id))
    assert result["status"] == "success", result
    content = cast(Any, result["content"])
    payload = cast(dict[str, Any], content[0]["json"])
    assert payload["origin_point_id"] == origin
    assert payload["destination_point_id"] == destination
    assert payload["source_kind"] == "schedule_derived"
    assert payload["total_usd"] == "5.80"
    assert len(payload["components"]) == 1
    component = payload["components"][0]
    assert component["facility"] == "greenway"
    assert component["price_usd"] == "5.80"
    assert component["rate_period"] == "peak"
    assert component["published_schedule"]["rate_name"] == "mainline_plaza"
    return {"status": "succeeded", "window_id": window_id, "checks": ["greenway_peak"]}


def _run(data: dict[str, Any], tool_use_id: str) -> dict[str, Any]:
    tool_use = cast(
        ToolUse,
        {
            "name": "get_annual_toll_ballpark",
            "toolUseId": tool_use_id,
            "input": data,
        },
    )

    async def invoke() -> ToolResult:
        result: ToolResult | None = None
        async for event in ballpark.get_annual_toll_ballpark.stream(
            tool_use, {"agent": object()}
        ):
            if "tool_result" in event:
                result = cast(ToolResult, event["tool_result"])
        assert result is not None
        return result

    result = asyncio.run(invoke())
    assert result["status"] == "success", result
    content = cast(Any, result["content"])
    return cast(dict[str, Any], content[0]["json"])


def _request(
    outbound: tuple[str, str, str],
    return_: tuple[str, str, str],
    *,
    weekdays: list[str] | None = None,
    annual_days: int = 53,
    gross_income: str = "120000.00",
) -> dict[str, Any]:
    return {
        "outbound": {
            "origin_point_id": outbound[0],
            "destination_point_id": outbound[1],
            "departure_time": outbound[2],
        },
        "return": {
            "origin_point_id": return_[0],
            "destination_point_id": return_[1],
            "departure_time": return_[2],
        },
        "weekdays": weekdays or ["monday"],
        "planned_annual_commute_days": annual_days,
        "gross_annual_income_usd": gross_income,
    }


def _assert_annualized(payload: dict[str, Any], annual_days: int) -> None:
    for scenario in payload.values():
        assert Decimal(scenario["annual_toll_usd"]) == (
            Decimal(scenario["daily_toll_usd"]) * annual_days
        ).quantize(Decimal("0.01"))


def _raw_scenarios(
    payload: dict[str, Any],
    case_input: dict[str, Any],
    sample_legs: list[_SampleLeg],
    fixed_daily: Decimal,
) -> dict[str, dict[str, str]]:
    start = date.fromisoformat(payload["target_window"]["start_date"])
    end = date.fromisoformat(payload["target_window"]["end_date"])
    weekdays = {
        (
            "monday",
            "tuesday",
            "wednesday",
            "thursday",
            "friday",
            "saturday",
            "sunday",
        ).index(day)
        for day in case_input["weekdays"]
    }
    dates = [
        start + timedelta(days=offset)
        for offset in range((end - start).days + 1)
        if (start + timedelta(days=offset)).weekday() in weekdays
    ]
    samples: list[dict[date, Decimal]] = []
    connection = cast(Any, ballpark.route_validation.connect_to_pricing_database())
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
            )
            for facility, first_id, second_id, local_time in sample_legs:
                if facility == "i66":
                    cursor.execute(
                        """SELECT sample_date, price_usd
                           FROM oracle.get_i66_ballpark_samples(
                               %s, %s, %s, %s, %s, transaction_timestamp()
                           )""",
                        (
                            first_id,
                            second_id,
                            "EB" if first_id < 3200 else "WB",
                            time.fromisoformat(local_time),
                            dates,
                        ),
                    )
                else:
                    cursor.execute(
                        """SELECT sample_date, price_usd
                           FROM oracle.get_i95_i495_ballpark_samples(
                               %s, %s, %s, transaction_timestamp()
                           )""",
                        (first_id, time.fromisoformat(local_time), dates),
                    )
                samples.append(
                    {row["sample_date"]: row["price_usd"] for row in cursor.fetchall()}
                )
    finally:
        connection.rollback()
        connection.close()

    complete_dates = set(dates).intersection(*(set(sample) for sample in samples))
    assert len(complete_dates) == payload["coverage"]["complete_pair_count"]
    totals = sorted(
        fixed_daily + sum((sample[day] for sample in samples), start=Decimal())
        for day in complete_dates
    )
    annual_days = case_input["planned_annual_commute_days"]
    result: dict[str, dict[str, str]] = {}
    for name, percentile in (("p25", 0.25), ("p50", 0.50), ("p90", 0.90)):
        daily = totals[ceil(percentile * len(totals)) - 1]
        result[name] = {
            "daily_toll_usd": f"{daily:.2f}",
            "annual_toll_usd": f"{daily * annual_days:.2f}",
        }
    return result


def run_annual_checks() -> dict[str, Any]:
    """Run the fixed and dynamic annual-ballpark contract checks."""
    _configure_rds_endpoint()
    fixed_input = _request(
        ("greenway:1:entry:EB", "greenway:28:exit:EB", "08:00:00"),
        ("greenway:28:entry:WB", "greenway:1:exit:WB", "17:30:00"),
    )
    payload = _run(fixed_input, "annual-ballpark-fixed")
    assert payload["method"] == "recent_complete_same_date_round_trips"
    assert payload["sample_status"] == "complete"
    assert payload["coverage"]["eligible_date_count"] == 12
    assert payload["coverage"]["coverage_percent"] == "100.0"
    assert payload["uses_current_fixed_rates"] is True
    assert payload["income"]["estimated_after_tax_usd"] == "80000.00"
    assert payload["assumptions"]["scope"] == "tolled_portions_only"
    assert payload["scenarios"]["p50"]["daily_toll_usd"] == "11.60"
    assert payload["scenarios"]["p50"]["annual_toll_usd"] == "614.80"
    assert Decimal(
        payload["scenarios"]["p50"]["annual_total_tolled_commute_cost_usd"]
    ) == Decimal("614.80") + Decimal(payload["vehicle_cost"]["annual_usd"])
    assert payload["facilities"][0]["facility"] == "greenway"

    dynamic_cases: list[
        tuple[str, dict[str, Any], list[str], list[_SampleLeg], Decimal]
    ] = [
        (
            "springfield-pentagon",
            _request(
                ("i95:206NO", "i95:223ND", "09:00:00"),
                ("i95:2233SO", "i95:206SD", "17:30:00"),
                weekdays=["monday", "tuesday", "wednesday", "thursday", "friday"],
                annual_days=240,
            ),
            ["i95_i495"],
            [
                ("i95_i495", 1255, None, "09:00:00"),
                ("i95_i495", 1207, None, "17:30:00"),
            ],
            Decimal(),
        ),
        (
            "springfield-westpark-backlick",
            _request(
                ("i95:206NO", "i495:185ND", "08:30:00"),
                ("i495:185SO", "i95:205SD", "17:30:00"),
                weekdays=["monday", "tuesday", "wednesday", "thursday", "friday"],
                annual_days=240,
            ),
            ["i95_i495"],
            [
                ("i95_i495", 1140, None, "08:30:00"),
                ("i95_i495", 1089, None, "08:30:00"),
                ("i95_i495", 1062, None, "17:30:00"),
                ("i95_i495", 1379, None, "17:30:00"),
            ],
            Decimal(),
        ),
        (
            "leesburg-washington",
            _request(
                ("greenway:1:entry:EB", "i66:16:exit:EB", "07:00:00"),
                ("i66:16:entry:WB", "greenway:1:exit:WB", "17:00:00"),
                weekdays=["monday", "friday"],
                annual_days=96,
            ),
            ["greenway", "dtr", "i66"],
            [
                ("i66", 3110, 3130, "07:00:00"),
                ("i66", 3200, 3220, "17:00:00"),
            ],
            Decimal("23.60"),
        ),
    ]
    for (
        tool_use_id,
        case_input,
        expected_facilities,
        sample_legs,
        fixed_daily,
    ) in dynamic_cases:
        payload = _run(case_input, f"annual-ballpark-{tool_use_id}")
        complete_days = payload["coverage"]["complete_pair_count"]
        assert 0 < complete_days <= payload["coverage"]["eligible_date_count"]
        assert set(payload["scenarios"]) == {"p25", "p50", "p90"}
        assert [
            item["facility"] for item in payload["facilities"]
        ] == expected_facilities
        assert all(
            item["sample_count"] == complete_days for item in payload["facilities"]
        )
        toll_scenarios = {
            name: {
                "daily_toll_usd": scenario["daily_toll_usd"],
                "annual_toll_usd": scenario["annual_toll_usd"],
            }
            for name, scenario in payload["scenarios"].items()
        }
        assert toll_scenarios == _raw_scenarios(
            payload, case_input, sample_legs, fixed_daily
        )
        _assert_annualized(
            payload["scenarios"], case_input["planned_annual_commute_days"]
        )
        for facility in payload["facilities"]:
            _assert_annualized(
                facility["scenarios"], case_input["planned_annual_commute_days"]
            )
        if len(expected_facilities) == 1:
            assert toll_scenarios == payload["facilities"][0]["scenarios"]
        else:
            fixed = {item["facility"]: item for item in payload["facilities"]}
            assert {
                scenario["daily_toll_usd"]
                for scenario in fixed["greenway"]["scenarios"].values()
            } == {"11.60"}
            assert {
                scenario["daily_toll_usd"]
                for scenario in fixed["dtr"]["scenarios"].values()
            } == {"12.00"}
        assert not ({"complete_days", "excluded_dates", "routes"} & payload.keys())

    return {"status": "succeeded", "cases": 4}
