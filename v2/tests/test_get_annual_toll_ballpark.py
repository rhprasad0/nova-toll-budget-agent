# pyright: basic

import asyncio
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any, cast
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError
from strands.types.tools import ToolResult, ToolUse

from agent_tools import get_annual_toll_ballpark as ballpark

_EASTERN = ZoneInfo("America/New_York")


def _input() -> dict[str, Any]:
    return {
        "outbound": {
            "origin_point_id": "airport_iad",
            "destination_point_id": "i66:6:entry:EB",
            "departure_time": "08:00:00",
        },
        "return": {
            "origin_point_id": "i66:6:exit:WB",
            "destination_point_id": "airport_iad",
            "departure_time": "17:30:00",
        },
        "weekdays": ["monday", "wednesday", "friday"],
        "planned_annual_commute_days": 144,
        "gross_annual_income_usd": "120000.00",
    }


def _route(*, status: str = "valid", facility_legs=None):
    if status == "valid":
        return ballpark._BallparkRouteDb.model_validate(
            {
                "status": "valid",
                "reason": None,
                "point_ids": ["airport_iad", "i66:6:entry:EB"],
                "connection_ids": ["iad_to_i66"],
                "connection_types": ["airport_access"],
                "general_purpose_gaps": [],
                "facility_legs": facility_legs or [],
            }
        )
    return ballpark._BallparkRouteDb.model_validate(
        {
            "status": status,
            "reason": {
                "code": "no_supported_route",
                "details": {
                    "origin_point_id": "airport_iad",
                    "destination_point_id": "nowhere",
                },
            },
            "point_ids": [],
            "connection_ids": [],
            "connection_types": [],
            "general_purpose_gaps": [],
            "facility_legs": [],
        }
    )


def _i95_northbound_restart_route():
    return ballpark._BallparkRouteDb.model_validate(
        {
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
            "facility_legs": [],
        }
    )


def _greenway_route():
    return ballpark._BallparkRouteDb.model_validate(
        {
            "status": "valid",
            "reason": None,
            "point_ids": ["greenway:1:entry:EB", "greenway:28:exit:EB"],
            "connection_ids": ["source:greenway:EB:1:28"],
            "connection_types": ["within_facility"],
            "general_purpose_gaps": [],
            "facility_legs": [
                {
                    "route_step_id": "step-1",
                    "facility": "greenway",
                    "point_ids": ["greenway:1:entry:EB", "greenway:28:exit:EB"],
                    "connection_ids": ["source:greenway:EB:1:28"],
                    "pricing_key": {"source_route_key": "EB:1:28", "charge_index": 1},
                }
            ],
        }
    )


def _summary(*, complete=1):
    return ballpark._SummaryRow.model_validate(
        {
            "eligible_date_count": 1,
            "complete_pair_count": complete,
            "coverage_percent": "100.0" if complete else "0.0",
            "coverage_by_weekday": [
                {
                    "sample_isodow": 3,
                    "eligible_date_count": 1,
                    "complete_pair_count": complete,
                    "coverage_percent": "100.0" if complete else "0.0",
                }
            ],
            "available_start_date": date(2026, 8, 19) if complete else None,
            "available_end_date": date(2026, 8, 19) if complete else None,
            "sample_status": "complete" if complete else "partial",
            "uses_modeled": False,
            "uses_current_fixed_rates": False,
            "facility_scenarios": [
                {
                    "facility": "i66",
                    "sample_count": 1,
                    "uses_modeled": False,
                    "uses_current_fixed_rates": False,
                    "scenarios": {
                        key: {
                            "daily_round_trip_usd": "4.00",
                            "annualized_usd": "576.00",
                        }
                        for key in ("p25", "p50", "p90")
                    },
                }
            ]
            if complete
            else [],
            "p25_daily_usd": Decimal("7.00") if complete else None,
            "p50_daily_usd": Decimal("8.00") if complete else None,
            "p90_daily_usd": Decimal("9.00") if complete else None,
            "p25_annualized_usd": Decimal("1008.00") if complete else None,
            "p50_annualized_usd": Decimal("1152.00") if complete else None,
            "p90_annualized_usd": Decimal("1296.00") if complete else None,
        },
        context={
            "dates": [date(2026, 8, 19)],
            "annual_days": 144,
            "facilities": ["i66"],
        },
    )


def _tool_use(data: Any) -> ToolUse:
    return cast(
        ToolUse,
        {
            "name": "get_annual_toll_ballpark",
            "toolUseId": "ballpark-123",
            "input": data,
        },
    )


async def _invoke(data: Any) -> tuple[list[dict[str, Any]], ToolResult]:
    events = []
    result = None
    async for event in ballpark.get_annual_toll_ballpark.stream(
        _tool_use(data), {"agent": object()}
    ):
        if event.get("type") == "tool_stream":
            value = event["tool_stream_event"]["data"]
            if isinstance(value, dict) and "stage" in value:
                events.append(value)
        if "tool_result" in event:
            result = event["tool_result"]
    assert result is not None
    return events, result


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update({"extra": True}),
        lambda value: value.update({"weekdays": ["monday", "monday"]}),
        lambda value: value.update({"weekdays": []}),
        lambda value: value.update({"planned_annual_commute_days": 160}),
        lambda value: value.pop("gross_annual_income_usd"),
        lambda value: value.update({"gross_annual_income_usd": "120000"}),
        lambda value: value["outbound"].update({"departure_time": "8am"}),
        lambda value: value.update({"pricing_profile": {"vehicle_class": "truck"}}),
    ],
)
def test_request_is_strict_and_profile_is_implicit(mutation):
    data = _input()
    mutation(data)
    with pytest.raises(ValidationError):
        ballpark._BallparkRequest.model_validate(data)


def test_overnight_fails_before_database(monkeypatch):
    monkeypatch.setattr(
        ballpark.route_validation,
        "connect_to_pricing_database",
        lambda: pytest.fail("database should not be opened"),
    )
    data = _input()
    data["return"]["departure_time"] = "07:30:00"
    events, result = asyncio.run(_invoke(data))
    assert events == []
    assert result["content"] == [
        {"json": {"error": "ballpark_unavailable", "reason": "overnight_schedule"}}
    ]


def test_wall_time_resolution_rejects_dst_gap_and_fold():
    assert (
        ballpark._resolve_unambiguous_eastern_datetime(date(2026, 3, 8), time(2, 30))
        is None
    )
    assert (
        ballpark._resolve_unambiguous_eastern_datetime(date(2025, 11, 2), time(1, 30))
        is None
    )
    assert ballpark._resolve_unambiguous_eastern_datetime(
        date(2026, 3, 9), time(8)
    ) == datetime(2026, 3, 9, 8, tzinfo=_EASTERN)


def test_fixed_rates_are_computed_for_each_sample_date():
    request = ballpark._BallparkRequest.model_validate(
        {
            **_input(),
            "weekdays": ["monday", "saturday"],
            "planned_annual_commute_days": 100,
        }
    )
    legs, prices = ballpark._build_summary_query_inputs(
        (_greenway_route(), _route()),
        request,
        [date(2026, 8, 17), date(2026, 8, 22)],
    )
    assert legs[0] == {
        "direction": "outbound",
        "route_step_id": "step-1",
        "facility": "greenway",
    }
    assert [item["price_usd"] for item in prices] == ["5.80", "5.25"]


def test_compact_response_uses_database_scenarios():
    request = ballpark._BallparkRequest.model_validate(_input())
    response = ballpark._build_ballpark_response(
        request,
        datetime(2026, 8, 20, 12, tzinfo=_EASTERN),
        _summary(),
        Decimal("20.00"),
    )
    output = response.model_dump(mode="json")
    assert output["income"] == {
        "gross_annual_usd": "120000.00",
        "estimated_tax_usd": "40000.00",
        "estimated_after_tax_usd": "80000.00",
    }
    assert output["tolled_distance"] == {
        "daily_round_trip_miles": "20.00",
        "annual_miles": "2880.00",
    }
    assert output["vehicle_cost"] == {"daily_usd": "13.70", "annual_usd": "1972.80"}
    assert output["scenarios"]["p50"] == {
        "daily_toll_usd": "8.00",
        "annual_toll_usd": "1152.00",
        "daily_total_tolled_commute_cost_usd": "21.70",
        "average_monthly_tolled_commute_cost_usd": "260.40",
        "annual_total_tolled_commute_cost_usd": "3124.80",
        "estimated_annual_income_after_tax_and_tolled_commute_usd": "76875.20",
        "tolled_commute_share_of_after_tax_income_percent": "3.9",
        "additional_gross_income_to_offset_usd": "4687.20",
    }
    assert output["facilities"][0]["scenarios"]["p25"]["daily_toll_usd"] == "4.00"
    assert not (
        {"complete_days", "excluded_dates", "routes", "pricing_profile"} & output.keys()
    )


def test_no_complete_response_keeps_compact_coverage():
    response = ballpark._build_ballpark_response(
        ballpark._BallparkRequest.model_validate(_input()),
        datetime(2026, 8, 20, 12, tzinfo=_EASTERN),
        _summary(complete=0),
        Decimal("20.00"),
    )
    assert isinstance(response, ballpark._NoCompleteResponse)
    assert response.coverage.complete_pair_count == 0
    assert response.facilities == []
    assert response.vehicle_cost.annual_usd == Decimal("1972.80")


def test_canonical_offer_decision_math():
    request = ballpark._BallparkRequest.model_validate(
        {
            **_input(),
            "weekdays": ["monday", "tuesday", "wednesday", "thursday", "friday"],
            "planned_annual_commute_days": 240,
        }
    )
    summary = _summary().model_copy(
        update={
            "p25_daily_usd": Decimal("12.00"),
            "p50_daily_usd": Decimal("18.00"),
            "p90_daily_usd": Decimal("31.00"),
            "p25_annualized_usd": Decimal("2880.00"),
            "p50_annualized_usd": Decimal("4320.00"),
            "p90_annualized_usd": Decimal("7440.00"),
        }
    )

    output = ballpark._build_ballpark_response(
        request,
        datetime(2026, 8, 20, 12, tzinfo=_EASTERN),
        summary,
        Decimal("20.00"),
    ).model_dump(mode="json")

    assert output["income"]["estimated_tax_usd"] == "40000.00"
    assert output["income"]["estimated_after_tax_usd"] == "80000.00"
    assert output["vehicle_cost"] == {"daily_usd": "13.70", "annual_usd": "3288.00"}
    assert output["scenarios"]["p50"] == {
        "daily_toll_usd": "18.00",
        "annual_toll_usd": "4320.00",
        "daily_total_tolled_commute_cost_usd": "31.70",
        "average_monthly_tolled_commute_cost_usd": "634.00",
        "annual_total_tolled_commute_cost_usd": "7608.00",
        "estimated_annual_income_after_tax_and_tolled_commute_usd": "72392.00",
        "tolled_commute_share_of_after_tax_income_percent": "9.5",
        "additional_gross_income_to_offset_usd": "11412.00",
    }


def test_cost_can_exceed_estimated_after_tax_income():
    request = ballpark._BallparkRequest.model_validate(
        {**_input(), "gross_annual_income_usd": "1000.00"}
    )

    output = ballpark._build_ballpark_response(
        request,
        datetime(2026, 8, 20, 12, tzinfo=_EASTERN),
        _summary(),
        Decimal("20.00"),
    ).model_dump(mode="json")

    assert (
        output["scenarios"]["p90"][
            "estimated_annual_income_after_tax_and_tolled_commute_usd"
        ]
        == "-2602.13"
    )
    assert (
        output["scenarios"]["p90"]["tolled_commute_share_of_after_tax_income_percent"]
        == "490.3"
    )


def test_database_summary_rejects_cross_field_inconsistency():
    inconsistent = _summary().model_dump(mode="python")
    inconsistent["complete_pair_count"] = 84
    with pytest.raises(ValidationError, match="coverage is inconsistent"):
        ballpark._SummaryRow.model_validate(
            inconsistent,
            context={
                "dates": [date(2026, 8, 19)],
                "annual_days": 144,
                "facilities": ["i66"],
            },
        )


def test_streams_stages_and_returns_summary(monkeypatch):
    connection = type(
        "Connection",
        (),
        {
            "commit": lambda self: None,
            "rollback": lambda self: None,
            "close": lambda self: None,
        },
    )()
    monkeypatch.setattr(
        ballpark.route_validation, "connect_to_pricing_database", lambda: connection
    )
    monkeypatch.setattr(
        ballpark,
        "_start_transaction_and_fetch_routes_and_dates",
        lambda *_: (
            datetime(2026, 8, 20, 12, tzinfo=_EASTERN),
            (_route(), _route()),
            [date(2026, 8, 19)],
            Decimal("20.00"),
        ),
    )
    monkeypatch.setattr(ballpark, "_fetch_and_validate_summary", lambda *_: _summary())
    events, result = asyncio.run(_invoke(_input()))
    assert [(event["stage"], event["status"]) for event in events] == [
        ("route_validation", "running"),
        ("route_validation", "completed"),
        ("historical_pricing", "running"),
        ("historical_pricing", "completed"),
        ("ballpark_calculation", "running"),
        ("ballpark_calculation", "completed"),
    ]
    output = cast(Any, result["content"])[0]["json"]
    assert output["scenarios"]["p90"]["annual_toll_usd"] == "1296.00"


def test_route_unavailable_stops_before_summary(monkeypatch):
    connection = object()
    monkeypatch.setattr(
        ballpark.route_validation, "connect_to_pricing_database", lambda: connection
    )
    monkeypatch.setattr(
        ballpark,
        "_start_transaction_and_fetch_routes_and_dates",
        lambda *_: (
            datetime(2026, 8, 20, 12, tzinfo=_EASTERN),
            (_route(status="no_supported_route"), _route()),
            [date(2026, 8, 19)],
            None,
        ),
    )
    monkeypatch.setattr(
        ballpark,
        "_fetch_and_validate_summary",
        lambda *_: pytest.fail("summary should not run"),
    )
    monkeypatch.setattr(ballpark, "_close_connection", lambda *_args, **_kwargs: None)
    _, result = asyncio.run(_invoke(_input()))
    output = cast(Any, result["content"])[0]["json"]
    assert output["reason"] == "route_unavailable"


def test_missing_priced_leg_distance_stops_before_summary(monkeypatch):
    connection = object()
    monkeypatch.setattr(
        ballpark.route_validation, "connect_to_pricing_database", lambda: connection
    )
    monkeypatch.setattr(
        ballpark,
        "_start_transaction_and_fetch_routes_and_dates",
        lambda *_: (
            datetime(2026, 8, 20, 12, tzinfo=_EASTERN),
            (_route(), _route()),
            [date(2026, 8, 19)],
            None,
        ),
    )
    monkeypatch.setattr(
        ballpark,
        "_fetch_and_validate_summary",
        lambda *_: pytest.fail("summary should not run"),
    )
    monkeypatch.setattr(ballpark, "_close_connection", lambda *_args, **_kwargs: None)

    _, result = asyncio.run(_invoke(_input()))

    output = cast(Any, result["content"])[0]["json"]
    assert output == {
        "error": "ballpark_unavailable",
        "reason": "distance_unavailable",
    }


def test_northbound_i95_restart_stops_before_annual_summary(monkeypatch):
    connection = object()
    monkeypatch.setattr(
        ballpark.route_validation, "connect_to_pricing_database", lambda: connection
    )
    monkeypatch.setattr(
        ballpark,
        "_start_transaction_and_fetch_routes_and_dates",
        lambda *_: (
            datetime(2026, 8, 20, 12, tzinfo=_EASTERN),
            (_i95_northbound_restart_route(), _route()),
            [date(2026, 8, 19)],
            None,
        ),
    )
    monkeypatch.setattr(
        ballpark,
        "_fetch_and_validate_summary",
        lambda *_: pytest.fail("summary should not run"),
    )
    monkeypatch.setattr(ballpark, "_close_connection", lambda *_args, **_kwargs: None)

    _, result = asyncio.run(_invoke(_input()))

    output = cast(Any, result["content"])[0]["json"]
    assert output["reason"] == "route_unavailable"
    assert output["outbound"]["reason"]["code"] == (
        "i95_northbound_requires_i495_restart"
    )


def test_history_failure_is_safe(monkeypatch, caplog):
    secret = "private historical row"
    monkeypatch.setattr(
        ballpark.route_validation, "connect_to_pricing_database", lambda: object()
    )
    monkeypatch.setattr(
        ballpark,
        "_start_transaction_and_fetch_routes_and_dates",
        lambda *_: (
            datetime(2026, 8, 20, 12, tzinfo=_EASTERN),
            (_route(), _route()),
            [date(2026, 8, 19)],
            Decimal("20.00"),
        ),
    )
    monkeypatch.setattr(
        ballpark,
        "_fetch_and_validate_summary",
        lambda *_: (_ for _ in ()).throw(RuntimeError(secret)),
    )
    monkeypatch.setattr(ballpark, "_close_connection", lambda *_args, **_kwargs: None)
    with caplog.at_level("ERROR"):
        events, result = asyncio.run(_invoke(_input()))
    assert events[-1] == ballpark._progress_event("historical_pricing", "failed")
    assert result["status"] == "error"
    assert secret not in caplog.text


def test_cleanup_failure_is_safe(monkeypatch, caplog):
    secret = "private cleanup detail"
    monkeypatch.setattr(
        ballpark.route_validation, "connect_to_pricing_database", lambda: object()
    )
    monkeypatch.setattr(
        ballpark,
        "_start_transaction_and_fetch_routes_and_dates",
        lambda *_: (
            datetime(2026, 8, 20, 12, tzinfo=_EASTERN),
            (_route(status="no_supported_route"), _route()),
            [date(2026, 8, 19)],
            None,
        ),
    )
    monkeypatch.setattr(
        ballpark,
        "_close_connection",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError(secret)),
    )
    with caplog.at_level("ERROR"):
        asyncio.run(_invoke(_input()))
    assert secret not in caplog.text
