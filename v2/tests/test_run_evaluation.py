"""Offline fixtures and pass/fail branches for the pricing evaluators."""

import json
from datetime import date
from typing import Any, cast

from eval.run_evaluation import (
    JSON,
    _i66_holidays,  # pyright: ignore[reportPrivateUsage]
    _movement_value_is_reported,  # pyright: ignore[reportPrivateUsage]
    evaluate_annual_alternatives,
    evaluate_annual_confirmation,
    evaluate_annual_day_estimate,
    evaluate_annual_income_clarification,
    evaluate_annual_missing_inputs,
    evaluate_annual_relaxed,
    evaluate_annual_route_unavailable,
    evaluate_annual_turn,
    evaluate_current_clarification_turns,
    evaluate_dca_pentagon_parity_turns,
    evaluate_fallback_turns,
    evaluate_i66_schedule_turn,
    evaluate_unavailable_turn,
    evaluate_westpark_turn,
    load_cases,
    load_rows,
)


def _current_example() -> tuple[dict[str, Any], dict[str, Any], str]:
    rows = load_rows()
    metadata = rows[1]
    success = {
        "name": "get_current_toll_price",
        "input": metadata["expected_call"],
        "tool_result": {
            "origin_point_id": "i95:206NO",
            "destination_point_id": "i495:185ND",
            "source_kind": "observed",
            "total_usd": "16.40",
            "components": [
                {
                    "route_step_id": "step-1",
                    "facility": "i95_i495",
                    "source_kind": "observed",
                    "price_usd": "4.80",
                    "source_status": "SOUTHBOUND_OPEN",
                    "observed_at": "2026-08-22T10:50:00-04:00",
                    "recent_movement": {
                        "direction": "unchanged",
                        "net_change_usd": "0.00",
                        "net_change_percent": "0.0",
                    },
                    "prior_week_comparison": {
                        "median_usd": "4.80",
                        "minimum_usd": "4.80",
                        "maximum_usd": "4.80",
                        "current_delta_usd": "0.00",
                    },
                },
                {
                    "route_step_id": "step-2",
                    "facility": "i95_i495",
                    "source_kind": "observed",
                    "price_usd": "11.60",
                    "source_status": "NO_DETERMINATION",
                    "observed_at": "2026-08-22T10:50:00-04:00",
                    "recent_movement": {
                        "direction": "mixed",
                        "net_change_usd": "0.35",
                        "net_change_percent": "3.1",
                    },
                    "prior_week_comparison": {
                        "median_usd": "12.05",
                        "minimum_usd": "11.25",
                        "maximum_usd": "12.30",
                        "current_delta_usd": "-0.45",
                    },
                },
            ],
        },
        "is_error": False,
    }
    good_response = (
        "### 🚗 Current toll\n\n**Estimate: $16.40** at 9:30 AM EDT.\n\n"
        "**Provenance:** Observed pricing.\n\n"
        "- ➡️ unchanged: $0.00 (0.0%)\n"
        "- 🔄 mixed: $0.35 (3.1%)\n"
        "- ✅ At the recent median of $4.80; range $4.80-$4.80\n"
        "- 🎉 You're getting a deal — below the recent median of $12.05; "
        "range $11.25-$12.30"
    )
    return metadata, success, good_response


def _annual_example() -> tuple[dict[str, Any], dict[str, JSON], str]:
    rows = load_rows()
    annual = rows[4]
    annual_call: dict[str, JSON] = {
        "name": "get_annual_toll_ballpark",
        "input": annual["expected_call"],
        "tool_result": {
            "coverage": {
                "eligible_date_count": 12,
                "complete_pair_count": 12,
                "coverage_percent": "100.0",
            },
            "sample_status": "complete",
            "income": {
                "gross_annual_usd": "120000.00",
                "estimated_after_tax_usd": "80000.00",
            },
            "vehicle_cost": {"annual_usd": "1885.12"},
            "scenarios": {
                name: {
                    "daily_toll_usd": daily_toll,
                    "daily_total_tolled_commute_cost_usd": daily,
                    "average_monthly_tolled_commute_cost_usd": monthly,
                    "annual_total_tolled_commute_cost_usd": annual_total,
                    "estimated_annual_income_after_tax_and_tolled_commute_usd": remaining,
                    "annual_toll_usd": annual_toll,
                    "additional_gross_income_to_offset_usd": offset,
                }
                for name, daily_toll, daily, monthly, annual_total, remaining, annual_toll, offset in (
                    (
                        "p25",
                        "15.63",
                        "23.00",
                        "460.00",
                        "5520.00",
                        "74480.00",
                        "3634.88",
                        "8280.00",
                    ),
                    (
                        "p50",
                        "16.63",
                        "24.00",
                        "480.00",
                        "5760.00",
                        "74240.00",
                        "3874.88",
                        "8640.00",
                    ),
                    (
                        "p90",
                        "17.63",
                        "25.00",
                        "500.00",
                        "6000.00",
                        "74000.00",
                        "4114.88",
                        "9000.00",
                    ),
                )
            },
        },
        "is_error": False,
    }
    annual_response = (
        "### 💼 Annual commute impact\n\n"
        "**P50 leaves $74240.00 after assumed tax and tolled commuting.**\n\n"
        "- 🧾 Gross income: $120000.00; after one-third tax: $80000.00\n"
        "- 🚗 Tolled-segment vehicle cost: $1885.12\n"
        "- 🛣️ Annualized daily-P50 toll scenario: $16.63 daily; $3874.88 annual\n"
        "- 💵 Total annual tolled-commute cost under P50: $5760.00\n"
        "- 🎯 Additional gross salary needed: $8640.00\n\n"
        "| Scenario | Daily | Monthly | Annual | Remaining |\n"
        "|---|---:|---:|---:|---:|\n"
        "| P25 | $23.00 | $460.00 | $5520.00 | $74480.00 |\n"
        "| P50 | $24.00 | $480.00 | $5760.00 | $74240.00 |\n"
        "| P90 | $25.00 | $500.00 | $6000.00 | $74000.00 |\n\n"
        "⚠️ Historical coverage; tolled straight-line portions only at $0.685/mile "
        "as a fixed TollChat vehicle-cost assumption."
    )
    return annual, annual_call, annual_response


def no_complete_result() -> dict[str, Any]:
    return {
        "error": "ballpark_unavailable",
        "reason": "no_complete_paired_days",
        "coverage": {"complete_pair_count": 0},
        "income": {
            "gross_annual_usd": "120000.00",
            "estimated_tax_usd": "40000.00",
            "estimated_after_tax_usd": "80000.00",
        },
        "vehicle_cost": {"daily_usd": "7.85", "annual_usd": "1885.12"},
        "assumptions": {"vehicle_cost_per_mile_usd": "0.685"},
    }


def no_complete_call(expected_call: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": "get_annual_toll_ballpark",
        "input": expected_call,
        "tool_result": no_complete_result(),
        "is_error": False,
    }


def test_movement_value_sign() -> None:
    assert _movement_value_is_reported("down $0.50", "-0.50")
    assert _movement_value_is_reported("\u2212$0.50", "-0.50")
    assert not _movement_value_is_reported("$0.50", "-0.50")


def test_case_selection() -> None:
    rows = load_rows()
    assert [row["id"] for row in rows] == [
        "reagan-airport-pentagon-eads-westpark-parity",
        "springfield-franconia-to-westpark",
        "dulles-airport-to-backlick-tp1sb-fallback",
        "old-keene-mill-to-reagan-i95-unavailable",
        "leesburg-route-28-job-offer",
        "springfield-franconia-tysons-job-offer",
        "leesburg-route-28-missing-schedule",
        "leesburg-route-28-salary-range",
        "dulles-to-reagan-annual-route-unavailable",
        "leesburg-route-28-confirm-annual-days",
        "dulles-to-reagan-current-price",
        "i66-west-to-route-7-current-price",
        "route-7-to-i495-south-current-price",
        "leesburg-to-washington-i395-current-price",
        "leesburg-to-washington-i395-job-offer",
        "annual-independent-ramps",
        "annual-backlick-alternatives",
        "annual-backlick-alternative-selection",
        "annual-divergent-areas-confirmation",
        "annual-ordinary-reversal-regression",
    ]
    assert [case.name for case in load_cases(window="i95_northbound")] == [
        "springfield-franconia-to-westpark",
        "dulles-airport-to-backlick-tp1sb-fallback",
        "dulles-to-reagan-current-price",
        "annual-independent-ramps",
        "annual-backlick-alternatives",
        "annual-backlick-alternative-selection",
        "annual-divergent-areas-confirmation",
        "annual-ordinary-reversal-regression",
    ]
    assert [case.name for case in load_cases(window="i95_northbound", weekday=6)] == [
        "dulles-airport-to-backlick-tp1sb-fallback",
        "dulles-to-reagan-current-price",
        "annual-independent-ramps",
        "annual-backlick-alternatives",
        "annual-backlick-alternative-selection",
        "annual-divergent-areas-confirmation",
        "annual-ordinary-reversal-regression",
    ]
    assert [case.name for case in load_cases(window="i95_reversal")] == [
        "dulles-airport-to-backlick-tp1sb-fallback",
        "old-keene-mill-to-reagan-i95-unavailable",
        "annual-independent-ramps",
        "annual-backlick-alternatives",
        "annual-backlick-alternative-selection",
        "annual-divergent-areas-confirmation",
        "annual-ordinary-reversal-regression",
    ]
    assert [case.name for case in load_cases(window="i95_southbound")] == [
        "reagan-airport-pentagon-eads-westpark-parity",
        "old-keene-mill-to-reagan-i95-unavailable",
        "i66-west-to-route-7-current-price",
        "route-7-to-i495-south-current-price",
        "leesburg-to-washington-i395-current-price",
        "annual-independent-ramps",
        "annual-backlick-alternatives",
        "annual-backlick-alternative-selection",
        "annual-divergent-areas-confirmation",
        "annual-ordinary-reversal-regression",
    ]
    assert [case.name for case in load_cases(window="greenway_eb_peak")] == [
        "i66-west-to-route-7-current-price",
        "route-7-to-i495-south-current-price",
    ]

    new_case_ids = {
        "annual-independent-ramps",
        "annual-backlick-alternatives",
        "annual-backlick-alternative-selection",
        "annual-divergent-areas-confirmation",
        "annual-ordinary-reversal-regression",
    }
    for window in ("i95_northbound", "i95_southbound", "i95_reversal"):
        selected_ids = {case.name for case in load_cases(window=window)}
        assert new_case_ids <= selected_ids


def test_i66_schedule() -> None:
    rows = load_rows()
    assert date(2026, 7, 3) in _i66_holidays(2026)
    assert date(2026, 7, 5) not in _i66_holidays(2026)
    assert date(2027, 7, 5) in _i66_holidays(2027)
    i66_free = rows[11]
    i66_free_call = {
        "name": "get_current_toll_price",
        "input": i66_free["expected_call"],
        "tool_result": {
            "origin_point_id": "i66:1:entry:EB",
            "destination_point_id": "i66:4:exit:EB",
            "source_kind": "schedule_derived",
            "total_usd": "0.00",
            "components": [
                {
                    "facility": "i66",
                    "component_evaluated_at": "2026-08-18T14:17:00-04:00",
                    "price_usd": "0.00",
                    "source_kind": "schedule_derived",
                    "pricing_method": "published_schedule",
                }
            ],
        },
    }
    i66_free_metadata = {**i66_free, "active_window": "i95_southbound"}
    assert evaluate_i66_schedule_turn(
        [i66_free_call],
        "**$0.00 estimate** ✅ Schedule-derived pricing applies.",
        i66_free_metadata,
    )[0].test_pass
    assert (
        evaluate_i66_schedule_turn(
            [i66_free_call],
            "**Price unavailable** ⚠️ There is no data.",
            i66_free_metadata,
        )[0].label
        == "bad_free_response"
    )
    i66_active_call = json.loads(json.dumps(i66_free_call))
    i66_active_call["tool_result"].update(source_kind="observed", total_usd="3.25")
    i66_active_call["tool_result"]["components"][0].update(
        component_evaluated_at="2026-08-18T07:23:00-04:00",
        observed_at="2026-08-18T07:22:00-04:00",
        price_usd="3.25",
        source_kind="observed",
        pricing_method="source_observation",
    )
    assert evaluate_i66_schedule_turn(
        [i66_active_call],
        "**$3.25 estimate** ✅ Observed pricing at 7:22 AM EDT.",
        {**i66_free, "active_window": "greenway_eb_peak"},
    )[0].test_pass
    i66_active_zero = json.loads(json.dumps(i66_active_call))
    i66_active_zero["tool_result"]["total_usd"] = "0.00"
    i66_active_zero["tool_result"]["components"][0]["price_usd"] = "0.00"
    assert (
        evaluate_i66_schedule_turn(
            [i66_active_zero],
            "**$0.00 estimate** ✅ Observed pricing at 7:22 AM EDT.",
            i66_free,
        )[0].label
        == "state_mismatch"
    )
    i66_free_observed = json.loads(json.dumps(i66_active_call))
    i66_free_observed["tool_result"]["components"][0]["component_evaluated_at"] = (
        "2026-08-18T14:17:00-04:00"
    )
    assert (
        evaluate_i66_schedule_turn(
            [i66_free_observed],
            "**$3.25 estimate** ✅ Observed pricing at 7:22 AM EDT.",
            i66_free,
        )[0].label
        == "state_mismatch"
    )
    wb_active = rows[12]
    i66_wb_active = json.loads(json.dumps(i66_active_call))
    i66_wb_active["input"] = wb_active["expected_call"]
    i66_wb_active["tool_result"].update(
        origin_point_id="i66:4:entry:WB",
        destination_point_id="i66:5:exit:WB",
    )
    i66_wb_active["tool_result"]["components"][0].update(
        component_evaluated_at="2026-08-18T17:23:00-04:00",
        observed_at="2026-08-18T17:22:00-04:00",
    )
    assert evaluate_i66_schedule_turn(
        [i66_wb_active],
        "**$3.25 estimate** ✅ Observed pricing at 5:22 PM EDT.",
        wb_active,
    )[0].test_pass


def test_current_price_response() -> None:
    metadata, success, good_response = _current_example()
    assert evaluate_westpark_turn([success], good_response, metadata)[0].test_pass
    assert (
        evaluate_westpark_turn(
            [success],
            good_response
            + "\n\nOne component has a NO_DETERMINATION source-status qualification.",
            metadata,
        )[0].label
        == "spurious_source_status"
    )
    for qualification in ("inconclusive", "indeterminate", "unknown"):
        assert (
            evaluate_westpark_turn(
                [success],
                good_response + f"\n\nThe source status metadata is {qualification}.",
                metadata,
            )[0].label
            == "spurious_source_status"
        )
    assert (
        evaluate_westpark_turn(
            [success],
            good_response + "\n\n**Source status:**\n- unknown",
            metadata,
        )[0].label
        == "spurious_source_status"
    )
    assert (
        evaluate_westpark_turn([], good_response, metadata)[0].label == "tool_mismatch"
    )
    wrong_input = {
        **success,
        "input": {**metadata["expected_call"], "destination_point_id": "wrong"},
    }
    assert (
        evaluate_westpark_turn([wrong_input], good_response, metadata)[0].label
        == "input_mismatch"
    )
    error = {**success, "tool_result": {"error": "pricing_unavailable"}}
    assert (
        evaluate_westpark_turn([error], good_response, metadata)[0].label
        == "tool_error"
    )
    assert (
        evaluate_westpark_turn([success], "$16.40 at 9:30 AM EST", metadata)[0].label
        == "missing_markdown"
    )
    missing_provenance = good_response.replace(
        "**Provenance:** Observed pricing.\n\n", ""
    )
    assert (
        evaluate_westpark_turn([success], missing_provenance, metadata)[0].label
        == "missing_provenance"
    )
    missing_movement = good_response.replace(
        "- ➡️ unchanged: $0.00 (0.0%)\n- 🔄 mixed: $0.35 (3.1%)\n", ""
    )
    assert (
        evaluate_westpark_turn([success], missing_movement, metadata)[0].label
        == "missing_movement"
    )
    missing_comparison = good_response.replace(
        "- ✅ At the recent median of $4.80; range $4.80-$4.80\n"
        "- 🎉 You're getting a deal — below the recent median of $12.05; "
        "range $11.25-$12.30",
        "",
    )
    assert (
        evaluate_westpark_turn([success], missing_comparison, metadata)[0].label
        == "missing_comparison"
    )
    closure = {
        **success,
        "tool_result": {
            "status": "currently_unavailable",
            "point_ids": ["i95:206NO", "i495:185ND"],
        },
    }
    assert (
        evaluate_westpark_turn([closure], "### 🚧 Closed", metadata)[0].label
        == "tool_unavailable"
    )


def test_current_price_unavailable() -> None:
    rows = load_rows()
    _, success, _ = _current_example()
    unavailable_metadata = rows[10]
    unavailable = {
        **success,
        "input": unavailable_metadata["expected_call"],
        "tool_result": {
            "origin_point_id": "airport_iad",
            "destination_point_id": "airport_dca",
            "error": "pricing_unavailable",
            "reason": "incomplete_route_price",
            "unavailable_components": [{"observed_at": "2026-08-22T15:40:00-04:00"}],
        },
    }
    unavailable_response = (
        "### 🚫 Current toll unavailable\n\nThe complete price cannot be provided as "
        "of 3:40 PM EDT."
    )
    assert evaluate_westpark_turn(
        [unavailable],
        unavailable_response,
        unavailable_metadata,
    )[0].test_pass
    for invented_toll in (
        "$999.00",
        "USD 999.00",
        "999.00 USD",
        "999 dollars",
        "\uff04999.00",
        "$about 999.00",
    ):
        assert (
            evaluate_westpark_turn(
                [unavailable],
                unavailable_response + f" It would cost {invented_toll}.",
                unavailable_metadata,
            )[0].label
            == "invented_financials"
        )
    unknown = {
        **unavailable,
        "tool_result": {
            "status": "unknown_availability",
            "reason": {"code": "i95_stale_evidence"},
            "origin_point_id": "airport_iad",
            "destination_point_id": "airport_dca",
        },
    }
    assert evaluate_westpark_turn(
        [unknown],
        "### 🚧 Current toll unavailable\n\nThe I-95 evidence is stale.",
        unavailable_metadata,
    )[0].test_pass


def test_dca_pentagon_parity() -> None:
    rows = load_rows()
    _, success, good_response = _current_example()
    parity = rows[0]
    parity_calls: list[dict[str, JSON]] = []
    for expected_call in parity["expected_calls"]:
        call = json.loads(json.dumps(success))
        call["input"] = expected_call
        call["tool_result"].update(
            origin_point_id=expected_call["origin_point_id"],
            destination_point_id=expected_call["destination_point_id"],
        )
        for index, component in enumerate(call["tool_result"]["components"]):
            component.update(
                pricing_method="source_observation",
                od_pair_id=index + 1,
                proxy_od_pair_id=None,
            )
        parity_calls.append(call)
    parity_turns: list[dict[str, JSON]] = [
        {"response": good_response, "calls": [call]} for call in parity_calls
    ]
    assert evaluate_dca_pentagon_parity_turns(parity_turns, parity)[0].test_pass
    parity_observed_without_proxy = json.loads(json.dumps(parity_turns))
    for turn in parity_observed_without_proxy:
        for component in turn["calls"][0]["tool_result"]["components"]:
            component.pop("proxy_od_pair_id")
    assert evaluate_dca_pentagon_parity_turns(parity_observed_without_proxy, parity)[
        0
    ].test_pass
    parity_modeled_component = json.loads(json.dumps(parity_turns))
    modeled_component = parity_modeled_component[1]["calls"][0]["tool_result"][
        "components"
    ][0]
    modeled_component.update(
        source_kind="modeled", pricing_method="identity_proxy_v1", proxy_od_pair_id=3
    )
    parity_modeled_component[1]["response"] += "\n\nModeled pricing."
    assert (
        evaluate_dca_pentagon_parity_turns(parity_modeled_component, parity)[0].label
        == "parity_mismatch"
    )
    parity_modeled_without_proxy = json.loads(json.dumps(parity_modeled_component))
    parity_modeled_without_proxy[1]["calls"][0]["tool_result"]["components"][0].pop(
        "proxy_od_pair_id"
    )
    assert (
        evaluate_dca_pentagon_parity_turns(parity_modeled_without_proxy, parity)[
            0
        ].label
        == "malformed_projection"
    )
    assert (
        evaluate_dca_pentagon_parity_turns(parity_turns[:1], parity)[0].label
        == "turn_count"
    )
    extra_parity_call = json.loads(json.dumps(parity_turns))
    extra_parity_call[1]["calls"].append(parity_calls[1])
    assert (
        evaluate_dca_pentagon_parity_turns(extra_parity_call, parity)[0].label
        == "tool_mismatch"
    )
    wrong_parity_input = json.loads(json.dumps(parity_turns))
    wrong_parity_input[1]["calls"][0]["input"]["origin_point_id"] = "airport_dca"
    assert (
        evaluate_dca_pentagon_parity_turns(wrong_parity_input, parity)[0].label
        == "input_mismatch"
    )
    wrong_parity_result = json.loads(json.dumps(parity_turns))
    wrong_parity_result[1]["calls"][0]["tool_result"]["origin_point_id"] = "airport_dca"
    assert (
        evaluate_dca_pentagon_parity_turns(wrong_parity_result, parity)[0].label
        == "result_mismatch"
    )
    parity_tool_error = json.loads(json.dumps(parity_turns))
    parity_tool_error[1]["calls"][0]["is_error"] = True
    assert (
        evaluate_dca_pentagon_parity_turns(parity_tool_error, parity)[0].label
        == "tool_error"
    )
    parity_bad_style = json.loads(json.dumps(parity_turns))
    parity_bad_style[1]["response"] = "$16.40 at 9:30 AM EDT"
    assert (
        evaluate_dca_pentagon_parity_turns(parity_bad_style, parity)[0].label
        == "missing_markdown"
    )
    parity_total_mismatch = json.loads(json.dumps(parity_turns))
    parity_total_mismatch[1]["calls"][0]["tool_result"]["total_usd"] = "16.41"
    parity_total_mismatch[1]["calls"][0]["tool_result"]["components"][1][
        "price_usd"
    ] = "11.61"
    parity_total_mismatch[1]["response"] = parity_total_mismatch[1]["response"].replace(
        "$16.40", "$16.41"
    )
    assert (
        evaluate_dca_pentagon_parity_turns(parity_total_mismatch, parity)[0].label
        == "parity_mismatch"
    )
    for field in (
        "route_step_id",
        "price_usd",
        "od_pair_id",
    ):
        parity_component_mismatch = json.loads(json.dumps(parity_turns))
        component = parity_component_mismatch[1]["calls"][0]["tool_result"][
            "components"
        ][0]
        component[field] = (
            "4.81"
            if field == "price_usd"
            else 3
            if field in {"od_pair_id", "proxy_od_pair_id"}
            else "changed"
        )
        if field == "price_usd":
            parity_component_mismatch[1]["calls"][0]["tool_result"]["total_usd"] = (
                "16.41"
            )
            parity_component_mismatch[1]["response"] = parity_component_mismatch[1][
                "response"
            ].replace("$16.40", "$16.41")
        assert (
            evaluate_dca_pentagon_parity_turns(parity_component_mismatch, parity)[
                0
            ].label
            == "parity_mismatch"
        )
    parity_modeled_component = json.loads(json.dumps(parity_turns))
    modeled_component = parity_modeled_component[1]["calls"][0]["tool_result"][
        "components"
    ][0]
    modeled_component.update(
        source_kind="modeled", pricing_method="identity_proxy_v1", proxy_od_pair_id=3
    )
    parity_modeled_component[1]["response"] += "\n\nModeled pricing."
    assert (
        evaluate_dca_pentagon_parity_turns(parity_modeled_component, parity)[0].label
        == "parity_mismatch"
    )
    parity_advanced_time = json.loads(json.dumps(parity_turns))
    parity_advanced_time[1]["calls"][0]["tool_result"]["components"][0][
        "observed_at"
    ] = "2026-08-22T10:51:00-04:00"
    assert evaluate_dca_pentagon_parity_turns(parity_advanced_time, parity)[0].test_pass
    parity_equal_omission = json.loads(json.dumps(parity_turns))
    for turn in parity_equal_omission:
        for component in turn["calls"][0]["tool_result"]["components"]:
            component.pop("od_pair_id")
    assert (
        evaluate_dca_pentagon_parity_turns(parity_equal_omission, parity)[0].label
        == "malformed_projection"
    )
    parity_non_mapping = json.loads(json.dumps(parity_turns))
    parity_non_mapping[1]["calls"][0]["tool_result"]["components"] = [
        "not",
        "components",
    ]
    assert (
        evaluate_dca_pentagon_parity_turns(parity_non_mapping, parity)[0].label
        == "malformed_projection"
    )
    parity_non_finite = json.loads(json.dumps(parity_turns))
    parity_non_finite[1]["calls"][0]["tool_result"]["components"][0]["price_usd"] = (
        "Infinity"
    )
    assert (
        evaluate_dca_pentagon_parity_turns(parity_non_finite, parity)[0].label
        == "malformed_projection"
    )
    parity_fallback_endpoint = json.loads(json.dumps(parity_turns))
    fallback_payload = parity_fallback_endpoint[1]["calls"][0]["tool_result"]
    fallback_payload.pop("origin_point_id")
    fallback_payload["point_ids"] = ["i95:2233SO", "i495:1859ND"]
    assert (
        evaluate_dca_pentagon_parity_turns(parity_fallback_endpoint, parity)[0].label
        == "result_mismatch"
    )
    for invalid_components in cast(tuple[JSON, ...], (None, {})):
        parity_invalid_components = json.loads(json.dumps(parity_turns))
        parity_invalid_components[1]["calls"][0]["tool_result"]["components"] = (
            invalid_components
        )
        assert (
            evaluate_dca_pentagon_parity_turns(parity_invalid_components, parity)[
                0
            ].label
            == "malformed_projection"
        )
    for field in ("route_step_id", "source_kind"):
        parity_null_identity = json.loads(json.dumps(parity_turns))
        parity_null_identity[1]["calls"][0]["tool_result"]["components"][0][field] = (
            None
        )
        assert (
            evaluate_dca_pentagon_parity_turns(parity_null_identity, parity)[0].label
            == "malformed_projection"
        )
    for field in ("od_pair_id", "proxy_od_pair_id"):
        parity_bool_identifier = json.loads(json.dumps(parity_turns))
        parity_bool_identifier[1]["calls"][0]["tool_result"]["components"][0][field] = (
            True
        )
        assert (
            evaluate_dca_pentagon_parity_turns(parity_bool_identifier, parity)[0].label
            == "malformed_projection"
        )
    parity_wrong_facility = json.loads(json.dumps(parity_turns))
    parity_wrong_facility[1]["calls"][0]["tool_result"]["components"][0]["facility"] = (
        "i66"
    )
    assert (
        evaluate_dca_pentagon_parity_turns(parity_wrong_facility, parity)[0].label
        == "malformed_projection"
    )
    parity_wrong_provenance = json.loads(json.dumps(parity_turns))
    parity_wrong_provenance[1]["calls"][0]["tool_result"]["components"][0][
        "pricing_method"
    ] = "identity_proxy_v1"
    assert (
        evaluate_dca_pentagon_parity_turns(parity_wrong_provenance, parity)[0].label
        == "malformed_projection"
    )
    parity_negative_total = json.loads(json.dumps(parity_turns))
    parity_negative_total[1]["calls"][0]["tool_result"]["total_usd"] = "-1.00"
    parity_negative_total[1]["response"] = parity_negative_total[1]["response"].replace(
        "$16.40", "$-1.00"
    )
    assert (
        evaluate_dca_pentagon_parity_turns(parity_negative_total, parity)[0].label
        == "malformed_projection"
    )
    parity_negative_component = json.loads(json.dumps(parity_turns))
    parity_negative_component[1]["calls"][0]["tool_result"]["components"][0][
        "price_usd"
    ] = "-4.80"
    assert (
        evaluate_dca_pentagon_parity_turns(parity_negative_component, parity)[0].label
        == "malformed_projection"
    )
    parity_mismatched_sum = json.loads(json.dumps(parity_turns))
    parity_mismatched_sum[1]["calls"][0]["tool_result"]["total_usd"] = "16.41"
    parity_mismatched_sum[1]["response"] = parity_mismatched_sum[1]["response"].replace(
        "$16.40", "$16.41"
    )
    assert (
        evaluate_dca_pentagon_parity_turns(parity_mismatched_sum, parity)[0].label
        == "malformed_projection"
    )


def test_current_route_clarification() -> None:
    rows = load_rows()
    _, success, good_response = _current_example()
    washington_current = rows[13]
    washington_current_call = json.loads(json.dumps(success))
    washington_current_call["input"] = washington_current["expected_call"]
    washington_current_call["tool_result"].update(
        origin_point_id="greenway:1:entry:EB", destination_point_id="i95:2249ND"
    )
    washington_current_turns: list[dict[str, JSON]] = [
        {"response": "### 🛣️ Route choice\n\n**I-66 or I-395?**", "calls": []},
        {"response": good_response, "calls": [washington_current_call]},
    ]
    assert evaluate_current_clarification_turns(
        washington_current_turns, washington_current
    )[0].test_pass
    closed_current = json.loads(json.dumps(washington_current_turns))
    closed_current[1]["calls"][0]["tool_result"] = {
        "status": "currently_unavailable",
        "point_ids": ["greenway:1:entry:EB", "i95:2249ND"],
    }
    closed_current[1]["response"] = (
        "### 🚧 Current toll unavailable\n\nThe route is currently unavailable."
    )
    assert evaluate_current_clarification_turns(closed_current, washington_current)[
        0
    ].test_pass
    invented_closed_toll = json.loads(json.dumps(closed_current))
    invented_closed_toll[1]["response"] += " It would cost $999.00."
    assert (
        evaluate_current_clarification_turns(invented_closed_toll, washington_current)[
            0
        ].label
        == "invented_financials"
    )
    premature_current = json.loads(json.dumps(washington_current_turns))
    premature_current[0]["calls"] = [washington_current_call]
    assert (
        evaluate_current_clarification_turns(premature_current, washington_current)[
            0
        ].label
        == "bad_clarification"
    )
    extra_current = json.loads(json.dumps(washington_current_turns))
    extra_current[1]["calls"].append(washington_current_call)
    assert (
        evaluate_current_clarification_turns(extra_current, washington_current)[0].label
        == "tool_mismatch"
    )
    wrong_current_input = json.loads(json.dumps(washington_current_turns))
    wrong_current_input[1]["calls"][0]["input"]["destination_point_id"] = "wrong"
    assert (
        evaluate_current_clarification_turns(wrong_current_input, washington_current)[
            0
        ].label
        == "input_mismatch"
    )
    blank_current = json.loads(json.dumps(washington_current_turns))
    blank_current[1]["response"] = "  "
    assert (
        evaluate_current_clarification_turns(blank_current, washington_current)[0].label
        == "blank_response"
    )
    ungrounded_current = json.loads(json.dumps(washington_current_turns))
    ungrounded_current[1]["response"] = "### 🚗 Current toll\n\n**Estimate pending.**"
    assert (
        evaluate_current_clarification_turns(ungrounded_current, washington_current)[
            0
        ].label
        == "ungrounded_price"
    )


def test_current_route_fallback() -> None:
    rows = load_rows()
    fallback = {**rows[2], "active_window": "i95_northbound"}
    fallback_turns = [
        {
            "response": (
                "### 🛣️ End at the junction\n\nWould you like me to price the "
                "trip to the I-495 Express southbound end? The omitted I-95 "
                "general-purpose segment is not included."
            ),
            "calls": [
                {
                    "name": "get_current_toll_price",
                    "input": fallback["expected_calls"][0],
                    "tool_result": {
                        "status": "currently_unavailable",
                        "reason": {
                            "code": "i95_opposite_direction_open",
                            "details": {
                                "required_i95_directions": ["SB"],
                                "availability": "northbound",
                            },
                        },
                        "general_purpose_gaps": [
                            {
                                "connection_id": "source:i95_shared:Southbound:182SO:205SD",
                                "boundary_point_id": "i495:192SD",
                                "role": "suffix",
                                "i95_direction": "SB",
                                "fallback_required": True,
                            }
                        ],
                    },
                    "is_error": False,
                }
            ],
        },
        {
            "response": "### 🚗 Current toll\n\n**Estimate: $7.25** at 9:30 AM EST.",
            "calls": [
                {
                    "name": "get_current_toll_price",
                    "input": fallback["expected_calls"][1],
                    "tool_result": {
                        "origin_point_id": "airport_iad",
                        "destination_point_id": "i495:192SD",
                        "total_usd": "7.25",
                    },
                    "is_error": False,
                }
            ],
        },
    ]
    assert evaluate_fallback_turns(fallback_turns, fallback)[0].test_pass
    wrong_fallback_connection = json.loads(json.dumps(fallback_turns))
    wrong_fallback_connection[0]["calls"][0]["tool_result"]["general_purpose_gaps"][0][
        "connection_id"
    ] = "wrong"
    assert (
        evaluate_fallback_turns(wrong_fallback_connection, fallback)[0].label
        == "bad_route"
    )
    wrong_fallback = json.loads(json.dumps(fallback_turns))
    wrong_fallback[1]["calls"][0]["input"]["destination_point_id"] = "wrong"
    assert (
        evaluate_fallback_turns(wrong_fallback, fallback)[0].label == "input_mismatch"
    )
    extra_call = json.loads(json.dumps(fallback_turns))
    extra_call[0]["calls"].append(extra_call[0]["calls"][0])
    assert evaluate_fallback_turns(extra_call, fallback)[0].label == "tool_mismatch"
    malformed_reason = json.loads(json.dumps(fallback_turns))
    malformed_reason[0]["calls"][0]["tool_result"]["reason"]["code"] = "unknown"
    assert evaluate_fallback_turns(malformed_reason, fallback)[0].label == "bad_route"
    missing_disclosure = json.loads(json.dumps(fallback_turns))
    missing_disclosure[0]["response"] = "### 🛣️ Would you like I-495 southbound?"
    assert evaluate_fallback_turns(missing_disclosure, fallback)[0].label == "bad_offer"
    unstyled_offer = json.loads(json.dumps(fallback_turns))
    unstyled_offer[0]["response"] = (
        "Would you like me to price the trip to the I-495 Express southbound "
        "end? The omitted I-95 general-purpose segment is not included."
    )
    assert (
        evaluate_fallback_turns(unstyled_offer, fallback)[0].label == "missing_markdown"
    )
    wrong_fallback_direction = json.loads(json.dumps(fallback_turns))
    wrong_fallback_direction[0]["calls"][0]["tool_result"]["reason"]["details"][
        "required_i95_directions"
    ] = ["NB"]
    assert (
        evaluate_fallback_turns(wrong_fallback_direction, fallback)[0].label
        == "bad_route"
    )
    wrong_result_endpoints = json.loads(json.dumps(fallback_turns))
    wrong_result_endpoints[1]["calls"][0]["tool_result"]["origin_point_id"] = "wrong"
    assert (
        evaluate_fallback_turns(wrong_result_endpoints, fallback)[0].label
        == "result_mismatch"
    )


def test_current_route_unavailable() -> None:
    rows = load_rows()
    unavailable = {**rows[3], "active_window": "i95_southbound"}
    unavailable_turns = [
        {
            "response": (
                "### 🚧 I-95 unavailable\n\nThe northbound trip is unavailable "
                "because the Express Lanes are currently running southbound."
            ),
            "calls": [
                {
                    "name": "get_current_toll_price",
                    "input": unavailable["expected_call"],
                    "tool_result": {
                        "status": "currently_unavailable",
                        "point_ids": ["i95:203NO", "airport_dca"],
                        "reason": {
                            "code": "i95_opposite_direction_open",
                            "details": {
                                "required_i95_directions": ["NB"],
                                "availability": "southbound",
                            },
                        },
                        "general_purpose_gaps": [],
                    },
                    "is_error": False,
                }
            ],
        }
    ]
    assert evaluate_unavailable_turn(unavailable_turns, unavailable)[0].test_pass
    invented_offer = json.loads(json.dumps(unavailable_turns))
    invented_offer[0]["response"] += " Would you like another price?"
    assert (
        evaluate_unavailable_turn(invented_offer, unavailable)[0].label == "bad_offer"
    )
    unavailable_bad_reason = json.loads(json.dumps(unavailable_turns))
    unavailable_bad_reason[0]["calls"][0]["tool_result"]["reason"]["code"] = (
        "i95_fully_closed"
    )
    assert (
        evaluate_unavailable_turn(unavailable_bad_reason, unavailable)[0].label
        == "bad_route"
    )
    wrong_unavailable_direction = json.loads(json.dumps(unavailable_turns))
    wrong_unavailable_direction[0]["calls"][0]["tool_result"]["reason"]["details"][
        "required_i95_directions"
    ] = ["SB"]
    assert (
        evaluate_unavailable_turn(wrong_unavailable_direction, unavailable)[0].label
        == "bad_route"
    )
    wrong_unavailable_result = json.loads(json.dumps(unavailable_turns))
    wrong_unavailable_result[0]["calls"][0]["tool_result"]["point_ids"] = [
        "wrong-origin",
        "wrong-destination",
    ]
    assert (
        evaluate_unavailable_turn(wrong_unavailable_result, unavailable)[0].label
        == "result_mismatch"
    )


def test_annual_price_response() -> None:
    annual, annual_call, annual_response = _annual_example()
    annual_turns = [{"response": annual_response, "calls": [annual_call]}]
    assert evaluate_annual_turn(annual_turns, annual)[0].test_pass
    bold_scenario_labels = annual_response
    for label, description in (
        ("P25", "lower historical scenario"),
        ("P50", "middle historical scenario"),
        ("P90", "higher historical scenario"),
    ):
        bold_scenario_labels = bold_scenario_labels.replace(
            f"| {label} |", f"| **{label} — {description}** |"
        )
    assert evaluate_annual_turn(
        [{"response": bold_scenario_labels, "calls": [annual_call]}], annual
    )[0].test_pass
    swapped_scenarios = (
        annual_response.replace("| P25 |", "| TEMP |")
        .replace("| P90 |", "| P25 |")
        .replace("| TEMP |", "| P90 |")
    )
    assert (
        evaluate_annual_turn(
            [{"response": swapped_scenarios, "calls": [annual_call]}], annual
        )[0].label
        == "misbound_money"
    )
    swapped_p50_columns = annual_response.replace(
        "| P50 | $24.00 | $480.00 |", "| P50 | $480.00 | $24.00 |"
    )
    assert (
        evaluate_annual_turn(
            [{"response": swapped_p50_columns, "calls": [annual_call]}], annual
        )[0].label
        == "misbound_money"
    )
    misplaced_p50 = annual_response.replace(
        "**P50 leaves $74240.00 after assumed tax and tolled commuting.**",
        "**P50 affordability estimate after assumed tax and tolled commuting.**",
    )
    assert (
        evaluate_annual_turn(
            [{"response": misplaced_p50, "calls": [annual_call]}], annual
        )[0].label
        == "misbound_money"
    )
    implicit_coverage = annual_response.replace(
        "Historical coverage",
        "Historical evidence: 12 of 12 eligible dates; complete sample",
    )
    assert evaluate_annual_turn(
        [{"response": implicit_coverage, "calls": [annual_call]}], annual
    )[0].test_pass
    missing_table = annual_response.replace("|", "")
    missing_table_turns = [{"response": missing_table, "calls": [annual_call]}]
    assert (
        evaluate_annual_turn(missing_table_turns, annual)[0].label
        == "missing_affordability_context"
    )
    missing_method = annual_response.replace(
        "Annualized daily-P50 toll scenario", "Toll"
    )
    missing_method_turns = [{"response": missing_method, "calls": [annual_call]}]
    assert (
        evaluate_annual_turn(missing_method_turns, annual)[0].label
        == "missing_affordability_context"
    )


def test_annual_missing_paired_history() -> None:
    rows = load_rows()
    _, annual_call, _ = _annual_example()
    washington_annual = rows[14]
    washington_annual_call = json.loads(json.dumps(annual_call))
    washington_annual_call["input"] = washington_annual["expected_call"]
    washington_annual_call["tool_result"] = {
        "error": "ballpark_unavailable",
        "reason": "no_complete_paired_days",
        "coverage": {"complete_pair_count": 0},
        "income": {
            "gross_annual_usd": "120000.00",
            "estimated_tax_usd": "40000.00",
            "estimated_after_tax_usd": "80000.00",
        },
        "vehicle_cost": {"daily_usd": "7.85", "annual_usd": "1885.12"},
        "assumptions": {"vehicle_cost_per_mile_usd": "0.685"},
    }
    washington_annual_turns: list[dict[str, JSON]] = [
        {"response": "### 🛣️ Route choice\n\n**I-66 or I-395?**", "calls": []},
        {
            "response": (
                "### ⚠️ Annual estimate unavailable\n\n"
                "There are no complete paired days, so the annual estimate is unavailable."
            ),
            "calls": [washington_annual_call],
        },
    ]
    assert evaluate_annual_turn(washington_annual_turns, washington_annual)[0].test_pass
    invented_annual_money = json.loads(json.dumps(washington_annual_turns))
    invented_annual_money[1]["response"] += (
        " Your income after commuting is $999999.00."
    )
    assert (
        evaluate_annual_turn(invented_annual_money, washington_annual)[0].label
        == "invented_financials"
    )
    misbound_annual_money = json.loads(json.dumps(washington_annual_turns))
    misbound_annual_money[1]["response"] += " Income after commuting is $120000.00."
    assert (
        evaluate_annual_turn(misbound_annual_money, washington_annual)[0].label
        == "misbound_money"
    )
    for response in (
        "Estimated tax is $80000.00.",
        "After-tax income is $40000.00.",
        "Annual vehicle cost is $7.85.",
        "Daily vehicle cost is $1885.12.",
    ):
        swapped_annual_money = json.loads(json.dumps(washington_annual_turns))
        swapped_annual_money[1]["response"] += f"\n{response}"
        assert (
            evaluate_annual_turn(swapped_annual_money, washington_annual)[0].label
            == "misbound_money"
        )
    same_line_swapped_vehicle_money = json.loads(json.dumps(washington_annual_turns))
    same_line_swapped_vehicle_money[1]["response"] += (
        "\nVehicle cost: $1885.12 per day; $7.85 annually."
    )
    assert (
        evaluate_annual_turn(same_line_swapped_vehicle_money, washington_annual)[
            0
        ].label
        == "misbound_money"
    )
    for daily_context in (
        "daily",
        "per day",
        "per office day",
        "per commute day",
        "per round trip",
    ):
        grounded_annual_money = json.loads(json.dumps(washington_annual_turns))
        grounded_annual_money[1]["response"] += (
            "\nGross annual income: $120000.00."
            "\nEstimated tax: $40000.00."
            "\nAfter-tax income: $80000.00."
            f"\nVehicle cost: $7.85 {daily_context}; $1885.12 annually."
            "\nVehicle cost: $0.685 per mile."
        )
        assert evaluate_annual_turn(grounded_annual_money, washington_annual)[
            0
        ].test_pass
    after_tax_assumption = json.loads(json.dumps(washington_annual_turns))
    after_tax_assumption[1]["response"] += (
        "\nAfter the one-third tax assumption: $80000.00."
    )
    assert evaluate_annual_turn(after_tax_assumption, washington_annual)[0].test_pass
    missing_toll_not_zero = json.loads(json.dumps(washington_annual_turns))
    missing_toll_not_zero[1]["response"] += "\nDo not treat the missing toll as $0."
    assert evaluate_annual_turn(missing_toll_not_zero, washington_annual)[0].test_pass
    premature_washington_annual = json.loads(json.dumps(washington_annual_turns))
    premature_washington_annual[0]["calls"] = [washington_annual_call]
    assert (
        evaluate_annual_turn(premature_washington_annual, washington_annual)[0].label
        == "bad_clarification"
    )
    springfield_annual = json.loads(json.dumps(washington_annual_turns))
    springfield_annual[1]["calls"][0]["input"]["outbound"]["destination_point_id"] = (
        "i95:206NO"
    )
    assert (
        evaluate_annual_turn(springfield_annual, washington_annual)[0].label
        == "input_mismatch"
    )
    blank_washington_annual = json.loads(json.dumps(washington_annual_turns))
    blank_washington_annual[1]["response"] = "\t"
    assert not evaluate_annual_turn(blank_washington_annual, washington_annual)[
        0
    ].test_pass


def test_annual_route_clarification() -> None:
    rows = load_rows()
    _, annual_call, annual_response = _annual_example()
    tysons = rows[5]
    tysons_call: dict[str, JSON] = {**annual_call, "input": tysons["expected_call"]}
    tysons_turns: list[dict[str, JSON]] = [
        {
            "response": (
                "**🛣️ Which Tysons exit: Westpark Drive, Jones Branch/Route 123, "
                "or Route 7?**"
            ),
            "calls": [],
        },
        {"response": annual_response, "calls": [tysons_call]},
    ]
    assert evaluate_annual_turn(tysons_turns, tysons)[0].test_pass
    premature_call = json.loads(json.dumps(tysons_turns))
    premature_call[0]["calls"] = [tysons_call]
    assert evaluate_annual_turn(premature_call, tysons)[0].label == "bad_clarification"


def test_annual_missing_inputs() -> None:
    rows = load_rows()
    _, annual_call, _ = _annual_example()
    missing = rows[6]
    missing_turns: list[dict[str, JSON]] = [
        {
            "response": (
                "### 💼 Schedule details\n\n**What outbound departure time, return "
                "departure time, office days, and planned annual commute days should I "
                "use? I estimate annual commute days as 52 times the weekly office days; "
                "Monday through Friday is 260, which you can adjust.**"
            ),
            "calls": [],
        }
    ]
    assert evaluate_annual_missing_inputs(missing_turns, missing)[0].test_pass
    missing_estimate_method = json.loads(json.dumps(missing_turns))
    missing_estimate_method[0]["response"] = missing_estimate_method[0][
        "response"
    ].replace(
        " I estimate annual commute days as 52 times the weekly office days; Monday "
        "through Friday is 260, which you can adjust.",
        "",
    )
    assert (
        evaluate_annual_missing_inputs(missing_estimate_method, missing)[0].label
        == "missing_annual_day_estimate"
    )
    missing_call = json.loads(json.dumps(missing_turns))
    missing_call[0]["calls"] = [annual_call]
    assert (
        evaluate_annual_missing_inputs(missing_call, missing)[0].label
        == "premature_call"
    )
    omitted_field = json.loads(json.dumps(missing_turns))
    omitted_field[0]["response"] = (
        omitted_field[0]["response"]
        .replace("office days, and ", "")
        .replace("weekly office days", "weekly schedule")
    )
    assert (
        evaluate_annual_missing_inputs(omitted_field, missing)[0].label
        == "missing_required_input"
    )


def test_annual_day_estimate() -> None:
    rows = load_rows()
    _, annual_call, annual_response = _annual_example()
    estimate_case = rows[9]
    estimate_call: dict[str, JSON] = {
        **annual_call,
        "input": estimate_case["expected_call"],
    }
    estimate_turns: list[dict[str, JSON]] = [
        {
            "response": (
                "### 📅 Annual commute-day estimate\n\n"
                "**Five weekdays times 52 weeks is 260 annual commute days. "
                "Should I use 260, or would you like to adjust it up or down?**"
            ),
            "calls": [],
        },
        {"response": annual_response, "calls": [estimate_call]},
    ]
    assert evaluate_annual_day_estimate(estimate_turns, estimate_case)[0].test_pass
    premature_estimate_call = json.loads(json.dumps(estimate_turns))
    premature_estimate_call[0]["calls"] = [estimate_call]
    assert (
        evaluate_annual_day_estimate(premature_estimate_call, estimate_case)[0].label
        == "premature_call"
    )
    wrong_estimate = json.loads(json.dumps(estimate_turns))
    wrong_estimate[0]["response"] = wrong_estimate[0]["response"].replace("260", "250")
    assert (
        evaluate_annual_day_estimate(wrong_estimate, estimate_case)[0].label
        == "bad_annual_day_estimate"
    )


def test_annual_income_clarification() -> None:
    rows = load_rows()
    _, annual_call, annual_response = _annual_example()
    income = rows[7]
    income_call: dict[str, JSON] = {**annual_call, "input": income["expected_call"]}
    income_turns: list[dict[str, JSON]] = [
        {
            "response": (
                "### 💰 Gross estimate needed\n\nPlease choose **one annual gross-income "
                "estimate** for that salary range."
            ),
            "calls": [],
        },
        {"response": annual_response, "calls": [income_call]},
    ]
    assert evaluate_annual_income_clarification(income_turns, income)[0].test_pass
    inferred_income = json.loads(json.dumps(income_turns))
    inferred_income[0]["response"] += " I'll use $120,000."
    assert (
        evaluate_annual_income_clarification(inferred_income, income)[0].label
        == "inferred_income"
    )
    premature_income_call = json.loads(json.dumps(income_turns))
    premature_income_call[0]["calls"] = [income_call]
    assert (
        evaluate_annual_income_clarification(premature_income_call, income)[0].label
        == "premature_call"
    )


def test_annual_route_unavailable() -> None:
    rows = load_rows()
    unavailable_annual = rows[8]
    unavailable_call = {
        "name": "get_annual_toll_ballpark",
        "input": unavailable_annual["expected_call"],
        "tool_result": {
            "error": "ballpark_unavailable",
            "reason": "route_unavailable",
            "outbound": {
                "origin_point_id": "airport_iad",
                "destination_point_id": "airport_dca",
                "status": "valid",
                "reason": None,
            },
            "return": {
                "origin_point_id": "airport_dca",
                "destination_point_id": "airport_iad",
                "status": "no_supported_route",
                "reason": {
                    "code": "no_supported_route",
                    "details": {
                        "origin_point_id": "airport_dca",
                        "destination_point_id": "airport_iad",
                    },
                },
            },
        },
        "is_error": False,
    }
    unavailable_annual_turns = [
        {
            "response": (
                "### 🚧 Annual route unavailable\n\nThe return toll route is "
                "**unavailable**, so I cannot estimate its vehicle cost or provide "
                "annual toll scenarios or financial totals."
            ),
            "calls": [unavailable_call],
        }
    ]
    assert evaluate_annual_route_unavailable(
        unavailable_annual_turns, unavailable_annual
    )[0].test_pass
    invented_totals = json.loads(json.dumps(unavailable_annual_turns))
    invented_totals[0]["response"] += " P50 costs $1,000."
    assert (
        evaluate_annual_route_unavailable(invented_totals, unavailable_annual)[0].label
        == "invented_financials"
    )
    offered_restart = json.loads(json.dumps(unavailable_annual_turns))
    offered_restart[0]["response"] += " I can restart with the current-price tool."
    assert (
        evaluate_annual_route_unavailable(offered_restart, unavailable_annual)[0].label
        == "bad_restart"
    )
    wrong_route_status = json.loads(json.dumps(unavailable_annual_turns))
    wrong_route_status[0]["calls"][0]["tool_result"]["return"]["status"] = "valid"
    assert (
        evaluate_annual_route_unavailable(wrong_route_status, unavailable_annual)[
            0
        ].label
        == "result_mismatch"
    )


def test_annual_route_alternatives_and_selection() -> None:
    rows = load_rows()
    alternative_payload = {
        "error": "ballpark_unavailable",
        "reason": "route_unavailable",
        "outbound": {
            "origin_point_id": "i95:205SD",
            "destination_point_id": "i95:223ND",
            "status": "invalid_origin",
            "reason": {
                "code": "origin_not_entry",
                "details": {
                    "point_id": "i95:205SD",
                    "point_type": "exit",
                    "alternatives": [
                        {
                            "point_id": "i95:212NO",
                            "label": "I-95 Near Franconia-Springfield Pkwy NB",
                            "aliases": [
                                "Franconia-Springfield Parkway",
                                "Route 289",
                                "Springfield",
                            ],
                        },
                        {
                            "point_id": "i95:203NO",
                            "label": "Old Keene Mill Road/Route 644",
                            "aliases": [
                                "Old Keene Mill Road",
                                "Route 644",
                                "Springfield",
                            ],
                        },
                    ],
                },
            },
        },
        "return": {
            "origin_point_id": "i95:2233SO",
            "destination_point_id": "i95:205SD",
            "status": "valid",
            "reason": None,
        },
    }
    alternatives = next(
        row for row in rows if row["id"] == "annual-backlick-alternatives"
    )
    alternative_call = {
        "name": "get_annual_toll_ballpark",
        "input": alternatives["expected_initial_call"],
        "tool_result": alternative_payload,
        "is_error": False,
    }
    alternative_turn = {
        "response": (
            "The morning ramp is unavailable. Choose either "
            "Franconia-Springfield Parkway or Old Keene Mill Road."
        ),
        "calls": [alternative_call],
    }
    assert evaluate_annual_alternatives([alternative_turn], alternatives)[0].test_pass
    varied_alternative_response = json.loads(json.dumps(alternative_turn))
    varied_alternative_response["response"] = (
        "## Available route choices\n\n"
        "The returned choices are Franconia-Springfield Parkway and "
        "Old Keene Mill Road. I will retain the evening return leg and "
        "schedule. Which option should I use?"
    )
    assert evaluate_annual_alternatives([varied_alternative_response], alternatives)[
        0
    ].test_pass
    shared_allowed_choices = json.loads(json.dumps(alternative_turn))
    shared_allowed_choices["response"] = (
        "Choose Franconia-Springfield Parkway, Old Keene Mill Road."
    )
    assert evaluate_annual_alternatives([shared_allowed_choices], alternatives)[
        0
    ].test_pass
    for valid_response in (
        "### Choose a morning origin\n\n- Franconia-Springfield Parkway\n- Old Keene Mill Road",
        "Which route should I use: Franconia-Springfield Parkway or Old Keene Mill Road?",
        "Please select Route 289 or Route 644. Your return stays at Backlick.",
        "Choose one:\n1. Franconia-Springfield Parkway\n2. Old Keene Mill Road\n- Return: Pentagon/Eads Street to Backlick Road",
        "Choose Franconia-Springfield Parkway or Old Keene Mill Road, and retain the return leg.",
    ):
        assert evaluate_annual_alternatives(
            [{**alternative_turn, "response": valid_response}], alternatives
        )[0].test_pass, valid_response
    missing_selection = json.loads(json.dumps(alternative_turn))
    missing_selection["response"] = (
        "The returned choices are Franconia-Springfield Parkway and Old Keene Mill Road."
    )
    assert (
        evaluate_annual_alternatives([missing_selection], alternatives)[0].label
        == "missing_selection"
    )
    missing_option = json.loads(json.dumps(alternative_turn))
    missing_option["response"] = (
        "Choose Franconia-Springfield Parkway or Backlick Road."
    )
    assert (
        evaluate_annual_alternatives([missing_option], alternatives)[0].label
        == "missing_alternative"
    )
    invented_before_selection = json.loads(json.dumps(alternative_turn))
    invented_before_selection["response"] += " The annual toll would be $1.00."
    assert (
        evaluate_annual_alternatives([invented_before_selection], alternatives)[0].label
        == "invented_financials"
    )
    for sign in ("-$", "$-", "\u2212$"):
        signed_before_selection = json.loads(json.dumps(alternative_turn))
        signed_before_selection["response"] += f" The annual toll would be {sign}1.00."
        assert (
            evaluate_annual_alternatives([signed_before_selection], alternatives)[
                0
            ].label
            == "invented_financials"
        )
    wrong_alternative = json.loads(json.dumps(alternative_turn))
    wrong_alternative["calls"][0]["tool_result"]["outbound"]["reason"]["details"][
        "alternatives"
    ][0]["point_id"] = "i95:999NO"
    assert (
        evaluate_annual_alternatives([wrong_alternative], alternatives)[0].label
        == "result_mismatch"
    )

    selection = next(
        row for row in rows if row["id"] == "annual-backlick-alternative-selection"
    )
    selection_call = no_complete_call(selection["expected_call"])
    selection_turns = [
        alternative_turn,
        {
            "response": (
                "### ⚠️ Annual estimate unavailable\n\n"
                "The selected route is valid, but no complete paired days are "
                "available, so the estimate is unavailable."
            ),
            "calls": [selection_call],
        },
    ]
    selection_turns[0] = {
        **alternative_turn,
        "calls": [{**alternative_call, "input": selection["expected_initial_call"]}],
    }
    assert evaluate_annual_alternatives(selection_turns, selection)[0].test_pass
    wrong_selected = json.loads(json.dumps(selection_turns))
    wrong_selected[1]["calls"][0]["input"]["outbound"]["origin_point_id"] = "i95:999NO"
    assert (
        evaluate_annual_alternatives(wrong_selected, selection)[0].label
        == "input_mismatch"
    )
    dropped_retained = json.loads(json.dumps(selection_turns))
    dropped_retained[1]["calls"][0]["input"]["return"]["departure_time"] = "08:00:00"
    assert (
        evaluate_annual_alternatives(dropped_retained, selection)[0].label
        == "input_mismatch"
    )
    premature_selection = json.loads(json.dumps(selection_turns))
    premature_selection[0]["calls"].append(selection_call)
    assert (
        evaluate_annual_alternatives(premature_selection, selection)[0].label
        == "tool_mismatch"
    )
    extra_selection = json.loads(json.dumps(selection_turns))
    extra_selection[1]["calls"].append(selection_call)
    assert (
        evaluate_annual_alternatives(extra_selection, selection)[0].label
        == "tool_mismatch"
    )


def test_annual_independent_routes() -> None:
    rows = load_rows()
    _, annual_call, annual_response = _annual_example()
    independent = next(row for row in rows if row["id"] == "annual-independent-ramps")
    independent_success = json.loads(json.dumps(annual_call))
    independent_success["input"] = independent["expected_call"]
    independent_success["tool_result"]["income"]["gross_annual_usd"] = "120000.00"
    independent_success_turn = {
        "response": annual_response,
        "calls": [independent_success],
    }
    assert evaluate_annual_relaxed([independent_success_turn], independent)[0].test_pass

    scenario_additional_gross = json.loads(json.dumps(independent_success_turn))
    scenario_additional_gross["response"] += (
        "\nP25 additional gross income to offset is $8280.00."
        "\nP50 additional gross income to offset is $8640.00."
        "\nP90 additional gross income to offset is $9000.00."
    )
    assert evaluate_annual_relaxed([scenario_additional_gross], independent)[
        0
    ].test_pass
    swapped_additional_gross = json.loads(json.dumps(scenario_additional_gross))
    swapped_additional_gross["response"] = swapped_additional_gross["response"].replace(
        "P50 additional gross income to offset is $8640.00",
        "P50 additional gross income to offset is $9000.00",
    )
    assert (
        evaluate_annual_relaxed([swapped_additional_gross], independent)[0].label
        == "misbound_money"
    )
    missing_disclosures = json.loads(json.dumps(independent_success_turn))
    missing_disclosures["response"] = (
        "P25 daily cost is $23.00, monthly cost is $460.00, annual cost is "
        "$5520.00, and remaining income is $74480.00."
    )
    assert (
        evaluate_annual_relaxed([missing_disclosures], independent)[0].label
        == "missing_markdown"
    )

    independent_turn = {
        "response": (
            "### ⚠️ Annual estimate unavailable\n\n"
            "The route is valid; no complete paired days are available, so the "
            "estimate is unavailable."
        ),
        "calls": [no_complete_call(independent["expected_call"])],
    }
    assert evaluate_annual_relaxed([independent_turn], independent)[0].test_pass
    invented_independent = json.loads(json.dumps(independent_turn))
    invented_independent["response"] += " The annual toll is $999.00."
    assert (
        evaluate_annual_relaxed([invented_independent], independent)[0].label
        == "invented_financials"
    )
    structural_failure = json.loads(json.dumps(independent_turn))
    structural_failure["calls"][0]["tool_result"] = {
        "error": "ballpark_unavailable",
        "reason": "route_unavailable",
    }
    assert (
        evaluate_annual_relaxed([structural_failure], independent)[0].label
        == "tool_error"
    )


def test_annual_divergent_route_confirmation() -> None:
    rows = load_rows()
    divergent = next(
        row for row in rows if row["id"] == "annual-divergent-areas-confirmation"
    )
    divergent_turns: list[dict[str, JSON]] = [
        {
            "response": (
                "Pentagon and Westpark are different work areas. Would you like "
                "me to combine these commute legs?"
            ),
            "calls": [],
        },
        {
            "response": (
                "### ⚠️ Annual estimate unavailable\n\n"
                "Historical sample data are insufficient: there are no complete "
                "paired days for an annual estimate."
            ),
            "calls": [no_complete_call(divergent["expected_call"])],
        },
    ]
    assert evaluate_annual_confirmation(divergent_turns, divergent)[0].test_pass
    premature_confirmation = json.loads(json.dumps(divergent_turns))
    premature_confirmation[0]["calls"] = [
        cast(list[JSON], divergent_turns[1]["calls"])[0]
    ]
    assert (
        evaluate_annual_confirmation(premature_confirmation, divergent)[0].label
        == "bad_confirmation"
    )


def test_annual_reversed_route() -> None:
    rows = load_rows()
    reversal = next(
        row for row in rows if row["id"] == "annual-ordinary-reversal-regression"
    )
    assert evaluate_annual_relaxed(
        [
            {
                "response": (
                    "### ⚠️ Annual estimate unavailable\n\n"
                    "The inferred reverse route has no complete paired days, so "
                    "the estimate is unavailable."
                ),
                "calls": [no_complete_call(reversal["expected_call"])],
            }
        ],
        reversal,
    )[0].test_pass
