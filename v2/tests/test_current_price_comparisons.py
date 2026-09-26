"""Current-price comparison and provenance contracts."""

from collections.abc import Callable
from datetime import datetime, timedelta
from decimal import Decimal
from typing import cast
from zoneinfo import ZoneInfo

import pytest

from agent_tools import current_price_domain as pricing_tool
from tests.current_price_support import (
    i66_leg,
    i66_rows,
    i95_leg,
    i95_rows,
)

type FixtureValue = JSON | datetime | Decimal

type JSON = str | int | float | bool | list[JSON] | dict[str, JSON] | None


_EASTERN = ZoneInfo("America/New_York")


def _i66_schedule_rows() -> list[pricing_tool._I66ComparisonRow]:
    evaluated_at = datetime(2026, 8, 13, 12, 0, tzinfo=_EASTERN)
    return [
        pricing_tool._I66ComparisonRow.model_validate(
            {
                "evaluated_at": evaluated_at,
                "comparison_kind": comparison_kind,
                "comparison_offset": comparison_offset,
                "bin_start_at": bin_start,
                "bin_end_at": bin_start + timedelta(minutes=6),
                "interval_end_at": None,
                "observed_at": None,
                "price_usd": Decimal("0.00"),
                "available": True,
                "availability_reason": None,
                "source_kind": "schedule_derived",
                "pricing_method": "published_schedule",
            }
        )
        for comparison_kind, comparison_offset, bin_start in (
            ("current", 0, evaluated_at),
            ("prior_cycle", 1, evaluated_at - timedelta(minutes=6)),
            ("prior_cycle", 2, evaluated_at - timedelta(minutes=12)),
            ("prior_week", 1, evaluated_at - timedelta(days=7)),
            ("prior_week", 2, evaluated_at - timedelta(days=14)),
            ("prior_week", 3, evaluated_at - timedelta(days=21)),
        )
    ]


def test_i66_pricer_returns_current_price_and_comparisons() -> None:
    component = pricing_tool._build_i66_component(i66_leg(), i66_rows())

    assert isinstance(component, pricing_tool._I66ObservedComponent)
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


def test_i66_pricer_returns_schedule_derived_zero() -> None:
    component = pricing_tool._build_i66_component(i66_leg(), _i66_schedule_rows())

    assert isinstance(component, pricing_tool._I66ScheduleComponent)
    assert component.price_usd == Decimal("0.00")
    assert component.source_kind == "schedule_derived"
    assert component.pricing_method == "published_schedule"
    assert component.rate_period == "off_peak"
    assert component.published_schedule.schedule_id == (
        "vdot_i66_inside_beltway_2026-08-10"
    )
    assert "observed_at" not in component.model_dump(mode="json")


@pytest.mark.parametrize(
    ("source_kind", "pricing_method", "od_pair_id", "proxy_od_pair_id"),
    [
        ("observed", "source_observation", 1261, None),
        ("modeled", "identity_proxy_v1", 1374, 1146),
    ],
)
def test_i95_pricer_returns_current_price_comparisons_and_provenance(
    source_kind: str, pricing_method: str, od_pair_id: int, proxy_od_pair_id: int | None
) -> None:
    leg = (
        i95_leg()
        if source_kind == "observed"
        else i95_leg(
            entry="191NO",
            exit_="201ND",
            od_pair_id=1374,
            point_ids=["i495:192NO", "i95:201ND"],
        )
    )
    component = pricing_tool._build_i95_i495_component(
        leg, i95_rows(source_kind=source_kind)
    )

    assert isinstance(component, pricing_tool._I95Component)
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


def _callback_9(row: dict[str, FixtureValue]) -> object:
    return row.update({"price_usd": Decimal("-0.01")})


def _callback_10(row: dict[str, FixtureValue]) -> object:
    return row.update(
        {"observed_at": cast(datetime, row["evaluated_at"]) + timedelta(minutes=1)}
    )


def _callback_11(row: dict[str, FixtureValue]) -> object:
    return row.update(
        {"bin_end_at": cast(datetime, row["bin_end_at"]) + timedelta(minutes=1)}
    )


def _callback_12(row: dict[str, FixtureValue]) -> object:
    return row.update({"source_status": None})


def _strict_callback_11(row: dict[str, FixtureValue]) -> object:
    return row.update({"comparison_offset": 1})


def _strict_callback_12(row: dict[str, FixtureValue]) -> object:
    return row.update({"proxy_od_pair_id": 1146})


@pytest.mark.parametrize(
    "mutation",
    [
        _strict_callback_11,
        _callback_9,
        _callback_10,
        _callback_11,
        _strict_callback_12,
        _callback_12,
    ],
)
def test_i95_comparison_row_rejects_invalid_database_data(
    mutation: Callable[[dict[str, FixtureValue]], object],
) -> None:
    row = i95_rows()[0].model_dump(mode="python")
    mutation(row)

    with pytest.raises(ValueError):
        pricing_tool._I95ComparisonRow.model_validate(row)


def _callback_13(rows: list[dict[str, FixtureValue]]) -> object:
    return rows.append(dict(rows[0]))


def _callback_14(rows: list[dict[str, FixtureValue]]) -> object:
    return rows[1].update(
        {
            "source_kind": "modeled",
            "pricing_method": "identity_proxy_v1",
            "proxy_od_pair_id": 1146,
        }
    )


def _strict_callback_14(rows: list[dict[str, FixtureValue]]) -> object:
    return rows[0].update({"od_pair_id": 9999})


@pytest.mark.parametrize(
    "mutation",
    [
        _strict_callback_14,
        _callback_13,
        _callback_14,
    ],
)
def test_i95_fetch_rejects_misaligned_row_sets(
    monkeypatch: pytest.MonkeyPatch,
    mutation: Callable[[list[dict[str, FixtureValue]]], object],
) -> None:
    rows = [row.model_dump(mode="python") for row in i95_rows()]
    mutation(rows)

    def _strict_callback_13(*_args: object) -> object:
        return rows

    monkeypatch.setattr(pricing_tool, "_fetch_pricing_rows", _strict_callback_13)

    with pytest.raises(ValueError, match="I-95/I-495"):
        pricing_tool._fetch_i95_i495_comparisons(1261)


@pytest.mark.parametrize(
    "reason",
    [
        "missing_observation",
        "stale_observation",
        "facility_unavailable",
        "exceptional_i95_schedule",
    ],
)
def test_i95_pricer_preserves_unavailable_diagnostic(reason: str) -> None:
    result = pricing_tool._build_i95_i495_component(
        i95_leg(), i95_rows(unavailable_reason=reason)
    )

    assert isinstance(result, pricing_tool._UnavailableComponent)
    assert result.reason == reason
    assert result.source_status == {
        "missing_observation": None,
        "exceptional_i95_schedule": "CLOSED",
    }.get(reason, "NORTHBOUND_OPEN")
    assert "price_usd" not in result.model_dump()


def _callback_15(data: dict[str, FixtureValue]) -> object:
    return data.update({"connection_ids": ["source:i95_shared:Northbound:203NO:224ND"]})


def _callback_16(data: dict[str, FixtureValue]) -> object:
    return cast(dict[str, JSON], data["pricing_key"]).update(
        {"source_route_key": "bad-key"}
    )


def _strict_callback_15(data: dict[str, FixtureValue]) -> object:
    return data.update({"point_ids": ["i95:204NO", "i95:223ND"]})


@pytest.mark.parametrize(
    "mutation",
    [
        _callback_15,
        _strict_callback_15,
        _callback_16,
    ],
)
def test_i95_pricer_rejects_misaligned_leg(
    mutation: Callable[[dict[str, FixtureValue]], object],
) -> None:
    data = i95_leg().model_dump(mode="python")
    mutation(data)
    leg = pricing_tool.route_validation._I95FacilityLeg.model_validate(data)
    with pytest.raises(ValueError, match="I-95/I-495"):
        pricing_tool._build_i95_i495_component(leg, i95_rows())


def test_i66_pricer_omits_incomplete_history() -> None:
    component = pricing_tool._build_i66_component(i66_leg(), i66_rows()[:1])

    assert isinstance(component, pricing_tool._I66ObservedComponent)
    assert component.recent_movement is None
    assert component.prior_week_comparison is None


def test_prior_week_expectation_excludes_nonexistent_spring_forward_bin() -> None:
    assert (
        pricing_tool._count_valid_prior_week_bins(
            datetime(2026, 3, 22, 2, 0, tzinfo=_EASTERN)
        )
        == 2
    )


def _callback_17(row: dict[str, FixtureValue]) -> object:
    # A naive timestamp is the invalid fixture this test must reject.
    return row.update({"evaluated_at": datetime(2026, 8, 13, 8, 32)})  # noqa: DTZ001


def _callback_18(row: dict[str, FixtureValue]) -> object:
    return row.update(
        {"observed_at": cast(datetime, row["evaluated_at"]) + timedelta(minutes=1)}
    )


def _callback_19(row: dict[str, FixtureValue]) -> object:
    return row.update(
        {"available": False, "availability_reason": "missing_observation"}
    )


def _strict_callback_29(row: dict[str, FixtureValue]) -> object:
    return row.update({"comparison_offset": 1})


@pytest.mark.parametrize(
    "mutation",
    [
        _strict_callback_29,
        _callback_17,
        _callback_18,
        _callback_19,
    ],
)
def test_i66_comparison_row_rejects_invalid_database_data(
    mutation: Callable[[dict[str, FixtureValue]], object],
) -> None:
    row = i66_rows()[0].model_dump(mode="python")
    mutation(row)

    with pytest.raises(ValueError):
        pricing_tool._I66ComparisonRow.model_validate(row)


@pytest.mark.parametrize("reason", ["missing_observation", "stale_observation"])
def test_i66_pricer_preserves_unavailable_diagnostic(reason: str) -> None:
    result = pricing_tool._build_i66_component(
        i66_leg(), i66_rows(unavailable_reason=reason)
    )

    assert isinstance(result, pricing_tool._UnavailableComponent)
    assert result.reason == reason
    assert "price_usd" not in result.model_dump()


def _callback_20(data: dict[str, FixtureValue]) -> object:
    return data.update({"point_ids": ["i66:7:entry:EB", "i66:10:exit:EB"]})


def _callback_21(data: dict[str, FixtureValue]) -> object:
    return cast(dict[str, JSON], data["pricing_key"]).update(
        {"source_route_key": "bad-key"}
    )


def _strict_callback_30(data: dict[str, FixtureValue]) -> object:
    return data.update({"connection_ids": ["source:i66:EB:7:10"]})


@pytest.mark.parametrize(
    "mutation",
    [
        _strict_callback_30,
        _callback_20,
        _callback_21,
    ],
)
def test_i66_pricer_rejects_misaligned_leg(
    mutation: Callable[[dict[str, FixtureValue]], object],
) -> None:
    data = i66_leg().model_dump(mode="python")
    mutation(data)
    leg = pricing_tool.route_validation._I66FacilityLeg.model_validate(data)
    with pytest.raises(ValueError, match="I-66"):
        pricing_tool._build_i66_component(leg, i66_rows())
