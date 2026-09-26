"""Published Greenway and DTR schedule contracts."""

import json
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import cast
from zoneinfo import ZoneInfo

import pytest

from agent_tools import current_price_domain as pricing_tool
from tests.current_price_support import (
    dtr_handoff_leg,
    dtr_leg,
    greenway_leg,
)

type FixtureValue = JSON | datetime | Decimal

type JSON = str | int | float | bool | list[JSON] | dict[str, JSON] | None


_EASTERN = ZoneInfo("America/New_York")


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
    direction: str,
    entry: str,
    exit_: str,
    evaluated_at: datetime,
    price: str,
    period: str,
    rate_name: str,
) -> None:
    component = pricing_tool.price_greenway_leg(
        greenway_leg(direction=direction, entry=entry, exit_=exit_), evaluated_at
    )

    assert component.price_usd == Decimal(price)
    assert component.rate_period == period
    assert component.published_schedule.rate_name == rate_name
    assert component.component_evaluated_at.tzinfo == _EASTERN


def _callback_4(data: dict[str, FixtureValue]) -> object:
    return data.update({"connection_ids": ["source:greenway:EB:1:8"]})


def _callback_5(data: dict[str, FixtureValue]) -> object:
    return data.update({"point_ids": ["greenway:1:entry:EB", "greenway:8:exit:EB"]})


def _strict_callback_6(data: dict[str, FixtureValue]) -> object:
    return cast(dict[str, JSON], data["pricing_key"]).update({"charge_index": 2})


def _strict_callback_7(data: dict[str, FixtureValue]) -> object:
    return cast(dict[str, JSON], data["pricing_key"]).update(
        {"source_route_key": "bad-key"}
    )


@pytest.mark.parametrize(
    "mutation",
    [
        _strict_callback_6,
        _callback_4,
        _callback_5,
        _strict_callback_7,
    ],
)
def test_greenway_pricer_rejects_misaligned_legs(
    mutation: Callable[[dict[str, FixtureValue]], object],
) -> None:
    data = greenway_leg().model_dump(mode="python")
    mutation(data)
    leg = pricing_tool.route_validation._GreenwayFacilityLeg.model_validate(data)

    with pytest.raises(ValueError, match="Greenway"):
        pricing_tool.price_greenway_leg(
            leg, datetime(2026, 8, 17, 8, 0, tzinfo=_EASTERN)
        )


def test_greenway_pricer_requires_aware_evaluation_time() -> None:
    with pytest.raises(ValueError, match="aware"):
        pricing_tool.price_greenway_leg(
            greenway_leg(),
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
def test_dtr_schedule_rates(
    direction: str,
    entry: str,
    exit_: str,
    charge_index: int,
    price: str,
    rate_name: str,
) -> None:
    component = pricing_tool.price_dtr_leg(
        dtr_leg(
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


def test_dtr_pricer_matches_every_canonical_source_charge() -> None:
    source = json.loads(
        (
            Path(__file__).parents[1] / "oracle" / "sources" / "dulles_toll_road.json"
        ).read_text()
    )

    checked = 0
    for pair in source["pairs"]:
        for charge_index, charge in enumerate(pair["charges"], 1):
            component = pricing_tool.price_dtr_leg(
                dtr_leg(
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
def test_dtr_handoff_is_a_ramp_charge(route_key: str) -> None:
    component = pricing_tool.price_dtr_leg(
        dtr_handoff_leg(route_key, "step-1"),
        datetime(2026, 8, 17, 12, tzinfo=_EASTERN),
    )

    assert component.price_usd == Decimal("2.00")
    assert component.published_schedule.rate_name == "ramp"


def _callback_6(data: dict[str, FixtureValue]) -> object:
    return data.update({"connection_ids": ["source:dtr:EB:10:17"]})


def _callback_7(data: dict[str, FixtureValue]) -> object:
    return data.update({"point_ids": ["dtr:10:entry:EB", "dtr:17:exit:EB"]})


def _callback_8(data: dict[str, FixtureValue]) -> object:
    return cast(dict[str, JSON], data["pricing_key"]).update(
        {"source_route_key": "WB:10:16"}
    )


def _strict_callback_8(data: dict[str, FixtureValue]) -> object:
    return cast(dict[str, JSON], data["pricing_key"]).update({"charge_index": 4})


@pytest.mark.parametrize(
    "mutation",
    [
        _strict_callback_8,
        _callback_6,
        _callback_7,
        _callback_8,
    ],
)
def test_dtr_pricer_rejects_misaligned_legs(
    mutation: Callable[[dict[str, FixtureValue]], object],
) -> None:
    data = dtr_leg().model_dump(mode="python")
    mutation(data)
    leg = pricing_tool.route_validation._DtrFacilityLeg.model_validate(data)

    with pytest.raises(ValueError, match="DTR"):
        pricing_tool.price_dtr_leg(leg, datetime(2026, 8, 17, 8, 0, tzinfo=_EASTERN))


def test_dtr_pricer_requires_aware_evaluation_time() -> None:
    with pytest.raises(ValueError, match="aware"):
        pricing_tool.price_dtr_leg(
            dtr_leg(),
            datetime(2026, 8, 17, 8),  # noqa: DTZ001
        )
