"""Code-graded live regression for the shared I-66/Dulles boundary.

``--check`` exercises fixtures and grader branches without network access.
Without it, the runner invokes TollChat and saves the live report.
"""

from __future__ import annotations

import json
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
from agent.toll_agent import build_agent, plan_toll_route  # noqa: E402

_CASES_PATH = Path(__file__).resolve().parent / "test-cases.jsonl"
_RESULTS_DIR = Path(__file__).resolve().parents[2] / "results"


def load_rows(path: Path = _CASES_PATH) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def load_cases(path: Path = _CASES_PATH) -> list[Case[str, str]]:
    return [
        Case[str, str](
            name=row["id"],
            input=row["conversation"][0]["content"],
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


def _trace_messages(traces: list[dict[str, Any]]) -> Messages:
    def walk(trace: dict[str, Any]) -> Messages:
        messages = [cast(Message, trace["message"])] if trace.get("message") else []
        for child in trace.get("children", []):
            messages.extend(walk(child))
        return messages

    return [message for trace in traces for message in walk(trace)]


def _tool_result(call: dict[str, Any]) -> dict[str, Any] | None:
    result = call.get("tool_result")
    if isinstance(result, str):
        try:
            result = json.loads(result)
        except json.JSONDecodeError:
            return None
    return cast(dict[str, Any], result) if isinstance(result, dict) else None


def evaluate_calls(
    calls: list[dict[str, Any]], metadata: dict[str, Any]
) -> list[EvaluationOutput]:
    """Require the directed planner handoff and exactly its two priced legs."""
    expected_calls = cast(list[dict[str, Any]], metadata["expected_calls"])
    expected_names = [call["name"] for call in expected_calls]
    actual_names = [call.get("name") for call in calls]
    if actual_names != expected_names:
        return _result(
            False,
            f"expected tool calls {expected_names}, got {actual_names}",
            "tool_mismatch",
        )
    for actual, expected in zip(calls, expected_calls, strict=True):
        raw_input = actual.get("input")
        expected_input = cast(dict[str, Any], expected["input"])
        if not isinstance(raw_input, dict):
            return _result(
                False,
                f"{expected['name']} input {raw_input} did not match {expected_input}",
                "input_mismatch",
            )
        actual_input = cast(dict[str, Any], raw_input)
        if any(actual_input.get(key) != value for key, value in expected_input.items()):
            return _result(
                False,
                f"{expected['name']} input {actual_input} did not match {expected_input}",
                "input_mismatch",
            )

    plan = _tool_result(calls[0])
    if plan is None or "error" in plan:
        return _result(False, f"planner returned {plan}", "planner_error")
    raw_steps = plan.get("steps")
    steps = cast(list[dict[str, Any]], raw_steps) if isinstance(raw_steps, list) else []
    if [step.get("kind") for step in steps] != ["priced", "connector", "priced"]:
        return _result(
            False,
            f"planner step kinds {[step.get('kind') for step in steps]} were unexpected",
            "step_mismatch",
        )
    connectors = [step for step in steps if step.get("kind") == "connector"]
    expected_connector = metadata["expected_connector"]
    if len(connectors) != 1 or any(
        connectors[0].get(key) != value for key, value in expected_connector.items()
    ):
        return _result(
            False,
            f"planner connector {connectors} did not match {expected_connector}",
            "connector_mismatch",
        )
    return _result(
        True, "directed untolled connector and legs matched", "route_matched"
    )


def evaluate_response(response: str) -> list[EvaluationOutput]:
    lowered = response.casefold()
    if "airport" in lowered:
        return _result(False, "response mentioned an airport", "airport_mentioned")
    if "i-66 / dulles toll road junction" not in lowered:
        return _result(
            False,
            "response omitted I-66 / Dulles Toll Road junction",
            "connector_missing",
        )
    if not any(term in lowered for term in ("untolled", "no toll", "$0.00")):
        return _result(
            False,
            "response did not identify the connector as untolled",
            "untolled_missing",
        )
    return _result(True, "response named the untolled connector", "response_matched")


def task_function(case: Case[str, str]) -> dict[str, Any]:
    response = build_agent()(str(case.input))
    summary: dict[str, Any] = response.metrics.get_summary()
    traces = cast(list[dict[str, Any]], summary.get("traces", []))
    calls = tools_use_extractor.extract_agent_tools_used_from_messages(  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        _trace_messages(traces)
    )
    return {"output": str(response), "trajectory": [{"calls": calls}]}


class DullesConnectorEvaluator(Evaluator[str, str]):
    """Grade planner evidence and the final user-facing response."""

    def evaluate(
        self, evaluation_case: EvaluationData[str, str]
    ) -> list[EvaluationOutput]:
        trajectory = evaluation_case.actual_trajectory
        turns = (
            cast(list[dict[str, Any]], trajectory)
            if isinstance(trajectory, list)
            else []
        )
        calls = cast(list[dict[str, Any]], turns[0].get("calls", [])) if turns else []
        metadata = evaluation_case.metadata or {}
        return [
            *evaluate_calls(calls, metadata),
            *evaluate_response(str(evaluation_case.actual_output or "")),
        ]


def main() -> None:
    configure_local_pricing_env()
    report = Experiment[str, str](
        cases=load_cases(), evaluators=[DullesConnectorEvaluator()]
    ).run_evaluations(task_function)
    _RESULTS_DIR.mkdir(exist_ok=True)
    report.to_file(str(_RESULTS_DIR / f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"))
    print(f"Overall score: {report.overall_score:.2f}")
    report.display(include_input=False)
    if not all(report.test_passes):
        raise SystemExit("deterministic I-66/Dulles junction evaluation failed")


def _self_check() -> None:
    rows = load_rows()
    assert len(rows) == 2

    for row in rows:
        expected_calls = cast(list[dict[str, Any]], row["expected_calls"])
        plan = plan_toll_route(**cast(dict[str, Any], expected_calls[0]["input"]))
        calls = [
            {
                **expected,
                "tool_result": json.dumps(
                    plan if expected["name"] == "plan_toll_route" else {}
                ),
            }
            for expected in expected_calls
        ]
        assert evaluate_calls(calls, row)[0].label == "route_matched"

    row: dict[str, Any] = rows[-1]
    expected_calls = cast(list[dict[str, Any]], row["expected_calls"])
    plan = plan_toll_route(**cast(dict[str, Any], expected_calls[0]["input"]))
    steps = cast(list[dict[str, Any]], plan["steps"])
    bad_plan = {
        **plan,
        "steps": [
            {**step, "price_usd": "1.00"} if step.get("kind") == "connector" else step
            for step in steps
        ],
    }
    extra_step_plan: dict[str, Any] = {
        **plan,
        "steps": [
            *steps,
            {"kind": "unpriced", "reason": "unexpected"},
        ],
    }
    extra_step_calls: list[dict[str, Any]] = [
        {
            **expected_calls[0],
            "tool_result": json.dumps(extra_step_plan),
        },
        *expected_calls[1:],
    ]
    assert evaluate_calls(extra_step_calls, row)[0].label == "step_mismatch"
    bad_calls: list[dict[str, Any]] = [
        {
            **expected_calls[0],
            "tool_result": json.dumps(bad_plan),
        },
        *expected_calls[1:],
    ]
    assert evaluate_calls(bad_calls, row)[0].label == "connector_mismatch"
    assert (
        evaluate_response("The I-66 / Dulles Toll Road junction is untolled.")[0].label
        == "response_matched"
    )
    assert (
        evaluate_response("Dulles Airport Access Highway is untolled.")[0].label
        == "airport_mentioned"
    )
    assert (
        evaluate_response("The I-66 / Dulles Toll Road junction is tolled.")[0].label
        == "untolled_missing"
    )
    print("self-check ok (two directions and negative connector/response guards)")


if __name__ == "__main__":
    if "--check" in sys.argv:
        _self_check()
    else:
        main()
