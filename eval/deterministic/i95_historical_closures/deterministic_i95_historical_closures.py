"""Code-graded live regression for Issue #17's historical I-95 closures.

The grader is deterministic; the live TollChat invocation is stochastic.
``--check`` only exercises the loader and grader against synthetic traces.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import UTC, datetime
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
from agent.toll_agent import build_agent  # noqa: E402

_CASES_PATH = Path(__file__).resolve().parent / "test-cases.jsonl"
_RESULTS_DIR = Path(__file__).resolve().parents[2] / "results"
_MONEY_RE = re.compile(r"\$\s*\d|\b\d+\.\d{2}\b|\b(?:USD|dollars?)\b", re.I)
_UNAVAILABLE_RE = re.compile(r"\b(?:unavailable|cannot\s+(?:provide|price))\b", re.I)
_GENERAL_PURPOSE_RE = re.compile(
    r"\b(?:I-95\s+general[- ]purpose lanes|general[- ]purpose lanes\s+"
    r"(?:on|of)\s+(?:the\s+)?I-95)\b",
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
                expected_trajectory=[row["expected_trajectory"][0]["tool"]],
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


def _report_passed(test_passes: list[bool]) -> bool:
    return all(test_passes)


def _turns(evaluation_case: EvaluationData[str, str]) -> list[dict[str, Any]]:
    trajectory = evaluation_case.actual_trajectory
    return (
        cast(list[dict[str, Any]], trajectory) if isinstance(trajectory, list) else []
    )


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


class ClosureTraceEvaluator(Evaluator[str, str]):
    """Require the one authorized call and its captured unavailable result."""

    def evaluate(
        self, evaluation_case: EvaluationData[str, str]
    ) -> list[EvaluationOutput]:
        metadata: dict[str, Any] = evaluation_case.metadata or {}
        turns = _turns(evaluation_case)
        calls = (
            cast(list[dict[str, Any]], turns[0].get("calls", []))
            if len(turns) == 1
            else []
        )
        return evaluate_closure_calls(calls, metadata)


def evaluate_closure_calls(
    calls: list[dict[str, Any]], metadata: dict[str, Any]
) -> list[EvaluationOutput]:
    """Grade captured calls against one historical closure fixture."""
    expected = metadata["expected_trajectory"][0]
    if len(calls) != 1 or calls[0].get("name") != expected["tool"]:
        return _result(
            False,
            f"expected exactly one {expected['tool']} call, got "
            f"{[call.get('name') for call in calls]}",
            "tool_mismatch",
        )
    expected_input: dict[str, Any] = expected["input"]
    raw_input = calls[0].get("input")
    actual_input = (
        cast(dict[str, Any], raw_input) if isinstance(raw_input, dict) else {}
    )
    if not isinstance(raw_input, dict) or not all(
        actual_input.get(key) == value for key, value in expected_input.items()
    ):
        return _result(
            False,
            f"tool input {actual_input} lacks required arguments {expected_input}",
            "input_mismatch",
        )
    captured = _tool_result(calls[0])
    if captured is None:
        return _result(False, "missing or invalid captured tool result", "bad_result")
    error = str(captured.get("error", ""))
    expected_od = str(metadata["expected_od_pair_id"])
    expected_status = str(metadata["expected_link_status"])
    if expected_od not in error or expected_status not in error:
        return _result(False, f"unexpected closure result: {captured}", "wrong_result")
    forbidden = sorted(_MONETARY_FIELDS & captured.keys())
    if forbidden:
        return _result(
            False,
            f"unavailable result exposed monetary fields: {forbidden}",
            "fare_exposed",
        )
    return _result(True, "exact call returned the expected closure", "closed")


class ClosureResponseEvaluator(Evaluator[str, str]):
    """Require an unavailable answer with no invented fare."""

    def evaluate(
        self, evaluation_case: EvaluationData[str, str]
    ) -> list[EvaluationOutput]:
        response = str(evaluation_case.actual_output or "")
        if not _UNAVAILABLE_RE.search(response):
            return _result(
                False, "response did not report unavailability", "not_refused"
            )
        if not _GENERAL_PURPOSE_RE.search(response):
            return _result(
                False,
                "response did not suggest the I-95 general-purpose lanes",
                "alternative_missing",
            )
        if _MONEY_RE.search(response):
            return _result(
                False, "response quoted a fare for a closed lane", "fare_quoted"
            )
        return _result(True, "response reported unavailable with no fare", "refused")


def main() -> None:
    configure_local_pricing_env()
    experiment = Experiment[str, str](
        cases=load_cases(),
        evaluators=[ClosureTraceEvaluator(), ClosureResponseEvaluator()],
    )
    report = experiment.run_evaluations(task_function)
    _RESULTS_DIR.mkdir(exist_ok=True)
    report.to_file(str(_RESULTS_DIR / f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"))
    print(f"Overall score: {report.overall_score:.2f}")
    report.display(include_input=False)
    if not _report_passed(report.test_passes):
        raise SystemExit("code-graded historical I-95 closure regression failed")


def _self_check() -> None:
    cases = load_cases()
    assert [case.name for case in cases] == [
        "i95-nb-closed",
        "i95-sb-closed",
        "i95-both-closed-nb",
        "i95-both-closed-sb",
    ]

    metadata = cast(dict[str, Any], cases[0].metadata)
    expected = metadata["expected_trajectory"][0]
    call = {
        "name": "i95_route",
        "input": expected["input"],
        "tool_result": json.dumps(
            {
                "error": "od_pair_id 1132 is not currently available: "
                "link_status='CLOSED'",
                "valid_options": [],
            }
        ),
    }

    def fake(
        calls: list[dict[str, Any]],
        output: str = "Lane is unavailable; use the I-95 general-purpose lanes.",
    ) -> EvaluationData[str, str]:
        return EvaluationData[str, str](
            input="x",
            actual_output=output,
            actual_trajectory=[{"calls": calls}],
            metadata=metadata,
        )

    trace = ClosureTraceEvaluator()
    response = ClosureResponseEvaluator()
    assert trace.evaluate(fake([call]))[0].label == "closed"
    assert (
        trace.evaluate(fake([{**call, "input": {**expected["input"], "extra": True}}]))[
            0
        ].label
        == "closed"
    )
    assert trace.evaluate(fake([]))[0].label == "tool_mismatch"
    assert trace.evaluate(fake([call, call]))[0].label == "tool_mismatch"
    assert (
        trace.evaluate(
            fake([{**call, "input": {**expected["input"], "origin": "US-17"}}])
        )[0].label
        == "input_mismatch"
    )
    assert (
        trace.evaluate(
            fake(
                [{**call, "tool_result": {"total_usd": "6.75", "error": "1132 CLOSED"}}]
            )
        )[0].label
        == "fare_exposed"
    )
    assert response.evaluate(fake([call]))[0].label == "refused"
    assert (
        response.evaluate(fake([call], "Lane is CLOSED and unavailable."))[0].label
        == "alternative_missing"
    )
    assert (
        response.evaluate(fake([call], "The fare is $6.75."))[0].label == "not_refused"
    )
    assert (
        response.evaluate(
            fake([call], "Unavailable; I-95 general-purpose lanes cost $6.75.")
        )[0].label
        == "fare_quoted"
    )
    assert (
        response.evaluate(
            fake(
                [call],
                "The I-95 lanes are not closed; use the I-66 general-purpose lanes.",
            )
        )[0].label
        == "not_refused"
    )
    assert (
        response.evaluate(
            fake(
                [call],
                "The I-95 Express Lanes are unavailable; use general-purpose lanes on I-66.",
            )
        )[0].label
        == "alternative_missing"
    )
    assert _report_passed([True, True])
    assert not _report_passed([True, False])
    print(
        "self-check ok (case loading and evaluator mutations; live integrations excluded)"
    )


if __name__ == "__main__":
    if "--check" in sys.argv:
        _self_check()
    else:
        main()
