# pyright: basic

import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from zoneinfo import ZoneInfo

import pytest
from strands.tools.loader import load_tools_from_module_path
from strands.tools.registry import ToolRegistry
from strands.types.tools import ToolResult, ToolUse

from agent_tools import get_current_toll_price as pricing_tool

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


def _tool_use(input_data: Any) -> ToolUse:
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
    empty_path = {
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


def _route_result(row: dict[str, Any]) -> ToolResult:
    return {
        "toolUseId": "tool-123",
        "status": "success",
        "content": [{"json": row}],
    }


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


def _greenway_leg(
    *, direction: str = "EB", entry: str = "1", exit_: str = "28"
) -> pricing_tool.route_validation._GreenwayFacilityLeg:  # pyright: ignore[reportPrivateUsage]
    route_key = f"{direction}:{entry}:{exit_}"
    return pricing_tool.route_validation._GreenwayFacilityLeg.model_validate(  # pyright: ignore[reportPrivateUsage]
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


def _dtr_leg(
    *,
    route_step_id: str = "step-1",
    direction: str = "EB",
    entry: str = "10",
    exit_: str = "16",
    charge_index: int = 1,
) -> pricing_tool.route_validation._DtrFacilityLeg:  # pyright: ignore[reportPrivateUsage]
    route_key = f"{direction}:{entry}:{exit_}"
    return pricing_tool.route_validation._DtrFacilityLeg.model_validate(  # pyright: ignore[reportPrivateUsage]
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


def _dtr_handoff_leg(
    route_key: str, route_step_id: str
) -> pricing_tool.route_validation._DtrFacilityLeg:  # pyright: ignore[reportPrivateUsage]
    point_ids = {
        "greenway_to_dtr": ["greenway:28:exit:EB", "dtr:28:entry:EB"],
        "dtr_to_greenway": ["dtr:28:exit:WB", "greenway:28:entry:WB"],
    }[route_key]
    return pricing_tool.route_validation._DtrFacilityLeg.model_validate(  # pyright: ignore[reportPrivateUsage]
        {
            "route_step_id": route_step_id,
            "facility": "dtr",
            "point_ids": point_ids,
            "connection_ids": [route_key],
            "pricing_key": {"source_route_key": route_key, "charge_index": 1},
        }
    )


def _i66_leg(
    *,
    route_step_id: str = "step-1",
    direction: str = "EB",
    entry: str = "6",
    exit_: str = "10",
    start_zone_id: int = 3110,
    end_zone_id: int = 3110,
) -> pricing_tool.route_validation._I66FacilityLeg:  # pyright: ignore[reportPrivateUsage]
    route_key = f"{direction}:{entry}:{exit_}"
    return pricing_tool.route_validation._I66FacilityLeg.model_validate(  # pyright: ignore[reportPrivateUsage]
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


def _i66_rows(
    *, unavailable_reason: str | None = None
) -> list[pricing_tool._I66ComparisonRow]:  # pyright: ignore[reportPrivateUsage]
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
            }
            for kind, offset, price in [
                ("prior_cycle", 1, "6.20"),
                ("prior_cycle", 2, "5.10"),
                ("prior_week", 1, "5.20"),
                ("prior_week", 2, "5.00"),
                ("prior_week", 3, "4.10"),
            ]
        )
    return [
        pricing_tool._I66ComparisonRow.model_validate(row)  # pyright: ignore[reportPrivateUsage]
        for row in rows
    ]


def _i95_leg(
    *,
    route_step_id: str = "step-1",
    direction: str = "Northbound",
    entry: str = "203NO",
    exit_: str = "223ND",
    od_pair_id: int = 1261,
    point_ids: list[str] | None = None,
) -> pricing_tool.route_validation._I95FacilityLeg:  # pyright: ignore[reportPrivateUsage]
    route_key = f"{direction}:{entry}:{exit_}"
    return pricing_tool.route_validation._I95FacilityLeg.model_validate(  # pyright: ignore[reportPrivateUsage]
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


def _i95_rows(
    *,
    unavailable_reason: str | None = None,
    source_kind: str = "observed",
    od_pair_id: int | None = None,
) -> list[pricing_tool._I95ComparisonRow]:  # pyright: ignore[reportPrivateUsage]
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
        "source_status": None if missing else "NORTHBOUND_OPEN",
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
    return [
        pricing_tool._I95ComparisonRow.model_validate(row)  # pyright: ignore[reportPrivateUsage]
        for row in rows
    ]


def _pricing_route(
    row: dict[str, Any], legs: list[dict[str, Any]]
) -> pricing_tool.route_validation._PricingRouteResponse:  # pyright: ignore[reportPrivateUsage]
    return pricing_tool.route_validation._PricingRouteResponse.model_validate(  # pyright: ignore[reportPrivateUsage]
        {**row, "facility_legs": legs}
    )


def _run_tool(input_data: Any | None = None) -> list[dict[str, Any]]:
    async def collect() -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        async for event in pricing_tool.get_current_toll_price.stream(
            _tool_use(_input() if input_data is None else input_data),
            {"agent": object()},
        ):
            events.append(dict(event))
        return events

    return asyncio.run(collect())


def _progress_events(events: list[dict[str, Any]]) -> list[dict[str, str]]:
    progress = []
    for event in events:
        if event.get("type") != "tool_stream":
            continue
        data = event["tool_stream_event"]["data"]
        if isinstance(data, dict) and "stage" in data:
            validated = pricing_tool._ProgressEvent.model_validate(data)  # pyright: ignore[reportPrivateUsage]
            progress.append(cast(dict[str, str], validated.model_dump(mode="json")))
    return progress


def _result(events: list[dict[str, Any]]) -> ToolResult:
    result = cast(ToolResult, events[-1]["tool_result"])
    if result["status"] == "error":
        pricing_tool._OperationError.model_validate(result)  # pyright: ignore[reportPrivateUsage]
    else:
        content = cast(Any, result["content"])
        pricing_tool._OUTPUT_ADAPTER.validate_json(  # pyright: ignore[reportPrivateUsage]
            json.dumps(content[0]["json"])
        )
    return result


def _install_route(monkeypatch, legs: list[dict[str, Any]]) -> None:
    row = _route_row()
    response = _pricing_route(row, legs)
    monkeypatch.setattr(
        pricing_tool.route_validation,
        "_validate_pricing_route",
        lambda *_args, **_kwargs: response,
    )


def test_strands_loads_exact_strict_input_schema():
    assert not hasattr(pricing_tool.route_validation, "TOOL_SPEC")
    loaded = load_tools_from_module_path("agent_tools.get_current_toll_price")
    assert loaded == [pricing_tool.get_current_toll_price]
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
        pricing_tool._OUTPUT_ADAPTER.json_schema(mode="serialization")  # pyright: ignore[reportPrivateUsage]
    )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda data: data.pop("pricing_profile"),
        lambda data: data.update({"requested_at": "TOP-SECRET"}),
        lambda data: data["pricing_profile"].update({"vehicle_class": 2}),
        lambda data: data["pricing_profile"].update({"occupancy": 3}),
    ],
)
def test_malformed_input_fails_safely_without_route_validation(
    monkeypatch, caplog, mutation
):
    input_data = _input()
    mutation(input_data)
    monkeypatch.setattr(
        pricing_tool.route_validation,
        "_validate_pricing_route",
        lambda *_args, **_kwargs: pytest.fail("invalid input reached the database"),
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
    assert caplog.records[0].failureStage == "input_validation"
    assert "TOP-SECRET" not in caplog.text


def test_unsupported_profile_short_circuits_without_progress(monkeypatch):
    input_data = _input()
    input_data["pricing_profile"]["transponder_mode"] = "hov"
    monkeypatch.setattr(
        pricing_tool.route_validation,
        "_validate_pricing_route",
        lambda *_args, **_kwargs: pytest.fail("unsupported profile reached RDS"),
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
def test_nonvalid_routes_complete_validation_without_pricing(monkeypatch, row):
    response = _pricing_route(row, [])
    monkeypatch.setattr(
        pricing_tool.route_validation,
        "_validate_pricing_route",
        lambda *_args, **_kwargs: response,
    )

    monkeypatch.setattr(
        pricing_tool,
        "_success",
        lambda *_args, **_kwargs: pytest.fail("nonvalid route reached pricing"),
    )
    input_data = _input()
    if row["point_ids"]:
        input_data.update(
            {
                "origin_point_id": row["point_ids"][0],
                "destination_point_id": row["point_ids"][-1],
            }
        )

    events = _run_tool(input_data)

    assert [
        (event["stage"], event["status"]) for event in _progress_events(events)
    ] == [
        ("route_validation", "running"),
        ("route_validation", "completed"),
    ]
    payload = cast(Any, _result(events))["content"][0]["json"]
    assert payload["status"] == row["status"]
    assert ("facility_legs" in payload) is bool(row["point_ids"])
    assert "total_usd" not in payload
    assert "components" not in payload


def test_route_failure_streams_failed_and_returns_only_safe_error(monkeypatch, caplog):
    secret = "private-pricing-route"

    def fail(*_args, **_kwargs):
        raise RuntimeError(secret)

    monkeypatch.setattr(
        pricing_tool.route_validation,
        "_validate_pricing_route",
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


@pytest.mark.parametrize(
    ("direction", "entry", "exit_", "evaluated_at", "price", "period", "rate_name"),
    [
        (
            "EB",
            "1",
            "2A",
            datetime(2026, 8, 17, 6, 29, tzinfo=_EASTERN),
            "4.55",
            "off_peak",
            "secondary_plaza",
        ),
        (
            "EB",
            "1",
            "2A",
            datetime(2026, 8, 17, 6, 30, tzinfo=_EASTERN),
            "5.10",
            "peak",
            "secondary_plaza",
        ),
        (
            "EB",
            "1",
            "28",
            datetime(2026, 8, 17, 8, 59, tzinfo=_EASTERN),
            "5.80",
            "peak",
            "mainline_plaza",
        ),
        (
            "EB",
            "1",
            "28",
            datetime(2026, 8, 17, 9, 0, tzinfo=_EASTERN),
            "5.25",
            "off_peak",
            "mainline_plaza",
        ),
        (
            "WB",
            "28",
            "1",
            datetime(2026, 8, 17, 16, 0, tzinfo=_EASTERN),
            "5.80",
            "peak",
            "mainline_plaza",
        ),
        (
            "WB",
            "8",
            "1",
            datetime(2026, 8, 17, 18, 29, tzinfo=_EASTERN),
            "5.10",
            "peak",
            "secondary_plaza",
        ),
        (
            "WB",
            "28",
            "1",
            datetime(2026, 8, 17, 18, 30, tzinfo=_EASTERN),
            "5.25",
            "off_peak",
            "mainline_plaza",
        ),
        (
            "EB",
            "1",
            "28",
            datetime(2026, 8, 22, 7, 0, tzinfo=_EASTERN),
            "5.25",
            "off_peak",
            "mainline_plaza",
        ),
        (
            "EB",
            "1",
            "28",
            datetime(2026, 8, 17, 10, 30, tzinfo=UTC),
            "5.80",
            "peak",
            "mainline_plaza",
        ),
    ],
)
def test_greenway_schedule_rates(
    direction, entry, exit_, evaluated_at, price, period, rate_name
):
    component = pricing_tool._price_greenway(
        _greenway_leg(direction=direction, entry=entry, exit_=exit_), evaluated_at
    )

    assert component.price_usd == Decimal(price)
    assert component.rate_period == period
    assert component.published_schedule.rate_name == rate_name
    assert component.component_evaluated_at.tzinfo == _EASTERN


@pytest.mark.parametrize(
    "mutation",
    [
        lambda data: data["pricing_key"].update({"charge_index": 2}),
        lambda data: data.update({"connection_ids": ["source:greenway:EB:1:8"]}),
        lambda data: data.update(
            {"point_ids": ["greenway:1:entry:EB", "greenway:8:exit:EB"]}
        ),
        lambda data: data["pricing_key"].update({"source_route_key": "bad-key"}),
    ],
)
def test_greenway_pricer_rejects_misaligned_legs(mutation):
    data = _greenway_leg().model_dump(mode="python")
    mutation(data)
    leg = pricing_tool.route_validation._GreenwayFacilityLeg.model_validate(data)  # pyright: ignore[reportPrivateUsage]

    with pytest.raises(ValueError, match="Greenway"):
        pricing_tool._price_greenway(leg, datetime(2026, 8, 17, 8, 0, tzinfo=_EASTERN))


def test_greenway_pricer_requires_aware_evaluation_time():
    with pytest.raises(ValueError, match="aware"):
        pricing_tool._price_greenway(
            _greenway_leg(),
            datetime(2026, 8, 17, 8),  # noqa: DTZ001
        )


@pytest.mark.parametrize(
    ("direction", "entry", "exit_", "charge_index", "price", "rate_name"),
    [
        ("EB", "28", "10", 1, "2.00", "ramp"),
        ("EB", "10", "17", 1, "2.00", "ramp"),
        ("EB", "10", "17", 2, "4.00", "mainline_plaza"),
        ("EB", "10", "17", 3, "2.00", "ramp"),
        ("WB", "66", "28", 1, "4.00", "mainline_plaza"),
        ("EB", "16", "17", 1, "4.00", "mainline_plaza"),
        ("EB", "16", "17", 2, "2.00", "ramp"),
    ],
)
def test_dtr_schedule_rates(direction, entry, exit_, charge_index, price, rate_name):
    component = pricing_tool._price_dtr(
        _dtr_leg(
            direction=direction,
            entry=entry,
            exit_=exit_,
            charge_index=charge_index,
        ),
        datetime(2026, 8, 17, 10, 0, tzinfo=UTC),
    )

    assert component.price_usd == Decimal(price)
    assert component.published_schedule.rate_name == rate_name
    assert component.component_evaluated_at.tzinfo == _EASTERN


def test_dtr_pricer_matches_every_canonical_source_charge():
    source = json.loads(
        (
            Path(__file__).parents[1] / "oracle" / "sources" / "dulles_toll_road.json"
        ).read_text()
    )

    checked = 0
    for pair in source["pairs"]:
        for charge_index, charge in enumerate(pair["charges"], 1):
            component = pricing_tool._price_dtr(
                _dtr_leg(
                    direction=pair["direction"],
                    entry=pair["entry"],
                    exit_=pair["exit"],
                    charge_index=charge_index,
                ),
                datetime(2026, 8, 17, 12, tzinfo=_EASTERN),
            )
            assert component.price_usd == Decimal(charge["price_off_peak_usd"])
            assert component.published_schedule.rate_name == (
                "mainline_plaza" if charge["label"] == "Mainline plaza" else "ramp"
            )
            checked += 1

    assert checked == 175


@pytest.mark.parametrize("route_key", ["greenway_to_dtr", "dtr_to_greenway"])
def test_dtr_handoff_is_a_ramp_charge(route_key):
    component = pricing_tool._price_dtr(
        _dtr_handoff_leg(route_key, "step-1"),
        datetime(2026, 8, 17, 12, tzinfo=_EASTERN),
    )

    assert component.price_usd == Decimal("2.00")
    assert component.published_schedule.rate_name == "ramp"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda data: data["pricing_key"].update({"charge_index": 4}),
        lambda data: data.update({"connection_ids": ["source:dtr:EB:10:17"]}),
        lambda data: data.update({"point_ids": ["dtr:10:entry:EB", "dtr:17:exit:EB"]}),
        lambda data: data["pricing_key"].update({"source_route_key": "WB:10:16"}),
    ],
)
def test_dtr_pricer_rejects_misaligned_legs(mutation):
    data = _dtr_leg().model_dump(mode="python")
    mutation(data)
    leg = pricing_tool.route_validation._DtrFacilityLeg.model_validate(data)  # pyright: ignore[reportPrivateUsage]

    with pytest.raises(ValueError, match="DTR"):
        pricing_tool._price_dtr(leg, datetime(2026, 8, 17, 8, 0, tzinfo=_EASTERN))


def test_dtr_pricer_requires_aware_evaluation_time():
    with pytest.raises(ValueError, match="aware"):
        pricing_tool._price_dtr(
            _dtr_leg(),
            datetime(2026, 8, 17, 8),  # noqa: DTZ001
        )


def test_greenway_only_route_streams_progress_and_returns_total(monkeypatch):
    leg = _greenway_leg().model_dump(mode="json")
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
                _greenway_leg().model_dump(mode="json"),
                _dtr_handoff_leg("greenway_to_dtr", "step-2").model_dump(mode="json"),
                _dtr_leg(route_step_id="step-3", entry="28", exit_="10").model_dump(
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
                _dtr_leg(
                    route_step_id="step-1",
                    direction="WB",
                    entry="66",
                    exit_="28",
                ).model_dump(mode="json"),
                _dtr_handoff_leg("dtr_to_greenway", "step-2").model_dump(mode="json"),
                _greenway_leg(direction="WB", entry="28", exit_="1")
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
    monkeypatch, input_data, row, legs, stages, facilities, total
):
    response = _pricing_route(row, legs)
    monkeypatch.setattr(
        pricing_tool.route_validation,
        "_validate_pricing_route",
        lambda *_args, **_kwargs: response,
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


def test_valid_no_toll_route_returns_zero_without_pricing_progress(monkeypatch):
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
    monkeypatch, destination, connection_id
):
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
    monkeypatch.setattr(
        pricing_tool.route_validation,
        "_validate_pricing_route",
        lambda *_args, **_kwargs: response,
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


def test_i66_pricer_returns_current_price_and_comparisons(monkeypatch):
    monkeypatch.setattr(pricing_tool, "_fetch_i66_prices", lambda *_args: _i66_rows())

    component = pricing_tool._price_i66(_i66_leg())

    assert isinstance(component, pricing_tool._I66Component)  # pyright: ignore[reportPrivateUsage]
    assert component.price_usd == Decimal("7.20")
    assert component.recent_movement is not None
    assert component.recent_movement.direction == "rising"
    assert component.recent_movement.net_change_usd == Decimal("2.10")
    assert component.recent_movement.net_change_percent == Decimal("41.2")
    assert component.prior_week_comparison is not None
    assert component.prior_week_comparison.median_usd == Decimal("5.00")
    assert component.prior_week_comparison.current_delta_percent == Decimal("44.0")
    assert component.prior_week_comparison.position == "above_recent_range"
    assert component.prior_week_comparison.higher_than_count == 3


@pytest.mark.parametrize(
    ("source_kind", "pricing_method", "od_pair_id", "proxy_od_pair_id"),
    [
        ("observed", "source_observation", 1261, None),
        ("modeled", "identity_proxy_v1", 1374, 1146),
    ],
)
def test_i95_pricer_returns_current_price_comparisons_and_provenance(
    monkeypatch, source_kind, pricing_method, od_pair_id, proxy_od_pair_id
):
    monkeypatch.setattr(
        pricing_tool,
        "_fetch_i95_prices",
        lambda *_args: _i95_rows(source_kind=source_kind),
    )

    leg = (
        _i95_leg()
        if source_kind == "observed"
        else _i95_leg(
            entry="191NO",
            exit_="201ND",
            od_pair_id=1374,
            point_ids=["i495:192NO", "i95:201ND"],
        )
    )
    component = pricing_tool._price_i95(leg)

    assert isinstance(component, pricing_tool._I95Component)  # pyright: ignore[reportPrivateUsage]
    assert component.price_usd == Decimal("8.20")
    assert component.source_kind == source_kind
    assert component.pricing_method == pricing_method
    assert component.od_pair_id == od_pair_id
    assert component.proxy_od_pair_id == proxy_od_pair_id
    assert component.bin_minutes == 10
    assert component.recent_movement is not None
    assert component.recent_movement.direction == "rising"
    assert component.recent_movement.net_change_usd == Decimal("2.10")
    assert component.prior_week_comparison is not None
    assert component.prior_week_comparison.median_usd == Decimal("6.00")
    assert component.prior_week_comparison.position == "above_recent_range"
    response = pricing_tool._success(  # pyright: ignore[reportPrivateUsage]
        pricing_tool._PricingRequest.model_validate(_input()),  # pyright: ignore[reportPrivateUsage]
        component.component_evaluated_at,
        [component],
    )
    assert cast(Any, response)["content"][0]["json"]["source_kind"] == source_kind


@pytest.mark.parametrize(
    "mutation",
    [
        lambda row: row.update({"comparison_offset": 1}),
        lambda row: row.update({"price_usd": Decimal("-0.01")}),
        lambda row: row.update(
            {"observed_at": row["evaluated_at"] + timedelta(minutes=1)}
        ),
        lambda row: row.update(
            {"bin_end_at": row["bin_end_at"] + timedelta(minutes=1)}
        ),
        lambda row: row.update({"proxy_od_pair_id": 1146}),
        lambda row: row.update({"source_status": None}),
    ],
)
def test_i95_comparison_row_rejects_invalid_database_data(mutation):
    row = _i95_rows()[0].model_dump(mode="python")
    mutation(row)

    with pytest.raises(ValueError):
        pricing_tool._I95ComparisonRow.model_validate(row)  # pyright: ignore[reportPrivateUsage]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda rows: rows[0].update({"od_pair_id": 9999}),
        lambda rows: rows.append(dict(rows[0])),
        lambda rows: rows[1].update(
            {
                "source_kind": "modeled",
                "pricing_method": "identity_proxy_v1",
                "proxy_od_pair_id": 1146,
            }
        ),
    ],
)
def test_i95_fetch_rejects_misaligned_row_sets(monkeypatch, mutation):
    rows = [row.model_dump(mode="python") for row in _i95_rows()]
    mutation(rows)
    monkeypatch.setattr(pricing_tool, "_fetch_rows", lambda *_args: rows)

    with pytest.raises(ValueError, match="I-95/I-495"):
        pricing_tool._fetch_i95_prices(1261)  # pyright: ignore[reportPrivateUsage]


@pytest.mark.parametrize(
    "reason", ["missing_observation", "stale_observation", "facility_unavailable"]
)
def test_i95_pricer_preserves_unavailable_diagnostic(monkeypatch, reason):
    monkeypatch.setattr(
        pricing_tool,
        "_fetch_i95_prices",
        lambda *_args: _i95_rows(unavailable_reason=reason),
    )

    result = pricing_tool._price_i95(_i95_leg())

    assert isinstance(result, pricing_tool._UnavailableComponent)  # pyright: ignore[reportPrivateUsage]
    assert result.reason == reason
    assert result.source_status == (
        None if reason == "missing_observation" else "NORTHBOUND_OPEN"
    )
    assert "price_usd" not in result.model_dump()


@pytest.mark.parametrize(
    "mutation",
    [
        lambda data: data.update(
            {"connection_ids": ["source:i95_shared:Northbound:203NO:224ND"]}
        ),
        lambda data: data.update({"point_ids": ["i95:204NO", "i95:223ND"]}),
        lambda data: data["pricing_key"].update({"source_route_key": "bad-key"}),
    ],
)
def test_i95_pricer_rejects_misaligned_leg(monkeypatch, mutation):
    data = _i95_leg().model_dump(mode="python")
    mutation(data)
    leg = pricing_tool.route_validation._I95FacilityLeg.model_validate(data)  # pyright: ignore[reportPrivateUsage]
    monkeypatch.setattr(pricing_tool, "_fetch_i95_prices", lambda *_args: _i95_rows())

    with pytest.raises(ValueError, match="I-95/I-495"):
        pricing_tool._price_i95(leg)


def test_i95_to_reagan_prices_only_the_i95_leg(monkeypatch):
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
    response = _pricing_route(row, [_i95_leg().model_dump(mode="json")])
    monkeypatch.setattr(
        pricing_tool.route_validation,
        "_validate_pricing_route",
        lambda *_args, **_kwargs: response,
    )
    monkeypatch.setattr(pricing_tool, "_fetch_i95_prices", lambda *_args: _i95_rows())

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
                _dtr_leg(route_step_id="step-1", entry="10", exit_="1819"),
                _dtr_leg(
                    route_step_id="step-2",
                    entry="10",
                    exit_="1819",
                    charge_index=2,
                ),
                _i95_leg(
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
                _i95_leg(
                    entry="191NO",
                    exit_="182ND",
                    od_pair_id=1014,
                    point_ids=["i495:191NO", "i495:182ND"],
                ),
                _dtr_leg(
                    route_step_id="step-2",
                    direction="WB",
                    entry="1819",
                    exit_="10",
                ),
                _dtr_leg(
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
                _i66_leg(
                    direction="WB",
                    entry="11",
                    exit_="5",
                    start_zone_id=3220,
                    end_zone_id=3230,
                ),
                _i95_leg(
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
                _i95_leg(
                    entry="191NO",
                    exit_="187ND",
                    od_pair_id=1010,
                    point_ids=["i495:191NO", "i495:187ND"],
                ),
                _i66_leg(
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
    monkeypatch, origin, destination, row, legs, facilities, od_pair_id, total
):
    response = _pricing_route(row, [leg.model_dump(mode="json") for leg in legs])
    monkeypatch.setattr(
        pricing_tool.route_validation,
        "_validate_pricing_route",
        lambda *_args, **_kwargs: response,
    )
    requested_od_pairs: list[int] = []

    def fetch_i95_prices(requested_od_pair_id: int):
        requested_od_pairs.append(requested_od_pair_id)
        return _i95_rows(od_pair_id=requested_od_pair_id)

    monkeypatch.setattr(pricing_tool, "_fetch_i95_prices", fetch_i95_prices)
    monkeypatch.setattr(pricing_tool, "_fetch_i66_prices", lambda *_args: _i66_rows())

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


def test_i95_unavailable_returns_no_partial_price(monkeypatch):
    row = {
        **_route_row(),
        "point_ids": ["i95:203NO", "i95:223ND"],
        "connection_ids": ["source:i95_shared:Northbound:203NO:223ND"],
        "i95_evidence": _i95_evidence("northbound"),
    }
    response = _pricing_route(row, [_i95_leg().model_dump(mode="json")])
    monkeypatch.setattr(
        pricing_tool.route_validation,
        "_validate_pricing_route",
        lambda *_args, **_kwargs: response,
    )
    monkeypatch.setattr(
        pricing_tool,
        "_fetch_i95_prices",
        lambda *_args: _i95_rows(unavailable_reason="stale_observation"),
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


def test_i95_failure_streams_failed_and_sanitizes_error(monkeypatch, caplog):
    secret = "private I-95 crash"
    row = {
        **_route_row(),
        "point_ids": ["i95:203NO", "i95:223ND"],
        "connection_ids": ["source:i95_shared:Northbound:203NO:223ND"],
        "i95_evidence": _i95_evidence("northbound"),
    }
    response = _pricing_route(row, [_i95_leg().model_dump(mode="json")])
    monkeypatch.setattr(
        pricing_tool.route_validation,
        "_validate_pricing_route",
        lambda *_args, **_kwargs: response,
    )
    monkeypatch.setattr(
        pricing_tool,
        "_fetch_i95_prices",
        lambda *_args: (_ for _ in ()).throw(RuntimeError(secret)),
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


def test_i66_pricer_omits_incomplete_history(monkeypatch):
    monkeypatch.setattr(
        pricing_tool,
        "_fetch_i66_prices",
        lambda *_args: _i66_rows()[:1],
    )

    component = pricing_tool._price_i66(_i66_leg())

    assert isinstance(component, pricing_tool._I66Component)  # pyright: ignore[reportPrivateUsage]
    assert component.recent_movement is None
    assert component.prior_week_comparison is None


def test_prior_week_expectation_excludes_nonexistent_spring_forward_bin():
    assert (
        pricing_tool._expected_prior_weeks(  # pyright: ignore[reportPrivateUsage]
            datetime(2026, 3, 22, 2, 0, tzinfo=_EASTERN)
        )
        == 2
    )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda row: row.update({"comparison_offset": 1}),
        lambda row: row.update(
            {"evaluated_at": datetime(2026, 8, 13, 8, 32)}  # noqa: DTZ001
        ),
        lambda row: row.update(
            {"observed_at": row["evaluated_at"] + timedelta(minutes=1)}
        ),
        lambda row: row.update(
            {
                "available": False,
                "availability_reason": "missing_observation",
            }
        ),
    ],
)
def test_i66_comparison_row_rejects_invalid_database_data(mutation):
    row = _i66_rows()[0].model_dump(mode="python")
    mutation(row)

    with pytest.raises(ValueError):
        pricing_tool._I66ComparisonRow.model_validate(row)  # pyright: ignore[reportPrivateUsage]


@pytest.mark.parametrize("reason", ["missing_observation", "stale_observation"])
def test_i66_pricer_preserves_unavailable_diagnostic(monkeypatch, reason):
    monkeypatch.setattr(
        pricing_tool,
        "_fetch_i66_prices",
        lambda *_args: _i66_rows(unavailable_reason=reason),
    )

    result = pricing_tool._price_i66(_i66_leg())

    assert isinstance(result, pricing_tool._UnavailableComponent)  # pyright: ignore[reportPrivateUsage]
    assert result.reason == reason
    assert "price_usd" not in result.model_dump()


@pytest.mark.parametrize(
    "mutation",
    [
        lambda data: data.update({"connection_ids": ["source:i66:EB:7:10"]}),
        lambda data: data.update({"point_ids": ["i66:7:entry:EB", "i66:10:exit:EB"]}),
        lambda data: data["pricing_key"].update({"source_route_key": "bad-key"}),
    ],
)
def test_i66_pricer_rejects_misaligned_leg(monkeypatch, mutation):
    data = _i66_leg().model_dump(mode="python")
    mutation(data)
    leg = pricing_tool.route_validation._I66FacilityLeg.model_validate(data)  # pyright: ignore[reportPrivateUsage]
    monkeypatch.setattr(pricing_tool, "_fetch_i66_prices", lambda *_args: _i66_rows())

    with pytest.raises(ValueError, match="I-66"):
        pricing_tool._price_i66(leg)


@pytest.mark.parametrize(
    ("input_data", "row", "legs", "facilities", "expected_i66_zone_pair"),
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
                _dtr_leg(route_step_id="step-1", entry="10", exit_="66").model_dump(
                    mode="json"
                ),
                _dtr_leg(
                    route_step_id="step-2", entry="10", exit_="66", charge_index=2
                ).model_dump(mode="json"),
                _i66_leg(route_step_id="step-3").model_dump(mode="json"),
            ],
            ["dtr", "dtr", "i66"],
            (3110, 3110),
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
                _i66_leg(
                    route_step_id="step-1",
                    direction="WB",
                    entry="11",
                    exit_="6",
                    start_zone_id=3220,
                    end_zone_id=3220,
                ).model_dump(mode="json"),
                _dtr_leg(
                    route_step_id="step-2", direction="WB", entry="66", exit_="10"
                ).model_dump(mode="json"),
                _dtr_leg(
                    route_step_id="step-3",
                    direction="WB",
                    entry="66",
                    exit_="10",
                    charge_index=2,
                ).model_dump(mode="json"),
            ],
            ["i66", "dtr", "dtr"],
            (3220, 3220),
        ),
    ],
)
def test_i66_dtr_junction_prices_both_directions(
    monkeypatch, input_data, row, legs, facilities, expected_i66_zone_pair
):
    row = {
        **row,
    }
    response = _pricing_route(row, legs)
    monkeypatch.setattr(
        pricing_tool.route_validation,
        "_validate_pricing_route",
        lambda *_args, **_kwargs: response,
    )
    requested_i66_zone_pairs: list[tuple[int, int]] = []

    def fetch_i66_prices(start_zone_id: int, end_zone_id: int):
        requested_i66_zone_pairs.append((start_zone_id, end_zone_id))
        return _i66_rows()

    monkeypatch.setattr(pricing_tool, "_fetch_i66_prices", fetch_i66_prices)

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
    assert requested_i66_zone_pairs == [expected_i66_zone_pair]
    assert payload["source_kind"] == "mixed"
    assert payload["total_usd"] == "13.20"


def test_i66_unavailable_returns_no_partial_price(monkeypatch):
    row = {
        **_route_row(),
        "point_ids": ["i66:6:entry:EB", "i66:10:exit:EB"],
        "connection_ids": ["source:i66:EB:6:10"],
    }
    response = _pricing_route(row, [_i66_leg().model_dump(mode="json")])
    monkeypatch.setattr(
        pricing_tool.route_validation,
        "_validate_pricing_route",
        lambda *_args, **_kwargs: response,
    )
    monkeypatch.setattr(
        pricing_tool,
        "_fetch_i66_prices",
        lambda *_args: _i66_rows(unavailable_reason="stale_observation"),
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


def test_i66_failure_streams_failed_and_sanitizes_error(monkeypatch, caplog):
    secret = "private I-66 crash"
    row = {
        **_route_row(),
        "point_ids": ["i66:6:entry:EB", "i66:10:exit:EB"],
        "connection_ids": ["source:i66:EB:6:10"],
    }
    response = _pricing_route(row, [_i66_leg().model_dump(mode="json")])
    monkeypatch.setattr(
        pricing_tool.route_validation,
        "_validate_pricing_route",
        lambda *_args, **_kwargs: response,
    )
    monkeypatch.setattr(
        pricing_tool,
        "_fetch_i66_prices",
        lambda *_args: (_ for _ in ()).throw(RuntimeError(secret)),
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


def test_greenway_failure_streams_failed_and_sanitizes_error(monkeypatch, caplog):
    secret = "private Greenway crash"

    def fail(*_args, **_kwargs):
        raise RuntimeError(secret)

    _install_route(monkeypatch, [_greenway_leg().model_dump(mode="json")])
    monkeypatch.setattr(
        pricing_tool,
        "_price_greenway",
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


def test_dtr_failure_streams_failed_and_sanitizes_error(monkeypatch, caplog):
    secret = "private DTR crash"

    def fail(*_args, **_kwargs):
        raise RuntimeError(secret)

    row = {
        **_route_row(),
        "point_ids": ["dtr:28:entry:EB", "dtr:10:exit:EB"],
        "connection_ids": ["source:dtr:EB:28:10"],
    }
    response = _pricing_route(
        row,
        [_dtr_leg(entry="28", exit_="10").model_dump(mode="json")],
    )
    monkeypatch.setattr(
        pricing_tool.route_validation,
        "_validate_pricing_route",
        lambda *_args, **_kwargs: response,
    )
    monkeypatch.setattr(
        pricing_tool,
        "_price_dtr",
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
