"""Code-grade TollChat's I-95/395 one-way access recovery behavior."""

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

_CASES_PATH = Path(__file__).with_name("test-cases.jsonl")
_RESULTS_DIR = _REPO_ROOT / "eval" / "results"
_MONEY_RE = re.compile(r"\$\s*\d|\b\d+\.\d{2}\b|\b(?:USD|dollars?)\b", re.I)


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


def _calls(response: object) -> list[dict[str, Any]]:
    summary: dict[str, Any] = cast(Any, response).metrics.get_summary()
    traces = cast(list[dict[str, Any]], summary.get("traces", []))
    return tools_use_extractor.extract_agent_tools_used_from_messages(  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        _trace_messages(traces)
    )


def _tool_result(call: dict[str, Any]) -> dict[str, Any] | None:
    value = call.get("tool_result")
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return None
    return cast(dict[str, Any], value) if isinstance(value, dict) else None


def _matches_input(call: dict[str, Any], expected: dict[str, Any]) -> bool:
    actual = call.get("input")
    actual_input = cast(dict[str, Any], actual) if isinstance(actual, dict) else None
    return actual_input is not None and all(
        actual_input.get(key) == value for key, value in expected.items()
    )


def evaluate_one_way_access_turn(
    calls: list[dict[str, Any]], response: str, metadata: dict[str, Any]
) -> list[EvaluationOutput]:
    expected_calls = metadata["expected_trajectory"][0]["calls"]
    if len(calls) != len(expected_calls) or [call.get("name") for call in calls] != [
        expected["tool"] for expected in expected_calls
    ]:
        return _result(
            False,
            f"unexpected calls: {[call.get('name') for call in calls]}",
            "tool_mismatch",
        )
    if any(
        not _matches_input(call, expected["input"])
        for call, expected in zip(calls, expected_calls, strict=True)
    ):
        return _result(False, "tool arguments did not match fixture", "input_mismatch")

    access = _tool_result(calls[0])
    if access is None:
        return _result(False, "missing access-check result", "bad_access_result")
    mismatch = metadata.get("expected_mismatch")
    if mismatch:
        if (
            access.get("status") != "one_way_mismatch"
            or access.get("direction") != mismatch["direction"]
        ):
            return _result(
                False, f"unexpected access result: {access}", "wrong_mismatch"
            )
        if access.get("constraints") != [mismatch["constraint"]]:
            return _result(
                False, f"unexpected mismatch constraint: {access}", "wrong_constraint"
            )
        lowered = response.casefold()
        if any(term.casefold() not in lowered for term in metadata["response_terms"]):
            return _result(False, "response omitted recovery facts", "response_missing")
        if _MONEY_RE.search(response):
            return _result(False, "mismatch response quoted money", "fare_exposed")
        return _result(
            True, "one-way mismatch was explained without a fare", "mismatch"
        )

    if access != {
        "status": "supported",
        "direction": metadata["expected_supported_direction"],
    }:
        return _result(
            False, f"unexpected supported result: {access}", "wrong_supported"
        )
    priced = _tool_result(calls[1])
    if priced is None:
        return _result(False, "missing pricing result", "bad_price_result")
    if "error" in priced and _MONEY_RE.search(response):
        return _result(False, "unavailable route quoted money", "fare_exposed")
    return _result(True, "access check preceded the exact pricing call", "supported")


def task_function(case: Case[str, str]) -> dict[str, Any]:
    agent = build_agent()
    response = agent(str(case.input))
    return {"output": str(response), "trajectory": [{"calls": _calls(response)}]}


class OneWayAccessEvaluator(Evaluator[str, str]):
    def evaluate(
        self, evaluation_case: EvaluationData[str, str]
    ) -> list[EvaluationOutput]:
        trajectory = evaluation_case.actual_trajectory
        turns = (
            cast(list[dict[str, Any]], trajectory)
            if isinstance(trajectory, list)
            else []
        )
        turn = turns[0] if len(turns) == 1 else {}
        return evaluate_one_way_access_turn(
            cast(list[dict[str, Any]], turn.get("calls", [])),
            str(evaluation_case.actual_output or ""),
            evaluation_case.metadata or {},
        )


def main() -> None:
    configure_local_pricing_env()
    report = Experiment[str, str](
        cases=load_cases(), evaluators=[OneWayAccessEvaluator()]
    ).run_evaluations(task_function)
    _RESULTS_DIR.mkdir(exist_ok=True)
    report.to_file(str(_RESULTS_DIR / f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"))
    report.display(include_input=False)
    if not all(report.test_passes):
        raise SystemExit("deterministic I-95 one-way access evaluation failed")


def _self_check() -> None:
    rows = load_rows()
    assert [row["id"] for row in rows] == [
        "invalid-southbound-destination",
        "invalid-northbound-origin",
        "invalid-cross-corridor-origin",
        "invalid-cross-corridor-destination",
        "supported-direct-control",
    ]
    mismatch = rows[0]
    expected = mismatch["expected_trajectory"][0]["calls"][0]
    call = {
        "name": expected["tool"],
        "input": expected["input"],
        "tool_result": {
            "status": "one_way_mismatch",
            "direction": mismatch["expected_mismatch"]["direction"],
            "constraints": [mismatch["expected_mismatch"]["constraint"]],
        },
    }
    assert (
        evaluate_one_way_access_turn(
            [call], " ".join(mismatch["response_terms"]), mismatch
        )[0].label
        == "mismatch"
    )
    assert evaluate_one_way_access_turn([], "", mismatch)[0].label == "tool_mismatch"
    cross_mismatch = rows[2]
    cross_call = {
        "name": "plan_toll_route",
        "input": cross_mismatch["expected_trajectory"][0]["calls"][0]["input"],
        "tool_result": {
            "status": "one_way_mismatch",
            "direction": cross_mismatch["expected_mismatch"]["direction"],
            "constraints": [cross_mismatch["expected_mismatch"]["constraint"]],
        },
    }
    assert (
        evaluate_one_way_access_turn(
            [cross_call], " ".join(cross_mismatch["response_terms"]), cross_mismatch
        )[0].label
        == "mismatch"
    )
    supported = rows[4]
    calls = [
        {
            "name": expected["tool"],
            "input": supported["expected_trajectory"][0]["calls"][0]["input"],
            "tool_result": {"status": "supported", "direction": "Southbound"},
        },
        {
            "name": "i95_route",
            "input": supported["expected_trajectory"][0]["calls"][1]["input"],
            "tool_result": {"error": "CLOSED"},
        },
    ]
    assert (
        evaluate_one_way_access_turn(calls, "Lane unavailable.", supported)[0].label
        == "supported"
    )
    print("self-check ok (fixtures and deterministic evaluator branches; no network)")


if __name__ == "__main__":
    if "--check" in sys.argv:
        _self_check()
    else:
        main()
