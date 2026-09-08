# pyright: basic
"""Code-grade TollChat v2 pricing and affordability regressions."""

from __future__ import annotations

import json
import os
import re
import sys
from argparse import ArgumentParser
from calendar import monthcalendar
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from zoneinfo import ZoneInfo

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
_EASTERN = ZoneInfo("America/New_York")
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
    "🚫",
    "💼",
    "💰",
    "🧾",
    "🎯",
    "📅",
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
    path: Path = _CASES_PATH,
    suite: str = "all",
    window: str = "all",
    weekday: int | None = None,
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
        if weekday is None or weekday in row.get("weekdays", range(1, 8))
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


def _eastern_time(timestamp: str) -> str:
    return (
        datetime.fromisoformat(timestamp)
        .astimezone(_EASTERN)
        .strftime("%I:%M %p %Z")
        .lstrip("0")
    )


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
        or any(
            not any(
                variant in folded
                for variant in {
                    source_kind.casefold(),
                    source_kind.casefold().replace("_", "-"),
                    source_kind.casefold().replace("_", " "),
                }
            )
            for source_kind in source_kinds
        )
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
    if call.get("is_error") or not isinstance(payload, dict):
        return _result(False, "current-price tool returned an error", "tool_error")
    allowed_unavailable = (
        metadata.get("allow_pricing_unavailable")
        and payload.get("error") == "pricing_unavailable"
        and payload.get("reason") == "incomplete_route_price"
    )
    if "error" in payload and not allowed_unavailable:
        return _result(False, "current-price tool returned an error", "tool_error")
    expected = metadata["expected_call"]
    actual_origin, actual_destination = _result_endpoints(payload)
    if (
        actual_origin != expected["origin_point_id"]
        or actual_destination != expected["destination_point_id"]
    ):
        return _result(False, "tool result endpoints did not match", "result_mismatch")

    if "total_usd" not in payload:
        if payload.get("status") in metadata.get("allowed_route_statuses", []):
            folded = response.casefold()
            terms = (
                ("unavailable", "closed")
                if payload.get("status") == "currently_unavailable"
                else ("stale", "unknown", "inconclusive")
            )
            if not any(term in folded for term in terms):
                return _result(
                    False,
                    "response did not explain route availability",
                    "ungrounded_unavailability",
                )
            if re.search(r"\$\s*\d", response):
                return _result(
                    False,
                    "response invented a toll for an unpriced route",
                    "invented_financials",
                )
            if style_error := _response_style_error(response, "response"):
                return style_error
            return _result(
                True,
                "exact route call and grounded route unavailability passed",
                "passed",
            )
        if allowed_unavailable:
            folded = response.casefold()
            if not any(term in folded for term in ("unavailable", "can't", "cannot")):
                return _result(
                    False,
                    "response did not explain temporary price unavailability",
                    "ungrounded_unavailability",
                )
            observation_times = {
                _eastern_time(component["observed_at"])
                for component in payload.get("unavailable_components", [])
                if component.get("observed_at")
            }
            if not observation_times or any(
                value not in response for value in observation_times
            ):
                return _result(
                    False,
                    "response omitted the exact unavailable-component observation time",
                    "missing_time",
                )
            if style_error := _response_style_error(response, "response"):
                return style_error
            return _result(
                True,
                "exact route call and grounded price unavailability passed",
                "passed",
            )
        return _result(
            False, "tool returned no usable current toll", "tool_unavailable"
        )
    expected_price = f"${payload['total_usd']}"
    if expected_price not in response:
        return _result(False, f"response omitted {expected_price}", "ungrounded_price")
    if len(payload.get("components", [])) != metadata.get(
        "expected_component_count", 2
    ):
        return _result(
            False, "priced route did not contain two components", "bad_route"
        )
    if not _EASTERN_TIME.search(response):
        return _result(False, "response omitted observation time", "missing_time")

    if style_error := _response_style_error(response, "response"):
        return style_error
    components = [
        component
        for component in payload.get("components", [])
        if isinstance(component, dict)
    ]
    folded = " ".join(response.casefold().split())
    if any(
        component.get("facility") == "i95_i495"
        and component.get("source_status") == "NO_DETERMINATION"
        for component in components
    ) and (
        "no_determination" in folded
        or "no determination" in folded
        or "source-status qualification" in folded
        or re.search(
            r"(?:\b(?:undetermined|inconclusive|indeterminate|unknown)\b"
            r".{0,40}\b(?:source|status)\b|\b(?:source|status)\b.{0,40}"
            r"\b(?:undetermined|inconclusive|indeterminate|unknown)\b)",
            folded,
        )
    ):
        return _result(
            False,
            "response surfaced non-material I-95/I-495 source status",
            "spurious_source_status",
        )
    if context_error := _component_context_error(payload, response):
        return context_error
    return _result(True, "exact route call and grounded response passed", "passed")


def evaluate_current_clarification_turns(
    turns: list[dict[str, Any]], metadata: dict[str, Any]
) -> list[EvaluationOutput]:
    if len(turns) != 2 or turns[0].get("calls"):
        return _result(
            False,
            "clarification must precede the current-price tool call",
            "bad_clarification",
        )
    clarification = str(turns[0].get("response", ""))
    required_choices = metadata["expected_clarification"]
    if not clarification.strip() or (
        any(
            choice.casefold() not in clarification.casefold()
            for choice in required_choices
        )
        or "?" not in clarification
    ):
        return _result(
            False, "clarification omitted a route choice", "bad_clarification"
        )
    answer = str(turns[1].get("response", ""))
    if not answer.strip():
        return _result(False, "current-price answer was blank", "blank_response")
    return evaluate_westpark_turn(
        cast(list[dict[str, Any]], turns[1].get("calls", [])), answer, metadata
    )


def _i66_holidays(year: int) -> set[date]:
    def nth(month: int, weekday: int, occurrence: int) -> date:
        days = [week[weekday] for week in monthcalendar(year, month) if week[weekday]]
        return date(year, month, days[occurrence])

    fixed = {
        date(year, 1, 1),
        date(year, 6, 19),
        date(year, 7, 4),
        date(year, 11, 11),
        date(year, 12, 25),
    }
    holidays = fixed | {
        nth(1, 0, 2),
        nth(2, 0, 2),
        nth(5, 0, -1),
        nth(9, 0, 0),
        nth(10, 0, 1),
        nth(11, 3, 3),
    }
    return holidays | {
        day + timedelta(days=1 if day.weekday() == 6 else -1)
        for day in fixed
        if day.weekday() >= 5
    }


def evaluate_i66_schedule_turn(
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
        return _result(False, "I-66 current-price tool returned an error", "tool_error")
    components = payload.get("components")
    if not isinstance(components, list) or len(components) != 1:
        return _result(False, "I-66 trip did not have one component", "bad_route")
    component = components[0]
    if not isinstance(component, dict) or component.get("facility") != "i66":
        return _result(False, "tool result was not an I-66 component", "bad_route")
    try:
        evaluated = datetime.fromisoformat(str(component["component_evaluated_at"]))
        total = Decimal(str(payload["total_usd"]))
        price = Decimal(str(component["price_usd"]))
    except (KeyError, ValueError):
        return _result(False, "I-66 tool result was incomplete", "result_mismatch")

    local = evaluated.astimezone(_EASTERN)
    wall_time = local.time().replace(tzinfo=None)
    direction = metadata.get("i66_direction")
    is_active = (
        local.weekday() < 5
        and local.date() not in _i66_holidays(local.year)
        and (
            (direction == "EB" and time(5, 30) <= wall_time < time(9, 30))
            or (direction == "WB" and time(15) <= wall_time < time(19))
        )
    )
    is_free = not is_active
    expected_source = "schedule_derived" if is_free else "observed"
    expected_method = "published_schedule" if is_free else "source_observation"
    if (
        component.get("source_kind") != expected_source
        or component.get("pricing_method") != expected_method
        or (is_free and (price != 0 or total != 0))
        or (not is_free and (price <= 0 or total <= 0))
    ):
        return _result(
            False, "I-66 state did not match the timed window", "state_mismatch"
        )

    folded = response.casefold()
    if is_free and (
        not re.search(r"\$0(?:\.00)?\b", response)
        or any(
            term in folded
            for term in (
                "invalid",
                "unavailable",
                "no data",
                "can't price",
                "cannot price",
            )
        )
    ):
        return _result(
            False, "free I-66 trip was not reported as $0", "bad_free_response"
        )
    if not is_free and f"${payload['total_usd']}" not in response:
        return _result(
            False, "response omitted the active I-66 toll", "ungrounded_price"
        )
    if not is_free and (
        not component.get("observed_at")
        or _eastern_time(str(component["observed_at"])) not in response
    ):
        return _result(
            False, "response omitted the I-66 observation time", "missing_time"
        )
    if style_error := _response_style_error(response, "I-66 response"):
        return style_error
    if context_error := _component_context_error(payload, response):
        return context_error
    return _result(True, "I-66 timed state and grounded response passed", "passed")


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
    turns: list[dict[str, Any]], metadata: dict[str, Any]
) -> list[EvaluationOutput]:
    clarification = metadata.get("expected_clarification")
    if clarification:
        if len(turns) != 2 or turns[0].get("calls"):
            return _result(
                False,
                "Tysons clarification must precede the annual tool call",
                "bad_clarification",
            )
        response = str(turns[0].get("response", ""))
        folded = response.casefold()
        if (
            any(str(choice).casefold() not in folded for choice in clarification)
            or "?" not in response
            or "restart" in folded
        ):
            return _result(
                False, "Tysons clarification omitted an exit", "bad_clarification"
            )
        if style_error := _response_style_error(response, "Tysons clarification"):
            return style_error
        calls = turns[1].get("calls", [])
        response = str(turns[1].get("response", ""))
    else:
        if len(turns) != 1:
            return _result(False, "expected one annual turn", "turn_count")
        calls = turns[0].get("calls", [])
        response = str(turns[0].get("response", ""))

    if len(calls) != 1 or calls[0].get("name") != "get_annual_toll_ballpark":
        return _result(False, "expected exactly one annual call", "tool_mismatch")
    call = calls[0]
    if call.get("input") != metadata["expected_call"]:
        return _result(False, "annual arguments did not match", "input_mismatch")
    payload = call.get("tool_result")
    if metadata.get("annual_behavior") == "no_complete_paired_days":
        if (
            call.get("is_error")
            or not isinstance(payload, dict)
            or payload.get("error") != "ballpark_unavailable"
            or payload.get("reason") != "no_complete_paired_days"
            or payload.get("coverage", {}).get("complete_pair_count") != 0
        ):
            return _result(False, "annual tool returned no scenarios", "tool_error")
        if not response.strip():
            return _result(False, "annual answer was blank", "blank_response")
        if style_error := _response_style_error(response, "annual response"):
            return style_error
        folded = response.casefold()
        if not (
            "complete" in folded
            and any(
                term in folded for term in ("unavailable", "insufficient", "cannot")
            )
        ):
            return _result(
                False,
                "response did not explain missing complete paired days",
                "ungrounded_unavailability",
            )
        income = payload.get("income", {})
        vehicle_cost = payload.get("vehicle_cost", {})
        assumptions = payload.get("assumptions", {})
        bindings: list[tuple[Decimal, tuple[tuple[str, ...], ...]]] = []
        if isinstance(income, dict):
            bindings.extend(
                (Decimal(str(value)), tuple((term,) for term in terms))
                for key, terms in (
                    ("gross_annual_usd", ("gross", "income")),
                    ("estimated_tax_usd", ("estimated", "tax")),
                    ("estimated_after_tax_usd", ("after", "tax")),
                )
                if (value := income.get(key)) is not None
            )
        if isinstance(vehicle_cost, dict):
            bindings.extend(
                (Decimal(str(value)), terms)
                for key, terms in (
                    (
                        "daily_usd",
                        (
                            ("vehicle",),
                            ("cost",),
                            (
                                "daily",
                                "per day",
                                "per office day",
                                "per commute day",
                                "per round trip",
                            ),
                        ),
                    ),
                    ("annual_usd", (("vehicle",), ("cost",), ("annual", "annually"))),
                )
                if (value := vehicle_cost.get(key)) is not None
            )
        if (
            isinstance(assumptions, dict)
            and (per_mile := assumptions.get("vehicle_cost_per_mile_usd")) is not None
        ):
            bindings.append(
                (Decimal(str(per_mile)), (("per",), ("mile",), ("vehicle",), ("cost",)))
            )
        for line in response.splitlines():
            first_money = re.search(r"\$\s*[\d,]+(?:\.\d+)?", line)
            for match in re.finditer(r"\$\s*([\d,]+(?:\.\d+)?)", line):
                value = Decimal(match.group(1).replace(",", ""))
                clause_start = line.rfind(";", 0, match.start()) + 1
                clause_end = line.find(";", match.end())
                clause = line[clause_start : None if clause_end < 0 else clause_end]
                context = (
                    line[: first_money.start()] + clause
                    if first_money is not None
                    else clause
                ).casefold()
                if value == 0 and re.search(
                    r"(?:do\s+not\s+treat\s+(?:the\s+)?(?:missing\s+)?toll(?:\s+amount)?\s+as\s*\$0|not\s+(?:treated|counted|reported)\s+as\s*\$0|\$0(?:\.00)?\s+is\s+not)",
                    line,
                    re.IGNORECASE,
                ):
                    continue
                matching_terms = [
                    terms for expected, terms in bindings if value == expected
                ]
                if not matching_terms:
                    return _result(
                        False,
                        "response invented financial values absent from the tool result",
                        "invented_financials",
                    )
                if not any(
                    all(
                        any(term in context for term in alternatives)
                        for alternatives in terms
                    )
                    for terms in matching_terms
                ):
                    return _result(
                        False,
                        "response relabeled a financial value from the tool result",
                        "misbound_money",
                    )
        return _result(
            True, "annual route validated but has no complete paired days", "passed"
        )
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
    coverage = payload.get("coverage", {})
    coverage_reported = "coverage" in folded
    if isinstance(coverage, dict):
        complete_pairs = coverage.get("complete_pair_count")
        eligible_dates = coverage.get("eligible_date_count")
        sample_status = str(payload.get("sample_status", "")).casefold()
        coverage_reported = coverage_reported or bool(
            isinstance(complete_pairs, int)
            and isinstance(eligible_dates, int)
            and sample_status
            and f"{complete_pairs} of {eligible_dates}" in folded
            and sample_status in folded
        )
    if not (
        "###" in response
        and "**" in response
        and "|" in response
        and ("one-third" in folded or "1/3" in response)
        and "0.685" in response
        and "straight-line" in folded
        and "tolled" in folded
        and "additional gross" in folded
        and "annualized daily-p50 toll scenario" in folded
        and "fixed" in folded
        and "tollchat" in folded
        and "historical" in folded
        and coverage_reported
        and "hov" not in folded
        and "aaa" not in folded
    ):
        return _result(
            False,
            "annual response omitted required hierarchy or assumptions",
            "missing_affordability_context",
        )

    scenarios = cast(dict[str, dict[str, Any]], payload["scenarios"])
    lines = [line.replace(",", "") for line in response.splitlines()]

    for label, scenario in scenarios.items():
        cells: list[str] = []
        for line in lines:
            candidate = [cell.strip() for cell in line.strip().strip("|").split("|")]
            scenario_label = re.sub(r"[*_`]", "", candidate[0]).strip()
            if line.lstrip().startswith("|") and re.match(
                rf"^{re.escape(label)}\b", scenario_label, re.IGNORECASE
            ):
                cells = candidate
                break
        row_values = (
            scenario["daily_total_tolled_commute_cost_usd"],
            scenario["average_monthly_tolled_commute_cost_usd"],
            scenario["annual_total_tolled_commute_cost_usd"],
            scenario["estimated_annual_income_after_tax_and_tolled_commute_usd"],
        )
        if len(cells) != 5 or any(
            f"${value}" not in cell
            for value, cell in zip(row_values, cells[1:], strict=True)
        ):
            return _result(
                False,
                f"{label.upper()} money was not bound to its scenario row",
                "misbound_money",
            )

    p50 = scenarios["p50"]
    required_contexts = (
        (
            "**",
            "p50",
            f"${p50['estimated_annual_income_after_tax_and_tolled_commute_usd']}",
        ),
        ("-", "gross", f"${payload['income']['gross_annual_usd']}"),
        ("-", "tax", f"${payload['income']['estimated_after_tax_usd']}"),
        ("-", "vehicle", f"${payload['vehicle_cost']['annual_usd']}"),
        (
            "-",
            "annualized daily-p50 toll scenario",
            f"${p50['daily_toll_usd']}",
            f"${p50['annual_toll_usd']}",
        ),
        ("-", "total annual", f"${p50['annual_total_tolled_commute_cost_usd']}"),
        (
            "-",
            "additional gross",
            f"${p50['additional_gross_income_to_offset_usd']}",
        ),
    )
    if any(
        not any(
            all(term.casefold() in line.casefold() for term in terms) for line in lines
        )
        for terms in required_contexts
    ):
        return _result(
            False,
            "annual money was not bound to its required lead or bullet",
            "misbound_money",
        )
    return _result(True, "annual tool call and affordability response passed", "passed")


def evaluate_annual_missing_inputs(
    turns: list[dict[str, Any]], metadata: dict[str, Any]
) -> list[EvaluationOutput]:
    if len(turns) != 1:
        return _result(False, "expected one missing-input turn", "turn_count")
    turn = turns[0]
    if turn.get("calls"):
        return _result(
            False, "annual tool called before inputs were complete", "premature_call"
        )
    response = str(turn.get("response", ""))
    if style_error := _response_style_error(response, "missing-input response"):
        return style_error
    folded = response.casefold()
    required_terms = {
        "outbound_departure_time": ("outbound", "leave"),
        "return_departure_time": ("return",),
        "weekdays": ("weekday", "days of the week", "office days"),
        "planned_annual_commute_days": (
            "annual commute day",
            "annual office day",
            "commute days per year",
            "office days per year",
            "days per year",
        ),
    }
    asks_for_values = "?" in response or any(
        term in folded for term in ("what ", "please provide", "could you provide")
    )
    if not asks_for_values or any(
        not any(term in folded for term in required_terms[field])
        for field in metadata["expected_missing_fields"]
    ):
        return _result(
            False,
            "response did not ask for every missing annual input",
            "missing_required_input",
        )
    if re.search(r"(?:what|which).{0,30}(?:income|salary)", folded):
        return _result(False, "response re-requested supplied income", "repeated_input")
    if "planned_annual_commute_days" in metadata["expected_missing_fields"] and not (
        "52" in response
        and "260" in response
        and "monday" in folded
        and "friday" in folded
        and any(term in folded for term in ("adjust", "up or down", "higher", "lower"))
    ):
        return _result(
            False,
            "response omitted the adjustable 52-week annual-day estimate",
            "missing_annual_day_estimate",
        )
    return _result(
        True, "all missing annual inputs requested before any call", "passed"
    )


def evaluate_annual_day_estimate(
    turns: list[dict[str, Any]], metadata: dict[str, Any]
) -> list[EvaluationOutput]:
    if len(turns) != 2:
        return _result(
            False, "expected annual-day confirmation and answer", "turn_count"
        )
    estimate_turn = turns[0]
    if estimate_turn.get("calls"):
        return _result(
            False, "annual tool called before days were confirmed", "premature_call"
        )
    response = str(estimate_turn.get("response", ""))
    if style_error := _response_style_error(response, "annual-day estimate"):
        return style_error
    folded = response.casefold()
    estimate = str(metadata["expected_estimated_annual_commute_days"])
    if not (
        "52" in response
        and estimate in response
        and any(term in folded for term in ("accept", "confirm", "use"))
        and any(term in folded for term in ("adjust", "up or down", "higher", "lower"))
    ):
        return _result(
            False,
            "response did not propose an adjustable 52-week estimate",
            "bad_annual_day_estimate",
        )
    return evaluate_annual_turn([turns[1]], metadata)


def evaluate_annual_income_clarification(
    turns: list[dict[str, Any]], metadata: dict[str, Any]
) -> list[EvaluationOutput]:
    if len(turns) != 2:
        return _result(False, "expected income clarification and answer", "turn_count")
    clarification = turns[0]
    if clarification.get("calls"):
        return _result(
            False, "annual tool called before income was selected", "premature_call"
        )
    response = str(clarification.get("response", ""))
    if style_error := _response_style_error(response, "income clarification"):
        return style_error
    folded = response.casefold()
    if not (
        (
            "?" in response
            or any(
                term in folded
                for term in (
                    "please give",
                    "please provide",
                    "could you provide",
                    "please choose",
                )
            )
        )
        and any(term in folded for term in ("one", "single"))
        and "annual" in folded
        and any(term in folded for term in ("gross", "income", "salary"))
    ):
        return _result(
            False,
            "response did not request one annual gross estimate",
            "bad_clarification",
        )
    amount = Decimal(str(metadata["forbidden_inferred_income_usd"]))
    forbidden = {
        f"${amount:f}",
        f"${amount:,.0f}",
        f"${amount:,.2f}",
    }
    selection = re.compile(
        rf"(?:i(?:'|\u2019)ll use|i will use|we(?:'|\u2019)ll use|we will use|using|assume)"
        rf".{{0,20}}(?:{'|'.join(re.escape(value) for value in forbidden)})",
        re.IGNORECASE,
    )
    if selection.search(response):
        return _result(
            False, "response selected an income from the range", "inferred_income"
        )
    return evaluate_annual_turn([turns[1]], metadata)


def evaluate_annual_route_unavailable(
    turns: list[dict[str, Any]], metadata: dict[str, Any]
) -> list[EvaluationOutput]:
    if len(turns) != 1:
        return _result(False, "expected one unavailable annual turn", "turn_count")
    turn = turns[0]
    calls = turn.get("calls", [])
    if len(calls) != 1 or calls[0].get("name") != "get_annual_toll_ballpark":
        return _result(False, "expected exactly one annual call", "tool_mismatch")
    call = calls[0]
    if call.get("input") != metadata["expected_call"]:
        return _result(False, "annual arguments did not match", "input_mismatch")
    payload = call.get("tool_result")
    if (
        call.get("is_error")
        or not isinstance(payload, dict)
        or payload.get("error") != "ballpark_unavailable"
        or payload.get("reason") != "route_unavailable"
    ):
        return _result(
            False, "annual tool did not return route unavailability", "tool_error"
        )
    expected_call = metadata["expected_call"]
    expected_status = metadata["expected_route_status"]
    for direction in ("outbound", "return"):
        actual = payload.get(direction)
        expected = expected_status[direction]
        expected_input = expected_call[direction]
        if not isinstance(actual, dict) or (
            actual.get("origin_point_id") != expected_input["origin_point_id"]
            or actual.get("destination_point_id")
            != expected_input["destination_point_id"]
            or actual.get("status") != expected["status"]
            or (actual.get("reason") or {}).get("code") != expected["reason_code"]
        ):
            return _result(
                False, "annual route status did not match", "result_mismatch"
            )

    response = str(turn.get("response", ""))
    if style_error := _response_style_error(response, "annual unavailable response"):
        return style_error
    folded = response.casefold()
    if (
        not any(term in folded for term in ("unavailable", "unsupported"))
        or "return" not in folded
    ):
        return _result(
            False,
            "response did not explain route unavailability",
            "missing_unavailability",
        )
    if any(term in folded for term in ("restart", "current-price", "current price")):
        return _result(False, "response offered a current-price restart", "bad_restart")
    allowed_income = Decimal(str(expected_call["gross_annual_income_usd"]))
    without_input = response
    for value in (
        f"${allowed_income:f}",
        f"${allowed_income:,.0f}",
        f"${allowed_income:,.2f}",
    ):
        without_input = without_input.replace(value, "")
    if re.search(r"\$\s*\d", without_input) or any(
        term in folded
        for term in (
            "p25",
            "p50",
            "p90",
            "after-tax",
            "after tax",
            "additional gross",
            "|",
        )
    ):
        return _result(
            False, "response invented unavailable financials", "invented_financials"
        )
    return _result(True, "annual route unavailability was safely explained", "passed")


def task_function(case: Case[str, str]) -> dict[str, Any]:
    agent = build_agent()
    turns = []
    response: object = ""
    previous_call_count = 0
    metadata = case.metadata or {}
    prompts = list(metadata.get("conversation", [str(case.input)]))
    if follow_up := metadata.get("follow_up"):
        prompts.append(str(follow_up))
    for prompt in prompts:
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
        if metadata.get("suite") == "fallback":
            return evaluate_fallback_turns(turns, metadata)
        if metadata.get("suite") == "unavailable":
            return evaluate_unavailable_turn(turns, metadata)
        if metadata.get("suite") == "i66_schedule":
            calls = turns[0].get("calls", []) if len(turns) == 1 else []
            return evaluate_i66_schedule_turn(
                cast(list[dict[str, Any]], calls),
                str(evaluation_case.actual_output or ""),
                metadata,
            )
        if metadata.get("suite") == "annual":
            behavior = metadata.get("annual_behavior")
            if behavior == "missing_inputs":
                return evaluate_annual_missing_inputs(turns, metadata)
            if behavior == "annual_day_estimate":
                return evaluate_annual_day_estimate(turns, metadata)
            if behavior == "income_clarification":
                return evaluate_annual_income_clarification(turns, metadata)
            if behavior == "route_unavailable":
                return evaluate_annual_route_unavailable(turns, metadata)
            return evaluate_annual_turn(turns, metadata)
        if metadata.get("expected_clarification"):
            return evaluate_current_clarification_turns(turns, metadata)
        calls = turns[0].get("calls", []) if len(turns) == 1 else []
        return evaluate_westpark_turn(
            cast(list[dict[str, Any]], calls),
            str(evaluation_case.actual_output or ""),
            metadata,
        )


def _configure_database() -> None:
    os.environ.setdefault("DB_NAME", "nova_toll")
    default_ca = _V2_ROOT / "infra/build/loader/rds-ca-bundle.pem"
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
        cases=load_cases(
            suite=suite,
            window=window,
            weekday=datetime.now(_EASTERN).isoweekday(),
        ),
        evaluators=[TollChatEvaluator()],
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
    ]
    assert [case.name for case in load_cases(window="i95_northbound")] == [
        "springfield-franconia-to-westpark",
        "dulles-airport-to-backlick-tp1sb-fallback",
        "dulles-to-reagan-current-price",
    ]
    assert [case.name for case in load_cases(window="i95_northbound", weekday=6)] == [
        "dulles-airport-to-backlick-tp1sb-fallback",
        "dulles-to-reagan-current-price",
    ]
    assert [case.name for case in load_cases(window="i95_reversal")] == [
        "dulles-airport-to-backlick-tp1sb-fallback",
        "old-keene-mill-to-reagan-i95-unavailable",
    ]
    assert [case.name for case in load_cases(window="i95_southbound")] == [
        "reagan-airport-to-westpark",
        "pentagon-eads-to-westpark",
        "old-keene-mill-to-reagan-i95-unavailable",
        "i66-west-to-route-7-current-price",
        "route-7-to-i495-south-current-price",
        "leesburg-to-washington-i395-current-price",
    ]
    assert [case.name for case in load_cases(window="greenway_eb_peak")] == [
        "i66-west-to-route-7-current-price",
        "route-7-to-i495-south-current-price",
    ]
    assert date(2026, 7, 3) in _i66_holidays(2026)
    assert date(2026, 7, 5) not in _i66_holidays(2026)
    assert date(2027, 7, 5) in _i66_holidays(2027)
    i66_free = rows[12]
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
    wb_active = rows[13]
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
    metadata = rows[2]
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
    assert evaluate_westpark_turn([success], good_response, metadata)[0].test_pass
    washington_current = rows[14]
    washington_current_call = json.loads(json.dumps(success))
    washington_current_call["input"] = washington_current["expected_call"]
    washington_current_call["tool_result"].update(
        origin_point_id="greenway:1:entry:EB", destination_point_id="i95:2249ND"
    )
    washington_current_turns = [
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
    unavailable_metadata = rows[11]
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
    assert evaluate_westpark_turn(
        [unavailable],
        "### 🚫 Current toll unavailable\n\nThe complete price cannot be provided as "
        "of 3:40 PM EDT.",
        unavailable_metadata,
    )[0].test_pass
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
    annual_turns = [{"response": annual_response, "calls": [annual_call]}]
    assert evaluate_annual_turn(annual_turns, annual)[0].test_pass
    washington_annual = rows[15]
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
    washington_annual_turns = [
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
    tysons = rows[6]
    tysons_call = {**annual_call, "input": tysons["expected_call"]}
    tysons_turns = [
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

    missing = rows[7]
    missing_turns = [
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

    estimate_case = rows[10]
    estimate_call = {**annual_call, "input": estimate_case["expected_call"]}
    estimate_turns = [
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

    income = rows[8]
    income_call = {**annual_call, "input": income["expected_call"]}
    income_turns = [
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

    unavailable_annual = rows[9]
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
    print("self-check ok (fixtures and evaluator pass/fail branches; no network)")


if __name__ == "__main__":
    if "--check" in sys.argv:
        _self_check()
    else:
        parser = ArgumentParser()
        parser.add_argument(
            "--window",
            choices=(
                "all",
                "i95_northbound",
                "i95_reversal",
                "i95_southbound",
                "greenway_eb_peak",
                "greenway_wb_peak",
            ),
            required=True,
        )
        parser.add_argument(
            "--suite",
            choices=(
                "all",
                "direct",
                "fallback",
                "unavailable",
                "annual",
                "i66_schedule",
            ),
            default="all",
        )
        args = parser.parse_args()
        main(args.window, args.suite)
