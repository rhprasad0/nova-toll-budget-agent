from datetime import datetime
from decimal import Decimal
from typing import Any, cast
from zoneinfo import ZoneInfo

import pytest

import timed_checks

NEW_YORK = ZoneInfo("America/New_York")
WINDOW_EXPECTATIONS: dict[str, dict[str, Any]] = {
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


def test_freshness_boundaries_and_dst() -> None:
    schedule = "47 1 * * 2"
    assert timed_checks.scheduled_run_is_fresh(
        schedule, datetime(2026, 8, 18, 1, 57, tzinfo=NEW_YORK)
    )
    assert not timed_checks.scheduled_run_is_fresh(
        schedule, datetime(2026, 8, 18, 1, 57, 1, tzinfo=NEW_YORK)
    )
    assert not timed_checks.scheduled_run_is_fresh(
        schedule, datetime(2026, 8, 18, 1, 58, tzinfo=NEW_YORK)
    )
    assert not timed_checks.scheduled_run_is_fresh(
        "17 14 * * 4", datetime(2026, 8, 21, 14, 25, tzinfo=NEW_YORK)
    )
    assert timed_checks.scheduled_run_is_fresh(
        "", datetime(2026, 11, 1, 1, 55, tzinfo=NEW_YORK)
    )
    assert timed_checks.scheduled_run_is_fresh(
        "30 1 * * 7", datetime(2026, 11, 1, 1, 35, tzinfo=NEW_YORK)
    )


def test_configured_database_endpoint_is_not_replaced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_client(*_args: object, **_kwargs: object) -> None:
        pytest.fail("unexpected RDS lookup")

    monkeypatch.setenv("DB_HOST", "reviewed-development.example")
    monkeypatch.setenv("DB_PORT", "5432")
    monkeypatch.setattr(timed_checks.boto3, "client", fail_client)
    timed_checks._configure_rds_endpoint()  # pyright: ignore[reportPrivateUsage]


def test_route_checks_cover_all_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(timed_checks, "_configure_rds_endpoint", lambda: None)

    def validate(origin: str, destination: str, tool_use_id: str) -> dict[str, object]:
        if tool_use_id.endswith("-northbound") or tool_use_id.endswith("-southbound"):
            northbound = tool_use_id.endswith("-northbound")
            window_id = tool_use_id.rsplit("-", 1)[0]
            expected = WINDOW_EXPECTATIONS[window_id]
            state = expected["northbound_status" if northbound else "southbound_status"]
            if state == "valid":
                return {
                    "origin_point_id": origin,
                    "destination_point_id": destination,
                    "method": "latest_complete_current_facility_prices",
                    "total_usd": "1.00",
                    "components": [{"facility": "i95_i495"}],
                }
            direction = "northbound" if northbound else "southbound"
            return {
                "status": state,
                "reason": {"code": expected[f"{direction}_reason"]},
                "i95_evidence": {
                    "availability": expected["availability"],
                    "northbound_link_status": expected["northbound_link_status"],
                    "southbound_link_status": expected["southbound_link_status"],
                },
            }
        if tool_use_id.endswith("-i66-pricing-route"):
            return {
                "method": "latest_complete_current_facility_prices",
                "components": [{"facility": "i66"}],
            }
        if tool_use_id.endswith("-restart-offer"):
            return {
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
        if tool_use_id.endswith("-restart-accepted"):
            return {
                "origin_point_id": origin,
                "destination_point_id": destination,
                "method": "latest_complete_current_facility_prices",
                "total_usd": "1.00",
                "components": [{"facility": "i95_i495"}],
            }
        if tool_use_id.endswith("-greenway-to-dca"):
            window_id = tool_use_id.removesuffix("-greenway-to-dca")
            expected = WINDOW_EXPECTATIONS[window_id]
            if expected["northbound_status"] == "valid":
                return {
                    "origin_point_id": origin,
                    "destination_point_id": destination,
                    "method": "latest_complete_current_facility_prices",
                    "total_usd": "1.00",
                    "components": [
                        {"facility": facility}
                        for facility in (
                            "greenway",
                            "dtr",
                            "dtr",
                            "i95_i495",
                            "i95_i495",
                        )
                    ],
                }
            return {
                "status": expected["northbound_status"],
                "reason": {"code": expected["northbound_reason"]},
                "i95_evidence": {
                    "availability": expected["availability"],
                    "northbound_link_status": expected["northbound_link_status"],
                    "southbound_link_status": expected["southbound_link_status"],
                },
                "point_ids": [
                    "greenway:1:entry:EB",
                    "greenway:28:exit:EB",
                    "dtr:28:entry:EB",
                    "dtr:1819:exit:EB",
                    "i495:182SO",
                    "i95:2239ND",
                    "airport_dca",
                ],
                "connection_ids": [
                    "source:greenway:EB:1:28",
                    "greenway_to_dtr",
                    "source:dtr:EB:28:1819",
                    "dulles_toll_road_to_i495",
                    "source:i95_shared:Southbound:182SO:2239ND",
                    "i95_north_to_dca_from_i495_south",
                ],
                "connection_types": [
                    "within_facility",
                    "toll_handoff",
                    "within_facility",
                    "toll_handoff",
                    "general_purpose_gap",
                    "airport_access",
                ],
                "general_purpose_gaps": [
                    {
                        "connection_id": "source:i95_shared:Southbound:182SO:2239ND",
                        "boundary_point_id": "i495:192SD",
                        "role": "suffix",
                        "i95_direction": "NB",
                        "fallback_required": window_id != "i95_northbound",
                    }
                ],
            }
        raise AssertionError(tool_use_id)

    monkeypatch.setattr(timed_checks, "_validate", validate)

    def pricing_result(tool_use: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": "success",
            "content": [
                {
                    "json": {
                        "origin_point_id": tool_use["input"]["origin_point_id"],
                        "destination_point_id": tool_use["input"][
                            "destination_point_id"
                        ],
                        "source_kind": "schedule_derived",
                        "total_usd": "5.80",
                        "components": [
                            {
                                "facility": "greenway",
                                "price_usd": "5.80",
                                "rate_period": "peak",
                                "published_schedule": {"rate_name": "mainline_plaza"},
                            }
                        ],
                    }
                }
            ],
        }

    monkeypatch.setattr(timed_checks, "_run_pricing_tool", pricing_result)
    for window_id in timed_checks.WINDOW_IDS:
        result = timed_checks.run_route_checks(window_id)
        assert result["window_id"] == window_id


def test_annual_checks_cover_fixed_and_dynamic_cases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(timed_checks, "_configure_rds_endpoint", lambda: None)
    expected_facilities_by_case = {
        "annual-ballpark-springfield-pentagon": ["i95_i495"],
        "annual-ballpark-springfield-westpark-backlick": ["i95_i495"],
        "annual-ballpark-leesburg-washington": ["greenway", "dtr", "i66"],
    }

    def payload(data: dict[str, Any], tool_use_id: str) -> dict[str, Any]:
        annual_days = int(data["planned_annual_commute_days"])
        if tool_use_id == "annual-ballpark-fixed":
            daily = "11.60"
            fixed_scenarios = {
                name: {
                    "daily_toll_usd": daily,
                    "annual_toll_usd": f"{Decimal(daily) * annual_days:.2f}",
                    "annual_total_tolled_commute_cost_usd": f"{Decimal(daily) * annual_days + Decimal('10.00'):.2f}",
                }
                for name in ("p25", "p50", "p90")
            }
            return {
                "method": "recent_complete_same_date_round_trips",
                "sample_status": "complete",
                "coverage": {
                    "eligible_date_count": 12,
                    "complete_pair_count": 12,
                    "coverage_percent": "100.0",
                },
                "uses_current_fixed_rates": True,
                "income": {"estimated_after_tax_usd": "80000.00"},
                "assumptions": {"scope": "tolled_portions_only"},
                "scenarios": fixed_scenarios,
                "vehicle_cost": {"annual_usd": "10.00"},
                "facilities": [{"facility": "greenway"}],
            }
        complete = 4
        dynamic_scenarios = {
            name: {
                "daily_toll_usd": daily,
                "annual_toll_usd": f"{Decimal(daily) * annual_days:.2f}",
            }
            for name, daily in (
                ("p25", "10.00"),
                ("p50", "11.00"),
                ("p90", "12.00"),
            )
        }
        if tool_use_id == "annual-ballpark-leesburg-washington":
            facilities = [
                {
                    "facility": "greenway",
                    "sample_count": complete,
                    "scenarios": {
                        name: {
                            "daily_toll_usd": "11.60",
                            "annual_toll_usd": f"{Decimal('11.60') * annual_days:.2f}",
                        }
                        for name in ("p25", "p50", "p90")
                    },
                },
                {
                    "facility": "dtr",
                    "sample_count": complete,
                    "scenarios": {
                        name: {
                            "daily_toll_usd": "12.00",
                            "annual_toll_usd": f"{Decimal('12.00') * annual_days:.2f}",
                        }
                        for name in ("p25", "p50", "p90")
                    },
                },
                {
                    "facility": "i66",
                    "sample_count": complete,
                    "scenarios": dynamic_scenarios,
                },
            ]
        else:
            facilities = [
                {
                    "facility": facility,
                    "sample_count": complete,
                    "scenarios": dynamic_scenarios,
                }
                for facility in expected_facilities_by_case[tool_use_id]
            ]
        return {
            "coverage": {
                "eligible_date_count": complete,
                "complete_pair_count": complete,
            },
            "scenarios": dynamic_scenarios,
            "facilities": facilities,
        }

    monkeypatch.setattr(timed_checks, "_run", payload)

    def raw_scenarios(
        response: dict[str, Any], *_args: object
    ) -> dict[str, dict[str, str]]:
        return cast(dict[str, dict[str, str]], response["scenarios"])

    monkeypatch.setattr(timed_checks, "_raw_scenarios", raw_scenarios)
    result = timed_checks.run_annual_checks()
    assert result["cases"] == 4
