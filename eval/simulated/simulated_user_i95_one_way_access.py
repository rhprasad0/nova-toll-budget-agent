"""Up-to-three-turn simulated-user evidence for I-95/395 access recovery."""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
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
from strands_evals.types.trace import Session  # noqa: E402

from agent.dev_chat import configure_local_pricing_env  # noqa: E402
from agent.toll_agent import build_agent  # noqa: E402
from eval.deterministic.i95_one_way_access.deterministic_i95_one_way_access import (  # noqa: E402
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
    for row in load_rows()[:2]:
        constraint = row["expected_mismatch"]["constraint"]
        selected = constraint["nearby_options"][0]
        cases.append(
            Case[str, str](
                name=f"{row['id']}-simulated",
                input=row["conversation"][0]["content"],
                metadata={**row, "selected_alternative": selected},
                expected_assertion=(
                    "The agent explains why the originally requested I-95/395 "
                    "Express Lanes ramp cannot serve this direction, offers only "
                    "the two compatible nearby choices, and prices or truthfully "
                    "reports unavailable the route after the driver selects the "
                    "assigned alternative. It never substitutes a different ramp "
                    "or invents a fare."
                ),
            )
        )
    return cases


def build_actor_profile(case: Case[str, str]) -> ActorProfile:
    metadata = case.metadata or {}
    selected = metadata["selected_alternative"]
    return ActorProfile(
        traits={"communication_style": "concise and direct"},
        context=(
            "You are an ordinary driver. Your original trip facts are fixed and "
            f"the only acceptable replacement is {selected!r}."
        ),
        actor_goal=(
            "Use up to three turns: first ask for the original trip without "
            "volunteering an alternative; after the agent explains the one-way "
            f"constraint, say 'Use {selected} instead.'; after the result, ask "
            "whether that was the selected route. Do not change the trip, request "
            "a different road, or ask for live traffic routing."
        ),
    )


def _result(passed: bool, reason: str, label: str) -> list[EvaluationOutput]:
    return [
        EvaluationOutput(
            score=float(passed), test_pass=passed, reason=reason, label=label
        )
    ]


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


class OneWaySimulationTraceEvaluator(Evaluator[str, str]):
    """Code-grade the distinct access and recovery calls across actor turns."""

    def evaluate(
        self, evaluation_case: EvaluationData[str, str]
    ) -> list[EvaluationOutput]:
        session = evaluation_case.actual_trajectory
        if not isinstance(session, Session):
            return _result(
                False, "actual trajectory was not a telemetry session", "bad_trajectory"
            )
        metadata = evaluation_case.metadata or {}
        expected = metadata["expected_trajectory"][0]["calls"][0]["input"]
        selected = metadata["selected_alternative"]
        calls = extract_unique_tool_calls(session)
        if [call["name"] for call in calls] != [
            "i95_access_options",
            "i95_access_options",
            "i95_route",
        ]:
            return _result(
                False,
                f"unexpected calls: {[call['name'] for call in calls]}",
                "tool_order",
            )
        expected_selected = {
            **expected,
            "origin"
            if metadata["expected_mismatch"]["constraint"]["role"] == "entry"
            else "destination": selected,
        }
        if not _matches_input(calls[0], expected) or any(
            not _matches_input(call, expected_selected) for call in calls[1:]
        ):
            return _result(
                False,
                "access or pricing inputs changed the assigned route",
                "input_mismatch",
            )
        first = _tool_result(calls[0])
        second = _tool_result(calls[1])
        if first is None or second is None:
            return _result(False, "missing access-check result", "bad_access_result")
        if (
            first.get("status") != "one_way_mismatch"
            or second.get("status") != "supported"
        ):
            return _result(
                False,
                f"unexpected access results: {first}, {second}",
                "wrong_access_result",
            )
        return _result(
            True,
            "recovery kept the route and priced only the selected alternative",
            "recovered",
        )


def build_helpfulness_evaluator(model_id: str) -> HelpfulnessEvaluator[str, str]:
    today = datetime.now(ZoneInfo("America/New_York")).date()
    evaluator: HelpfulnessEvaluator[str, str] = HelpfulnessEvaluator(model=model_id)
    evaluator.system_prompt += (
        "\n\n# Evaluation context\n"
        f"The evaluation date in America/New_York is {today:%B} {today.day}, {today.year}. "
        "TollChat prices Northern Virginia toll roads only. Do not reward invented "
        "routing, fares, or access points. When I-95 Express Lanes are unavailable, "
        "it is appropriate to state that precisely and call the I-95 general-purpose "
        "lanes an unpriced alternative. Do not infer that this claims the general-purpose "
        "lanes are closed or require a non-tool-grounded alternate route."
    )
    return evaluator


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
            OneWaySimulationTraceEvaluator(),
            GoalSuccessRateEvaluator(model=model_id),
            build_helpfulness_evaluator(model_id),
        ],
    ).run_evaluations(task_function)
    _RESULTS_DIR.mkdir(exist_ok=True)
    report.to_file(str(_RESULTS_DIR / f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"))
    report.display(include_input=False)
    raise_for_evaluation_errors(report)


def _self_check() -> None:
    cases = load_cases()
    assert len(cases) == 2
    assert all(
        "up to three turns" in build_actor_profile(case).actor_goal for case in cases
    )
    assert all((case.metadata or {}).get("selected_alternative") for case in cases)
    assert (
        "Do not infer that this claims"
        in build_helpfulness_evaluator("test").system_prompt
    )
    bad = OneWaySimulationTraceEvaluator().evaluate(
        EvaluationData[str, str](input="x", actual_output="", actual_trajectory=[])
    )
    assert bad[0].label == "bad_trajectory"
    print("self-check ok (two actor profiles and calibrated judge; no network)")


if __name__ == "__main__":
    if "--check" in sys.argv:
        _self_check()
    else:
        main()
