import asyncio
import json
import logging
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from zoneinfo import ZoneInfo

import pytest
from pydantic import BaseModel
from strands.tools.loader import load_tools_from_module_path
from strands.tools.registry import ToolRegistry
from strands.types.tools import ToolResult, ToolUse

from agent_tools import current_price_domain as pricing_tool
from agent_tools import get_current_toll_price as pricing_transport
from tests.current_price_support import (
    dtr_handoff_leg,
    dtr_leg,
    greenway_leg,
    i66_leg,
    i66_rows,
    i95_leg,
    i95_rows,
)

type FixtureValue = JSON | datetime | Decimal

type JSON = str | int | float | bool | list[JSON] | dict[str, JSON] | None


_EASTERN = ZoneInfo("America/New_York")


def _input() -> dict[str, Any]:
    return {
        "origin_point_id": "greenway:1:entry:EB",
        "destination_point_id": "greenway:28:exit:EB",
        "pricing_profile": {
            "vehicle_class": "two_axle_passenger",
            "payment_method": "e_zpass",
            "transponder_mode": "toll",
        },
    }


def _tool_use(input_data: object) -> ToolUse:
    return cast(
        ToolUse,
        {
            "name": "get_current_toll_price",
            "toolUseId": "tool-123",
            "input": input_data,
        },
    )


def _route_row() -> dict[str, Any]:
    return {
        "status": "valid",
        "reason": None,
        "point_ids": ["greenway:1:entry:EB", "greenway:28:exit:EB"],
        "connection_ids": ["source:greenway:EB:1:28"],
        "connection_types": ["within_facility"],
        "general_purpose_gaps": [],
        "i95_evidence": None,
    }


def _nonvalid_route_rows() -> list[dict[str, Any]]:
    origin = "greenway:1:entry:EB"
    destination = "greenway:28:exit:EB"
    empty_path: dict[str, JSON] = {
        "point_ids": [],
        "connection_ids": [],
        "connection_types": [],
        "general_purpose_gaps": [],
        "i95_evidence": None,
    }
    return [
        {
            **empty_path,
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
        },
        {
            **empty_path,
            "status": "invalid_origin",
            "reason": {
                "code": "origin_not_found",
                "details": {"point_id": origin},
            },
        },
        {
            **empty_path,
            "status": "invalid_destination",
            "reason": {
                "code": "destination_not_found",
                "details": {"point_id": destination},
            },
        },
        {
            **empty_path,
            "status": "no_supported_route",
            "reason": {
                "code": "no_supported_route",
                "details": {
                    "origin_point_id": origin,
                    "destination_point_id": destination,
                },
            },
        },
        {
            **empty_path,
            "status": "traversal_limit_exceeded",
            "reason": {
                "code": "traversal_limit_exceeded",
                "details": {
                    "origin_point_id": origin,
                    "destination_point_id": destination,
                    "maximum_connections": 12,
                },
            },
        },
        {
            "status": "currently_unavailable",
            "reason": {
                "code": "i95_fully_closed",
                "details": {
                    "required_i95_directions": ["NB"],
                    "availability": "closed",
                },
            },
            "point_ids": ["i95:202NO", "i95:201ND"],
            "connection_ids": ["source:i95_shared:Northbound:202NO:201ND"],
            "connection_types": ["within_facility"],
            "general_purpose_gaps": [],
            "i95_evidence": _i95_evidence("closed"),
        },
        {
            "status": "currently_unavailable",
            "reason": {
                "code": "i95_opposite_direction_open",
                "details": {
                    "required_i95_directions": ["NB"],
                    "availability": "southbound",
                },
            },
            "point_ids": ["i95:202NO", "i95:201ND"],
            "connection_ids": ["source:i95_shared:Northbound:202NO:201ND"],
            "connection_types": ["within_facility"],
            "general_purpose_gaps": [],
            "i95_evidence": _i95_evidence("southbound"),
        },
        {
            "status": "unknown_availability",
            "reason": {
                "code": "i95_missing_source",
                "details": {
                    "required_i95_directions": ["NB"],
                    "availability": "unknown",
                },
            },
            "point_ids": ["i95:202NO", "i95:201ND"],
            "connection_ids": ["source:i95_shared:Northbound:202NO:201ND"],
            "connection_types": ["within_facility"],
            "general_purpose_gaps": [],
            "i95_evidence": {"availability": "unknown", "reason": "missing_source"},
        },
    ]


def _i95_evidence(availability: str) -> dict[str, str]:
    return {
        "availability": availability,
        "northbound_corridor_name": "I-95 NB",
        "northbound_link_status": (
            "NORTHBOUND_OPEN" if availability == "northbound" else "CLOSED"
        ),
        "northbound_interval_end_at": "2026-08-17T12:00:00+00:00",
        "northbound_calculated_at": "2026-08-17T11:59:00+00:00",
        "southbound_corridor_name": "I-95 SB",
        "southbound_link_status": "CLOSED",
        "southbound_interval_end_at": "2026-08-17T12:00:00+00:00",
        "southbound_calculated_at": "2026-08-17T11:59:00+00:00",
    }


def _pricing_route(
    row: dict[str, Any], legs: list[dict[str, Any]]
) -> pricing_tool.route_validation._PricingRouteResponse:
    return pricing_tool.route_validation._PricingRouteResponse.model_validate(
        {**row, "facility_legs": legs}
    )


def _southbound_westpark_pricing_route(
    origin_point_id: str,
) -> pricing_tool.route_validation._PricingRouteResponse:
    connection_id = "source:i95_shared:Southbound:2233SO:1859ND"
    airport = origin_point_id == "airport_dca"
    row = {
        **_route_row(),
        "point_ids": (
            ["airport_dca", "i95:2233SO", "i495:1859ND"]
            if airport
            else ["i95:2233SO", "i495:1859ND"]
        ),
        "connection_ids": (
            ["dca_to_i95_south", connection_id] if airport else [connection_id]
        ),
        "connection_types": (
            ["airport_access", "general_purpose_gap"]
            if airport
            else ["general_purpose_gap"]
        ),
        "general_purpose_gaps": [
            {
                "connection_id": connection_id,
                "boundary_point_id": "i495:192SD",
                "role": "prefix",
                "i95_direction": "SB",
                "fallback_required": False,
            }
        ],
        "i95_evidence": _i95_evidence("southbound"),
    }
    legs = [
        i95_leg(
            route_step_id="step-1",
            direction="Southbound",
            entry="2233SO",
            exit_="1859ND",
            od_pair_id=1204,
            point_ids=["i95:2233SO", "i495:192SD"],
        ).model_dump(mode="json"),
        i95_leg(
            route_step_id="step-2",
            direction="Southbound",
            entry="2233SO",
            exit_="1859ND",
            od_pair_id=1005,
            point_ids=["i495:192SD", "i495:1859ND"],
        ).model_dump(mode="json"),
    ]
    return _pricing_route(row, legs)


def _run_tool(input_data: object = None) -> list[dict[str, Any]]:
    async def collect() -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        async for event in pricing_transport.get_current_toll_price.stream(
            _tool_use(_input() if input_data is None else input_data),
            {"agent": object()},
        ):
            events.append(dict(event))
        return events

    return asyncio.run(collect())


def _progress_events(events: list[dict[str, Any]]) -> list[dict[str, str]]:
    progress: list[dict[str, str]] = []
    for event in events:
        if event.get("type") != "tool_stream":
            continue
        data = event["tool_stream_event"]["data"]
        if isinstance(data, dict) and "stage" in data:
            validated = pricing_tool._ProgressEvent.model_validate(data)
            progress.append(cast(dict[str, str], validated.model_dump(mode="json")))
    return progress


def _result(events: list[dict[str, Any]]) -> ToolResult:
    result = cast(ToolResult, events[-1]["tool_result"])
    if result["status"] == "error":
        pricing_tool._OperationError.model_validate(result)
    else:
        content = cast(Any, result["content"])
        pricing_tool._OUTPUT_ADAPTER.validate_json(json.dumps(content[0]["json"]))
    return result


def _install_route(monkeypatch: pytest.MonkeyPatch, legs: list[dict[str, Any]]) -> None:
    row = _route_row()
    response = _pricing_route(row, legs)

    def _strict_callback_1(*_args: object, **_kwargs: object) -> object:
        return response

    monkeypatch.setattr(
        pricing_tool.route_validation,
        "fetch_validated_pricing_route",
        _strict_callback_1,
    )


def _domain_result(
    request: dict[str, Any],
    route: pricing_tool.route_validation._PricingRouteResponse,
    evaluated_at: datetime | None,
    pricing_inputs: dict[str, object],
) -> dict[str, Any]:
    return pricing_tool.build_current_price_result(
        pricing_tool._PricingRequest.model_validate(request),
        route,
        evaluated_at,
        pricing_inputs,
    )


def test_strands_loads_exact_strict_input_schema() -> None:
    assert not hasattr(pricing_tool.route_validation, "TOOL_SPEC")
    loaded = load_tools_from_module_path("agent_tools.get_current_toll_price")
    assert loaded == [pricing_transport.get_current_toll_price]
    registry = ToolRegistry()
    registry.register_tool(loaded[0])
    registered_spec = registry.get_all_tools_config()["get_current_toll_price"]
    assert registered_spec == pricing_tool.TOOL_SPEC
    schema = registered_spec["inputSchema"]["json"]
    assert schema["required"] == [
        "origin_point_id",
        "destination_point_id",
        "pricing_profile",
    ]
    assert set(schema["properties"]) == {
        "origin_point_id",
        "destination_point_id",
        "pricing_profile",
    }
    assert schema["additionalProperties"] is False
    profile_schema = schema["$defs"]["_PricingProfile"]
    assert set(profile_schema["properties"]) == {
        "vehicle_class",
        "payment_method",
        "transponder_mode",
    }
    assert profile_schema["additionalProperties"] is False
    assert registered_spec["outputSchema"]["json"] == (
        pricing_tool._OUTPUT_ADAPTER.json_schema(mode="serialization")
    )


def test_tool_matches_domain_builder_for_every_canonical_i95_i495_source_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = json.loads(
        (Path(__file__).parents[1] / "oracle" / "sources" / "i95.json").read_text()
    )
    evaluated_at = datetime(2026, 8, 13, 8, 32, 6, tzinfo=_EASTERN)
    monkeypatch.setattr(pricing_tool, "_current_eastern_time", lambda: evaluated_at)

    checked = 0
    for pair in source["pairs"]:
        entry = pair["entry"]
        exit_ = pair["exit"]
        direction = pair["direction"]
        origin = (
            "i495" if source["nodes"][entry]["path"].startswith("495") else "i95"
        ) + f":{entry}"
        destination = (
            "i495" if source["nodes"][exit_]["path"].startswith("495") else "i95"
        ) + f":{exit_}"
        od_pair_ids = pair["ods"]
        boundary = "i495:192NO" if direction == "Northbound" else "i495:192SD"
        component_points = (
            [[origin, boundary], [boundary, destination]]
            if len(od_pair_ids) == 2
            else [[origin, destination]]
        )
        legs = [
            i95_leg(
                route_step_id=f"step-{index}",
                direction=direction,
                entry=entry,
                exit_=exit_,
                od_pair_id=od_pair_id,
                point_ids=point_ids,
            )
            for index, (od_pair_id, point_ids) in enumerate(
                zip(od_pair_ids, component_points, strict=True), start=1
            )
        ]
        route = _pricing_route(
            {
                **_route_row(),
                "point_ids": [origin, destination],
                "connection_ids": [f"source:i95_shared:{direction}:{entry}:{exit_}"],
                "i95_evidence": (
                    None
                    if origin.startswith("i495:") and destination.startswith("i495:")
                    else _i95_evidence(direction.lower())
                ),
            },
            [leg.model_dump(mode="json") for leg in legs],
        )
        request = {
            **_input(),
            "origin_point_id": origin,
            "destination_point_id": destination,
        }

        rows_by_od_pair = {
            od_pair_id: i95_rows(od_pair_id=od_pair_id) for od_pair_id in od_pair_ids
        }
        payload = _domain_result(
            request,
            route,
            evaluated_at,
            {
                f"step-{index}": rows_by_od_pair[od_pair_id]
                for index, od_pair_id in enumerate(od_pair_ids, start=1)
            },
        )

        def _strict_callback_37(
            *_args: object, response: object = route, **_kwargs: object
        ) -> object:
            return response

        monkeypatch.setattr(
            pricing_tool.route_validation,
            "fetch_validated_pricing_route",
            _strict_callback_37,
        )
        requested_od_pairs: list[int] = []

        def fetch_rows(
            requested_od_pair_id: int,
            rows: dict[int, list[pricing_tool._I95ComparisonRow]] = rows_by_od_pair,
            requested: list[int] = requested_od_pairs,
        ) -> list[pricing_tool._I95ComparisonRow]:
            requested.append(requested_od_pair_id)
            return rows[requested_od_pair_id]

        monkeypatch.setattr(pricing_tool, "_fetch_i95_i495_comparisons", fetch_rows)
        tool_payload = cast(Any, _result(_run_tool(request)))["content"][0]["json"]

        assert tool_payload == payload
        assert requested_od_pairs == od_pair_ids
        assert payload["origin_point_id"] == origin
        assert payload["destination_point_id"] == destination
        assert payload["evaluated_at"] == "2026-08-13T08:32:06-04:00"
        assert payload["source_kind"] == "observed"
        assert payload["total_usd"] == f"{Decimal('8.20') * len(od_pair_ids):.2f}"
        assert [component["route_step_id"] for component in payload["components"]] == [
            f"step-{index}" for index in range(1, len(od_pair_ids) + 1)
        ]
        assert [component["od_pair_id"] for component in payload["components"]] == (
            od_pair_ids
        )
        checked += 1

    assert checked == 685
    assert sum(len(pair["ods"]) for pair in source["pairs"]) == 980


@pytest.mark.parametrize(
    ("unavailable_reason", "source_kind", "expected_reason", "expected_source"),
    [
        ("missing_observation", "observed", "missing_observation", None),
        ("stale_observation", "observed", "stale_observation", None),
        ("facility_unavailable", "observed", "facility_unavailable", None),
        (
            "exceptional_i95_schedule",
            "observed",
            "exceptional_i95_schedule",
            None,
        ),
        (None, "observed", None, "observed"),
        (None, "modeled", None, "modeled"),
    ],
)
def test_domain_builder_characterizes_i95_i495_price_states(
    unavailable_reason: str | None,
    source_kind: str,
    expected_reason: str | None,
    expected_source: str | None,
) -> None:
    leg = i95_leg(
        entry="191NO" if source_kind == "modeled" else "203NO",
        exit_="201ND" if source_kind == "modeled" else "223ND",
        od_pair_id=1374 if source_kind == "modeled" else 1261,
        point_ids=(
            ["i495:192NO", "i95:201ND"]
            if source_kind == "modeled"
            else ["i95:203NO", "i95:223ND"]
        ),
    )
    route = _pricing_route(
        {
            **_route_row(),
            "point_ids": leg.point_ids,
            "connection_ids": leg.connection_ids,
            "i95_evidence": _i95_evidence("northbound"),
        },
        [leg.model_dump(mode="json")],
    )
    rows = i95_rows(
        unavailable_reason=unavailable_reason,
        source_kind=source_kind,
        od_pair_id=leg.pricing_key.od_pair_id,
    )

    payload = _domain_result(
        {
            **_input(),
            "origin_point_id": leg.point_ids[0],
            "destination_point_id": leg.point_ids[-1],
        },
        route,
        rows[0].evaluated_at,
        {leg.route_step_id: rows},
    )

    if expected_reason is not None:
        assert payload["reason"] == "incomplete_route_price"
        assert payload["unavailable_components"][0]["reason"] == expected_reason
        assert "total_usd" not in payload
    else:
        assert payload["source_kind"] == expected_source
        assert payload["components"][0]["source_kind"] == expected_source
        assert payload["total_usd"] == "8.20"


def _callback_1(data: dict[str, FixtureValue]) -> object:
    return data.update({"requested_at": "TOP-SECRET"})


def _callback_2(data: dict[str, FixtureValue]) -> object:
    return cast(dict[str, JSON], data["pricing_profile"]).update({"vehicle_class": 2})


def _callback_3(data: dict[str, FixtureValue]) -> object:
    return cast(dict[str, JSON], data["pricing_profile"]).update({"occupancy": 3})


def _strict_callback_3(data: dict[str, FixtureValue]) -> object:
    return data.pop("pricing_profile")


@pytest.mark.parametrize(
    "mutation",
    [
        _strict_callback_3,
        _callback_1,
        _callback_2,
        _callback_3,
    ],
)
def test_malformed_input_fails_safely_without_route_validation(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    mutation: Callable[[dict[str, FixtureValue]], object],
) -> None:
    input_data = _input()
    mutation(input_data)

    def _strict_callback_2(*_args: object, **_kwargs: object) -> object:
        return pytest.fail("invalid input reached the database")

    monkeypatch.setattr(
        pricing_tool.route_validation,
        "fetch_validated_pricing_route",
        _strict_callback_2,
    )

    with caplog.at_level(logging.ERROR):
        events = _run_tool(input_data)

    assert _progress_events(events) == []
    assert _result(events) == {
        "toolUseId": "tool-123",
        "status": "error",
        "content": [
            {"text": "Unable to get the current toll price. Reference: tool-123."}
        ],
    }
    assert caplog.records[0].__dict__["failureStage"] == "input_validation"
    assert "TOP-SECRET" not in caplog.text


def test_unsupported_profile_short_circuits_without_progress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_data = _input()
    input_data["pricing_profile"]["transponder_mode"] = "hov"

    def _strict_callback_4(*_args: object, **_kwargs: object) -> object:
        return pytest.fail("unsupported profile reached RDS")

    monkeypatch.setattr(
        pricing_tool.route_validation,
        "fetch_validated_pricing_route",
        _strict_callback_4,
    )

    events = _run_tool(input_data)

    assert _progress_events(events) == []
    assert _result(events)["content"] == [
        {
            "json": {
                "origin_point_id": "greenway:1:entry:EB",
                "destination_point_id": "greenway:28:exit:EB",
                "error": "pricing_unavailable",
                "reason": "unsupported_pricing_profile",
            }
        }
    ]


@pytest.mark.parametrize("row", _nonvalid_route_rows(), ids=lambda row: row["status"])
def test_nonvalid_routes_complete_validation_without_pricing(
    monkeypatch: pytest.MonkeyPatch, row: dict[str, JSON]
) -> None:
    response = _pricing_route(row, [])

    def _strict_callback_5(*_args: object, **_kwargs: object) -> object:
        return response

    monkeypatch.setattr(
        pricing_tool.route_validation,
        "fetch_validated_pricing_route",
        _strict_callback_5,
    )

    input_data = _input()
    if row["point_ids"]:
        input_data.update(
            {
                "origin_point_id": cast(list[str], row["point_ids"])[0],
                "destination_point_id": cast(list[str], row["point_ids"])[-1],
            }
        )

    expected = _domain_result(input_data, response, None, {})
    events = _run_tool(input_data)

    assert [
        (event["stage"], event["status"]) for event in _progress_events(events)
    ] == [
        ("route_validation", "running"),
        ("route_validation", "completed"),
    ]
    payload = cast(Any, _result(events))["content"][0]["json"]
    assert payload == expected
    assert payload["status"] == row["status"]
    assert ("facility_legs" in payload) is bool(row["point_ids"])
    assert "total_usd" not in payload
    assert "components" not in payload


def test_route_failure_streams_failed_and_returns_only_safe_error(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    secret = "private-pricing-route"

    def fail(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError(secret)

    monkeypatch.setattr(
        pricing_tool.route_validation,
        "fetch_validated_pricing_route",
        fail,
    )

    with caplog.at_level(logging.ERROR):
        events = _run_tool()

    assert [
        (event["stage"], event["status"]) for event in _progress_events(events)
    ] == [
        ("route_validation", "running"),
        ("route_validation", "failed"),
    ]
    result = _result(events)
    assert result["status"] == "error"
    assert result["content"] == [
        {"text": "Unable to get the current toll price. Reference: tool-123."}
    ]
    assert secret not in str(_progress_events(events))
    assert secret not in caplog.text


def test_greenway_only_route_streams_progress_and_returns_total(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    leg = greenway_leg().model_dump(mode="json")
    _install_route(monkeypatch, [leg])
    evaluated_at = datetime(2026, 8, 17, 6, 30, tzinfo=_EASTERN)
    monkeypatch.setattr(pricing_tool, "_current_eastern_time", lambda: evaluated_at)

    events = _run_tool()

    assert [
        (event["stage"], event["status"]) for event in _progress_events(events)
    ] == [
        ("route_validation", "running"),
        ("route_validation", "completed"),
        ("greenway_pricing", "running"),
        ("greenway_pricing", "completed"),
    ]
    result = _result(events)
    assert result["status"] == "success"
    payload = cast(Any, result)["content"][0]["json"]
    assert payload == {
        "origin_point_id": "greenway:1:entry:EB",
        "destination_point_id": "greenway:28:exit:EB",
        "method": "latest_complete_current_facility_prices",
        "evaluated_at": "2026-08-17T06:30:00-04:00",
        "maximum_observation_age_minutes": 30,
        "pricing_profile": _input()["pricing_profile"],
        "source_kind": "schedule_derived",
        "components": [
            {
                "route_step_id": "step-1",
                "price_usd": "5.80",
                "source_kind": "schedule_derived",
                "pricing_method": "published_schedule",
                "facility": "greenway",
                "component_evaluated_at": "2026-08-17T06:30:00-04:00",
                "rate_period": "peak",
                "published_schedule": {
                    "schedule_id": "dulles_greenway_toll_calculator_2026-08-04",
                    "rate_name": "mainline_plaza",
                    "source_url": "https://www.dullesgreenway.com/toll-calculator/",
                    "retrieved_at": "2026-08-04",
                },
            }
        ],
        "total_usd": "5.80",
    }


@pytest.mark.parametrize(
    ("input_data", "row", "legs", "stages", "facilities", "total"),
    [
        (
            {
                **_input(),
                "destination_point_id": "dtr:10:exit:EB",
            },
            {
                **_route_row(),
                "point_ids": [
                    "greenway:1:entry:EB",
                    "greenway:28:exit:EB",
                    "dtr:28:entry:EB",
                    "dtr:10:exit:EB",
                ],
                "connection_ids": [
                    "source:greenway:EB:1:28",
                    "greenway_to_dtr",
                    "source:dtr:EB:28:10",
                ],
                "connection_types": [
                    "within_facility",
                    "toll_handoff",
                    "within_facility",
                ],
            },
            [
                greenway_leg().model_dump(mode="json"),
                dtr_handoff_leg("greenway_to_dtr", "step-2").model_dump(mode="json"),
                dtr_leg(route_step_id="step-3", entry="28", exit_="10").model_dump(
                    mode="json"
                ),
            ],
            ["greenway_pricing", "dtr_pricing"],
            ["greenway", "dtr", "dtr"],
            "9.25",
        ),
        (
            {
                **_input(),
                "origin_point_id": "dtr:66:entry:WB",
                "destination_point_id": "greenway:1:exit:WB",
            },
            {
                **_route_row(),
                "point_ids": [
                    "dtr:66:entry:WB",
                    "dtr:28:exit:WB",
                    "greenway:28:entry:WB",
                    "greenway:1:exit:WB",
                ],
                "connection_ids": [
                    "source:dtr:WB:66:28",
                    "dtr_to_greenway",
                    "source:greenway:WB:28:1",
                ],
                "connection_types": [
                    "within_facility",
                    "toll_handoff",
                    "within_facility",
                ],
            },
            [
                dtr_leg(
                    route_step_id="step-1",
                    direction="WB",
                    entry="66",
                    exit_="28",
                ).model_dump(mode="json"),
                dtr_handoff_leg("dtr_to_greenway", "step-2").model_dump(mode="json"),
                greenway_leg(direction="WB", entry="28", exit_="1")
                .model_copy(update={"route_step_id": "step-3"})
                .model_dump(mode="json"),
            ],
            ["dtr_pricing", "greenway_pricing"],
            ["dtr", "dtr", "greenway"],
            "11.25",
        ),
    ],
)
def test_greenway_dtr_routes_price_every_component_in_route_order(
    monkeypatch: pytest.MonkeyPatch,
    input_data: object,
    row: dict[str, JSON],
    legs: list[dict[str, JSON]],
    stages: list[str],
    facilities: list[str],
    total: str,
) -> None:
    response = _pricing_route(row, legs)

    def _strict_callback_9(*_args: object, **_kwargs: object) -> object:
        return response

    monkeypatch.setattr(
        pricing_tool.route_validation,
        "fetch_validated_pricing_route",
        _strict_callback_9,
    )
    monkeypatch.setattr(
        pricing_tool,
        "_current_eastern_time",
        lambda: datetime(2026, 8, 17, 12, tzinfo=_EASTERN),
    )

    events = _run_tool(input_data)

    progress = _progress_events(events)
    assert [event["stage"] for event in progress if event["status"] == "running"] == [
        "route_validation",
        *stages,
    ]
    payload = cast(Any, _result(events))["content"][0]["json"]
    assert [component["facility"] for component in payload["components"]] == facilities
    assert payload["total_usd"] == total


def test_valid_no_toll_route_returns_zero_without_pricing_progress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_route(monkeypatch, [])
    monkeypatch.setattr(
        pricing_tool,
        "_current_eastern_time",
        lambda: datetime(2026, 8, 22, 12, tzinfo=_EASTERN),
    )

    events = _run_tool()

    assert [event["stage"] for event in _progress_events(events)] == [
        "route_validation",
        "route_validation",
    ]
    payload = cast(Any, _result(events))["content"][0]["json"]
    assert payload["source_kind"] == "none"
    assert payload["components"] == []
    assert payload["total_usd"] == "0.00"


@pytest.mark.parametrize(
    ("destination", "connection_id"),
    [
        ("i66:6:entry:EB", "iad_to_i66"),
        ("dtr:66:entry:WB", "iad_to_dtr_via_i66"),
        ("i495:182NO", "iad_to_i495_north"),
        ("i495:182SO", "iad_to_i495_south"),
    ],
)
def test_iad_terminal_connectors_return_zero_toll(
    monkeypatch: pytest.MonkeyPatch, destination: str, connection_id: str
) -> None:
    row = {
        "status": "valid",
        "reason": None,
        "point_ids": ["airport_iad", destination],
        "connection_ids": [connection_id],
        "connection_types": ["airport_access"],
        "general_purpose_gaps": [],
        "i95_evidence": None,
    }
    response = _pricing_route(row, [])

    def _strict_callback_10(*_args: object, **_kwargs: object) -> object:
        return response

    monkeypatch.setattr(
        pricing_tool.route_validation,
        "fetch_validated_pricing_route",
        _strict_callback_10,
    )
    monkeypatch.setattr(
        pricing_tool,
        "_current_eastern_time",
        lambda: datetime(2026, 8, 19, 12, tzinfo=_EASTERN),
    )

    events = _run_tool(
        {
            **_input(),
            "origin_point_id": "airport_iad",
            "destination_point_id": destination,
        }
    )

    assert [event["stage"] for event in _progress_events(events)] == [
        "route_validation",
        "route_validation",
    ]
    payload = cast(Any, _result(events))["content"][0]["json"]
    assert payload["origin_point_id"] == "airport_iad"
    assert payload["destination_point_id"] == destination
    assert payload["source_kind"] == "none"
    assert payload["components"] == []
    assert payload["total_usd"] == "0.00"


def test_i95_to_reagan_prices_only_the_i95_leg(monkeypatch: pytest.MonkeyPatch) -> None:
    row = {
        **_route_row(),
        "point_ids": ["i95:203NO", "i95:223ND", "airport_dca"],
        "connection_ids": [
            "source:i95_shared:Northbound:203NO:223ND",
            "i95_north_to_dca",
        ],
        "connection_types": ["within_facility", "airport_access"],
        "i95_evidence": _i95_evidence("northbound"),
    }
    response = _pricing_route(row, [i95_leg().model_dump(mode="json")])

    def _strict_callback_16(*_args: object, **_kwargs: object) -> object:
        return response

    monkeypatch.setattr(
        pricing_tool.route_validation,
        "fetch_validated_pricing_route",
        _strict_callback_16,
    )

    def _strict_callback_17(*_args: object) -> object:
        return i95_rows()

    monkeypatch.setattr(
        pricing_tool, "_fetch_i95_i495_comparisons", _strict_callback_17
    )

    events = _run_tool(
        {
            **_input(),
            "origin_point_id": "i95:203NO",
            "destination_point_id": "airport_dca",
        }
    )

    payload = cast(Any, _result(events))["content"][0]["json"]
    assert [
        event["stage"]
        for event in _progress_events(events)
        if event["status"] == "running"
    ] == ["route_validation", "i95_i495_pricing"]
    assert [component["facility"] for component in payload["components"]] == [
        "i95_i495"
    ]
    assert payload["source_kind"] == "observed"
    assert payload["total_usd"] == "8.20"


@pytest.mark.parametrize("origin_point_id", ["airport_dca", "i95:2233SO"])
def test_southbound_westpark_routes_price_both_components(
    monkeypatch: pytest.MonkeyPatch, origin_point_id: str
) -> None:
    response = _southbound_westpark_pricing_route(origin_point_id)

    def _strict_callback_18(*_args: object, **_kwargs: object) -> object:
        return response

    monkeypatch.setattr(
        pricing_tool.route_validation,
        "fetch_validated_pricing_route",
        _strict_callback_18,
    )
    requested_od_pairs: list[int] = []

    def fetch_prices(od_pair_id: int) -> list[pricing_tool._I95ComparisonRow]:
        requested_od_pairs.append(od_pair_id)
        return i95_rows(od_pair_id=od_pair_id)

    monkeypatch.setattr(pricing_tool, "_fetch_i95_i495_comparisons", fetch_prices)

    events = _run_tool(
        {
            **_input(),
            "origin_point_id": origin_point_id,
            "destination_point_id": "i495:1859ND",
        }
    )

    payload = cast(Any, _result(events))["content"][0]["json"]
    assert requested_od_pairs == [1204, 1005]
    assert [component["route_step_id"] for component in payload["components"]] == [
        "step-1",
        "step-2",
    ]
    assert payload["total_usd"] == "16.40"


@pytest.mark.parametrize(
    ("origin", "destination", "row", "legs", "facilities", "od_pair_id", "total"),
    [
        (
            "dtr:10:entry:EB",
            "i495:181ND",
            {
                **_route_row(),
                "point_ids": [
                    "dtr:10:entry:EB",
                    "dtr:1819:exit:EB",
                    "i495:182NO",
                    "i495:181ND",
                ],
                "connection_ids": [
                    "source:dtr:EB:10:1819",
                    "dulles_toll_road_to_i495_north",
                    "source:i95_shared:Northbound:182NO:181ND",
                ],
                "connection_types": [
                    "within_facility",
                    "toll_handoff",
                    "within_facility",
                ],
            },
            [
                dtr_leg(route_step_id="step-1", entry="10", exit_="1819"),
                dtr_leg(
                    route_step_id="step-2",
                    entry="10",
                    exit_="1819",
                    charge_index=2,
                ),
                i95_leg(
                    route_step_id="step-3",
                    entry="182NO",
                    exit_="181ND",
                    od_pair_id=1038,
                    point_ids=["i495:182NO", "i495:181ND"],
                ),
            ],
            ["dtr", "dtr", "i95_i495"],
            1038,
            "14.20",
        ),
        (
            "i495:191NO",
            "dtr:10:exit:WB",
            {
                **_route_row(),
                "point_ids": [
                    "i495:191NO",
                    "i495:182ND",
                    "dtr:1819:entry:WB",
                    "dtr:10:exit:WB",
                ],
                "connection_ids": [
                    "source:i95_shared:Northbound:191NO:182ND",
                    "i495_to_dulles_toll_road",
                    "source:dtr:WB:1819:10",
                ],
                "connection_types": [
                    "within_facility",
                    "toll_handoff",
                    "within_facility",
                ],
            },
            [
                i95_leg(
                    entry="191NO",
                    exit_="182ND",
                    od_pair_id=1014,
                    point_ids=["i495:191NO", "i495:182ND"],
                ),
                dtr_leg(
                    route_step_id="step-2",
                    direction="WB",
                    entry="1819",
                    exit_="10",
                ),
                dtr_leg(
                    route_step_id="step-3",
                    direction="WB",
                    entry="1819",
                    exit_="10",
                    charge_index=2,
                ),
            ],
            ["i95_i495", "dtr", "dtr"],
            1014,
            "14.20",
        ),
        (
            "i66:11:entry:WB",
            "i495:181ND",
            {
                **_route_row(),
                "point_ids": [
                    "i66:11:entry:WB",
                    "i66:5:exit:WB",
                    "i495:187NO",
                    "i495:181ND",
                ],
                "connection_ids": [
                    "source:i66:WB:11:5",
                    "i66_to_i495_north",
                    "source:i95_shared:Northbound:187NO:181ND",
                ],
                "connection_types": [
                    "within_facility",
                    "toll_handoff",
                    "within_facility",
                ],
            },
            [
                i66_leg(
                    direction="WB",
                    entry="11",
                    exit_="5",
                    start_zone_id=3220,
                    end_zone_id=3230,
                ),
                i95_leg(
                    route_step_id="step-2",
                    entry="187NO",
                    exit_="181ND",
                    od_pair_id=1034,
                    point_ids=["i495:187NO", "i495:181ND"],
                ),
            ],
            ["i66", "i95_i495"],
            1034,
            "15.40",
        ),
        (
            "i495:191NO",
            "i66:10:exit:EB",
            {
                **_route_row(),
                "point_ids": [
                    "i495:191NO",
                    "i495:187ND",
                    "i66:3:entry:EB",
                    "i66:10:exit:EB",
                ],
                "connection_ids": [
                    "source:i95_shared:Northbound:191NO:187ND",
                    "i495_to_i66",
                    "source:i66:EB:3:10",
                ],
                "connection_types": [
                    "within_facility",
                    "toll_handoff",
                    "within_facility",
                ],
            },
            [
                i95_leg(
                    entry="191NO",
                    exit_="187ND",
                    od_pair_id=1010,
                    point_ids=["i495:191NO", "i495:187ND"],
                ),
                i66_leg(
                    route_step_id="step-2",
                    entry="3",
                    exit_="10",
                    start_zone_id=3100,
                    end_zone_id=3110,
                ),
            ],
            ["i95_i495", "i66"],
            1010,
            "15.40",
        ),
    ],
)
def test_i495_junctions_price_every_facility(
    monkeypatch: pytest.MonkeyPatch,
    origin: str,
    destination: str,
    row: dict[str, JSON],
    legs: list[BaseModel],
    facilities: list[str],
    od_pair_id: int,
    total: str,
) -> None:
    response = _pricing_route(row, [leg.model_dump(mode="json") for leg in legs])

    def _strict_callback_19(*_args: object, **_kwargs: object) -> object:
        return response

    monkeypatch.setattr(
        pricing_tool.route_validation,
        "fetch_validated_pricing_route",
        _strict_callback_19,
    )
    requested_od_pairs: list[int] = []

    def fetch_i95_prices(
        requested_od_pair_id: int,
    ) -> list[pricing_tool._I95ComparisonRow]:
        requested_od_pairs.append(requested_od_pair_id)
        return i95_rows(od_pair_id=requested_od_pair_id)

    monkeypatch.setattr(pricing_tool, "_fetch_i95_i495_comparisons", fetch_i95_prices)

    def _strict_callback_20(*_args: object) -> object:
        return i66_rows()

    monkeypatch.setattr(pricing_tool, "_fetch_i66_comparisons", _strict_callback_20)

    events = _run_tool(
        {
            **_input(),
            "origin_point_id": origin,
            "destination_point_id": destination,
        }
    )

    payload = cast(Any, _result(events))["content"][0]["json"]
    assert [component["facility"] for component in payload["components"]] == facilities
    assert requested_od_pairs == [od_pair_id]
    assert payload["source_kind"] == (
        "observed" if set(facilities) <= {"i95_i495", "i66"} else "mixed"
    )
    assert payload["total_usd"] == total


def test_i95_unavailable_returns_no_partial_price(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = {
        **_route_row(),
        "point_ids": ["i95:203NO", "i95:223ND"],
        "connection_ids": ["source:i95_shared:Northbound:203NO:223ND"],
        "i95_evidence": _i95_evidence("northbound"),
    }
    response = _pricing_route(row, [i95_leg().model_dump(mode="json")])

    def _strict_callback_21(*_args: object, **_kwargs: object) -> object:
        return response

    monkeypatch.setattr(
        pricing_tool.route_validation,
        "fetch_validated_pricing_route",
        _strict_callback_21,
    )

    def _strict_callback_22(*_args: object) -> object:
        return i95_rows(unavailable_reason="stale_observation")

    monkeypatch.setattr(
        pricing_tool,
        "_fetch_i95_i495_comparisons",
        _strict_callback_22,
    )

    events = _run_tool(
        {
            **_input(),
            "origin_point_id": "i95:203NO",
            "destination_point_id": "i95:223ND",
        }
    )

    payload = cast(Any, _result(events))["content"][0]["json"]
    assert payload["reason"] == "incomplete_route_price"
    assert payload["unavailable_components"][0]["reason"] == "stale_observation"
    assert "components" not in payload
    assert "total_usd" not in payload


def test_multicomponent_route_returns_no_partial_price(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _southbound_westpark_pricing_route("i95:2233SO")
    input_data = {
        **_input(),
        "origin_point_id": "i95:2233SO",
        "destination_point_id": "i495:1859ND",
    }
    rows_by_od_pair = {
        1204: i95_rows(od_pair_id=1204),
        1005: i95_rows(od_pair_id=1005, unavailable_reason="stale_observation"),
    }
    evaluated_at = rows_by_od_pair[1204][0].evaluated_at
    expected = _domain_result(
        input_data,
        response,
        evaluated_at,
        {
            "step-1": rows_by_od_pair[1204],
            "step-2": rows_by_od_pair[1005],
        },
    )

    def _strict_callback_23(*_args: object, **_kwargs: object) -> object:
        return response

    monkeypatch.setattr(
        pricing_tool.route_validation,
        "fetch_validated_pricing_route",
        _strict_callback_23,
    )

    def _strict_callback_24(od_pair_id: int) -> object:
        return rows_by_od_pair[od_pair_id]

    monkeypatch.setattr(
        pricing_tool,
        "_fetch_i95_i495_comparisons",
        _strict_callback_24,
    )
    monkeypatch.setattr(pricing_tool, "_current_eastern_time", lambda: evaluated_at)

    payload = cast(Any, _result(_run_tool(input_data)))["content"][0]["json"]

    assert payload == expected
    assert [item["route_step_id"] for item in payload["unavailable_components"]] == [
        "step-2"
    ]
    assert "components" not in payload
    assert "total_usd" not in payload


def test_domain_builder_rejects_i95_rows_for_another_leg() -> None:
    response = _southbound_westpark_pricing_route("i95:2233SO")

    with pytest.raises(ValueError, match="wrong OD pair"):
        _domain_result(
            {
                **_input(),
                "origin_point_id": "i95:2233SO",
                "destination_point_id": "i495:1859ND",
            },
            response,
            datetime(2026, 8, 13, 8, 32, 6, tzinfo=_EASTERN),
            {
                "step-1": i95_rows(od_pair_id=1005),
                "step-2": i95_rows(od_pair_id=1204),
            },
        )


def test_i95_component_failure_marks_pricing_stage_failed(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    leg = i95_leg().model_dump(mode="json")
    leg["pricing_key"]["source_route_key"] = "Northbound:204NO:223ND"
    row = {
        **_route_row(),
        "point_ids": ["i95:203NO", "i95:223ND"],
        "connection_ids": ["source:i95_shared:Northbound:203NO:223ND"],
        "i95_evidence": _i95_evidence("northbound"),
    }
    response = _pricing_route(row, [leg])

    def _strict_callback_25(*_args: object, **_kwargs: object) -> object:
        return response

    monkeypatch.setattr(
        pricing_tool.route_validation,
        "fetch_validated_pricing_route",
        _strict_callback_25,
    )

    def _strict_callback_26(*_args: object) -> object:
        return i95_rows()

    monkeypatch.setattr(
        pricing_tool, "_fetch_i95_i495_comparisons", _strict_callback_26
    )

    with caplog.at_level(logging.ERROR):
        events = _run_tool(
            {
                **_input(),
                "origin_point_id": "i95:203NO",
                "destination_point_id": "i95:223ND",
            }
        )

    assert [
        (event["stage"], event["status"]) for event in _progress_events(events)
    ] == [
        ("route_validation", "running"),
        ("route_validation", "completed"),
        ("i95_i495_pricing", "running"),
        ("i95_i495_pricing", "failed"),
    ]
    assert _result(events)["status"] == "error"
    assert caplog.records[0].__dict__["failureStage"] == "i95_i495_pricing"


def test_i95_failure_streams_failed_and_sanitizes_error(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    secret = "private I-95 crash"
    row = {
        **_route_row(),
        "point_ids": ["i95:203NO", "i95:223ND"],
        "connection_ids": ["source:i95_shared:Northbound:203NO:223ND"],
        "i95_evidence": _i95_evidence("northbound"),
    }
    response = _pricing_route(row, [i95_leg().model_dump(mode="json")])

    def _strict_callback_27(*_args: object, **_kwargs: object) -> object:
        return response

    monkeypatch.setattr(
        pricing_tool.route_validation,
        "fetch_validated_pricing_route",
        _strict_callback_27,
    )

    def _strict_callback_28(*_args: object) -> object:
        raise RuntimeError(secret)

    monkeypatch.setattr(
        pricing_tool,
        "_fetch_i95_i495_comparisons",
        _strict_callback_28,
    )

    with caplog.at_level(logging.ERROR):
        events = _run_tool(
            {
                **_input(),
                "origin_point_id": "i95:203NO",
                "destination_point_id": "i95:223ND",
            }
        )

    assert [
        (event["stage"], event["status"]) for event in _progress_events(events)
    ] == [
        ("route_validation", "running"),
        ("route_validation", "completed"),
        ("i95_i495_pricing", "running"),
        ("i95_i495_pricing", "failed"),
    ]
    assert _result(events)["status"] == "error"
    assert secret not in str(_progress_events(events))
    assert secret not in caplog.text


@pytest.mark.parametrize(
    ("input_data", "row", "legs", "facilities", "expected_i66_component"),
    [
        (
            {
                **_input(),
                "origin_point_id": "dtr:10:entry:EB",
                "destination_point_id": "i66:10:exit:EB",
            },
            {
                **_route_row(),
                "point_ids": [
                    "dtr:10:entry:EB",
                    "dtr:66:exit:EB",
                    "i66:6:entry:EB",
                    "i66:10:exit:EB",
                ],
                "connection_ids": [
                    "source:dtr:EB:10:66",
                    "dulles_toll_road_to_i66",
                    "source:i66:EB:6:10",
                ],
                "connection_types": [
                    "within_facility",
                    "toll_handoff",
                    "within_facility",
                ],
            },
            [
                dtr_leg(route_step_id="step-1", entry="10", exit_="66").model_dump(
                    mode="json"
                ),
                dtr_leg(
                    route_step_id="step-2", entry="10", exit_="66", charge_index=2
                ).model_dump(mode="json"),
                i66_leg(route_step_id="step-3").model_dump(mode="json"),
            ],
            ["dtr", "dtr", "i66"],
            (3110, 3110, "EB"),
        ),
        (
            {
                **_input(),
                "origin_point_id": "i66:11:entry:WB",
                "destination_point_id": "dtr:10:exit:WB",
            },
            {
                **_route_row(),
                "point_ids": [
                    "i66:11:entry:WB",
                    "i66:6:exit:WB",
                    "dtr:66:entry:WB",
                    "dtr:10:exit:WB",
                ],
                "connection_ids": [
                    "source:i66:WB:11:6",
                    "i66_to_dulles_toll_road",
                    "source:dtr:WB:66:10",
                ],
                "connection_types": [
                    "within_facility",
                    "toll_handoff",
                    "within_facility",
                ],
            },
            [
                i66_leg(
                    route_step_id="step-1",
                    direction="WB",
                    entry="11",
                    exit_="6",
                    start_zone_id=3220,
                    end_zone_id=3220,
                ).model_dump(mode="json"),
                dtr_leg(
                    route_step_id="step-2", direction="WB", entry="66", exit_="10"
                ).model_dump(mode="json"),
                dtr_leg(
                    route_step_id="step-3",
                    direction="WB",
                    entry="66",
                    exit_="10",
                    charge_index=2,
                ).model_dump(mode="json"),
            ],
            ["i66", "dtr", "dtr"],
            (3220, 3220, "WB"),
        ),
    ],
)
def test_i66_dtr_junction_prices_both_directions(
    monkeypatch: pytest.MonkeyPatch,
    input_data: object,
    row: dict[str, JSON],
    legs: list[dict[str, JSON]],
    facilities: list[str],
    expected_i66_component: dict[str, JSON],
) -> None:
    row = {
        **row,
    }
    response = _pricing_route(row, legs)

    def _strict_callback_31(*_args: object, **_kwargs: object) -> object:
        return response

    monkeypatch.setattr(
        pricing_tool.route_validation,
        "fetch_validated_pricing_route",
        _strict_callback_31,
    )
    requested_i66_components: list[tuple[int, int, str]] = []

    def fetch_i66_prices(
        start_zone_id: int, end_zone_id: int, direction: str
    ) -> list[pricing_tool._I66ComparisonRow]:
        requested_i66_components.append((start_zone_id, end_zone_id, direction))
        return i66_rows()

    monkeypatch.setattr(pricing_tool, "_fetch_i66_comparisons", fetch_i66_prices)

    events = _run_tool(input_data)

    progress = _progress_events(events)
    payload = cast(Any, _result(events))["content"][0]["json"]
    pricing_stages = (
        ["dtr_pricing", "i66_pricing"]
        if facilities[0] == "dtr"
        else ["i66_pricing", "dtr_pricing"]
    )
    assert [event["stage"] for event in progress if event["status"] == "running"] == [
        "route_validation",
        *pricing_stages,
    ]
    assert [component["facility"] for component in payload["components"]] == facilities
    assert requested_i66_components == [expected_i66_component]
    assert payload["source_kind"] == "mixed"
    assert payload["total_usd"] == "13.20"


def test_i66_unavailable_returns_no_partial_price(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = {
        **_route_row(),
        "point_ids": ["i66:6:entry:EB", "i66:10:exit:EB"],
        "connection_ids": ["source:i66:EB:6:10"],
    }
    response = _pricing_route(row, [i66_leg().model_dump(mode="json")])

    def _strict_callback_32(*_args: object, **_kwargs: object) -> object:
        return response

    monkeypatch.setattr(
        pricing_tool.route_validation,
        "fetch_validated_pricing_route",
        _strict_callback_32,
    )

    def _strict_callback_33(*_args: object) -> object:
        return i66_rows(unavailable_reason="stale_observation")

    monkeypatch.setattr(
        pricing_tool,
        "_fetch_i66_comparisons",
        _strict_callback_33,
    )

    events = _run_tool(
        {
            **_input(),
            "origin_point_id": "i66:6:entry:EB",
            "destination_point_id": "i66:10:exit:EB",
        }
    )

    payload = cast(Any, _result(events))["content"][0]["json"]
    assert payload["reason"] == "incomplete_route_price"
    assert payload["unavailable_components"][0]["reason"] == "stale_observation"
    assert "components" not in payload
    assert "total_usd" not in payload


def test_i66_failure_streams_failed_and_sanitizes_error(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    secret = "private I-66 crash"
    row = {
        **_route_row(),
        "point_ids": ["i66:6:entry:EB", "i66:10:exit:EB"],
        "connection_ids": ["source:i66:EB:6:10"],
    }
    response = _pricing_route(row, [i66_leg().model_dump(mode="json")])

    def _strict_callback_34(*_args: object, **_kwargs: object) -> object:
        return response

    monkeypatch.setattr(
        pricing_tool.route_validation,
        "fetch_validated_pricing_route",
        _strict_callback_34,
    )

    def _strict_callback_35(*_args: object) -> object:
        raise RuntimeError(secret)

    monkeypatch.setattr(
        pricing_tool,
        "_fetch_i66_comparisons",
        _strict_callback_35,
    )

    with caplog.at_level(logging.ERROR):
        events = _run_tool(
            {
                **_input(),
                "origin_point_id": "i66:6:entry:EB",
                "destination_point_id": "i66:10:exit:EB",
            }
        )

    assert [
        (event["stage"], event["status"]) for event in _progress_events(events)
    ] == [
        ("route_validation", "running"),
        ("route_validation", "completed"),
        ("i66_pricing", "running"),
        ("i66_pricing", "failed"),
    ]
    assert _result(events)["status"] == "error"
    assert secret not in str(_progress_events(events))
    assert secret not in caplog.text


def test_greenway_failure_streams_failed_and_sanitizes_error(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    secret = "private Greenway crash"

    def fail(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError(secret)

    _install_route(monkeypatch, [greenway_leg().model_dump(mode="json")])
    monkeypatch.setattr(
        pricing_tool,
        "price_greenway_leg",
        fail,
    )

    with caplog.at_level(logging.ERROR):
        events = _run_tool()

    assert [
        (event["stage"], event["status"]) for event in _progress_events(events)
    ] == [
        ("route_validation", "running"),
        ("route_validation", "completed"),
        ("greenway_pricing", "running"),
        ("greenway_pricing", "failed"),
    ]
    assert _result(events)["status"] == "error"
    assert secret not in str(_progress_events(events))
    assert secret not in caplog.text


def test_dtr_failure_streams_failed_and_sanitizes_error(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    secret = "private DTR crash"

    def fail(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError(secret)

    row = {
        **_route_row(),
        "point_ids": ["dtr:28:entry:EB", "dtr:10:exit:EB"],
        "connection_ids": ["source:dtr:EB:28:10"],
    }
    response = _pricing_route(
        row,
        [dtr_leg(entry="28", exit_="10").model_dump(mode="json")],
    )

    def _strict_callback_36(*_args: object, **_kwargs: object) -> object:
        return response

    monkeypatch.setattr(
        pricing_tool.route_validation,
        "fetch_validated_pricing_route",
        _strict_callback_36,
    )
    monkeypatch.setattr(
        pricing_tool,
        "price_dtr_leg",
        fail,
    )

    with caplog.at_level(logging.ERROR):
        events = _run_tool(
            {
                **_input(),
                "origin_point_id": "dtr:28:entry:EB",
                "destination_point_id": "dtr:10:exit:EB",
            }
        )

    assert [
        (event["stage"], event["status"]) for event in _progress_events(events)
    ] == [
        ("route_validation", "running"),
        ("route_validation", "completed"),
        ("dtr_pricing", "running"),
        ("dtr_pricing", "failed"),
    ]
    assert _result(events)["status"] == "error"
    assert secret not in str(_progress_events(events))
    assert secret not in caplog.text
