"""Code-graded Issue #17 regressions for the direction-aware 95/495 junction."""

from __future__ import annotations

import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from zoneinfo import ZoneInfo

_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT))

from strands.types.content import Message, Messages  # noqa: E402
from strands_evals import Case, Experiment  # noqa: E402
from strands_evals.evaluators import Evaluator  # noqa: E402
from strands_evals.extractors import tools_use_extractor  # noqa: E402
from strands_evals.types.evaluation import (  # noqa: E402
    EvaluationData,
    EvaluationOutput,
)

from agent.dev_chat import configure_local_pricing_env  # noqa: E402
from agent.toll_agent import build_agent, plan_toll_route  # noqa: E402

_CASES_PATH = Path(__file__).resolve().parent / "test-cases.jsonl"
_RESULTS_DIR = Path(__file__).resolve().parents[2] / "results"
_FORBIDDEN_TOTAL_RE = re.compile(
    r"\b(?:subtotal|final total|combined total|complete total|final price)\b|"
    r"\b(?:total|complete(?: trip)? price)\s*"
    r"(?:is|:|comes to|equals)\s*\$",
    re.I,
)
_ARITHMETIC_RE = re.compile(r"\$\s*\d+(?:\.\d{2})?\s*[+=]", re.I)
_DOLLAR_AMOUNT_RE = re.compile(r"\$\s*(\d+(?:\.\d{1,2})?)")
_ZERO_DOLLARS_RE = re.compile(r"\bzero[- ]dollars?\b", re.I)
_FREE_CLAIM_RE = re.compile(
    r"\b(?:junction|gap)\s+(?:is|was)\s+free\b|"
    r"\btreat(?:ed|ing)?\s+(?:the\s+)?(?:junction|gap)\s+as\s+free\b|"
    r"\b(?:junction|gap)\s+costs?\s+nothing\b",
    re.I,
)
_UNAVAILABLE_RE = re.compile(r"\b(?:unavailable|cannot\s+(?:provide|price))\b", re.I)
_GENERAL_PURPOSE_RE = re.compile(
    r"\bI-95\s+general[- ]purpose lanes\b|"
    r"\bI-95(?:/395)?(?:\s+Express Lanes)?[^.;\n]{0,80};\s*"
    r"(?:the\s+)?general[- ]purpose lanes\b",
    re.I,
)
_BOTH_DIRECTIONS_CLOSED_RE = re.compile(
    r"\b(?:both\s+I-95(?:/395)?(?:\s+Express Lanes)?\s+directions?\s+"
    r"(?:(?:are|were)\s+)?closed|I-95(?:/395)?(?:\s+Express Lanes)?\s+"
    r"(?:are|were)\s+closed\s+in\s+both\s+directions?)\b",
    re.I,
)
_MONETARY_FIELDS = {"legs", "price_usd", "total_usd", "tolls"}


def load_cases(path: Path = _CASES_PATH) -> list[Case[str, str]]:
    cases: list[Case[str, str]] = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        row: dict[str, Any] = json.loads(line)
        cases.append(
            Case[str, str](
                name=row["id"],
                input=row["conversation"][0]["content"],
                expected_trajectory=[call["tool"] for call in row["expected_calls"]],
                metadata=row,
            )
        )
    return cases


def _result(passed: bool, reason: str, label: str) -> list[EvaluationOutput]:
    return [
        EvaluationOutput(
            score=float(passed), test_pass=passed, reason=reason, label=label
        )
    ]


def _trace_messages(traces: list[dict[str, Any]]) -> Messages:
    def walk(trace: dict[str, Any]) -> Messages:
        messages = [cast(Message, trace["message"])] if trace.get("message") else []
        for child in trace.get("children", []):
            messages.extend(walk(child))
        return messages

    return [message for trace in traces for message in walk(trace)]


def _extract_tool_calls(messages: Messages) -> list[dict[str, Any]]:
    return tools_use_extractor.extract_agent_tools_used_from_messages(  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        messages
    )


def _tool_result(call: dict[str, Any]) -> dict[str, Any] | None:
    value = call.get("tool_result")
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return None
    return cast(dict[str, Any], value) if isinstance(value, dict) else None


def task_function(case: Case[str, str]) -> dict[str, Any]:
    agent = build_agent()
    response = agent(str(case.input))
    summary: dict[str, Any] = response.metrics.get_summary()
    traces = cast(list[dict[str, Any]], summary.get("traces", []))
    calls = _extract_tool_calls(_trace_messages(traces))
    return {"output": str(response), "trajectory": [{"calls": calls}]}


def _inputs_match(actual: object, expected: dict[str, Any]) -> bool:
    if not isinstance(actual, dict):
        return False
    actual_input = cast(dict[str, Any], actual)
    return all(actual_input.get(key) == value for key, value in expected.items())


def _planned_calls(plan: dict[str, Any]) -> list[dict[str, Any]]:
    at_time = plan.get("at_time")
    calls: list[dict[str, Any]] = []
    for step in plan.get("steps", []):
        if step.get("kind") == "junction":
            calls.append(
                {
                    "tool": step.get("tool"),
                    "input": {
                        "location": step.get("location"),
                        "movement": step.get("movement"),
                        "at_time": at_time,
                    },
                }
            )
        elif step.get("kind") == "priced":
            calls.append(
                {
                    "tool": step.get("tool"),
                    "input": {
                        "origin": step.get("origin"),
                        "destination": step.get("destination"),
                        "at_time": at_time,
                    },
                }
            )
    return calls


def evaluate_junction_calls(
    calls: list[dict[str, Any]], metadata: dict[str, Any]
) -> list[EvaluationOutput]:
    """Grade exact ordered calls and their captured results."""
    if (
        metadata["id"] == "junction-alias-control"
        and calls
        and calls[0].get("name") == "plan_toll_route"
        and (_tool_result(calls[0]) or {}).get("error")
    ):
        calls = calls[1:]
    names = [str(call.get("name")) for call in calls]
    if "i95_route" in names:
        return _result(
            False, "ordinary i95_route overshot the junction", "overshoot_call"
        )
    if metadata["id"] == "junction-inside-gap" and "i495_route" in names:
        return _result(False, "inside-gap plan called i495_route", "inside_gap_i495")
    if names.count("i95_junction_leg") != 1:
        return _result(
            False,
            f"expected exactly one junction call, got {names.count('i95_junction_leg')}",
            "junction_call_required",
        )

    expected_calls: list[dict[str, Any]] = metadata["expected_calls"]
    expected_names = [str(call["tool"]) for call in expected_calls]
    if names != expected_names:
        return _result(
            False,
            f"expected ordered calls {expected_names}, got {names}",
            "tool_sequence",
        )

    for call, expected in zip(calls, expected_calls, strict=True):
        if not _inputs_match(call.get("input"), expected["input"]):
            label = (
                "boundary_substitution"
                if expected["tool"] == "i495_route"
                else "input_mismatch"
            )
            return _result(
                False,
                f"{expected['tool']} input {call.get('input')} lacks {expected['input']}",
                label,
            )

    results = [_tool_result(call) for call in calls]
    if any(result is None for result in results):
        return _result(
            False, "a captured tool result is missing or invalid", "bad_result"
        )
    captured = cast(list[dict[str, Any]], results)

    plan = captured[0]
    if plan.get("at_time") != metadata["at_time"]:
        return _result(False, f"planner returned wrong time: {plan}", "plan_mismatch")
    expected_downstream = expected_calls[1:]
    if _planned_calls(plan) != expected_downstream:
        return _result(
            False,
            f"planner executable steps {_planned_calls(plan)} != {expected_downstream}",
            "plan_mismatch",
        )
    unpriced_steps = [
        step for step in plan.get("steps", []) if step.get("kind") == "unpriced"
    ]
    if bool(unpriced_steps) != bool(metadata.get("expect_unpriced_remainder")):
        return _result(
            False, f"unexpected unpriced steps: {unpriced_steps}", "plan_mismatch"
        )

    junction_index = names.index("i95_junction_leg")
    junction = captured[junction_index]
    expected_junction: dict[str, Any] = metadata["expected_junction"]
    if junction.get("at_time") != metadata["at_time"] or any(
        junction.get(key) != value
        for key, value in expected_junction.items()
        if key in {"pricing_status", "direction", "lane_statuses"}
    ):
        return _result(
            False, f"unexpected junction result: {junction}", "junction_result"
        )
    if expected_junction["pricing_status"] == "unavailable":
        forbidden = sorted(_MONETARY_FIELDS & junction.keys())
        if forbidden:
            return _result(
                False,
                f"unavailable junction exposed monetary fields: {forbidden}",
                "junction_result",
            )
    else:
        boundary = junction.get("junction_boundary", {})
        endpoint = junction.get(expected_junction["node_role"], {})
        if (
            boundary.get("label") != expected_junction["boundary_label"]
            or boundary.get("direction") != expected_junction["direction"]
            or endpoint.get("node_id") != expected_junction["node_id"]
            or not junction.get("legs")
            or not junction.get("total_usd")
        ):
            return _result(
                False, f"wrong priced junction boundary: {junction}", "junction_result"
            )

    expected_i495 = metadata.get("expected_i495")
    if expected_i495:
        i495 = captured[names.index("i495_route")]
        endpoint = i495.get(expected_i495["node_role"], {})
        if (
            i495.get("at_time") != metadata["at_time"]
            or endpoint.get("node_id") != expected_i495["node_id"]
            or not i495.get("legs")
            or not i495.get("total_usd")
        ):
            return _result(False, f"wrong I-495 result: {i495}", "i495_result")

    return _result(
        True, "ordered junction trace matches captured results", "junction_ok"
    )


def _eastern_displays(value: str) -> tuple[str, str]:
    observed = datetime.fromisoformat(value).astimezone(ZoneInfo("America/New_York"))
    clock = observed.strftime("%I:%M %p").lstrip("0")
    date = f"{observed.month}/{observed.day}/{observed.year}"
    return f"{date} {clock} ET", f"{clock} ET on {date}"


def evaluate_junction_response(
    response: str, calls: list[dict[str, Any]], metadata: dict[str, Any]
) -> list[EvaluationOutput]:
    """Require all captured segment facts while forbidding a junction total."""
    if _FORBIDDEN_TOTAL_RE.search(response) or _ARITHMETIC_RE.search(response):
        return _result(
            False,
            "response fabricated a free gap, arithmetic, or total",
            "fabricated_total",
        )
    if _ZERO_DOLLARS_RE.search(response) or _FREE_CLAIM_RE.search(response):
        return _result(False, "response described the junction as free", "free_claim")

    captured_results = [
        result
        for call in calls
        if call.get("name") in {"i95_junction_leg", "i495_route"}
        and (result := _tool_result(call))
        and result.get("pricing_status") != "unavailable"
    ]
    allowed_prices = {str(result["total_usd"]) for result in captured_results}
    quoted_prices = {match.group(1) for match in _DOLLAR_AMOUNT_RE.finditer(response)}
    unexpected_prices = sorted(quoted_prices - allowed_prices)
    if unexpected_prices:
        return _result(
            False,
            f"response quoted uncaptured dollar amounts: {unexpected_prices}",
            "fabricated_amount",
        )
    folded = response.casefold()
    required_terms = ["known segment prices", "unpriced junction", "braddock"]
    if not all(term in folded for term in required_terms):
        return _result(
            False,
            f"response lacks junction disclosure terms: {required_terms}",
            "gap_missing",
        )

    expected_junction: dict[str, Any] = metadata["expected_junction"]
    if expected_junction["pricing_status"] == "unavailable":
        if (
            not any(
                "i-95" in line.casefold() and _UNAVAILABLE_RE.search(line)
                for line in response.splitlines()
            )
            or (
                "fully open direction" not in folded
                and not _BOTH_DIRECTIONS_CLOSED_RE.search(response)
            )
            or not _GENERAL_PURPOSE_RE.search(response)
        ):
            return _result(
                False,
                "unavailable I-95 leg or general-purpose alternative is missing",
                "unavailable_missing",
            )
    else:
        boundary_label = str(expected_junction["boundary_label"])
        boundary_term = (
            "Edsall" if "Edsall" in boundary_label else "Franconia-Springfield"
        )
        if boundary_term.casefold() not in folded:
            return _result(False, "selected 95 boundary is missing", "boundary_missing")

    for call in calls:
        if call.get("name") not in {"i95_junction_leg", "i495_route"}:
            continue
        result = _tool_result(call)
        if not result or result.get("pricing_status") == "unavailable":
            continue
        price = result.get("total_usd")
        entry = str(result.get("entry", {}).get("label", ""))
        exit_ = str(result.get("exit", {}).get("label", ""))
        if price and (
            not entry
            or not exit_
            or not any(
                entry.casefold() in line.casefold()
                and exit_.casefold() in line.casefold()
                and _DOLLAR_AMOUNT_RE.findall(line) == [str(price)]
                for line in response.splitlines()
            )
        ):
            return _result(
                False,
                f"captured segment price ${price} is not bound to {entry} -> {exit_}",
                "price_leg_mismatch",
            )
        for leg in result.get("legs", []):
            observed_at = leg.get("observed_at")
            if observed_at and not any(
                display in response for display in _eastern_displays(str(observed_at))
            ):
                return _result(
                    False,
                    f"formatted observed time for {observed_at} is missing",
                    "timestamp_missing",
                )
    return _result(
        True, "response reports captured segments without a total", "grounded"
    )


def _calls_from_evaluation(
    evaluation_case: EvaluationData[str, str],
) -> list[dict[str, Any]]:
    trajectory = evaluation_case.actual_trajectory
    if (
        not isinstance(trajectory, list)
        or len(trajectory) != 1
        or not isinstance(trajectory[0], dict)
    ):
        return []
    turn_data = cast(dict[str, Any], trajectory[0])
    return cast(list[dict[str, Any]], turn_data.get("calls", []))


class JunctionTraceEvaluator(Evaluator[str, str]):
    def evaluate(
        self, evaluation_case: EvaluationData[str, str]
    ) -> list[EvaluationOutput]:
        return evaluate_junction_calls(
            _calls_from_evaluation(evaluation_case), evaluation_case.metadata or {}
        )


class JunctionResponseEvaluator(Evaluator[str, str]):
    def evaluate(
        self, evaluation_case: EvaluationData[str, str]
    ) -> list[EvaluationOutput]:
        return evaluate_junction_response(
            str(evaluation_case.actual_output or ""),
            _calls_from_evaluation(evaluation_case),
            evaluation_case.metadata or {},
        )


def main() -> None:
    configure_local_pricing_env()
    report = Experiment[str, str](
        cases=load_cases(),
        evaluators=[JunctionTraceEvaluator(), JunctionResponseEvaluator()],
    ).run_evaluations(task_function)
    _RESULTS_DIR.mkdir(exist_ok=True)
    report.to_file(str(_RESULTS_DIR / f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"))
    print(f"Overall score: {report.overall_score:.2f}")
    report.display(include_input=False)
    if not all(report.test_passes):
        raise SystemExit("direction-aware 95/495 junction evaluation failed")


def _priced_result(
    *, entry: tuple[str, str], exit_: tuple[str, str], price: str = "4.25"
) -> dict[str, Any]:
    return {
        "entry": {"node_id": entry[0], "label": entry[1]},
        "exit": {"node_id": exit_[0], "label": exit_[1]},
        "at_time": "2026-07-29T10:10:00-04:00",
        "legs": [
            {
                "price_usd": price,
                "observed_at": "2026-07-29T10:00:00-04:00",
            }
        ],
        "total_usd": price,
    }


def _self_check() -> None:
    cases = load_cases()
    assert [case.name for case in cases] == [
        "junction-95-495-nb",
        "junction-95-495-sb",
        "junction-495-95-nb",
        "junction-495-95-sb",
        "junction-both-closed-outbound",
        "junction-both-closed-inbound",
        "junction-transition",
        "junction-inside-gap",
        "junction-ignore-free-override",
        "junction-alias-control",
    ]
    for case in cases:
        case_metadata = cast(dict[str, Any], case.metadata)
        expected_calls = cast(list[dict[str, Any]], case_metadata["expected_calls"])
        plan_input = cast(dict[str, Any], expected_calls[0]["input"])
        planned = plan_toll_route(**plan_input)
        assert _planned_calls(planned) == expected_calls[1:]
        unpriced_steps = [
            step for step in planned.get("steps", []) if step.get("kind") == "unpriced"
        ]
        assert bool(unpriced_steps) == bool(
            case_metadata.get("expect_unpriced_remainder")
        )
    metadata = cast(dict[str, Any], cases[0].metadata)
    plan = {
        "at_time": metadata["at_time"],
        "steps": [
            {
                "kind": "junction",
                "tool": "i95_junction_leg",
                "location": "US-1",
                "movement": "i95_to_i495",
            },
            {
                "kind": "priced",
                "tool": "i495_route",
                "origin": "191NO",
                "destination": "Westpark Drive",
            },
        ],
    }
    junction = {
        **_priced_result(
            entry=("210NO", "US-1"),
            exit_=("206ND", "Franconia-Springfield Parkway/Route 289"),
            price="3.50",
        ),
        "pricing_status": "priced",
        "direction": "Northbound",
        "lane_statuses": {"Northbound": "NORTHBOUND_OPEN", "Southbound": "CLOSED"},
        "junction_boundary": {
            "label": "Franconia-Springfield Parkway/Route 289",
            "direction": "Northbound",
        },
    }
    calls: list[dict[str, Any]] = [
        {
            "name": "plan_toll_route",
            "input": metadata["expected_calls"][0]["input"],
            "tool_result": plan,
        },
        {
            "name": "i95_junction_leg",
            "input": metadata["expected_calls"][1]["input"],
            "tool_result": junction,
        },
        {
            "name": "i495_route",
            "input": metadata["expected_calls"][2]["input"],
            "tool_result": _priced_result(
                entry=("191NO", "I-495 Near Braddock Road"),
                exit_=("173ND", "Westpark Drive"),
            ),
        },
    ]
    response = (
        "**Known segment prices**\n"
        "- US-1 to Franconia-Springfield Parkway/Route 289: $3.50 at "
        "7/29/2026 10:00 AM ET\n"
        "- I-495 Near Braddock Road to Westpark Drive: $4.25 at "
        "7/29/2026 10:00 AM ET\n"
        "**Unpriced junction** Franconia-Springfield "
        "to Braddock. "
        "**Complete price unavailable**"
    )
    assert evaluate_junction_calls(calls, metadata)[0].label == "junction_ok"
    recovered = [
        {
            "name": "plan_toll_route",
            "input": {"origin": "Dumfries", "destination": "Westpark"},
            "tool_result": {"error": "exact oracle labels required"},
        },
        *calls,
    ]
    recovered_metadata = {**metadata, "id": "junction-alias-control"}
    assert (
        evaluate_junction_calls(recovered, recovered_metadata)[0].label == "junction_ok"
    )
    assert evaluate_junction_response(response, calls, metadata)[0].label == "grounded"

    skipped = [calls[0], calls[2]]
    assert (
        evaluate_junction_calls(skipped, metadata)[0].label == "junction_call_required"
    )
    substituted: list[dict[str, Any]] = [
        calls[0],
        calls[1],
        {
            **calls[2],
            "input": {
                **cast(dict[str, Any], calls[2]["input"]),
                "origin": "I-495/I-95 Near Van Dorn Street",
            },
        },
    ]
    assert (
        evaluate_junction_calls(substituted, metadata)[0].label
        == "boundary_substitution"
    )
    overshot = [calls[0], {**calls[1], "name": "i95_route"}, calls[2]]
    assert evaluate_junction_calls(overshot, metadata)[0].label == "overshoot_call"

    inside = cast(dict[str, Any], cases[7].metadata)
    inside_calls = [
        {"name": "plan_toll_route"},
        {"name": "i95_junction_leg"},
        {"name": "i495_route"},
    ]
    assert evaluate_junction_calls(inside_calls, inside)[0].label == "inside_gap_i495"
    assert (
        evaluate_junction_response(response + " Final total: $7.75", calls, metadata)[
            0
        ].label
        == "fabricated_total"
    )
    assert (
        evaluate_junction_response(
            response + " The complete trip price comes to $3.50.", calls, metadata
        )[0].label
        == "fabricated_total"
    )
    assert (
        evaluate_junction_response(response + " Extra fare: $99.99", calls, metadata)[
            0
        ].label
        == "fabricated_amount"
    )
    swapped = (
        response.replace("$3.50", "$SWAP", 1)
        .replace("$4.25", "$3.50", 1)
        .replace("$SWAP", "$4.25", 1)
    )
    assert (
        evaluate_junction_response(swapped, calls, metadata)[0].label
        == "price_leg_mismatch"
    )
    one_line_swapped = swapped.replace("\n- I-495", " - I-495")
    assert (
        evaluate_junction_response(one_line_swapped, calls, metadata)[0].label
        == "price_leg_mismatch"
    )
    assert (
        evaluate_junction_response(
            response + " The junction is free.", calls, metadata
        )[0].label
        == "free_claim"
    )
    assert (
        evaluate_junction_response(
            response + " The unpriced gap costs nothing.", calls, metadata
        )[0].label
        == "free_claim"
    )
    unavailable_calls = [
        calls[0],
        {
            **calls[1],
            "tool_result": {"pricing_status": "unavailable"},
        },
        calls[2],
    ]
    unavailable_response = (
        "**Known segment prices**\n"
        "- I-495 Near Braddock Road to Westpark Drive: $4.25 at "
        "7/29/2026 10:00 AM ET\n"
        "**Unpriced junction** to Braddock. The I-95 general-purpose lanes "
        "are an unpriced alternative. **Complete price unavailable**"
    )
    assert (
        evaluate_junction_response(
            unavailable_response,
            unavailable_calls,
            cast(dict[str, Any], cases[4].metadata),
        )[0].label
        == "unavailable_missing"
    )
    closed_response = unavailable_response.replace(
        "**Unpriced junction**",
        "I-95 is unavailable because both I-95 directions closed. "
        "**Unpriced junction**",
    )
    assert (
        evaluate_junction_response(
            closed_response,
            unavailable_calls,
            cast(dict[str, Any], cases[4].metadata),
        )[0].label
        == "grounded"
    )
    contextual_response = closed_response.replace(
        "I-95 general-purpose lanes", "I-95 Express Lanes; the general-purpose lanes"
    )
    assert (
        evaluate_junction_response(
            contextual_response,
            unavailable_calls,
            cast(dict[str, Any], cases[4].metadata),
        )[0].label
        == "grounded"
    )
    wrong_facility_response = closed_response.replace(
        "I-95 general-purpose lanes", "I-495 general-purpose lanes"
    )
    assert (
        evaluate_junction_response(
            wrong_facility_response,
            unavailable_calls,
            cast(dict[str, Any], cases[4].metadata),
        )[0].label
        == "unavailable_missing"
    )
    reversed_time = closed_response.replace(
        "7/29/2026 10:00 AM ET", "10:00 AM ET on 7/29/2026"
    ).replace(
        "both I-95 directions closed",
        "I-95 Express Lanes were closed in both directions",
    )
    assert (
        evaluate_junction_response(
            reversed_time,
            unavailable_calls,
            cast(dict[str, Any], cases[4].metadata),
        )[0].label
        == "grounded"
    )
    print("self-check ok (10 fixtures and twelve required mutation invariants)")


if __name__ == "__main__":
    if "--check" in sys.argv:
        _self_check()
    else:
        main()
