"""Opt-in live checks for the annual toll ballpark tool."""

import asyncio
import os
from datetime import date, time, timedelta
from decimal import Decimal
from math import ceil
from typing import Any, cast

import boto3
import pytest
from strands.types.tools import ToolResult, ToolUse

from agent_tools import get_annual_toll_ballpark as ballpark

pytestmark = pytest.mark.live

_DB_IDENTIFIER = "nova-toll-db"
type _SampleLeg = tuple[str, int, int | None, str]


def _configure_rds_endpoint() -> None:
    rds = cast(
        Any,
        boto3.client(  # pyright: ignore[reportUnknownMemberType]
            "rds", region_name="us-east-1"
        ),
    )
    instance = cast(
        dict[str, Any],
        rds.describe_db_instances(DBInstanceIdentifier=_DB_IDENTIFIER)["DBInstances"][
            0
        ],
    )
    os.environ["DB_HOST"] = instance["Endpoint"]["Address"]
    os.environ["DB_PORT"] = str(instance["Endpoint"]["Port"])


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
    }


def _assert_annualized(payload: dict[str, Any], annual_days: int) -> None:
    for scenario in payload.values():
        assert Decimal(scenario["annualized_usd"]) == (
            Decimal(scenario["daily_round_trip_usd"]) * annual_days
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
    connection = cast(
        Any,
        ballpark.route_validation._connect(),  # pyright: ignore[reportPrivateUsage]
    )
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
                               %s, %s, %s, %s, transaction_timestamp()
                           )""",
                        (first_id, second_id, time.fromisoformat(local_time), dates),
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
            "daily_round_trip_usd": f"{daily:.2f}",
            "annualized_usd": f"{daily * annual_days:.2f}",
        }
    return result


def test_live_fixed_rate_round_trip() -> None:
    _configure_rds_endpoint()
    payload = _run(
        _request(
            ("greenway:1:entry:EB", "greenway:28:exit:EB", "08:00:00"),
            ("greenway:28:entry:WB", "greenway:1:exit:WB", "17:30:00"),
        ),
        "annual-ballpark-fixed",
    )
    assert payload["method"] == "recent_complete_same_date_round_trips"
    assert payload["sample_status"] == "complete"
    assert payload["coverage"]["eligible_date_count"] == 12
    assert payload["coverage"]["coverage_percent"] == "100.0"
    assert payload["uses_current_fixed_rates"] is True
    assert payload["scenarios"]["p50"]["daily_round_trip_usd"] == "11.60"
    assert payload["scenarios"]["p50"]["annualized_usd"] == "614.80"
    assert payload["facilities"][0]["facility"] == "greenway"


@pytest.mark.parametrize(
    (
        "tool_use_id",
        "case_input",
        "expected_facilities",
        "sample_legs",
        "fixed_daily",
    ),
    [
        pytest.param(
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
            id="springfield-pentagon",
        ),
        pytest.param(
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
            id="springfield-westpark-backlick",
        ),
        pytest.param(
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
            id="leesburg-washington",
        ),
    ],
)
def test_live_dynamic_smoke_routes_have_complete_samples(
    tool_use_id: str,
    case_input: dict[str, Any],
    expected_facilities: list[str],
    sample_legs: list[_SampleLeg],
    fixed_daily: Decimal,
) -> None:
    _configure_rds_endpoint()
    payload = _run(case_input, f"annual-ballpark-{tool_use_id}")
    complete_days = payload["coverage"]["complete_pair_count"]
    assert 0 < complete_days <= payload["coverage"]["eligible_date_count"]
    assert set(payload["scenarios"]) == {"p25", "p50", "p90"}
    assert [item["facility"] for item in payload["facilities"]] == expected_facilities
    assert all(item["sample_count"] == complete_days for item in payload["facilities"])
    annual_days = case_input["planned_annual_commute_days"]
    assert payload["scenarios"] == _raw_scenarios(
        payload, case_input, sample_legs, fixed_daily
    )
    _assert_annualized(payload["scenarios"], annual_days)
    for facility in payload["facilities"]:
        _assert_annualized(facility["scenarios"], annual_days)
    if len(expected_facilities) == 1:
        assert payload["scenarios"] == payload["facilities"][0]["scenarios"]
    else:
        fixed = {item["facility"]: item for item in payload["facilities"]}
        assert {
            scenario["daily_round_trip_usd"]
            for scenario in fixed["greenway"]["scenarios"].values()
        } == {"11.60"}
        assert {
            scenario["daily_round_trip_usd"]
            for scenario in fixed["dtr"]["scenarios"].values()
        } == {"12.00"}
    assert not ({"complete_days", "excluded_dates", "routes"} & payload.keys())
