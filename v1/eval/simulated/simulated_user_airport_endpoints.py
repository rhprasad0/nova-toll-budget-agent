"""Simulated drivers verify airport aliases, access, and misuse handling."""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

_REPO_ROOT = Path(__file__).resolve().parents[2]
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
from eval.deterministic.airport_endpoints.deterministic_airport_endpoints import (  # noqa: E402
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


def load_cases() -> list[Case[str, str]]:
    rows = {row["id"]: row for row in load_rows()}
    selected = [
        rows["iad-to-dulles-toll-road"],
        rows["i95-to-dca"],
        rows["access-highway-misuse"],
    ]
    return [
        Case(
            name=f"{row['id']}-simulated",
            input=row["conversation"][0]["content"],
            metadata=row,
            expected_assertion=(
                "The agent identifies the correct airport, keeps airport access "
                "untolled, itemizes only real tolls, and never treats the Dulles "
                "Airport Access Highway as a non-airport bypass."
            ),
        )
        for row in selected
    ]


def build_actor_profile(case: Case[str, str]) -> ActorProfile:
    metadata = case.metadata or {}
    misuse = metadata["id"] == "access-highway-misuse"
    return ActorProfile(
        traits={"communication_style": "concise and direct"},
        context="You are a driver who wants an accurate toll answer.",
        actor_goal=(
            "Confirm the agent does not invent a free route and end the conversation "
            "after the answer."
            if misuse
            else "Confirm the airport access portion and any actual toll charges, then end the conversation."
        ),
    )


def _result(passed: bool, reason: str, label: str) -> list[EvaluationOutput]:
    return [
        EvaluationOutput(
            score=float(passed), test_pass=passed, reason=reason, label=label
        )
    ]


class AirportSimulationTraceEvaluator(Evaluator[str, str]):
    def evaluate(
        self, evaluation_case: EvaluationData[str, str]
    ) -> list[EvaluationOutput]:
        session = evaluation_case.actual_trajectory
        if not isinstance(session, Session):
            return _result(False, "missing telemetry session", "bad_trajectory")
        metadata = evaluation_case.metadata or {}
        calls = extract_unique_tool_calls(session)
        expected = cast(list[dict[str, Any]], metadata["expected_calls"])
        if [call["name"] for call in calls] != [call["name"] for call in expected]:
            return _result(False, f"unexpected calls {calls}", "tool_mismatch")
        for actual, wanted in zip(calls, expected, strict=True):
            if actual["input"] != wanted["input"]:
                return _result(
                    False, f"expected {wanted}, got {actual}", "input_mismatch"
                )
        return _result(True, "airport tool trajectory matched", "route_matched")


def main() -> None:
    configure_local_pricing_env()
    model_id = os.environ.get(_MODEL_ID_ENV, _DEFAULT_MODEL_ID)
    telemetry, mapper = build_telemetry()

    def task(case: Case[str, str]) -> dict[str, object]:
        simulator = ActorSimulator(
            actor_profile=build_actor_profile(case),
            initial_query=str(case.input),
            model=model_id,
            max_turns=2,
        )
        return run_case_with_simulator(
            case.session_id,
            build_agent(),
            simulator,
            str(case.input),
            telemetry,
            mapper,
        )

    report = Experiment(
        cases=load_cases(),
        evaluators=[
            AirportSimulationTraceEvaluator(),
            GoalSuccessRateEvaluator(model=model_id),
            HelpfulnessEvaluator(model=model_id),
        ],
    ).run_evaluations(task)
    _RESULTS_DIR.mkdir(exist_ok=True)
    report.to_file(str(_RESULTS_DIR / f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"))
    report.display(include_input=False)
    raise_for_evaluation_errors(report)


def _self_check() -> None:
    cases = load_cases()
    assert len(cases) == 3
    assert {(case.name or "").split("-simulated")[0] for case in cases} == {
        "iad-to-dulles-toll-road",
        "i95-to-dca",
        "access-highway-misuse",
    }
    print("self-check ok (three airport user-simulation profiles; no network)")


if __name__ == "__main__":
    _self_check() if "--check" in sys.argv else main()
