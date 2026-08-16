"""Code-grade fixed directional access on I-66, I-495, and the Greenway."""

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
from eval.deterministic.i95_one_way_access.deterministic_i95_one_way_access import (  # noqa: E402
    evaluate_one_way_access_turn,
)

_CASES_PATH = Path(__file__).with_name("test-cases.jsonl")
_RESULTS_DIR = _REPO_ROOT / "eval" / "results"


def load_rows() -> list[dict[str, Any]]:
    return [json.loads(line) for line in _CASES_PATH.read_text().splitlines() if line]


def load_cases() -> list[Case[str, str]]:
    return [
        Case(name=row["id"], input=row["conversation"][0]["content"], metadata=row)
        for row in load_rows()
    ]


def _messages(traces: list[dict[str, Any]]) -> Messages:
    def walk(trace: dict[str, Any]) -> Messages:
        found = [cast(Message, trace["message"])] if trace.get("message") else []
        for child in trace.get("children", []):
            found.extend(walk(child))
        return found

    return [message for trace in traces for message in walk(trace)]


def _calls(response: object) -> list[dict[str, Any]]:
    summary = cast(Any, response).metrics.get_summary()
    return tools_use_extractor.extract_agent_tools_used_from_messages(  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        _messages(cast(list[dict[str, Any]], summary.get("traces", [])))
    )


class DirectionalAccessEvaluator(Evaluator[str, str]):
    def evaluate(
        self, evaluation_case: EvaluationData[str, str]
    ) -> list[EvaluationOutput]:
        trajectory = cast(list[dict[str, Any]], evaluation_case.actual_trajectory or [])
        calls = (
            cast(list[dict[str, Any]], trajectory[0].get("calls", []))
            if trajectory
            else []
        )
        return evaluate_one_way_access_turn(
            calls,
            str(evaluation_case.actual_output or ""),
            evaluation_case.metadata or {},
        )


def main() -> None:
    configure_local_pricing_env()

    def task(case: Case[str, str]) -> dict[str, Any]:
        response = build_agent()(str(case.input))
        return {"output": str(response), "trajectory": [{"calls": _calls(response)}]}

    report = Experiment(
        cases=load_cases(), evaluators=[DirectionalAccessEvaluator()]
    ).run_evaluations(task)
    _RESULTS_DIR.mkdir(exist_ok=True)
    report.to_file(str(_RESULTS_DIR / f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"))
    report.display(include_input=False)
    if not all(report.test_passes):
        raise SystemExit("non-I-95 directional access evaluation failed")


def _self_check() -> None:
    rows = load_rows()
    assert len(rows) == 5
    assert {row["expected_trajectory"][0]["calls"][0]["tool"] for row in rows} == {
        "plan_toll_route",
        "i66_route",
        "i495_route",
        "dulles_route",
    }
    for row in rows:
        expected = row["expected_trajectory"][0]["calls"][0]
        call = {
            "name": expected["tool"],
            "input": expected["input"],
            "tool_result": {
                "status": "one_way_mismatch",
                "direction": row["expected_mismatch"]["direction"],
                "constraints": [row["expected_mismatch"]["constraint"]],
            },
        }
        assert evaluate_one_way_access_turn(
            [call], " ".join(row["response_terms"]), row
        )[0].test_pass
    print("self-check ok (four fixed-direction corridors; no network)")


if __name__ == "__main__":
    _self_check() if "--check" in sys.argv else main()
