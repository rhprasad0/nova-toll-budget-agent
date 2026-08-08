"""Code-graded regressions for the movement-aware I-95/I-495 junction."""

from __future__ import annotations

import json
import re
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

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
_MONEY_RE = re.compile(r"\$\s*(\d+(?:\.\d{1,2})?)")
_ZERO_MONEY_RE = re.compile(r"\$\s*0(?:\.0{1,2})?\b")
_FREE_RE = re.compile(
    r"\b(?:junction|gap)\s+(?:is|was|costs?)\s+(?:free|nothing)\b|"
    r"\btreat(?:ed|ing)?\s+(?:the\s+)?(?:junction|gap)\s+as\s+free\b",
    re.I,
)
_MONETARY_FIELDS = {"legs", "price_usd", "total_usd", "tolls"}


def load_rows(path: Path = _CASES_PATH) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def load_cases(path: Path = _CASES_PATH) -> list[Case[str, str]]:
    return [
        Case[str, str](
            name=row["id"],
            input=row["conversation"][0]["content"],
            expected_trajectory=[call["tool"] for call in row["expected_calls"]],
            metadata=row,
        )
        for row in load_rows(path)
    ]


def _result(passed: bool, reason: str, label: str) -> list[EvaluationOutput]:
    return [
        EvaluationOutput(
            score=float(passed), test_pass=passed, reason=reason, label=label
        )
    ]


def _tool_result(call: dict[str, Any]) -> dict[str, Any] | None:
    value = call.get("tool_result")
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return None
    return cast(dict[str, Any], value) if isinstance(value, dict) else None


def _planned_calls(plan: dict[str, Any]) -> list[dict[str, Any]]:
    at_time = plan.get("at_time")
    calls: list[dict[str, Any]] = []
    for step in plan.get("steps", []):
        if step.get("kind") == "priced":
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
        elif step.get("kind") == "junction":
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
    return calls


def _prices(calls: list[dict[str, Any]]) -> list[str]:
    prices: list[str] = []
    for call in calls[1:]:
        result = _tool_result(call)
        if not result or result.get("pricing_status") == "unavailable":
            continue
        if call.get("name") == "dulles_route":
            prices.extend(str(toll["price_usd"]) for toll in result.get("tolls", []))
        elif result.get("total_usd") is not None:
            prices.append(str(result["total_usd"]))
    return prices


def evaluate_junction_calls(
    calls: list[dict[str, Any]], metadata: dict[str, Any]
) -> list[EvaluationOutput]:
    """Require one exact planner-derived trajectory and grounded results."""
    expected = cast(list[dict[str, Any]], metadata["expected_calls"])
    names = [call.get("name") for call in calls]
    expected_names = [call["tool"] for call in expected]
    if names != expected_names:
        return _result(
            False, f"expected calls {expected_names}, got {names}", "tool_mismatch"
        )
    for actual, wanted in zip(calls, expected, strict=True):
        raw_input = actual.get("input")
        actual_input = (
            cast(dict[str, Any], raw_input) if isinstance(raw_input, dict) else None
        )
        if actual_input is None or any(
            actual_input.get(key) != value
            for key, value in cast(dict[str, Any], wanted["input"]).items()
        ):
            return _result(
                False,
                f"{wanted['tool']} input {actual_input} did not match {wanted['input']}",
                "input_mismatch",
            )

    captured = [_tool_result(call) for call in calls]
    if any(result is None for result in captured):
        return _result(False, "captured result missing or invalid", "bad_result")
    results = cast(list[dict[str, Any]], captured)
    plan = results[0]
    if "error" in plan or _planned_calls(plan) != expected[1:]:
        return _result(False, f"planner returned the wrong route: {plan}", "bad_plan")

    junction = results[names.index("i95_junction_leg")]
    wanted_junction = cast(dict[str, Any], metadata["expected_junction"])
    if any(
        junction.get(key) != value
        for key, value in wanted_junction.items()
        if key in {"pricing_status", "direction", "lane_statuses"}
    ):
        return _result(False, f"wrong junction status: {junction}", "junction_result")
    if wanted_junction["pricing_status"] == "unavailable":
        forbidden = sorted(_MONETARY_FIELDS & junction.keys())
        if forbidden:
            return _result(
                False,
                f"unavailable junction exposed {forbidden}",
                "junction_result",
            )
    else:
        endpoint = junction.get(wanted_junction["node_role"], {})
        legs = junction.get("legs", [])
        boundary = junction.get("junction_boundary", {})
        if (
            boundary.get("label") != wanted_junction["boundary_label"]
            or endpoint.get("node_id") != wanted_junction["node_id"]
            or not legs
            or legs[0].get("od_pair_id") != wanted_junction["od_pair_id"]
            or not junction.get("total_usd")
        ):
            return _result(
                False, f"wrong junction boundary or OD: {junction}", "junction_result"
            )

    i495 = results[names.index("i495_route")]
    wanted_i495 = cast(dict[str, Any], metadata["expected_i495"])
    if i495.get(wanted_i495["node_role"], {}).get("node_id") != wanted_i495[
        "node_id"
    ] or not i495.get("total_usd"):
        return _result(False, f"wrong I-495 boundary: {i495}", "i495_result")
    if not _prices(calls):
        return _result(False, "trajectory captured no known fares", "prices_missing")
    return _result(True, "movement-aware junction trajectory matched", "junction_ok")


def evaluate_junction_response(
    response: str, calls: list[dict[str, Any]], metadata: dict[str, Any]
) -> list[EvaluationOutput]:
    """Require exact known-fare arithmetic while keeping the gap unpriced."""
    folded = response.casefold()
    required = (
        "known segment prices",
        "unpriced junction",
        "calculation",
        "known toll total",
        "braddock",
    )
    if any(term not in folded for term in required):
        return _result(False, f"missing response section from {required}", "sections")
    if _FREE_RE.search(response):
        return _result(False, "response called the junction free", "free_gap")
    unpriced_section = folded.split("unpriced junction", 1)[-1].split("calculation", 1)[
        0
    ]
    if _ZERO_MONEY_RE.search(unpriced_section):
        return _result(False, "response priced the junction at zero", "zero_gap")

    wanted = cast(dict[str, Any], metadata["expected_junction"])
    if wanted["pricing_status"] == "priced":
        boundary = (
            "edsall"
            if "Edsall" in wanted["boundary_label"]
            else "franconia-springfield"
        )
        if boundary not in folded:
            return _result(False, "selected I-95 boundary missing", "boundary_missing")
    elif (
        "unavailable" not in folded
        or "general-purpose" not in folded
        or not any(term in folded for term in ("closed", "fully open direction"))
    ):
        return _result(False, "closed I-95 outcome missing", "unavailable_missing")

    operands = _prices(calls)
    total = f"{sum(map(Decimal, operands), Decimal()):.2f}"
    plain = response.translate(str.maketrans("", "", "*_`"))
    expected_amounts = [*map(Decimal, operands), Decimal(total)]
    arithmetic_lines = [
        line for line in plain.splitlines() if "+" in line and "=" in line
    ]
    if not any(
        [Decimal(value) for value in _MONEY_RE.findall(line)] == expected_amounts
        for line in arithmetic_lines
    ):
        return _result(
            False,
            f"missing exact arithmetic for {operands} = {total}",
            "bad_math",
        )
    total_section = folded.split("known toll total", 1)[-1]
    if not re.search(rf"\$\s*{re.escape(total)}\b", total_section):
        return _result(False, "known toll total missing", "total_missing")
    if not re.search(r"not (?:a )?complete operator-issued fare", folded):
        return _result(False, "known total was not qualified", "total_qualification")
    return _result(True, "known fares summed and gap excluded", "grounded_response")


def _trace_messages(traces: list[dict[str, Any]]) -> Messages:
    def walk(trace: dict[str, Any]) -> Messages:
        messages = [cast(Message, trace["message"])] if trace.get("message") else []
        for child in trace.get("children", []):
            messages.extend(walk(child))
        return messages

    return [message for trace in traces for message in walk(trace)]


def task_function(case: Case[str, str]) -> dict[str, Any]:
    response = build_agent()(str(case.input))
    summary: dict[str, Any] = response.metrics.get_summary()
    traces = cast(list[dict[str, Any]], summary.get("traces", []))
    calls = tools_use_extractor.extract_agent_tools_used_from_messages(  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        _trace_messages(traces)
    )
    return {"output": str(response), "trajectory": [{"calls": calls}]}


def _calls(case: EvaluationData[str, str]) -> list[dict[str, Any]]:
    trajectory = case.actual_trajectory
    if not isinstance(trajectory, list) or len(trajectory) != 1:
        return []
    return cast(list[dict[str, Any]], trajectory[0].get("calls", []))


class JunctionTraceEvaluator(Evaluator[str, str]):
    def evaluate(
        self, evaluation_case: EvaluationData[str, str]
    ) -> list[EvaluationOutput]:
        return evaluate_junction_calls(
            _calls(evaluation_case), evaluation_case.metadata or {}
        )


class JunctionResponseEvaluator(Evaluator[str, str]):
    def evaluate(
        self, evaluation_case: EvaluationData[str, str]
    ) -> list[EvaluationOutput]:
        return evaluate_junction_response(
            str(evaluation_case.actual_output or ""),
            _calls(evaluation_case),
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
        raise SystemExit("I-95/I-495 junction evaluation failed")


def _synthetic_calls(row: dict[str, Any]) -> list[dict[str, Any]]:
    plan = plan_toll_route(**row["expected_calls"][0]["input"])
    results: dict[str, dict[str, Any]] = {
        "dulles_route": {
            "tolls": [
                {"label": "mainline", "price_usd": "2.00"},
                {"label": "ramp", "price_usd": "1.25"},
            ],
            "total_usd": "3.25",
        },
        "i495_route": {
            "entry": {"node_id": "182SO" if "182SO" in str(row) else "191NO"},
            "exit": {"node_id": "191SD" if "191SD" in str(row) else "999"},
            "legs": [{}],
            "total_usd": "5.00",
        },
    }
    wanted = row["expected_junction"]
    if wanted["pricing_status"] == "unavailable":
        results["i95_junction_leg"] = {
            "pricing_status": "unavailable",
            "lane_statuses": wanted["lane_statuses"],
            "reason": "both directions are CLOSED",
        }
    else:
        results["i95_junction_leg"] = {
            "pricing_status": "priced",
            "direction": wanted["direction"],
            "lane_statuses": wanted["lane_statuses"],
            "junction_boundary": {"label": wanted["boundary_label"]},
            wanted["node_role"]: {"node_id": wanted["node_id"]},
            "legs": [{"od_pair_id": wanted["od_pair_id"]}],
            "total_usd": "4.50",
        }
    return [
        {
            "name": expected["tool"],
            "input": expected["input"],
            "tool_result": plan if index == 0 else results[expected["tool"]],
        }
        for index, expected in enumerate(row["expected_calls"])
    ]


def _self_check() -> None:
    rows = load_rows()
    assert len(rows) == 5
    for row in rows:
        calls = _synthetic_calls(row)
        assert evaluate_junction_calls(calls, row)[0].label == "junction_ok"
        operands = _prices(calls)
        total = f"{sum(map(Decimal, operands), Decimal()):.2f}"
        boundary = row["expected_junction"].get("boundary_label", "")
        unavailable = boundary or (
            "I-95 is unavailable because both directions are closed. Consider "
            "the I-95 general-purpose lanes."
        )
        response = (
            "## Known segment prices\n"
            f"{unavailable}\nI-495 Near Braddock Road\n"
            "## Unpriced junction\nThe gap has no price.\n"
            "## Calculation\n"
            f"{' + '.join(f'${value}' for value in operands)} = ${total}\n"
            "## Known toll total\n"
            f"${total}. This excludes the gap and is not a complete operator-issued fare."
        )
        assert (
            evaluate_junction_response(response, calls, row)[0].label
            == "grounded_response"
        )
    row = rows[0]
    calls = _synthetic_calls(row)
    assert evaluate_junction_calls(calls + calls[-1:], row)[0].label == "tool_mismatch"
    good = (
        "Known segment prices. Unpriced junction at Braddock: the gap is free. "
        "Calculation. Known toll total."
    )
    assert evaluate_junction_response(good, calls, row)[0].label == "free_gap"
    zero_gap = (
        "Known segment prices. Unpriced junction at Braddock: $0.00, not free. "
        "Calculation. Known toll total."
    )
    assert evaluate_junction_response(zero_gap, calls, row)[0].label == "zero_gap"
    print(
        "self-check ok (5 cases, exact trajectories, boundaries, and known-total math)"
    )


if __name__ == "__main__":
    _self_check() if "--check" in sys.argv else main()
