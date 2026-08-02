"""Three-turn simulated-user evaluation for the eight single-leg base cases."""

from __future__ import annotations

import os
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, cast
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
from strands_evals.types.trace import (  # noqa: E402
    AgentInvocationSpan,
    Session,
    ToolExecutionSpan,
)

from agent.dev_chat import configure_local_pricing_env  # noqa: E402
from agent.toll_agent import build_agent  # noqa: E402
from eval.deterministic.single_leg_base_cases.deterministic_single_leg_base_cases import (  # noqa: E402
    evaluate_single_leg_calls,
    load_rows,
)
from eval.simulation_support import (  # noqa: E402
    build_telemetry,
    raise_for_evaluation_errors,
    run_case_with_simulator,
)

_RESULTS_DIR = _REPO_ROOT / "eval" / "results"
_MODEL_ID_ENV = "NOVA_TOLL_EVAL_MODEL_ID"
_DEFAULT_MODEL_ID = "us.anthropic.claude-haiku-4-5-20251001-v1:0"


def _follow_up(metadata: dict[str, Any]) -> str:
    if metadata.get("expected_observed_display"):
        return (
            "After confirming the fare and arithmetic, ask when VDOT observed the "
            "price. Do not suggest an answer."
        )
    return (
        "After confirming the fare and arithmetic, ask which Greenway rate period "
        "applies and why. Do not suggest an answer."
    )


def load_cases() -> list[Case[str, str]]:
    cases: list[Case[str, str]] = []
    for row in load_rows():
        fare = row["expected_final_usd"]
        provenance = (
            f"the VDOT observation time {row['expected_observed_display']}"
            if row.get("expected_observed_display")
            else f"the {row['expected_rate_period']} Greenway rate period"
        )
        cases.append(
            Case[str, str](
                name=f"{row['id']}-simulated",
                input=row["conversation"][0]["content"],
                metadata={
                    **row,
                    "task_description": (
                        "The driver wants the exact price for one fixed toll-road "
                        "trip. The origin, destination, and time are complete and "
                        "must never change."
                    ),
                    "simulation_follow_up": _follow_up(row),
                },
                expected_assertion=(
                    "Across all three turns, the agent keeps the fixed trip facts, "
                    f"consistently reports the exact final fare ${fare} with correct "
                    "arithmetic, and explains "
                    f"{provenance} without inventing another route or price."
                ),
            )
        )
    return cases


def build_actor_profile(case: Case[str, str]) -> ActorProfile:
    metadata = case.metadata or {}
    expected = metadata["expected_trajectory"][0]["input"]
    return ActorProfile(
        traits={
            "communication_style": "concise and direct",
            "domain_knowledge": "ordinary driver who wants auditable pricing",
        },
        context=(
            f"Your immutable trip origin is {expected['origin']}, destination is "
            f"{expected['destination']}, and departure time is {expected['at_time']}. "
            "Never change, omit, or reinterpret these facts."
        ),
        actor_goal=(
            "Use exactly three turns. Start with the supplied price request. After "
            "the first answer, ask the agent to confirm the final fare and show the "
            f"calculation. {_follow_up(metadata)} Do not request alternate routes, "
            "live traffic, source documents, or a different travel time."
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
        "TollChat is a pricing-only assistant. The case's historical trip time is "
        "intentional. Live routing and source-document requests are out of scope; "
        "do not penalize the agent for omitting them or reward unsupported facts."
    )
    return evaluator


class SingleLegSimulationTraceEvaluator(Evaluator[str, str]):
    """Code-grade unique tool executions from the agent-only telemetry session."""

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

        calls: list[dict[str, Any]] = []
        turn_count = 0
        seen: set[tuple[str, str]] = set()
        for trace_index, trace in enumerate(trajectory.traces):
            for span_index, span in enumerate(trace.spans):
                if isinstance(span, AgentInvocationSpan):
                    turn_count += 1
                if not isinstance(span, ToolExecutionSpan):
                    continue
                span_id = span.span_info.span_id or f"{trace_index}:{span_index}"
                key = (trace.trace_id, span_id)
                if key in seen:
                    continue
                seen.add(key)
                calls.append(
                    {
                        "name": span.tool_call.name,
                        "input": cast(
                            dict[str, Any],
                            span.tool_call.arguments,  # pyright: ignore[reportUnknownMemberType]
                        ),
                        "tool_result": span.tool_result.content,
                    }
                )
        return _evaluate_simulation(calls, turn_count, evaluation_case.metadata or {})


def _evaluate_simulation(
    calls: list[dict[str, Any]], turn_count: int, metadata: dict[str, Any]
) -> list[EvaluationOutput]:
    if turn_count != 3:
        return [
            EvaluationOutput(
                score=0.0,
                test_pass=False,
                reason=f"expected exactly three agent turns, got {turn_count}",
                label="turn_count",
            )
        ]
    return evaluate_single_leg_calls(calls, metadata)


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
            SingleLegSimulationTraceEvaluator(),
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
    assert len(cases) == 8
    assert len({case.name for case in cases}) == 8
    assert all(case.input and case.expected_assertion for case in cases)
    assert all((case.metadata or {}).get("task_description") for case in cases)
    assert all((case.metadata or {}).get("simulation_follow_up") for case in cases)
    assert all(
        "exactly three turns" in build_actor_profile(case).actor_goal for case in cases
    )
    assert (
        sum("VDOT" in (case.metadata or {})["simulation_follow_up"] for case in cases)
        == 6
    )
    assert (
        sum(
            "Greenway" in (case.metadata or {})["simulation_follow_up"]
            for case in cases
        )
        == 2
    )
    bad = SingleLegSimulationTraceEvaluator().evaluate(
        EvaluationData[str, str](input="x", actual_output="", actual_trajectory=[])
    )
    assert bad[0].label == "bad_trajectory"
    row = load_rows()[0]
    expected = row["expected_trajectory"][0]
    call = {
        "name": expected["tool"],
        "input": expected["input"],
        "tool_result": row["expected_result"],
    }
    assert _evaluate_simulation([call], 2, row)[0].label == "turn_count"
    assert _evaluate_simulation([call], 3, row)[0].label == "exact_result"
    print("self-check ok (8 case/profile shapes and bad-session guard; no network)")


if __name__ == "__main__":
    if "--check" in sys.argv:
        _self_check()
    else:
        main()
