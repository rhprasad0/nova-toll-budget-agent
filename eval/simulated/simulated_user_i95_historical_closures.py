"""Observational simulated-user eval for Issue #17's four I-95 closures."""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from strands_evals import ActorSimulator, Case, Experiment  # noqa: E402
from strands_evals.evaluators import (  # noqa: E402
    Evaluator,
    GoalSuccessRateEvaluator,
    HelpfulnessEvaluator,
)
from strands_evals.types.evaluation import (  # noqa: E402
    EvaluationData,
    EvaluationOutput,
)
from strands_evals.types.simulation import ActorProfile  # noqa: E402
from strands_evals.types.trace import Session  # noqa: E402

from agent.dev_chat import configure_local_pricing_env  # noqa: E402
from agent.toll_agent import build_agent  # noqa: E402
from eval.deterministic.i95_historical_closures.deterministic_i95_historical_closures import (  # noqa: E402
    evaluate_closure_calls,
)
from eval.simulation_support import (  # noqa: E402
    build_telemetry,
    extract_unique_tool_calls,
    raise_for_evaluation_errors,
    run_case_with_simulator,
)

_CASES_PATH = (
    _REPO_ROOT
    / "eval"
    / "deterministic"
    / "i95_historical_closures"
    / "test-cases.jsonl"
)
_RESULTS_DIR = _REPO_ROOT / "eval" / "results"
_MODEL_ID_ENV = "NOVA_TOLL_EVAL_MODEL_ID"
_DEFAULT_MODEL_ID = "us.anthropic.claude-haiku-4-5-20251001-v1:0"


def load_cases(path: Path = _CASES_PATH) -> list[Case[str, str]]:
    cases: list[Case[str, str]] = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        row: dict[str, Any] = json.loads(line)
        cases.append(
            Case[str, str](
                name=f"{row['id']}-simulated",
                input=row["conversation"][0]["content"],
                metadata={
                    **row,
                    "task_description": (
                        "The driver wants only the requested historical I-95 Express "
                        "Lanes fare. The origin, destination, and time are complete and "
                        "must not be changed. If those lanes are closed, they need a "
                        "safe alternative suggestion without an invented toll quote."
                    ),
                },
                expected_assertion=(
                    "Across the conversation, the agent consistently says the "
                    "requested I-95 Express Lanes trip is unavailable, quotes no "
                    "fare for it or the general-purpose lanes, and identifies the "
                    "I-95 general-purpose lanes as an unpriced alternative."
                ),
            )
        )
    return cases


def build_actor_profile(case: Case[str, str]) -> ActorProfile:
    metadata = case.metadata or {}
    expected_input = metadata["expected_trajectory"][0]["input"]
    return ActorProfile(
        traits={"communication_style": "concise and direct"},
        context=(
            f"Your trip origin is {expected_input['origin']}, destination is "
            f"{expected_input['destination']}, and departure time is "
            f"{expected_input['at_time']}. These facts are fixed; never change them."
        ),
        actor_goal=(
            "Get the requested pricing result. If the lanes are closed, continue "
            "with staged pricing clarification: first confirm that no Express fare "
            "exists, then ask separately whether the I-95 general-purpose lanes are "
            "unpriced. Do not ask for source documentation, alternate corridors, "
            "live traffic routing, or change the trip facts."
        ),
    )


def build_helpfulness_evaluator(
    model_id: str, today: date | None = None
) -> HelpfulnessEvaluator[str, str]:
    evaluation_date = today or datetime.now(ZoneInfo("America/New_York")).date()
    evaluator: HelpfulnessEvaluator[str, str] = HelpfulnessEvaluator(model=model_id)
    evaluator.system_prompt += (
        "\n\n# Evaluation context\n"
        f"The evaluation date in America/New_York is "
        f"{evaluation_date:%B} {evaluation_date.day}, {evaluation_date.year}. "
        "TollChat is a pricing-only assistant. Live traffic routing and source "
        "documentation are outside its scope; do not penalize the agent for not "
        "providing them, and do not reward unsupported facts."
    )
    return evaluator


class ClosureSimulationTraceEvaluator(Evaluator[str, str]):
    """Grade unique raw tool execution spans without LLM trace duplication."""

    def evaluate(
        self, evaluation_case: EvaluationData[str, str]
    ) -> list[EvaluationOutput]:
        trajectory = evaluation_case.actual_trajectory
        if not isinstance(trajectory, Session):
            return [
                EvaluationOutput(
                    score=0.0,
                    test_pass=False,
                    reason="actual trajectory was not a telemetry session",
                    label="bad_trajectory",
                )
            ]

        calls = extract_unique_tool_calls(trajectory)
        return evaluate_closure_calls(calls, evaluation_case.metadata or {})


def main() -> None:
    configure_local_pricing_env()
    model_id = os.environ.get(_MODEL_ID_ENV, _DEFAULT_MODEL_ID)
    if not model_id:
        raise ValueError(f"{_MODEL_ID_ENV} must not be empty")
    telemetry, mapper = build_telemetry()

    def task_function(case: Case[str, str]) -> dict[str, object]:
        simulator = ActorSimulator(
            actor_profile=build_actor_profile(case),
            initial_query=str(case.input),
            model=model_id,
            max_turns=3,
        )
        return run_case_with_simulator(
            case.session_id,
            build_agent(),
            simulator,
            str(case.input),
            telemetry,
            mapper,
        )

    report = Experiment[str, str](
        cases=load_cases(),
        evaluators=[
            ClosureSimulationTraceEvaluator(),
            GoalSuccessRateEvaluator(model=model_id),
            build_helpfulness_evaluator(model_id),
        ],
    ).run_evaluations(task_function)
    _RESULTS_DIR.mkdir(exist_ok=True)
    report.to_file(str(_RESULTS_DIR / f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"))
    print(f"Overall score: {report.overall_score:.2f}")
    report.display(include_input=False)
    raise_for_evaluation_errors(report)


def _self_check() -> None:
    cases = load_cases()
    assert len(cases) == 4
    assert len({case.name for case in cases}) == 4
    assert all(case.input for case in cases)
    assert all(case.expected_assertion for case in cases)
    assert all((case.metadata or {}).get("task_description") for case in cases)
    assert all((case.metadata or {}).get("expected_trajectory") for case in cases)
    print(
        "self-check ok (Case shapes only; live simulator, telemetry, and judges excluded)"
    )


if __name__ == "__main__":
    if "--check" in sys.argv:
        _self_check()
    else:
        main()
