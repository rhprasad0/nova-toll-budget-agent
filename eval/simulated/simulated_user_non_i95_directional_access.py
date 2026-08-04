"""Simulated drivers exercise fixed directional-ramp recovery."""

from __future__ import annotations

import json
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
from eval.deterministic.non_i95_directional_access.deterministic_non_i95_directional_access import (  # noqa: E402
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
    cases: list[Case[str, str]] = []
    # The cross-corridor and direct I-66 cases cover both complete replanning
    # and same-tool recovery; the deterministic suite covers all corridors.
    for row in load_rows()[:2]:
        selected = row["expected_mismatch"]["constraint"]["nearby_options"][0]
        cases.append(
            Case(
                name=f"{row['id']}-simulated",
                input=row["conversation"][0]["content"],
                metadata={**row, "selected_alternative": selected},
                expected_assertion=(
                    "The agent explains the fixed wrong-way ramp, offers only "
                    "compatible choices, and uses the selected recovery without "
                    "inventing a fare or changing the other endpoint."
                ),
            )
        )
    return cases


def build_actor_profile(case: Case[str, str]) -> ActorProfile:
    selected = (case.metadata or {})["selected_alternative"]
    return ActorProfile(
        traits={"communication_style": "concise and direct"},
        context=f"You are a driver. The only acceptable replacement is {selected!r}.",
        actor_goal=(
            "After the agent explains the fixed "
            f"directional restriction, say 'Use {selected} instead.' Then confirm "
            "that it kept the other endpoint. Do not propose another route."
        ),
    )


def _result(passed: bool, reason: str, label: str) -> list[EvaluationOutput]:
    return [
        EvaluationOutput(
            score=float(passed), test_pass=passed, reason=reason, label=label
        )
    ]


def _tool_result(call: dict[str, Any]) -> dict[str, Any]:
    value = call.get("tool_result")
    if isinstance(value, str):
        value = json.loads(value)
    return cast(dict[str, Any], value)


class RecoveryTraceEvaluator(Evaluator[str, str]):
    def evaluate(
        self, evaluation_case: EvaluationData[str, str]
    ) -> list[EvaluationOutput]:
        if not isinstance(evaluation_case.actual_trajectory, Session):
            return _result(False, "missing telemetry session", "bad_trajectory")
        metadata = evaluation_case.metadata or {}
        expected = metadata["expected_trajectory"][0]["calls"][0]
        calls = extract_unique_tool_calls(evaluation_case.actual_trajectory)
        same_tool = [call for call in calls if call["name"] == expected["tool"]]
        if len(same_tool) < 2:
            return _result(
                False, f"recovery calls were {[c['name'] for c in calls]}", "tool_order"
            )
        first, second = same_tool[:2]
        if _tool_result(first).get("status") != "one_way_mismatch":
            return _result(False, "first call did not reject the ramp", "wrong_access")
        role = metadata["expected_mismatch"]["constraint"]["role"]
        changed = "origin" if role == "entry" else "destination"
        original = expected["input"]
        selected = metadata["selected_alternative"]
        if first.get("input", {}).get(changed) != original[changed]:
            return _result(False, "first call changed the request", "input_mismatch")
        if second.get("input", {}).get(changed) != selected:
            return _result(
                False, "recovery ignored the selected option", "input_mismatch"
            )
        for key, value in original.items():
            if key != changed and second.get("input", {}).get(key) != value:
                return _result(False, f"recovery changed {key}", "input_mismatch")
        recovered = _tool_result(second)
        if recovered.get("status") == "one_way_mismatch" or "error" in recovered:
            return _result(
                False, f"selected recovery failed: {recovered}", "not_recovered"
            )
        return _result(True, "selected fixed-ramp recovery was replanned", "recovered")


def main() -> None:
    configure_local_pricing_env()
    model_id = os.environ.get(_MODEL_ID_ENV, _DEFAULT_MODEL_ID)
    telemetry, mapper = build_telemetry()

    def task(case: Case[str, str]) -> dict[str, object]:
        simulator = ActorSimulator(
            actor_profile=build_actor_profile(case),
            initial_query=str(case.input),
            model=model_id,
            max_turns=4,
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
            RecoveryTraceEvaluator(),
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
    assert len(cases) == 2
    assert all((case.metadata or {}).get("selected_alternative") for case in cases)
    assert all(
        "fixed directional restriction" in build_actor_profile(case).actor_goal
        for case in cases
    )
    bad = RecoveryTraceEvaluator().evaluate(
        EvaluationData[str, str](input="x", actual_output="", actual_trajectory=[])
    )
    assert bad[0].label == "bad_trajectory"
    print("self-check ok (two simulated recovery profiles; no network)")


if __name__ == "__main__":
    _self_check() if "--check" in sys.argv else main()
