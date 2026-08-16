"""Three-turn simulated-user regressions for the I-95/I-495 junction."""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from strands_evals import ActorSimulator, Case, Experiment  # noqa: E402
from strands_evals.evaluators import Evaluator  # noqa: E402
from strands_evals.types.evaluation import (  # noqa: E402
    EvaluationData,
    EvaluationOutput,
)
from strands_evals.types.simulation import ActorProfile  # noqa: E402
from strands_evals.types.trace import Session  # noqa: E402

from agent.dev_chat import configure_local_pricing_env  # noqa: E402
from agent.toll_agent import build_agent  # noqa: E402
from eval.deterministic.i95_i495_junctions.deterministic_i95_i495_junctions import (  # noqa: E402
    evaluate_junction_calls,
    evaluate_junction_response,
    load_rows,
    synthetic_calls,
)
from eval.simulation_support import (  # noqa: E402
    build_telemetry,
    extract_unique_tool_calls,
    raise_for_evaluation_errors,
    run_case_with_simulator,
)

_RESULTS_DIR = _REPO_ROOT / "eval" / "results"
_MODEL_ID_ENV = "NOVA_TOLL_EVAL_MODEL_ID"
_DEFAULT_MODEL_ID = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
_MAX_TURNS = 3


def build_batch_context() -> str:
    today = datetime.now(ZoneInfo("America/New_York")).date()
    return (
        f"The evaluation date in America/New_York is {today:%B} {today.day}, "
        f"{today.year}. TollChat is pricing-only. A known toll total should add "
        "every returned fare while excluding the unpriced I-95/I-495 junction; "
        "that sum is not a complete operator-issued fare."
    )


def load_cases() -> list[Case[str, str]]:
    cases: list[Case[str, str]] = []
    for row in load_rows():
        if "actor_challenge" not in row:
            continue
        cases.append(
            Case[str, str](
                name=f"{row['id']}-simulated",
                input=row["conversation"][0]["content"],
                metadata={
                    **row,
                    "batch_judge_suite": "i95_i495_junctions",
                    "batch_judge_context": build_batch_context(),
                    "task_description": (
                        "Keep the assigned route and historical time fixed. Verify "
                        "the movement-aware I-95 boundary and known toll total."
                    ),
                },
                expected_assertion=(
                    "Across at most three turns, TollChat keeps the fixed trip, uses "
                    "the fixture's movement-specific I-95 boundary or unavailable "
                    "status, sums all successfully returned fares, and clearly "
                    "excludes the unpriced junction without calling it free."
                ),
            )
        )
    return cases


def build_actor_profile(case: Case[str, str]) -> ActorProfile:
    metadata = case.metadata or {}
    plan = metadata["expected_calls"][0]["input"]
    return ActorProfile(
        traits={
            "communication_style": "concise, skeptical, and persistent",
            "domain_knowledge": "driver who understands the I-95/I-495 junction",
        },
        context=(
            f"Your immutable origin is {plan['origin']}, destination is "
            f"{plan['destination']}, and departure time is {metadata['at_time']}. "
            "The physical junction is unpriced, but every returned segment fare "
            "can be added into a known toll total."
        ),
        actor_goal=(
            "Use at most three turns. Begin with the supplied request. After the "
            f"first answer: {metadata['actor_challenge']} Never change the route or "
            "time, request alternate routing, or supply an expected dollar amount."
        ),
    )


class JunctionSimulationEvaluator(Evaluator[str, str]):
    """Code-grade unique tool executions and the complete conversation."""

    def evaluate(
        self, evaluation_case: EvaluationData[str, str]
    ) -> list[EvaluationOutput]:
        if not isinstance(evaluation_case.actual_trajectory, Session):
            return [
                EvaluationOutput(
                    score=0.0,
                    test_pass=False,
                    reason="actual trajectory was not a telemetry session",
                    label="bad_trajectory",
                )
            ]
        calls = extract_unique_tool_calls(evaluation_case.actual_trajectory)
        metadata = evaluation_case.metadata or {}
        return evaluate_junction_calls(calls, metadata) + evaluate_junction_response(
            str(evaluation_case.actual_output or ""), calls, metadata
        )


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
            max_turns=_MAX_TURNS,
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
        evaluators=[JunctionSimulationEvaluator()],
    ).run_evaluations(task_function)
    _RESULTS_DIR.mkdir(exist_ok=True)
    report.to_file(str(_RESULTS_DIR / f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"))
    print(f"Overall score: {report.overall_score:.2f}")
    report.display(include_input=False)
    raise_for_evaluation_errors(report)


def _self_check() -> None:
    cases = load_cases()
    assert len(cases) == 3
    assert all(case.expected_assertion for case in cases)
    assert all(
        "at most three turns" in build_actor_profile(case).actor_goal for case in cases
    )
    challenges = [build_actor_profile(case).actor_goal.casefold() for case in cases]
    assert "springfield/franconia" in challenges[0]
    assert "edsall" in challenges[1]
    assert "free" in challenges[2]
    bad = JunctionSimulationEvaluator().evaluate(
        EvaluationData[str, str](input="x", actual_output="", actual_trajectory=[])
    )
    assert bad[0].label == "bad_trajectory"
    row = load_rows()[0]
    calls = synthetic_calls(row)
    assert evaluate_junction_calls(calls, row)[0].label == "junction_ok"
    wrong_response = (
        "Known segment prices. Unpriced junction at Braddock: the gap is $0.00. "
        "Calculation. Known toll total."
    )
    assert evaluate_junction_response(wrong_response, calls, row)[0].label == "zero_gap"
    print("self-check ok (3 profiles, response guard, and three-turn cap)")


if __name__ == "__main__":
    _self_check() if "--check" in sys.argv else main()
