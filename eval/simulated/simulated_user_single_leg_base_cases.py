"""Three-turn simulated-user evaluation for the eight single-leg base cases."""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
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
from eval.deterministic.single_leg_base_cases.deterministic_single_leg_base_cases import (  # noqa: E402
    evaluate_single_leg_calls,
    load_rows,
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


def _follow_up(metadata: dict[str, Any]) -> str:
    if metadata.get("expected_observed_display"):
        return (
            "After confirming the fare and arithmetic, ask when VDOT observed the "
            "price. Do not suggest an answer."
        )
    return (
        "After confirming the fare and arithmetic, ask which Greenway rate period "
        "applies, which facility owns each mainline charge, and whether the "
        "total includes every listed charge. Do not name an expected facility or "
        "amount."
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
        fee_requirement = (
            " It must show the separate $2.00 Dulles Toll Road mainline item "
            "in the fixture's travel order."
            if row.get("expected_rate_period")
            else ""
        )
        cases.append(
            Case[str, str](
                name=f"{row['id']}-simulated",
                input=row["conversation"][0]["content"],
                metadata={
                    **row,
                    "batch_judge_suite": "single_leg_base_cases",
                    "batch_judge_context": build_helpfulness_context(),
                    "task_description": (
                        "The driver wants the exact price for one fixed toll-road "
                        "trip. The origin, destination, and time are complete and "
                        "must never change."
                    ),
                },
                expected_assertion=(
                    "Across the conversation, the agent keeps the fixed trip facts, "
                    f"consistently reports the exact final fare ${fare} with correct "
                    "arithmetic, and explains "
                    f"{provenance} without inventing another route or price."
                    f"{fee_requirement}"
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
            "Use up to three turns. Start with the supplied price request. After "
            "the first answer, ask the agent to confirm the final fare and show the "
            f"calculation. {_follow_up(metadata)} Do not request alternate routes, "
            "live traffic, source documents, or a different travel time."
        ),
    )


def build_helpfulness_context() -> str:
    evaluation_date = datetime.now(ZoneInfo("America/New_York")).date()
    return (
        f"The evaluation date in America/New_York is "
        f"{evaluation_date:%B} {evaluation_date.day}, {evaluation_date.year}. "
        "TollChat is a pricing-only assistant. The case's historical trip time is "
        "intentional. Live routing and source-document requests are out of scope; "
        "do not penalize the agent for omitting them or reward unsupported facts."
    )


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

        calls = extract_unique_tool_calls(trajectory)
        return evaluate_single_leg_calls(calls, evaluation_case.metadata or {})


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
    assert all(
        "up to three turns" in build_actor_profile(case).actor_goal for case in cases
    )
    assert "VDOT" in _follow_up(cases[0].metadata or {})
    assert "Greenway" in _follow_up(cases[-1].metadata or {})
    assert "facility owns each" in _follow_up(cases[-1].metadata or {})
    assert "total includes every listed charge" in _follow_up(cases[-1].metadata or {})
    assert "Dulles Toll Road" not in _follow_up(cases[-1].metadata or {})
    assert "$2.00" not in _follow_up(cases[-1].metadata or {})
    assert all(
        "separate $2.00 Dulles Toll Road" in str(case.expected_assertion)
        for case in cases[-2:]
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
    calls = [call]
    if expected["tool"] == "i95_route":
        calls.insert(
            0,
            {
                "name": "i95_access_options",
                "input": {
                    key: expected["input"][key] for key in ("origin", "destination")
                },
                "tool_result": {
                    "status": "supported",
                    "direction": row["expected_result"]["direction"],
                },
            },
        )
    assert evaluate_single_leg_calls(calls, row)[0].label == "exact_result"
    print("self-check ok (8 case/profile shapes and bad-session guard; no network)")


if __name__ == "__main__":
    if "--check" in sys.argv:
        _self_check()
    else:
        main()
