# pyright: basic

import asyncio
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any, cast
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError
from strands.tools.loader import load_tools_from_module_path
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
        "pricing_profile": {
            "vehicle_class": "two_axle_passenger",
            "payment_method": "e_zpass",
            "transponder_mode": "toll",
        },
    }


def _tool_use(data: Any) -> ToolUse:
    return cast(
        ToolUse,
        {
            "name": "get_annual_toll_ballpark",
            "toolUseId": "ballpark-123",
            "input": data,
        },
    )


def _route(
    direction: str, *, status: str = "valid", facility_legs: list[Any] | None = None
) -> ballpark._BallparkRoute:
    if direction == "outbound":
        origin, destination, departure = "airport_iad", "i66:6:entry:EB", "08:00:00"
        connection = "iad_to_i66"
    else:
        origin, destination, departure = "i66:6:exit:WB", "airport_iad", "17:30:00"
        connection = "i66_to_iad"
    if status != "valid":
        return ballpark._BallparkRoute.model_validate(
            {
                "status": status,
                "reason": {
                    "code": "no_supported_route",
                    "details": {
                        "origin_point_id": origin,
                        "destination_point_id": destination,
                    },
                },
                "point_ids": [],
                "connection_ids": [],
                "connection_types": [],
                "general_purpose_gaps": [],
                "facility_legs": [],
                "origin_point_id": origin,
                "destination_point_id": destination,
                "departure_time": departure,
            }
        )
    return ballpark._BallparkRoute.model_validate(
        {
            "status": "valid",
            "reason": None,
            "point_ids": [origin, destination],
            "connection_ids": [connection],
            "connection_types": ["airport_access"],
            "general_purpose_gaps": [],
            "facility_legs": facility_legs or [],
            "origin_point_id": origin,
            "destination_point_id": destination,
            "departure_time": departure,
        }
    )


def _routes() -> ballpark._Routes:
    return ballpark._Routes.model_validate(
        {"outbound": _route("outbound"), "return": _route("return")}
    )


def _greenway_route() -> ballpark._BallparkRoute:
    return ballpark._BallparkRoute.model_validate(
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
                    "pricing_key": {
                        "source_route_key": "EB:1:28",
                        "charge_index": 1,
                    },
                }
            ],
            "origin_point_id": "greenway:1:entry:EB",
            "destination_point_id": "greenway:28:exit:EB",
            "departure_time": "08:00:00",
        }
    )


async def _invoke(data: Any) -> tuple[list[dict[str, Any]], ToolResult]:
    events: list[dict[str, Any]] = []
    result: ToolResult | None = None
    async for event in ballpark.get_annual_toll_ballpark.stream(
        _tool_use(data), {"agent": object()}
    ):
        if event.get("type") == "tool_stream":
            data = event["tool_stream_event"]["data"]
            if isinstance(data, dict) and "stage" in data:
                events.append(cast(dict[str, Any], data))
        if "tool_result" in event:
            result = cast(ToolResult, event["tool_result"])
    assert result is not None
    return events, result


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update({"extra": True}),
        lambda value: value.update({"weekdays": ["monday", "monday"]}),
        lambda value: value.update({"weekdays": []}),
        lambda value: value.update({"planned_annual_commute_days": 160}),
        lambda value: value["outbound"].update({"departure_time": "8am"}),
        lambda value: value["return"].update({"offset": "-04:00"}),
    ],
)
def test_request_is_strict_and_bounded(mutation):
    data = _input()
    mutation(data)
    with pytest.raises(ValidationError):
        ballpark._BallparkRequest.model_validate(data)


def test_profile_and_overnight_fail_before_database(monkeypatch):
    monkeypatch.setattr(
        ballpark.route_validation,
        "_connect",
        lambda: pytest.fail("database should not be opened"),
    )
    unsupported = _input()
    unsupported["pricing_profile"]["vehicle_class"] = "truck"
    events, result = asyncio.run(_invoke(unsupported))
    assert events == []
    content = cast(Any, result["content"])
    assert content == [
        {
            "json": {
                "error": "ballpark_unavailable",
                "reason": "unsupported_pricing_profile",
            }
        }
    ]

    overnight = _input()
    overnight["return"]["departure_time"] = "07:30:00"
    events, result = asyncio.run(_invoke(overnight))
    assert events == []
    content = cast(Any, result["content"])
    assert content[0]["json"]["reason"] == "overnight_schedule"


def test_malformed_input_is_safe_and_never_connects(monkeypatch, caplog):
    monkeypatch.setattr(
        ballpark.route_validation,
        "_connect",
        lambda: pytest.fail("invalid input reached the database"),
    )
    malformed = _input()
    malformed["submitted_secret"] = "do-not-log-me"
    with caplog.at_level("ERROR"):
        events, result = asyncio.run(_invoke(malformed))
    assert events == []
    assert result["status"] == "error"
    assert "do-not-log-me" not in caplog.text


def test_wall_time_resolution_rejects_dst_gap_and_fold():
    assert ballpark._resolve_wall_time(date(2026, 3, 8), time(2, 30)) is None
    assert ballpark._resolve_wall_time(date(2025, 11, 2), time(1, 30)) is None
    ordinary = ballpark._resolve_wall_time(date(2026, 3, 9), time(8))
    assert ordinary == datetime(2026, 3, 9, 8, tzinfo=_EASTERN)


def test_sample_models_reject_bad_time_and_provenance():
    base = {
        "sample_date": date(2026, 8, 19),
        "sample_isodow": 3,
        "bin_start_at": datetime(2026, 8, 19, 8, tzinfo=_EASTERN),
        "bin_end_at": datetime(2026, 8, 19, 8, 10, tzinfo=_EASTERN),
        "interval_end_at": datetime(2026, 8, 19, 8, 5, tzinfo=_EASTERN),
        "observed_at": datetime(2026, 8, 19, 8, 6, tzinfo=_EASTERN),
        "od_pair_id": 1374,
        "price_usd": Decimal("6.20"),
        "uses_modeled": True,
        "pricing_method": "identity_proxy_v1",
        "proxy_od_pair_id": 1146,
    }
    assert ballpark._I95SampleRow.model_validate(base).uses_modeled
    with pytest.raises(ValidationError, match="provenance"):
        ballpark._I95SampleRow.model_validate(
            {**base, "uses_modeled": False, "proxy_od_pair_id": None}
        )
    with pytest.raises(ValidationError, match="time fields"):
        ballpark._I95SampleRow.model_validate(
            {**base, "sample_date": date(2026, 8, 18)}
        )

    row = ballpark._I95SampleRow.model_validate(base)
    with pytest.raises(ValueError, match="invalid rows"):
        ballpark._validate_sample_row_set(
            [row, row],
            [row.sample_date],
            time(8, 5),
            datetime(2026, 8, 20, tzinfo=_EASTERN),
            "I-95/I-495",
        )


def test_route_rejects_pricing_leg_from_an_unrelated_connection():
    route = _greenway_route().model_dump(mode="python")
    route["facility_legs"][0]["connection_ids"] = ["unrelated-connection"]
    with pytest.raises(ValidationError, match="connection is not in the route"):
        ballpark._BallparkRoute.model_validate(route)


def test_zero_toll_calendar_is_complete_and_dst_independent():
    request = ballpark._BallparkRequest.model_validate(
        {**_input(), "weekdays": ["sunday"], "planned_annual_commute_days": 53}
    )
    evaluated_at = datetime(2026, 3, 12, 12, tzinfo=_EASTERN)
    end_date = evaluated_at.date() - timedelta(days=1)
    start_date = end_date - timedelta(days=83)
    dates = [
        start_date + timedelta(days=offset)
        for offset in range(84)
        if (start_date + timedelta(days=offset)).weekday() == 6
    ]
    empty = {sample_date: {} for sample_date in dates}
    response = ballpark._calculate(
        request, evaluated_at, _routes(), dates, empty, empty
    )
    assert isinstance(response, ballpark._BallparkSuccess)
    assert len(response.complete_days) == 12
    assert date(2026, 3, 8) in {day.sample_date for day in response.complete_days}
    assert response.coverage.coverage_percent == "100.0"
    assert response.scenarios.middle.daily_round_trip_usd == Decimal("0.00")
    assert response.scenarios.middle.annualized_usd == Decimal("0.00")


def test_fixed_rates_use_each_sample_date_not_the_execution_date():
    evaluated_at = datetime(2026, 8, 23, 12, tzinfo=_EASTERN)
    monday, saturday = date(2026, 8, 17), date(2026, 8, 22)
    prices = ballpark._price_direction(
        object(), _greenway_route(), time(8), [monday, saturday], evaluated_at
    )
    monday_component = prices[monday]["step-1"]
    saturday_component = prices[saturday]["step-1"]
    assert monday_component.facility == "greenway"
    assert saturday_component.facility == "greenway"
    assert monday_component.price_usd == Decimal("5.80")
    assert saturday_component.price_usd == Decimal("5.25")
    assert monday_component.component_evaluated_at == evaluated_at
    assert saturday_component.component_evaluated_at == evaluated_at


def test_mixed_sample_calculates_nearest_rank_coverage_and_exclusions():
    request = ballpark._BallparkRequest.model_validate(
        {**_input(), "weekdays": ["monday"], "planned_annual_commute_days": 53}
    )
    routes = _routes()
    evaluated_at = datetime(2026, 8, 20, 16, 15, tzinfo=_EASTERN)
    dates = [date(2026, 6, 1) + timedelta(days=7 * offset) for offset in range(12)]
    outbound: dict[date, dict[str, Any]] = {sample_date: {} for sample_date in dates}
    return_: dict[date, dict[str, Any]] = {sample_date: {} for sample_date in dates}
    route_data = routes.model_dump(by_alias=True)
    for name, origin, destination in (
        ("outbound", "i66:1:entry:EB", "i66:4:exit:EB"),
        ("return", "i66:4:entry:WB", "i66:1:exit:WB"),
    ):
        route_data[name].update(
            {
                "origin_point_id": origin,
                "destination_point_id": destination,
                "point_ids": [origin, destination],
                "connection_ids": [
                    f"source:i66:{'EB:1:4' if name == 'outbound' else 'WB:4:1'}"
                ],
                "connection_types": ["within_facility"],
                "facility_legs": [
                    {
                        "route_step_id": "step-1",
                        "facility": "i66",
                        "point_ids": [origin, destination],
                        "connection_ids": [
                            f"source:i66:{'EB:1:4' if name == 'outbound' else 'WB:4:1'}"
                        ],
                        "pricing_key": {
                            "source_route_key": "EB:1:4"
                            if name == "outbound"
                            else "WB:4:1",
                            "start_zone_id": 3100,
                            "end_zone_id": 3100,
                        },
                    }
                ],
            }
        )
    routes = ballpark._Routes.model_validate(route_data)
    for index, sample_date in enumerate(dates[:-1], start=1):
        for target in (outbound, return_):
            target[sample_date]["step-1"] = ballpark._I66Component(
                route_step_id="step-1",
                facility="i66",
                price_usd=Decimal(index),
                source_kind="observed",
                pricing_method="source_observation",
                bin_start_at=datetime.combine(sample_date, time(8), _EASTERN),
                bin_end_at=datetime.combine(sample_date, time(8, 6), _EASTERN),
                interval_end_at=datetime.combine(sample_date, time(8, 5), _EASTERN),
                observed_at=datetime.combine(sample_date, time(8, 5), _EASTERN),
                start_zone_id=3100,
                end_zone_id=3100,
            )
    response = ballpark._calculate(
        request, evaluated_at, routes, dates, outbound, return_
    )
    assert isinstance(response, ballpark._BallparkSuccess)
    assert response.coverage.complete_pair_count == 11
    assert response.coverage.coverage_percent == "91.7"
    assert response.scenarios.low.rank == 3
    assert response.scenarios.middle.rank == 6
    assert response.scenarios.high.rank == 10
    assert response.scenarios.middle.daily_round_trip_usd == Decimal("12.00")
    assert response.scenarios.middle.annualized_usd == Decimal("636.00")
    assert response.excluded_dates[0].missing_outbound_route_step_ids == ["step-1"]
    assert response.sample_status == "partial"


def test_no_complete_days_preserves_coverage_and_evidence():
    request = ballpark._BallparkRequest.model_validate(
        {**_input(), "weekdays": ["monday"], "planned_annual_commute_days": 53}
    )
    dates = [date(2026, 6, 1) + timedelta(days=7 * offset) for offset in range(12)]
    route_data = _routes().model_dump(by_alias=True)
    for name in ("outbound", "return"):
        route_data[name]["connection_types"] = ["within_facility"]
        route_data[name]["facility_legs"] = [
            {
                "route_step_id": "step-1",
                "facility": "i66",
                "point_ids": route_data[name]["point_ids"],
                "connection_ids": route_data[name]["connection_ids"],
                "pricing_key": {
                    "source_route_key": "EB:1:4",
                    "start_zone_id": 3100,
                    "end_zone_id": 3100,
                },
            }
        ]
    routes = ballpark._Routes.model_validate(route_data)
    empty = {sample_date: {} for sample_date in dates}
    response = ballpark._calculate(
        request,
        datetime(2026, 8, 20, 16, 15, tzinfo=_EASTERN),
        routes,
        dates,
        empty,
        empty,
    )
    assert isinstance(response, ballpark._NoCompleteResponse)
    assert response.available_date_range is None
    assert response.missing_weekdays == ["monday"]
    assert len(response.excluded_dates) == 12
    assert response.coverage.coverage_percent == "0.0"


def test_streams_all_stages_and_returns_zero_toll(monkeypatch):
    request = ballpark._BallparkRequest.model_validate(_input())
    evaluated_at = datetime(2026, 8, 20, 16, 15, tzinfo=_EASTERN)
    end_date = evaluated_at.date() - timedelta(days=1)
    dates = [
        end_date - timedelta(days=offset)
        for offset in reversed(range(84))
        if (end_date - timedelta(days=offset)).weekday() in {0, 2, 4}
    ]
    fake_connection = object()
    monkeypatch.setattr(ballpark.route_validation, "_connect", lambda: fake_connection)
    monkeypatch.setattr(
        ballpark,
        "_begin_and_validate_routes",
        lambda *_args: (evaluated_at, _routes(), dates),
    )
    monkeypatch.setattr(
        ballpark,
        "_fetch_history",
        lambda *_args: (
            {sample_date: {} for sample_date in dates},
            {sample_date: {} for sample_date in dates},
        ),
    )
    monkeypatch.setattr(ballpark, "_close", lambda *_args, **_kwargs: None)
    events, result = asyncio.run(_invoke(request.model_dump(by_alias=True)))
    assert [(event["stage"], event["status"]) for event in events] == [
        ("route_validation", "running"),
        ("route_validation", "completed"),
        ("historical_pricing", "running"),
        ("historical_pricing", "completed"),
        ("ballpark_calculation", "running"),
        ("ballpark_calculation", "completed"),
    ]
    content = cast(Any, result["content"])
    payload = content[0]["json"]
    assert payload["method"] == "recent_complete_same_date_round_trips"
    assert payload["scenarios"]["middle"]["annualized_usd"] == "0.00"


def test_closing_stream_after_validation_rolls_back_and_closes(monkeypatch):
    connection = object()
    closed: list[tuple[object, bool]] = []
    monkeypatch.setattr(ballpark.route_validation, "_connect", lambda: connection)
    monkeypatch.setattr(
        ballpark,
        "_begin_and_validate_routes",
        lambda *_args: (
            datetime(2026, 8, 20, tzinfo=_EASTERN),
            _routes(),
            [date(2026, 8, 19)],
        ),
    )
    monkeypatch.setattr(
        ballpark,
        "_close",
        lambda value, *, rollback: closed.append((value, rollback)),
    )

    async def close_after_validation() -> None:
        stream = ballpark.get_annual_toll_ballpark.stream(
            _tool_use(_input()), {"agent": object()}
        )
        async for event in stream:
            if event.get("type") != "tool_stream":
                continue
            progress = event["tool_stream_event"]["data"]
            if (
                isinstance(progress, dict)
                and progress.get("stage") == ("route_validation")
                and progress.get("status") == "completed"
            ):
                await stream.aclose()
                return
        pytest.fail("route validation never completed")

    asyncio.run(close_after_validation())
    assert closed == [(connection, True)]


def test_nonvalid_route_stops_before_historical_pricing(monkeypatch):
    routes = ballpark._Routes.model_validate(
        {
            "outbound": _route("outbound", status="no_supported_route"),
            "return": _route("return"),
        }
    )
    monkeypatch.setattr(ballpark.route_validation, "_connect", lambda: object())
    monkeypatch.setattr(
        ballpark,
        "_begin_and_validate_routes",
        lambda *_args: (datetime(2026, 8, 20, tzinfo=_EASTERN), routes, []),
    )
    monkeypatch.setattr(
        ballpark,
        "_fetch_history",
        lambda *_args: pytest.fail("invalid route reached historical pricing"),
    )
    monkeypatch.setattr(ballpark, "_close", lambda *_args, **_kwargs: None)
    events, result = asyncio.run(_invoke(_input()))
    assert [(event["stage"], event["status"]) for event in events] == [
        ("route_validation", "running"),
        ("route_validation", "completed"),
    ]
    content = cast(Any, result["content"])
    assert content[0]["json"]["reason"] == "route_unavailable"


def test_nonvalid_route_cleanup_failure_returns_operation_error(monkeypatch):
    routes = ballpark._Routes.model_validate(
        {
            "outbound": _route("outbound", status="no_supported_route"),
            "return": _route("return"),
        }
    )
    monkeypatch.setattr(ballpark.route_validation, "_connect", lambda: object())
    monkeypatch.setattr(
        ballpark,
        "_begin_and_validate_routes",
        lambda *_args: (datetime(2026, 8, 20, tzinfo=_EASTERN), routes, []),
    )
    monkeypatch.setattr(
        ballpark,
        "_close",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("close failed")),
    )
    _, result = asyncio.run(_invoke(_input()))
    assert result["status"] == "error"


def test_history_failure_is_safe(monkeypatch, caplog):
    secret = "private historical row"
    monkeypatch.setattr(ballpark.route_validation, "_connect", lambda: object())
    monkeypatch.setattr(
        ballpark,
        "_begin_and_validate_routes",
        lambda *_args: (
            datetime(2026, 8, 20, tzinfo=_EASTERN),
            _routes(),
            [date(2026, 8, 19)],
        ),
    )

    def fail(*_args):
        raise RuntimeError(secret)

    monkeypatch.setattr(ballpark, "_fetch_history", fail)
    monkeypatch.setattr(ballpark, "_close", lambda *_args, **_kwargs: None)
    with caplog.at_level("ERROR"):
        events, result = asyncio.run(_invoke(_input()))
    assert events[-1]["stage"] == "historical_pricing"
    assert events[-1]["status"] == "failed"
    assert result["status"] == "error"
    assert secret not in caplog.text


def test_route_failure_is_safe_and_loads_only_ballpark_tool(monkeypatch, caplog):
    failure = "secret database row"

    def fail(*_args):
        raise RuntimeError(failure)

    monkeypatch.setattr(ballpark.route_validation, "_connect", lambda: object())
    monkeypatch.setattr(ballpark, "_begin_and_validate_routes", fail)
    monkeypatch.setattr(ballpark, "_close", lambda *_args, **_kwargs: None)
    with caplog.at_level("ERROR"):
        events, result = asyncio.run(_invoke(_input()))
    assert events[-1]["status"] == "failed"
    assert result == {
        "toolUseId": "ballpark-123",
        "status": "error",
        "content": [
            {
                "text": "Unable to calculate the annual toll ballpark. Reference: ballpark-123."
            }
        ],
    }
    assert "secret database row" not in caplog.text
    assert load_tools_from_module_path("agent_tools.get_annual_toll_ballpark") == [
        ballpark.get_annual_toll_ballpark
    ]
