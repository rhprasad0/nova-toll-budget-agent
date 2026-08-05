"""Code-grade live IAD and DCA endpoint routing."""

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
from agent.toll_agent import build_agent  # noqa: E402

_CASES_PATH = Path(__file__).with_name("test-cases.jsonl")
_RESULTS_DIR = _REPO_ROOT / "eval" / "results"


def load_rows() -> list[dict[str, Any]]:
    return [json.loads(line) for line in _CASES_PATH.read_text().splitlines() if line]


def load_cases() -> list[Case[str, str]]:
    return [
        Case(name=row["id"], input=row["conversation"][0]["content"], metadata=row)
        for row in load_rows()
    ]


def _result(passed: bool, reason: str, label: str) -> list[EvaluationOutput]:
    return [
        EvaluationOutput(
            score=float(passed), test_pass=passed, reason=reason, label=label
        )
    ]


def _messages(traces: list[dict[str, Any]]) -> Messages:
    def walk(trace: dict[str, Any]) -> Messages:
        messages = [cast(Message, trace["message"])] if trace.get("message") else []
        for child in trace.get("children", []):
            messages.extend(walk(child))
        return messages

    return [message for trace in traces for message in walk(trace)]


def _calls(response: object) -> list[dict[str, Any]]:
    summary = cast(Any, response).metrics.get_summary()
    return tools_use_extractor.extract_agent_tools_used_from_messages(  # pyright: ignore[reportUnknownMemberType,reportUnknownVariableType]
        _messages(cast(list[dict[str, Any]], summary.get("traces", [])))
    )


class AirportEndpointEvaluator(Evaluator[str, str]):
    def evaluate(
        self, evaluation_case: EvaluationData[str, str]
    ) -> list[EvaluationOutput]:
        trajectory = cast(list[dict[str, Any]], evaluation_case.actual_trajectory or [])
        calls = (
            cast(list[dict[str, Any]], trajectory[0].get("calls", []))
            if trajectory
            else []
        )
        metadata = evaluation_case.metadata or {}
        expected = cast(list[dict[str, Any]], metadata["expected_calls"])
        actual_names = [call.get("name") for call in calls]
        if actual_names != [call["name"] for call in expected]:
            return _result(False, f"expected {expected}, got {calls}", "tool_mismatch")
        for actual, wanted in zip(calls, expected, strict=True):
            if actual.get("input") != wanted["input"]:
                return _result(
                    False, f"expected {wanted}, got {actual}", "input_mismatch"
                )
        response = str(evaluation_case.actual_output or "").casefold()
        missing = [
            term
            for term in metadata["response_terms"]
            if term.casefold() not in response
        ]
        if missing:
            return _result(False, f"response omitted {missing}", "response_mismatch")
        return _result(True, "airport endpoint route matched", "route_matched")


def main() -> None:
    configure_local_pricing_env()

    def task(case: Case[str, str]) -> dict[str, Any]:
        response = build_agent()(str(case.input))
        return {"output": str(response), "trajectory": [{"calls": _calls(response)}]}

    report = Experiment(
        cases=load_cases(), evaluators=[AirportEndpointEvaluator()]
    ).run_evaluations(task)
    _RESULTS_DIR.mkdir(exist_ok=True)
    report.to_file(str(_RESULTS_DIR / f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"))
    report.display(include_input=False)
    if not all(report.test_passes):
        raise SystemExit("airport endpoint evaluation failed")


def _self_check() -> None:
    rows = load_rows()
    assert len(rows) == 6
    assert {row["id"] for row in rows} >= {"iad-to-i66", "dca-to-i95"}
    print("self-check ok (six airport endpoint cases; no network)")


if __name__ == "__main__":
    _self_check() if "--check" in sys.argv else main()
