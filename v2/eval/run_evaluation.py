"""Code-grade TollChat v2 pricing and affordability regressions."""

from __future__ import annotations

import json
import os
import re
import sys
from argparse import ArgumentParser
from calendar import monthcalendar
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, TypedDict, cast
from zoneinfo import ZoneInfo

import boto3
from strands.types.content import Message, Messages
from strands_evals import Case, Experiment
from strands_evals.evaluators import Evaluator
from strands_evals.extractors import tools_use_extractor
from strands_evals.types.evaluation import EvaluationData, EvaluationOutput


class DatabaseEndpoint(TypedDict):
    Address: str
    Port: int


class DatabaseInstance(TypedDict):
    Endpoint: DatabaseEndpoint


_V2_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_V2_ROOT))

from agent.toll_agent import build_agent  # noqa: E402

type JSON = str | int | float | bool | list[JSON] | dict[str, JSON] | None

_CASES_PATH = Path(__file__).with_name("test-cases.jsonl")
_RESULTS_DIR = Path(__file__).with_name("results")
_SCHEDULED_CASES = {
    "i95_northbound": "springfield-franconia-to-westpark",
    "i95_southbound": "reagan-airport-pentagon-eads-westpark-parity",
    "i95_reversal": "old-keene-mill-to-reagan-i95-unavailable",
    "greenway_eb_peak": "i66-west-to-route-7-current-price",
    "greenway_wb_peak": "route-7-to-i495-south-current-price",
}
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
_CURRENCY_PATTERN = re.compile(
    r"(?P<sign_before>[+\-\u2212]?)\s*\$\s*"
    r"(?P<sign_after>[+\-\u2212]?)\s*(?P<amount>[\d,]+(?:\.\d+)?)"
)
_UNPRICED_CURRENCY_PATTERN = re.compile(
    r"(?:[$\uFF04]\s*(?:about\s+)?[\d,]+(?:\.\d+)?"
    r"|\bUSD\b\s*(?:about\s+)?[\d,]+(?:\.\d+)?"
    r"|\b[\d,]+(?:\.\d+)?\s+(?:dollars?|USD)\b)",
    re.IGNORECASE,
)
_MOVEMENT_EMOJIS = {
    "rising": "📈",
    "falling": "📉",
    "unchanged": "➡️",
    "mixed": "🔄",
}
_MAX_FAILURE_SUMMARIES = 10
_MAX_FAILURE_TEXT_LENGTH = 128
_UNKNOWN_CASE = "unknown_case"
_UNKNOWN_LABEL = "unknown_label"
_EVALUATION_FAILED = "evaluation_failed"


@dataclass(frozen=True)
class EvaluationFailed(SystemExit):
    """A completed evaluation report containing one or more failed cases."""

    passed_count: int
    case_count: int
    failures: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        SystemExit.__init__(self, "TollChat evaluation failed")
        object.__setattr__(
            self,
            "failures",
            tuple(
                (case_id, " ".join(reason.split())[:300])
                for case_id, reason in self.failures
            ),
        )


class EvaluationExecutionError(RuntimeError):
    """An unscored task or evaluator error that must use operational alarms."""


class EvaluationFailure(EvaluationFailed):
    """A failed evaluation with bounded metadata for the Lambda boundary."""

    failure_count: int
    failure_summaries: list[dict[str, str]]
    summaries_truncated: bool

    def __init__(
        self,
        failure_count: int,
        failure_summaries: list[dict[str, str]],
        summaries_truncated: bool,
        *,
        passed_count: int = 0,
        case_count: int | None = None,
        failures: tuple[tuple[str, str], ...] | None = None,
    ) -> None:
        super().__init__(
            passed_count=passed_count,
            case_count=failure_count if case_count is None else case_count,
            failures=(
                tuple(
                    (summary["case_id"], summary["reason"])
                    for summary in failure_summaries
                )
                if failures is None
                else failures
            ),
        )
        object.__setattr__(self, "failure_count", failure_count)
        object.__setattr__(self, "failure_summaries", failure_summaries)
        object.__setattr__(self, "summaries_truncated", summaries_truncated)


def _report_field(value: object, field: str) -> object:
    if type(value) is dict:
        return cast(dict[str, JSON], value).get(field)
    try:
        return getattr(value, field)
    except Exception:
        return None


def _indexed(value: object, index: int) -> object:
    if type(value) is list:
        values = cast(list[object], value)
    elif type(value) is tuple:
        values = cast(tuple[object, ...], value)
    else:
        return None
    return values[index] if 0 <= index < len(values) else None


def _bounded_text(value: object, fallback: str) -> str:
    return value[:_MAX_FAILURE_TEXT_LENGTH] if type(value) is str else fallback


def _failure_summary(report: object, index: int) -> dict[str, str]:
    case = _indexed(_report_field(report, "cases"), index)
    details = _indexed(_report_field(report, "detailed_results"), index)
    failed_detail = None
    if type(details) is list:
        detail_values = cast(list[object], details)
    elif type(details) is tuple:
        detail_values = cast(tuple[object, ...], details)
    else:
        detail_values = ()
    for detail in detail_values:
        if _report_field(detail, "test_pass") is False:
            failed_detail = detail
            break
    return {
        "case_id": _bounded_text(
            _report_field(case, "name"),
            _UNKNOWN_CASE,
        ),
        "label": _bounded_text(
            _report_field(failed_detail, "label"),
            _UNKNOWN_LABEL,
        ),
        "reason": _bounded_text(
            _report_field(failed_detail, "reason"),
            _EVALUATION_FAILED,
        ),
    }


def load_rows(path: Path = _CASES_PATH) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def load_cases(
    path: Path = _CASES_PATH,
    suite: str = "all",
    window: str = "all",
    weekday: int | None = None,
) -> list[Case[str, str]]:
    scheduled_case = None
    if suite == "scheduled":
        if window not in _SCHEDULED_CASES:
            raise ValueError("scheduled suite requires a specific timed window")
        scheduled_case = _SCHEDULED_CASES[window]
        if window == "i95_northbound" and weekday == 6:
            # Springfield-Westpark is a weekday-only regression.
            scheduled_case = "dulles-to-reagan-current-price"
    return [
        Case[str, str](
            name=row["id"],
            input=row["prompt"],
            expected_assertion=(
                row["expected_assertion"]
                + " Use pricing_profile vehicle_class=two_axle_passenger, "
                "payment_method=e_zpass, transponder_mode=toll unless the user "
                "explicitly changes that profile."
            )
            if suite == "scheduled"
            else None,
            metadata={**row, "active_window": window},
        )
        for row in load_rows(path)
        if (
            row["id"] == scheduled_case
            if suite == "scheduled"
            else suite == "all" or row.get("suite") == suite
        )
        if window == "all" or window in row.get("windows", [])
        if weekday is None or weekday in row.get("weekdays", range(1, 8))
    ]


def _result(passed: bool, reason: str, label: str) -> list[EvaluationOutput]:
    return [
        EvaluationOutput(
            score=float(passed), test_pass=passed, reason=reason, label=label
        )
    ]


def _currency_decimal(match: re.Match[str]) -> Decimal:
    sign = match.group("sign_before") or match.group("sign_after")
    value = Decimal(match.group("amount").replace(",", ""))
    return -value if sign in ("-", "\u2212") else value


def _response_style_error(response: str, subject: str) -> list[EvaluationOutput] | None:
    if not any(mark in response for mark in ("#", "**", "- ")):
        return _result(False, f"{subject} omitted Markdown", "missing_markdown")
    if not any(emoji in response for emoji in _EMOJIS):
        return _result(False, f"{subject} omitted an emoji", "missing_emoji")
    return None


def _check_annual_additional_gross_bindings(
    payload: dict[str, Any], response: str
) -> list[EvaluationOutput] | None:
    scenarios = payload.get("scenarios")
    if not isinstance(scenarios, dict):
        return None
    for line in response.splitlines():
        markers = list(re.finditer(r"\badditional\s+gross\b", line, re.IGNORECASE))
        for index, marker in enumerate(markers):
            labels = list(
                re.finditer(r"\b(p25|p50|p90)\b", line[: marker.start()], re.IGNORECASE)
            )
            if not labels:
                continue
            label = labels[-1].group(1).casefold()
            scenario = cast(dict[str, JSON], scenarios).get(label)
            if not isinstance(scenario, dict):
                continue
            expected = cast(dict[str, JSON], scenario).get(
                "additional_gross_income_to_offset_usd"
            )
            if expected is None:
                continue
            expected_value = Decimal(str(expected))
            next_marker = (
                markers[index + 1].start() if index + 1 < len(markers) else len(line)
            )
            if any(
                _currency_decimal(match) != expected_value
                for match in _CURRENCY_PATTERN.finditer(
                    line[marker.end() : next_marker]
                )
            ):
                return _result(
                    False,
                    f"{label.upper()} additional gross income was not bound to its scenario",
                    "misbound_money",
                )
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
        if isinstance(item, dict) and isinstance(
            cast(dict[str, JSON], item).get("json"), dict
        ):
            return cast(dict[str, Any], item["json"])
        if isinstance(item, dict) and isinstance(
            cast(dict[str, JSON], item).get("text"), str
        ):
            try:
                value = json.loads(cast(str, item["text"]))
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                return cast(dict[str, Any], value)
    return None


def _result_endpoints(payload: dict[str, Any]) -> tuple[object, object]:
    point_ids: JSON = payload.get("point_ids", [])
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
        cast(dict[str, JSON], component)
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
            direction = str(cast(dict[str, JSON], movement).get("direction", ""))
            required = [
                direction,
                _MOVEMENT_EMOJIS.get(direction, ""),
            ]
            if cast(dict[str, JSON], movement).get("net_change_percent") is not None:
                required.append(f"{str(movement['net_change_percent']).lstrip('+-')}%")
            if not _movement_value_is_reported(
                response, cast(dict[str, JSON], movement).get("net_change_usd")
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
        cast(
            Callable[[Messages], list[dict[str, JSON]]],
            # The installed Strands extractor omits its argument/list annotations.
            tools_use_extractor.extract_agent_tools_used_from_messages,  # pyright: ignore[reportUnknownMemberType]
        )(messages),
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
        result = cast(dict[str, Any], results.get(tool_id) or {})
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
        and cast(dict[str, JSON], payload).get("error") == "pricing_unavailable"
        and cast(dict[str, JSON], payload).get("reason") == "incomplete_route_price"
    )
    if "error" in payload and not allowed_unavailable:
        return _result(False, "current-price tool returned an error", "tool_error")
    expected = metadata["expected_call"]
    actual_origin, actual_destination = _result_endpoints(
        cast(dict[str, JSON], payload)
    )
    if (
        actual_origin != expected["origin_point_id"]
        or actual_destination != expected["destination_point_id"]
    ):
        return _result(False, "tool result endpoints did not match", "result_mismatch")

    if "total_usd" not in payload:
        if _UNPRICED_CURRENCY_PATTERN.search(response):
            return _result(
                False,
                "response invented a toll for an unpriced route",
                "invented_financials",
            )
        if cast(dict[str, JSON], payload).get("status") in metadata.get(
            "allowed_route_statuses", []
        ):
            folded = response.casefold()
            terms = (
                ("unavailable", "closed")
                if cast(dict[str, JSON], payload).get("status")
                == "currently_unavailable"
                else ("stale", "unknown", "inconclusive")
            )
            if not any(term in folded for term in terms):
                return _result(
                    False,
                    "response did not explain route availability",
                    "ungrounded_unavailability",
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
                _eastern_time(cast(str, component["observed_at"]))
                for component in cast(
                    list[dict[str, JSON]],
                    cast(dict[str, JSON], payload).get("unavailable_components", []),
                )
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
        return _result(False, "response omitted the current toll", "ungrounded_price")
    if len(
        cast(list[JSON], cast(dict[str, JSON], payload).get("components", []))
    ) != metadata.get("expected_component_count", 2):
        return _result(
            False, "priced route did not contain two components", "bad_route"
        )
    if not _EASTERN_TIME.search(response):
        return _result(False, "response omitted observation time", "missing_time")

    if style_error := _response_style_error(response, "response"):
        return style_error
    components = [
        cast(dict[str, JSON], component)
        for component in cast(
            list[JSON], cast(dict[str, JSON], payload).get("components", [])
        )
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
    if context_error := _component_context_error(
        cast(dict[str, JSON], payload), response
    ):
        return context_error
    return _result(True, "exact route call and grounded response passed", "passed")


def _dca_pentagon_price_projection(
    payload: dict[str, Any],
) -> tuple[Decimal, tuple[tuple[object, ...], ...]] | None:
    fields = (
        "route_step_id",
        "facility",
        "source_kind",
        "pricing_method",
        "price_usd",
        "od_pair_id",
        "proxy_od_pair_id",
    )
    components: JSON = payload.get("components")
    if (
        not isinstance(components, list)
        or len(components) != 2
        or not all(isinstance(component, dict) for component in components)
    ):
        return None
    try:
        total = Decimal(str(cast(dict[str, JSON], payload)["total_usd"]))
    except (InvalidOperation, ValueError):
        return None
    if not total.is_finite() or total < 0:
        return None

    projection: list[tuple[object, ...]] = []
    component_total = Decimal()
    for component in cast(list[dict[str, JSON]], components):
        if any(
            field not in component for field in fields if field != "proxy_od_pair_id"
        ):
            return None
        if (
            not all(
                isinstance(component[field], str) and component[field]
                for field in (
                    "route_step_id",
                    "facility",
                    "source_kind",
                    "pricing_method",
                )
            )
            or type(component["od_pair_id"]) is not int
            or component["od_pair_id"] <= 0
        ):
            return None
        proxy_od_pair_id = component.get("proxy_od_pair_id")
        if proxy_od_pair_id is not None and (
            type(proxy_od_pair_id) is not int or proxy_od_pair_id <= 0
        ):
            return None
        try:
            price = Decimal(str(component["price_usd"]))
        except (InvalidOperation, ValueError):
            return None
        if not price.is_finite():
            return None
        if (
            price < 0
            or component["facility"] != "i95_i495"
            or (
                component["source_kind"] == "observed"
                and (
                    component["pricing_method"] != "source_observation"
                    or proxy_od_pair_id is not None
                )
            )
            or (
                component["source_kind"] == "modeled"
                and (
                    component["pricing_method"] != "identity_proxy_v1"
                    or proxy_od_pair_id is None
                )
            )
            or component["source_kind"] not in {"observed", "modeled"}
        ):
            return None
        component_total += price
        projection.append(
            tuple(
                price
                if field == "price_usd"
                else proxy_od_pair_id
                if field == "proxy_od_pair_id"
                else component[field]
                for field in fields
            )
        )
    return (total, tuple(projection)) if total == component_total else None


def evaluate_dca_pentagon_parity_turns(
    turns: list[dict[str, Any]], metadata: dict[str, Any]
) -> list[EvaluationOutput]:
    expected_calls = cast(list[dict[str, Any]], metadata["expected_calls"])
    if calls_error := _expected_calls_error(turns, expected_calls):
        return calls_error

    payloads: list[dict[str, Any]] = []
    for turn, expected_call in zip(turns, expected_calls, strict=True):
        call = cast(dict[str, Any], turn["calls"][0])
        payload = call.get("tool_result")
        if isinstance(payload, dict) and "error" not in payload:
            components = cast(dict[str, JSON], payload).get("components")
            if not isinstance(components, list):
                return _result(
                    False,
                    "current-price parity projection was malformed",
                    "malformed_projection",
                )
            if (
                cast(dict[str, JSON], payload).get("origin_point_id")
                != expected_call["origin_point_id"]
                or cast(dict[str, JSON], payload).get("destination_point_id")
                != expected_call["destination_point_id"]
            ):
                return _result(
                    False, "tool result endpoints did not match", "result_mismatch"
                )
        result = evaluate_westpark_turn(
            cast(list[dict[str, Any]], turn["calls"]),
            str(turn.get("response", "")),
            {**metadata, "expected_call": expected_call},
        )
        if not result[0].test_pass:
            return result
        payloads.append(cast(dict[str, Any], payload))

    first_projection = _dca_pentagon_price_projection(payloads[0])
    second_projection = _dca_pentagon_price_projection(payloads[1])
    if first_projection is None or second_projection is None:
        return _result(
            False,
            "current-price parity projection was malformed",
            "malformed_projection",
        )
    if first_projection != second_projection:
        return _result(
            False, "corrected route toll projection did not match", "parity_mismatch"
        )
    return _result(True, "corrected route toll parity passed", "passed")


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
    components = cast(dict[str, JSON], payload).get("components")
    if not isinstance(components, list) or len(components) != 1:
        return _result(False, "I-66 trip did not have one component", "bad_route")
    component = components[0]
    if (
        not isinstance(component, dict)
        or cast(dict[str, JSON], component).get("facility") != "i66"
    ):
        return _result(False, "tool result was not an I-66 component", "bad_route")
    try:
        evaluated = datetime.fromisoformat(str(component["component_evaluated_at"]))
        total = Decimal(str(cast(dict[str, JSON], payload)["total_usd"]))
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
        cast(dict[str, JSON], component).get("source_kind") != expected_source
        or cast(dict[str, JSON], component).get("pricing_method") != expected_method
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
        not cast(dict[str, JSON], component).get("observed_at")
        or _eastern_time(str(component["observed_at"])) not in response
    ):
        return _result(
            False, "response omitted the I-66 observation time", "missing_time"
        )
    if style_error := _response_style_error(response, "I-66 response"):
        return style_error
    if context_error := _component_context_error(
        cast(dict[str, JSON], payload), response
    ):
        return context_error
    return _result(True, "I-66 timed state and grounded response passed", "passed")


def evaluate_fallback_turns(
    turns: list[dict[str, Any]], metadata: dict[str, Any]
) -> list[EvaluationOutput]:
    if calls_error := _expected_calls_error(turns, metadata["expected_calls"]):
        return calls_error

    window = metadata.get("active_window")
    initial_payload = turns[0]["calls"][0].get("tool_result")
    if not isinstance(initial_payload, dict) or cast(
        dict[str, JSON], initial_payload
    ).get("status") != ("currently_unavailable"):
        return _result(False, "initial result was not unavailable", "bad_route")
    reason = cast(dict[str, JSON], initial_payload).get("reason", {})
    details = (
        cast(dict[str, JSON], reason).get("details", {})
        if isinstance(reason, dict)
        else {}
    )
    if (
        cast(dict[str, JSON], reason).get("code")
        != metadata["expected_reasons"].get(window)
        or cast(dict[str, JSON], details).get("availability")
        != metadata["expected_availability"].get(window)
        or cast(dict[str, JSON], details).get("required_i95_directions")
        != metadata["expected_required_i95_directions"]
        or cast(dict[str, JSON], initial_payload).get("general_purpose_gaps")
        != [
            {
                "connection_id": "source:i95_shared:Southbound:182SO:205SD",
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
    if _result_endpoints(cast(dict[str, JSON], accepted_payload)) != (
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
    if context_error := _component_context_error(
        cast(dict[str, JSON], accepted_payload), accepted_response
    ):
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
        or cast(dict[str, JSON], payload).get("status") != "currently_unavailable"
    ):
        return _result(False, "tool result was not unavailable", "bad_route")
    expected = metadata["expected_call"]
    if _result_endpoints(cast(dict[str, JSON], payload)) != (
        expected["origin_point_id"],
        expected["destination_point_id"],
    ):
        return _result(
            False, "unavailable result endpoints did not match", "result_mismatch"
        )
    reason = cast(dict[str, JSON], payload).get("reason", {})
    details = (
        cast(dict[str, JSON], reason).get("details", {})
        if isinstance(reason, dict)
        else {}
    )
    if (
        cast(dict[str, JSON], reason).get("code")
        != metadata["expected_reasons"].get(window)
        or cast(dict[str, JSON], details).get("availability")
        != metadata["expected_availability"].get(window)
        or cast(dict[str, JSON], details).get("required_i95_directions")
        != metadata["expected_required_i95_directions"]
    ):
        return _result(False, "unavailability reason did not match", "bad_route")
    if any(
        cast(dict[str, JSON], gap).get("fallback_required") is True
        for gap in cast(
            list[JSON], cast(dict[str, JSON], payload).get("general_purpose_gaps", [])
        )
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
    no_complete_paired_days = metadata.get(
        "annual_behavior"
    ) == "no_complete_paired_days" or (
        isinstance(payload, dict)
        and cast(dict[str, JSON], payload).get("error") == "ballpark_unavailable"
        and cast(dict[str, JSON], payload).get("reason") == "no_complete_paired_days"
    )
    if no_complete_paired_days:
        if (
            call.get("is_error")
            or not isinstance(payload, dict)
            or cast(dict[str, JSON], payload).get("error") != "ballpark_unavailable"
            or cast(dict[str, JSON], payload).get("reason") != "no_complete_paired_days"
            or cast(
                dict[str, JSON], cast(dict[str, JSON], payload).get("coverage", {})
            ).get("complete_pair_count")
            != 0
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
        income = cast(dict[str, JSON], payload).get("income", {})
        vehicle_cost = cast(dict[str, JSON], payload).get("vehicle_cost", {})
        assumptions = cast(dict[str, JSON], payload).get("assumptions", {})
        bindings: list[tuple[Decimal, tuple[tuple[str, ...], ...]]] = []
        if isinstance(income, dict):
            bindings.extend(
                (Decimal(str(value)), tuple((term,) for term in terms))
                for key, terms in (
                    ("gross_annual_usd", ("gross", "income")),
                    ("estimated_tax_usd", ("estimated", "tax")),
                    ("estimated_after_tax_usd", ("after", "tax")),
                )
                if (value := cast(dict[str, JSON], income).get(key)) is not None
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
                if (value := cast(dict[str, JSON], vehicle_cost).get(key)) is not None
            )
        if (
            isinstance(assumptions, dict)
            and (
                per_mile := cast(dict[str, JSON], assumptions).get(
                    "vehicle_cost_per_mile_usd"
                )
            )
            is not None
        ):
            bindings.append(
                (Decimal(str(per_mile)), (("per",), ("mile",), ("vehicle",), ("cost",)))
            )
        for line in response.splitlines():
            first_money = _CURRENCY_PATTERN.search(line)
            for match in _CURRENCY_PATTERN.finditer(line):
                value = _currency_decimal(match)
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
        or not isinstance(cast(dict[str, JSON], payload).get("scenarios"), dict)
    ):
        return _result(False, "annual tool returned no scenarios", "tool_error")

    if style_error := _response_style_error(response, "annual response"):
        return style_error
    folded = response.casefold()
    coverage = cast(dict[str, JSON], payload).get("coverage", {})
    coverage_reported = "coverage" in folded
    if isinstance(coverage, dict):
        complete_pairs = cast(dict[str, JSON], coverage).get("complete_pair_count")
        eligible_dates = cast(dict[str, JSON], coverage).get("eligible_date_count")
        sample_status = str(
            cast(dict[str, JSON], payload).get("sample_status", "")
        ).casefold()
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
    if additional_gross_error := _check_annual_additional_gross_bindings(
        cast(dict[str, JSON], payload), response
    ):
        return additional_gross_error
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
        or cast(dict[str, JSON], payload).get("error") != "ballpark_unavailable"
        or cast(dict[str, JSON], payload).get("reason") != "route_unavailable"
    ):
        return _result(
            False, "annual tool did not return route unavailability", "tool_error"
        )
    expected_call = metadata["expected_call"]
    expected_status = metadata["expected_route_status"]
    for direction in ("outbound", "return"):
        actual = cast(dict[str, JSON], payload).get(direction)
        expected = expected_status[direction]
        expected_input = expected_call[direction]
        if not isinstance(actual, dict) or (
            cast(dict[str, JSON], actual).get("origin_point_id")
            != expected_input["origin_point_id"]
            or cast(dict[str, JSON], actual).get("destination_point_id")
            != expected_input["destination_point_id"]
            or cast(dict[str, JSON], actual).get("status") != expected["status"]
            or cast(
                dict[str, JSON], cast(dict[str, JSON], actual).get("reason") or {}
            ).get("code")
            != expected["reason_code"]
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


def _check_annual_alternative_call(
    call: dict[str, Any], metadata: dict[str, Any]
) -> list[EvaluationOutput] | None:
    expected_call = metadata["expected_initial_call"]
    if call.get("name") != "get_annual_toll_ballpark":
        return _result(False, "expected exactly one annual call", "tool_mismatch")
    if call.get("input") != expected_call:
        return _result(False, "annual arguments did not match", "input_mismatch")
    payload = call.get("tool_result")
    if (
        call.get("is_error")
        or not isinstance(payload, dict)
        or cast(dict[str, JSON], payload).get("error") != "ballpark_unavailable"
        or cast(dict[str, JSON], payload).get("reason") != "route_unavailable"
    ):
        return _result(
            False, "annual tool did not return route unavailability", "tool_error"
        )

    expected_status = metadata["expected_route_status"]
    for direction in ("outbound", "return"):
        actual = cast(dict[str, JSON], payload).get(direction)
        expected = expected_status[direction]
        expected_input = expected_call[direction]
        if not isinstance(actual, dict) or (
            cast(dict[str, JSON], actual).get("origin_point_id")
            != expected_input["origin_point_id"]
            or cast(dict[str, JSON], actual).get("destination_point_id")
            != expected_input["destination_point_id"]
            or cast(dict[str, JSON], actual).get("status") != expected["status"]
            or cast(
                dict[str, JSON], cast(dict[str, JSON], actual).get("reason") or {}
            ).get("code")
            != expected["reason_code"]
        ):
            return _result(
                False, "annual route status did not match", "result_mismatch"
            )

    reason = cast(dict[str, JSON], payload["outbound"]).get("reason")
    details = (
        cast(dict[str, JSON], reason).get("details", {})
        if isinstance(reason, dict)
        else {}
    )
    alternatives = cast(dict[str, JSON], details).get("alternatives")
    actual_alternatives = (
        [
            (
                cast(dict[str, JSON], alternative).get("point_id"),
                cast(dict[str, JSON], alternative).get("label"),
            )
            for alternative in alternatives
            if isinstance(alternative, dict)
        ]
        if isinstance(alternatives, list)
        else []
    )
    expected_alternatives = [
        (alternative["point_id"], alternative["label"])
        for alternative in metadata["expected_alternatives"]
    ]
    if [point_id for point_id, _label in actual_alternatives] != metadata[
        "expected_alternative_ids"
    ] or actual_alternatives != expected_alternatives:
        return _result(
            False,
            "annual tool returned unexpected alternatives",
            "result_mismatch",
        )
    return None


def _check_annual_alternative_response(
    response: str, metadata: dict[str, Any], returned_alternatives: list[dict[str, Any]]
) -> list[EvaluationOutput] | None:
    folded = response.casefold()
    names_by_option = [
        {
            str(term).casefold()
            for term in (
                *terms,
                alternative_id,
                alternative["label"],
                *alternative.get("aliases", []),
            )
            if str(term).strip()
        }
        for terms, alternative_id, alternative in zip(
            metadata["expected_alternative_terms"],
            metadata["expected_alternative_ids"],
            returned_alternatives,
            strict=True,
        )
    ]
    unique_names = {
        name
        for option_names in names_by_option
        for name in option_names
        if sum(name in other_names for other_names in names_by_option) == 1
    }
    if any(
        not any(name in folded for name in option_names & unique_names)
        for option_names in names_by_option
    ):
        return _result(
            False,
            "response omitted a returned annual alternative",
            "missing_alternative",
        )
    if not any(
        term in folded
        for term in ("choose", "select", "which", "pick", "prefer", "would you like")
    ):
        return _result(
            False,
            "response did not wait for an alternative selection",
            "missing_selection",
        )
    if any(
        term in folded
        for term in ("p25", "p50", "p90", "annualized daily", "total annual")
    ):
        return _result(
            False,
            "response invented annual financial scenarios before selection",
            "invented_financials",
        )
    allowed_income = Decimal(
        str(metadata["expected_initial_call"]["gross_annual_income_usd"])
    )
    for match in _CURRENCY_PATTERN.finditer(response):
        value = _currency_decimal(match)
        if value != allowed_income:
            return _result(
                False,
                "response invented financial values before selection",
                "invented_financials",
            )
    return None


def evaluate_annual_relaxed(
    turns: list[dict[str, Any]], metadata: dict[str, Any]
) -> list[EvaluationOutput]:
    return evaluate_annual_turn(turns, metadata)


def evaluate_annual_confirmation(
    turns: list[dict[str, Any]], metadata: dict[str, Any]
) -> list[EvaluationOutput]:
    if len(turns) != 2 or turns[0].get("calls"):
        return _result(
            False,
            "divergent annual legs must be confirmed before the tool call",
            "bad_confirmation",
        )
    response = str(turns[0].get("response", ""))
    folded = response.casefold()
    terms = metadata.get("expected_confirmation_terms", [])
    asks_confirmation = "?" in response or any(
        term in folded
        for term in ("should i", "would you like", "shall i", "confirm", "combine")
    )
    if not asks_confirmation or any(
        str(term).casefold() not in folded for term in terms
    ):
        return _result(
            False,
            "divergent annual legs were not clearly confirmed",
            "bad_confirmation",
        )
    return evaluate_annual_relaxed([turns[1]], metadata)


def evaluate_annual_alternatives(
    turns: list[dict[str, Any]], metadata: dict[str, Any]
) -> list[EvaluationOutput]:
    selection = metadata.get("annual_behavior") == "alternative_selection"
    if len(turns) != (2 if selection else 1):
        return _result(
            False,
            "annual alternative flow had the wrong number of turns",
            "turn_count",
        )
    first = turns[0]
    calls = first.get("calls", [])
    if len(calls) != 1:
        return _result(
            False,
            "annual alternatives were not obtained with one call",
            "tool_mismatch",
        )
    if call_error := _check_annual_alternative_call(calls[0], metadata):
        return call_error
    if response_error := _check_annual_alternative_response(
        str(first.get("response", "")),
        metadata,
        calls[0]["tool_result"]["outbound"]["reason"]["details"]["alternatives"],
    ):
        return response_error
    if not selection:
        return _result(True, "annual alternatives were safely presented", "passed")

    selected = turns[1]
    selected_calls = selected.get("calls", [])
    if len(selected_calls) != 1 or selected_calls[0].get("name") != (
        "get_annual_toll_ballpark"
    ):
        return _result(
            False,
            "annual selection must make exactly one final call",
            "tool_mismatch",
        )
    if selected_calls[0].get("input") != metadata["expected_call"]:
        return _result(
            False,
            "selected annual alternative did not retain all inputs",
            "input_mismatch",
        )
    return evaluate_annual_relaxed([selected], metadata)


def task_function(case: Case[str, str]) -> dict[str, Any]:
    agent = build_agent()
    turns: list[dict[str, JSON]] = []
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
            {
                "response": str(response),
                "calls": cast(list[JSON], all_calls[previous_call_count:]),
            }
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
            calls: object = turns[0].get("calls", []) if len(turns) == 1 else []
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
            if behavior in {"route_alternatives", "alternative_selection"}:
                return evaluate_annual_alternatives(turns, metadata)
            if behavior in {
                "independent_legs",
                "divergent_confirmation",
                "ordinary_reversal",
            }:
                if behavior == "divergent_confirmation":
                    return evaluate_annual_confirmation(turns, metadata)
                return evaluate_annual_relaxed(turns, metadata)
            return evaluate_annual_turn(turns, metadata)
        if metadata.get("dca_pentagon_parity"):
            return evaluate_dca_pentagon_parity_turns(turns, metadata)
        if metadata.get("expected_clarification"):
            return evaluate_current_clarification_turns(turns, metadata)
        calls: object = turns[0].get("calls", []) if len(turns) == 1 else []
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
        # Optional boto3 service overloads lack stubs; the RDS response is typed.
        instance = boto3.client("rds", region_name="us-east-1").describe_db_instances(  # pyright: ignore[reportUnknownMemberType]
            DBInstanceIdentifier="nova-toll-db"
        )["DBInstances"][0]
        endpoint = cast(DatabaseInstance, instance)["Endpoint"]
        os.environ["DB_HOST"] = endpoint["Address"]
        os.environ["DB_PORT"] = str(endpoint["Port"])


def main(
    window: str,
    suite: str = "all",
    output_dir: Path | str | None = None,
    on_report: Callable[[object], None] | None = None,
) -> None:
    cases = load_cases(
        suite=suite, window=window, weekday=datetime.now(_EASTERN).isoweekday()
    )
    if suite == "scheduled" and len(cases) != 1:
        raise EvaluationExecutionError("Scheduled evaluation requires exactly one case")
    _configure_database()
    evaluators: list[Evaluator[str, str]] = [TollChatEvaluator()]
    task = task_function
    if suite == "scheduled":
        from eval import simulated

        evaluators = list(simulated.evaluators())
        task = simulated.task_function
    report = Experiment[str, str](
        cases=cases,
        evaluators=evaluators,
    ).run_evaluations(task)
    results_dir = _RESULTS_DIR if output_dir is None else Path(output_dir)
    results_dir.mkdir(parents=True, exist_ok=True)
    report.to_file(str(results_dir / f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"))
    report.display(include_input=False)
    if on_report is not None:
        on_report(report)
    if suite == "scheduled" and len(report.test_passes) != 3:
        raise EvaluationExecutionError("TollChat evaluation execution failed")
    if not all(report.test_passes):
        if any(
            not passed and not detailed_results
            for passed, detailed_results in zip(
                report.test_passes, report.detailed_results, strict=True
            )
        ):
            raise EvaluationExecutionError("TollChat evaluation execution failed")
        failed_indexes = [
            index for index, passed in enumerate(report.test_passes) if not passed
        ]
        if suite == "scheduled":
            # Strands emits one report row per judge; this is still one case.
            summaries = [_failure_summary(report, index) for index in failed_indexes]
            reason = " | ".join(
                f"{cast(list[dict[str, object]], _report_field(report, 'cases'))[index]['evaluator']}: {summary['reason']}"
                for index, summary in zip(failed_indexes, summaries, strict=True)
            )
            raise EvaluationFailure(
                failure_count=1,
                failure_summaries=summaries,
                summaries_truncated=False,
                passed_count=0,
                case_count=1,
                failures=((summaries[0]["case_id"], reason),),
            )
        reasons = _report_field(report, "reasons")
        legacy_failures = (
            tuple(
                (cast(str, case["name"]), reason)
                for case, passed, reason in zip(
                    cast(list[dict[str, object]], _report_field(report, "cases")),
                    report.test_passes,
                    cast(list[str] | tuple[str, ...], reasons),
                    strict=True,
                )
                if not passed
            )
            if isinstance(reasons, (list, tuple))
            else None
        )
        raise EvaluationFailure(
            failure_count=len(failed_indexes),
            failure_summaries=[
                _failure_summary(report, index)
                for index in failed_indexes[:_MAX_FAILURE_SUMMARIES]
            ],
            summaries_truncated=len(failed_indexes) > _MAX_FAILURE_SUMMARIES,
            passed_count=sum(report.test_passes),
            case_count=len(report.test_passes),
            failures=legacy_failures,
        )


if __name__ == "__main__":
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
            "scheduled",
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
