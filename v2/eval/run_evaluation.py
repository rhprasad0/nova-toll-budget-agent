# pyright: basic
"""Code-grade TollChat v2 current-toll routing regressions."""

from __future__ import annotations

import json
import os
import re
import sys
from argparse import ArgumentParser
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import boto3
from strands.types.content import Message, Messages
from strands_evals import Case, Experiment
from strands_evals.evaluators import Evaluator
from strands_evals.extractors import tools_use_extractor
from strands_evals.types.evaluation import EvaluationData, EvaluationOutput

_V2_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_V2_ROOT))

from agent.toll_agent import build_agent  # noqa: E402

_CASES_PATH = Path(__file__).with_name("test-cases.jsonl")
_RESULTS_DIR = Path(__file__).with_name("results")
_PROFILE = {
    "vehicle_class": "two_axle_passenger",
    "payment_method": "e_zpass",
    "transponder_mode": "toll",
}
_EMOJIS = (
    "🚗",
    "💵",
    "🛣️",
    "📈",
    "📉",
    "➡️",
    "🔄",
    "⚠️",
    "🎉",
    "✅",
    "🚧",
    "💼",
    "🧾",
    "🎯",
)
_EASTERN_TIME = re.compile(r"\b(?:1[0-2]|[1-9]):[0-5]\d [AP]M E(?:S|D)T\b")
_MOVEMENT_EMOJIS = {
    "rising": "📈",
    "falling": "📉",
    "unchanged": "➡️",
    "mixed": "🔄",
}


def load_rows(path: Path = _CASES_PATH) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def load_cases(
    path: Path = _CASES_PATH, suite: str = "all", window: str = "all"
) -> list[Case[str, str]]:
    return [
        Case[str, str](
            name=row["id"],
            input=row["prompt"],
            metadata={**row, "active_window": window},
        )
        for row in load_rows(path)
        if suite == "all" or row.get("suite") == suite
        if window == "all" or window in row.get("windows", [])
    ]


def _result(passed: bool, reason: str, label: str) -> list[EvaluationOutput]:
    return [
        EvaluationOutput(
            score=float(passed), test_pass=passed, reason=reason, label=label
        )
    ]


def _response_style_error(response: str, subject: str) -> list[EvaluationOutput] | None:
    if not any(mark in response for mark in ("#", "**", "- ")):
        return _result(False, f"{subject} omitted Markdown", "missing_markdown")
    if not any(emoji in response for emoji in _EMOJIS):
        return _result(False, f"{subject} omitted an emoji", "missing_emoji")
    return None


def _expected_calls_error(
    turns: list[dict[str, Any]], expected_calls: list[dict[str, Any]]
) -> list[EvaluationOutput] | None:
    if len(turns) != len(expected_calls):
        return _result(
            False,
            f"expected exactly {len(expected_calls)} conversation turns",
            "turn_count",
        )
    for index, (turn, expected_call) in enumerate(
        zip(turns, expected_calls, strict=True)
    ):
        calls = turn.get("calls", [])
        if len(calls) != 1 or calls[0].get("name") != "get_current_toll_price":
            return _result(
                False,
                f"turn {index + 1} expected exactly one current-price call",
                "tool_mismatch",
            )
        if calls[0].get("input") != expected_call:
            return _result(
                False, f"turn {index + 1} used the wrong endpoints", "input_mismatch"
            )
        if calls[0].get("is_error"):
            return _result(False, f"turn {index + 1} tool failed", "tool_error")
    return None


def _tool_payload(result: dict[str, Any]) -> dict[str, Any] | None:
    for item in result.get("content", []):
        if isinstance(item, dict) and isinstance(item.get("json"), dict):
            return cast(dict[str, Any], item["json"])
        if isinstance(item, dict) and isinstance(item.get("text"), str):
            try:
                value = json.loads(item["text"])
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                return cast(dict[str, Any], value)
    return None


def _result_endpoints(payload: dict[str, Any]) -> tuple[object, object]:
    point_ids = payload.get("point_ids", [])
    return (
        payload.get("origin_point_id")
        or (point_ids[0] if isinstance(point_ids, list) and point_ids else None),
        payload.get("destination_point_id")
        or (point_ids[-1] if isinstance(point_ids, list) and point_ids else None),
    )


def _movement_value_is_reported(response: str, raw_value: object) -> bool:
    value = Decimal(str(raw_value))
    magnitude = format(abs(value), "f")
    if value >= 0:
        return f"${magnitude}" in response
    return bool(
        re.search(
            rf"(?:[-\u2212]\${re.escape(magnitude)}|\$[-\u2212]{re.escape(magnitude)}|"
            rf"(?:down|decreased|fell|lower)\s+\${re.escape(magnitude)})",
            response,
            re.IGNORECASE,
        )
    )


def _component_context_error(
    payload: dict[str, Any], response: str
) -> list[EvaluationOutput] | None:
    folded = response.casefold()
    components = [
        component
        for component in payload.get("components", [])
        if isinstance(component, dict)
    ]
    source_kinds = {
        str(source_kind)
        for component in components
        if (source_kind := component.get("source_kind"))
    }
    if payload.get("source_kind"):
        source_kinds.add(str(payload["source_kind"]))
    if source_kinds and (
        not any(term in folded for term in ("pricing", "provenance"))
        or any(source_kind.casefold() not in folded for source_kind in source_kinds)
    ):
        return _result(
            False, "response omitted component price provenance", "missing_provenance"
        )

    for component in components:
        movement = component.get("recent_movement")
        if isinstance(movement, dict):
            direction = str(movement.get("direction", ""))
            required = [
                direction,
                _MOVEMENT_EMOJIS.get(direction, ""),
            ]
            if movement.get("net_change_percent") is not None:
                required.append(f"{str(movement['net_change_percent']).lstrip('+-')}%")
            if not _movement_value_is_reported(
                response, movement.get("net_change_usd")
            ) or any(value and value.casefold() not in folded for value in required):
                return _result(
                    False,
                    "response omitted tool-provided recent movement",
                    "missing_movement",
                )

        comparison = component.get("prior_week_comparison")
        if isinstance(comparison, dict):
            delta = Decimal(str(comparison["current_delta_usd"]))
            message = (
                "⚠️ Higher than the recent median"
                if delta > 0
                else "🎉 You're getting a deal — below the recent median"
                if delta < 0
                else "✅ At the recent median"
            )
            required = [
                message,
                f"${comparison['median_usd']}",
                f"${comparison['minimum_usd']}",
                f"${comparison['maximum_usd']}",
            ]
            if any(value.casefold() not in folded for value in required):
                return _result(
                    False,
                    "response omitted tool-provided historical comparison",
                    "missing_comparison",
                )
    return None


def _trace_messages(traces: list[dict[str, Any]]) -> Messages:
    def walk(trace: dict[str, Any]) -> Messages:
        messages = [cast(Message, trace["message"])] if trace.get("message") else []
        for child in trace.get("children", []):
            messages.extend(walk(child))
        return messages

    return [message for trace in traces for message in walk(trace)]


def _calls(response: object) -> list[dict[str, Any]]:
    summary = cast(dict[str, Any], cast(Any, response).metrics.get_summary())
    messages = _trace_messages(cast(list[dict[str, Any]], summary.get("traces", [])))
    calls = cast(
        list[dict[str, Any]],
        tools_use_extractor.extract_agent_tools_used_from_messages(messages),
    )
    tool_ids = [
        block["toolUse"]["toolUseId"]
        for message in messages
        if message.get("role") == "assistant"
        for block in message.get("content", [])
        if "toolUse" in block
    ]
    results = {
        result["toolUseId"]: result
        for message in messages
        if message.get("role") == "user"
        for block in message.get("content", [])
        if (result := block.get("toolResult"))
    }
    for call, tool_id in zip(calls, tool_ids, strict=True):
        result = cast(dict[str, Any], results.get(tool_id, {}))
        call["tool_result"] = _tool_payload(result)
        call["is_error"] = result.get("status") == "error"
    return calls


def evaluate_westpark_turn(
    calls: list[dict[str, Any]], response: str, metadata: dict[str, Any]
) -> list[EvaluationOutput]:
    if len(calls) != 1 or calls[0].get("name") != "get_current_toll_price":
        return _result(
            False, "expected exactly one current-price call", "tool_mismatch"
        )
    call = calls[0]
    if call.get("input") != metadata["expected_call"]:
        return _result(False, "current-price arguments did not match", "input_mismatch")
    payload = call.get("tool_result")
    if call.get("is_error") or not isinstance(payload, dict) or "error" in payload:
        return _result(False, "current-price tool returned an error", "tool_error")
    expected = metadata["expected_call"]
    actual_origin, actual_destination = _result_endpoints(payload)
    if (
        actual_origin != expected["origin_point_id"]
        or actual_destination != expected["destination_point_id"]
    ):
        return _result(False, "tool result endpoints did not match", "result_mismatch")

    if "total_usd" not in payload:
        return _result(
            False, "tool returned no usable current toll", "tool_unavailable"
        )
    expected_price = f"${payload['total_usd']}"
    if expected_price not in response:
        return _result(False, f"response omitted {expected_price}", "ungrounded_price")
    if len(payload.get("components", [])) != 2:
        return _result(
            False, "priced route did not contain two components", "bad_route"
        )
    if not _EASTERN_TIME.search(response):
        return _result(False, "response omitted observation time", "missing_time")

    if style_error := _response_style_error(response, "response"):
        return style_error
    if context_error := _component_context_error(payload, response):
        return context_error
    return _result(True, "exact route call and grounded response passed", "passed")


def evaluate_restart_turns(
    turns: list[dict[str, Any]], metadata: dict[str, Any]
) -> list[EvaluationOutput]:
    expected_calls = metadata["expected_calls"]
    if calls_error := _expected_calls_error(turns, expected_calls):
        return calls_error

    initial_call = turns[0]["calls"][0]
    initial_payload = initial_call.get("tool_result")
    if not isinstance(initial_payload, dict) or initial_payload.get("status") != (
        "invalid_origin"
    ):
        return _result(False, "initial result was not invalid_origin", "bad_route")
    reason = initial_payload.get("reason", {})
    details = reason.get("details", {}) if isinstance(reason, dict) else {}
    if (
        reason.get("code") != "i95_northbound_requires_i495_restart"
        or details.get("suggested_restart_point_id") != "i495:192NO"
        or details.get("suggested_destination_point_id") != "i495:185ND"
        or "alternatives" in details
    ):
        return _result(False, "initial restart contract was malformed", "bad_route")

    initial_response = str(turns[0].get("response", ""))
    folded = initial_response.casefold()
    if not (
        any(term in folded for term in ("would you like", "want me to", "should i"))
        and "i-495" in folded
        and "general-purpose" in folded
        and re.search(r"not (?:be )?included", folded)
    ):
        return _result(False, "restart offer or disclosure was missing", "bad_offer")
    if re.search(r"\$\s*\d", initial_response) or any(
        name in folded for name in ("edsall", "seminary")
    ):
        return _result(
            False, "initial offer included a price or bad alternative", "bad_offer"
        )
    if style_error := _response_style_error(initial_response, "restart offer"):
        return style_error

    accepted_call = turns[1]["calls"][0]
    accepted_payload = accepted_call.get("tool_result")
    if not isinstance(accepted_payload, dict) or "total_usd" not in accepted_payload:
        return _result(False, "accepted restart returned no price", "tool_unavailable")
    expected_accepted = expected_calls[1]
    if _result_endpoints(accepted_payload) != (
        expected_accepted["origin_point_id"],
        expected_accepted["destination_point_id"],
    ):
        return _result(
            False, "restart result endpoints did not match", "result_mismatch"
        )
    accepted_response = str(turns[1].get("response", ""))
    if f"${accepted_payload['total_usd']}" not in accepted_response:
        return _result(
            False, "accepted response omitted the tool price", "ungrounded_price"
        )
    if not _EASTERN_TIME.search(accepted_response):
        return _result(
            False, "accepted response omitted observation time", "missing_time"
        )
    if style_error := _response_style_error(accepted_response, "accepted response"):
        return style_error
    if context_error := _component_context_error(accepted_payload, accepted_response):
        return context_error
    return _result(True, "restart offer and accepted TP1NB price passed", "passed")


def evaluate_fallback_turns(
    turns: list[dict[str, Any]], metadata: dict[str, Any]
) -> list[EvaluationOutput]:
    if calls_error := _expected_calls_error(turns, metadata["expected_calls"]):
        return calls_error

    window = metadata.get("active_window")
    initial_payload = turns[0]["calls"][0].get("tool_result")
    if not isinstance(initial_payload, dict) or initial_payload.get("status") != (
        "currently_unavailable"
    ):
        return _result(False, "initial result was not unavailable", "bad_route")
    reason = initial_payload.get("reason", {})
    details = reason.get("details", {}) if isinstance(reason, dict) else {}
    if (
        reason.get("code") != metadata["expected_reasons"].get(window)
        or details.get("availability") != metadata["expected_availability"].get(window)
        or details.get("required_i95_directions")
        != metadata["expected_required_i95_directions"]
        or initial_payload.get("general_purpose_gaps")
        != [
            {
                "connection_id": "i495_to_i95_south",
                "boundary_point_id": "i495:192SD",
                "role": "suffix",
                "i95_direction": "SB",
                "fallback_required": True,
            }
        ]
    ):
        return _result(
            False, "initial TP1SB fallback contract was malformed", "bad_route"
        )

    initial_response = str(turns[0].get("response", ""))
    folded = initial_response.casefold()
    if not (
        any(term in folded for term in ("would you like", "want me to", "should i"))
        and "i-495" in folded
        and "southbound" in folded
        and "general-purpose" in folded
        and re.search(r"not (?:be )?included", folded)
    ):
        return _result(False, "TP1SB offer or disclosure was missing", "bad_offer")
    if re.search(r"\$\s*\d", initial_response) or "i495:192sd" in folded:
        return _result(False, "TP1SB offer exposed a price or point ID", "bad_offer")
    if style_error := _response_style_error(initial_response, "fallback offer"):
        return style_error

    accepted_payload = turns[1]["calls"][0].get("tool_result")
    if not isinstance(accepted_payload, dict) or "total_usd" not in accepted_payload:
        return _result(False, "accepted fallback returned no price", "tool_unavailable")
    expected_accepted = metadata["expected_calls"][1]
    if _result_endpoints(accepted_payload) != (
        expected_accepted["origin_point_id"],
        expected_accepted["destination_point_id"],
    ):
        return _result(
            False, "fallback result endpoints did not match", "result_mismatch"
        )
    accepted_response = str(turns[1].get("response", ""))
    if f"${accepted_payload['total_usd']}" not in accepted_response:
        return _result(
            False, "accepted response omitted the tool price", "ungrounded_price"
        )
    if not _EASTERN_TIME.search(accepted_response):
        return _result(
            False, "accepted response omitted observation time", "missing_time"
        )
    if style_error := _response_style_error(accepted_response, "accepted response"):
        return style_error
    if context_error := _component_context_error(accepted_payload, accepted_response):
        return context_error
    return _result(True, "TP1SB offer and accepted fallback price passed", "passed")


def evaluate_unavailable_turn(
    turns: list[dict[str, Any]], metadata: dict[str, Any]
) -> list[EvaluationOutput]:
    if calls_error := _expected_calls_error(turns, [metadata["expected_call"]]):
        return calls_error

    window = metadata.get("active_window")
    payload = turns[0]["calls"][0].get("tool_result")
    if (
        not isinstance(payload, dict)
        or payload.get("status") != "currently_unavailable"
    ):
        return _result(False, "tool result was not unavailable", "bad_route")
    expected = metadata["expected_call"]
    if _result_endpoints(payload) != (
        expected["origin_point_id"],
        expected["destination_point_id"],
    ):
        return _result(
            False, "unavailable result endpoints did not match", "result_mismatch"
        )
    reason = payload.get("reason", {})
    details = reason.get("details", {}) if isinstance(reason, dict) else {}
    if (
        reason.get("code") != metadata["expected_reasons"].get(window)
        or details.get("availability") != metadata["expected_availability"].get(window)
        or details.get("required_i95_directions")
        != metadata["expected_required_i95_directions"]
    ):
        return _result(False, "unavailability reason did not match", "bad_route")
    if any(
        gap.get("fallback_required") is True
        for gap in payload.get("general_purpose_gaps", [])
        if isinstance(gap, dict)
    ):
        return _result(False, "unexpected fallback-required gap", "bad_route")

    response = str(turns[0].get("response", ""))
    folded = response.casefold()
    expected_state = metadata["expected_availability"].get(window)
    if not (
        any(term in folded for term in ("unavailable", "closed"))
        and expected_state in folded
    ):
        return _result(False, "closure state was not explained", "missing_closure")
    if re.search(r"\$\s*\d", response) or any(
        term in folded for term in ("would you like", "want me to", "should i", "tp1")
    ):
        return _result(
            False, "response invented a price or fallback offer", "bad_offer"
        )
    if style_error := _response_style_error(response, "closure response"):
        return style_error
    return _result(True, "unavailability response matched the live state", "passed")


def evaluate_annual_turn(
    calls: list[dict[str, Any]], response: str, metadata: dict[str, Any]
) -> list[EvaluationOutput]:
    if len(calls) != 1 or calls[0].get("name") != "get_annual_toll_ballpark":
        return _result(False, "expected exactly one annual call", "tool_mismatch")
    call = calls[0]
    if call.get("input") != metadata["expected_call"]:
        return _result(False, "annual arguments did not match", "input_mismatch")
    payload = call.get("tool_result")
    if (
        call.get("is_error")
        or not isinstance(payload, dict)
        or "error" in payload
        or not isinstance(payload.get("scenarios"), dict)
    ):
        return _result(False, "annual tool returned no scenarios", "tool_error")

    if style_error := _response_style_error(response, "annual response"):
        return style_error
    folded = response.casefold()
    if not (
        "###" in response
        and "**" in response
        and "|" in response
        and ("one-third" in folded or "1/3" in response)
        and "0.685" in response
        and "straight-line" in folded
        and "tolled" in folded
        and "additional gross" in folded
        and "historical" in folded
        and "coverage" in folded
        and "hov" not in folded
    ):
        return _result(
            False,
            "annual response omitted required hierarchy or assumptions",
            "missing_affordability_context",
        )

    scenarios = cast(dict[str, dict[str, Any]], payload["scenarios"])
    required_values = [
        payload["income"]["gross_annual_usd"],
        payload["income"]["estimated_after_tax_usd"],
        payload["vehicle_cost"]["annual_usd"],
        scenarios["p50"]["annual_toll_usd"],
        scenarios["p50"]["additional_gross_income_to_offset_usd"],
    ]
    for scenario in scenarios.values():
        required_values.extend(
            scenario[field]
            for field in (
                "daily_total_tolled_commute_cost_usd",
                "average_monthly_tolled_commute_cost_usd",
                "annual_total_tolled_commute_cost_usd",
                "estimated_annual_income_after_tax_and_tolled_commute_usd",
            )
        )
    normalized = response.replace(",", "")
    if any(f"${value}" not in normalized for value in required_values):
        return _result(
            False, "annual response omitted tool-provided money", "ungrounded_money"
        )
    return _result(True, "annual tool call and affordability response passed", "passed")


def task_function(case: Case[str, str]) -> dict[str, Any]:
    agent = build_agent()
    turns = []
    response: object = ""
    previous_call_count = 0
    for prompt in (case.metadata or {}).get("conversation", [str(case.input)]):
        response = agent(prompt)
        all_calls = _calls(response)
        turns.append(
            {"response": str(response), "calls": all_calls[previous_call_count:]}
        )
        previous_call_count = len(all_calls)
    return {"output": str(response), "trajectory": turns}


class TollChatEvaluator(Evaluator[str, str]):
    def evaluate(
        self, evaluation_case: EvaluationData[str, str]
    ) -> list[EvaluationOutput]:
        trajectory = evaluation_case.actual_trajectory
        turns = (
            cast(list[dict[str, Any]], trajectory)
            if isinstance(trajectory, list)
            else []
        )
        metadata = evaluation_case.metadata or {}
        if metadata.get("suite") == "restart":
            return evaluate_restart_turns(turns, metadata)
        if metadata.get("suite") == "fallback":
            return evaluate_fallback_turns(turns, metadata)
        if metadata.get("suite") == "unavailable":
            return evaluate_unavailable_turn(turns, metadata)
        if metadata.get("suite") == "annual":
            calls = turns[0].get("calls", []) if len(turns) == 1 else []
            return evaluate_annual_turn(
                cast(list[dict[str, Any]], calls),
                str(evaluation_case.actual_output or ""),
                metadata,
            )
        calls = turns[0].get("calls", []) if len(turns) == 1 else []
        return evaluate_westpark_turn(
            cast(list[dict[str, Any]], calls),
            str(evaluation_case.actual_output or ""),
            metadata,
        )


def _configure_database() -> None:
    os.environ.setdefault("DB_NAME", "nova_toll")
    default_ca = Path("infra/build/ca/rds-ca-bundle.pem")
    if default_ca.exists():
        os.environ.setdefault("DB_CA_BUNDLE_PATH", str(default_ca))
    if "DB_HOST" not in os.environ or "DB_PORT" not in os.environ:
        instance = boto3.client("rds", region_name="us-east-1").describe_db_instances(
            DBInstanceIdentifier="nova-toll-db"
        )["DBInstances"][0]
        os.environ["DB_HOST"] = instance["Endpoint"]["Address"]
        os.environ["DB_PORT"] = str(instance["Endpoint"]["Port"])


def main(window: str, suite: str = "all") -> None:
    _configure_database()
    report = Experiment[str, str](
        cases=load_cases(suite=suite, window=window), evaluators=[TollChatEvaluator()]
    ).run_evaluations(task_function)
    _RESULTS_DIR.mkdir(exist_ok=True)
    report.to_file(str(_RESULTS_DIR / f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"))
    report.display(include_input=False)
    if not all(report.test_passes):
        raise SystemExit("TollChat evaluation failed")


def _self_check() -> None:
    assert _movement_value_is_reported("down $0.50", "-0.50")
    assert _movement_value_is_reported("\u2212$0.50", "-0.50")
    assert not _movement_value_is_reported("$0.50", "-0.50")
    rows = load_rows()
    assert [row["id"] for row in rows] == [
        "reagan-airport-to-westpark",
        "pentagon-eads-to-westpark",
        "northbound-i95-to-westpark-restart",
        "dulles-airport-to-backlick-tp1sb-fallback",
        "old-keene-mill-to-reagan-i95-unavailable",
        "leesburg-route-28-job-offer",
    ]
    assert [case.name for case in load_cases(window="i95_northbound")] == [
        "northbound-i95-to-westpark-restart",
        "dulles-airport-to-backlick-tp1sb-fallback",
    ]
    assert [case.name for case in load_cases(window="i95_reversal")] == [
        "northbound-i95-to-westpark-restart",
        "dulles-airport-to-backlick-tp1sb-fallback",
        "old-keene-mill-to-reagan-i95-unavailable",
    ]
    assert [case.name for case in load_cases(window="i95_southbound")] == [
        "reagan-airport-to-westpark",
        "pentagon-eads-to-westpark",
        "northbound-i95-to-westpark-restart",
        "old-keene-mill-to-reagan-i95-unavailable",
    ]
    metadata = rows[0]
    success = {
        "name": "get_current_toll_price",
        "input": metadata["expected_call"],
        "tool_result": {
            "origin_point_id": "airport_dca",
            "destination_point_id": "i495:1859ND",
            "source_kind": "observed",
            "total_usd": "16.40",
            "components": [
                {
                    "route_step_id": "step-1",
                    "source_kind": "observed",
                    "price_usd": "4.80",
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
                    "source_kind": "observed",
                    "price_usd": "11.60",
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
    assert evaluate_westpark_turn([success], good_response, metadata)[0].test_pass
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
            "point_ids": ["airport_dca", "i495:1859ND"],
        },
    }
    assert (
        evaluate_westpark_turn([closure], "### 🚧 Closed", metadata)[0].label
        == "tool_unavailable"
    )
    restart = rows[2]
    restart_turns = [
        {
            "response": (
                "### 🛣️ Start after the junction\n\nWould you like me to price "
                "from I-495? The general-purpose segment is not included."
            ),
            "calls": [
                {
                    "name": "get_current_toll_price",
                    "input": restart["expected_calls"][0],
                    "tool_result": {
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
                    "is_error": False,
                }
            ],
        },
        {
            "response": "### 🚗 Current toll\n\n**Estimate: $4.50** at 9:30 AM EST.",
            "calls": [
                {
                    "name": "get_current_toll_price",
                    "input": restart["expected_calls"][1],
                    "tool_result": {
                        "origin_point_id": "i495:192NO",
                        "destination_point_id": "i495:185ND",
                        "total_usd": "4.50",
                    },
                    "is_error": False,
                }
            ],
        },
    ]
    assert evaluate_restart_turns(restart_turns, restart)[0].test_pass
    bad_offer = json.loads(json.dumps(restart_turns))
    bad_offer[0]["response"] += " Try Edsall Road."
    assert evaluate_restart_turns(bad_offer, restart)[0].label == "bad_offer"
    unstyled_restart = json.loads(json.dumps(restart_turns))
    unstyled_restart[0]["response"] = (
        "Would you like me to price from I-495? The general-purpose segment "
        "is not included."
    )
    assert (
        evaluate_restart_turns(unstyled_restart, restart)[0].label == "missing_markdown"
    )
    wrong_restart_result = json.loads(json.dumps(restart_turns))
    wrong_restart_result[1]["calls"][0]["tool_result"]["origin_point_id"] = "wrong"
    assert (
        evaluate_restart_turns(wrong_restart_result, restart)[0].label
        == "result_mismatch"
    )

    fallback = {**rows[3], "active_window": "i95_northbound"}
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
                                "connection_id": "i495_to_i95_south",
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

    unavailable = {**rows[4], "active_window": "i95_southbound"}
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
    annual = rows[5]
    annual_call = {
        "name": "get_annual_toll_ballpark",
        "input": annual["expected_call"],
        "tool_result": {
            "income": {
                "gross_annual_usd": "120000.00",
                "estimated_after_tax_usd": "80000.00",
            },
            "vehicle_cost": {"annual_usd": "1885.12"},
            "scenarios": {
                name: {
                    "daily_total_tolled_commute_cost_usd": daily,
                    "average_monthly_tolled_commute_cost_usd": monthly,
                    "annual_total_tolled_commute_cost_usd": annual_total,
                    "estimated_annual_income_after_tax_and_tolled_commute_usd": remaining,
                    "annual_toll_usd": annual_toll,
                    "additional_gross_income_to_offset_usd": offset,
                }
                for name, daily, monthly, annual_total, remaining, annual_toll, offset in (
                    (
                        "p25",
                        "23.00",
                        "460.00",
                        "5520.00",
                        "74480.00",
                        "3634.88",
                        "8280.00",
                    ),
                    (
                        "p50",
                        "24.00",
                        "480.00",
                        "5760.00",
                        "74240.00",
                        "3874.88",
                        "8640.00",
                    ),
                    (
                        "p90",
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
        "- 🧾 Gross: $120000.00; after one-third tax: $80000.00\n"
        "- 🚗 Vehicle: $1885.12; toll: $3874.88\n"
        "- 🎯 Additional gross salary needed: $8640.00\n\n"
        "| Scenario | Daily | Monthly | Annual | Remaining |\n"
        "|---|---:|---:|---:|---:|\n"
        "| P25 | $23.00 | $460.00 | $5520.00 | $74480.00 |\n"
        "| P50 | $24.00 | $480.00 | $5760.00 | $74240.00 |\n"
        "| P90 | $25.00 | $500.00 | $6000.00 | $74000.00 |\n\n"
        "⚠️ Historical coverage; tolled straight-line portions only at $0.685/mile."
    )
    assert evaluate_annual_turn([annual_call], annual_response, annual)[0].test_pass
    missing_table = annual_response.replace("|", "")
    assert (
        evaluate_annual_turn([annual_call], missing_table, annual)[0].label
        == "missing_affordability_context"
    )
    print("self-check ok (fixtures and evaluator pass/fail branches; no network)")


if __name__ == "__main__":
    if "--check" in sys.argv:
        _self_check()
    else:
        parser = ArgumentParser()
        parser.add_argument(
            "--window",
            choices=("all", "i95_northbound", "i95_reversal", "i95_southbound"),
            required=True,
        )
        parser.add_argument(
            "--suite",
            choices=("all", "direct", "restart", "fallback", "unavailable", "annual"),
            default="all",
        )
        args = parser.parse_args()
        main(args.window, args.suite)
