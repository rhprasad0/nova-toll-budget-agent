"""Three-turn simulated-user track for Issue #19 junction routing."""

from __future__ import annotations

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

from agent.toll_agent import build_agent  # noqa: E402
from eval.deterministic.i66_i495_dulles_junctions.deterministic_i66_i495_dulles_junctions import (  # noqa: E402
    controlled_pricing,
    evaluate_junction_calls,
    fixture_calls,
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
_MAX_TURNS = 3


def _directions(row: dict[str, Any]) -> str:
    names = {"WB": "westbound", "EB": "eastbound"}
    directions = [str(segment["direction"]) for segment in row["expected_priced"]]
    return " then ".join(
        names.get(direction) or direction.casefold() for direction in directions
    )


def _assertion(row: dict[str, Any]) -> str:
    connector = row["expected_connector"]["label"]
    return (
        "Across the conversation, TollChat keeps the assigned route and directions, "
        f"specifically {_directions(row)}, uses the {connector}, preserves every "
        "captured fare, and performs arithmetic "
        "only over those fares without billing the connector, inventing a reverse edge, "
        "or substituting I-66 Outside the Beltway."
    )


def load_cases() -> list[Case[str, str]]:
    return [
        Case[str, str](
            name=f"{row['id']}-simulated",
            input=row["prompt"],
            metadata={
                **row,
                "task_description": (
                    "Price one fixed cross-corridor trip, then confirm its directed "
                    "junction and auditable fare calculation without changing roads."
                ),
            },
            expected_assertion=_assertion(row),
        )
        for row in load_rows()
    ]


def build_actor_profile(case: Case[str, str]) -> ActorProfile:
    metadata = case.metadata or {}
    plan_input = metadata["plan_input"]
    connector = metadata["expected_connector"]["label"]
    return ActorProfile(
        traits={
            "communication_style": "concise and verification-oriented",
            "domain_knowledge": "ordinary driver who understands compass directions",
        },
        context=(
            f"Your immutable trip origin is {plan_input['origin']} on "
            f"{plan_input['origin_corridor']}; destination is "
            f"{plan_input['destination']} on {plan_input['destination_corridor']}. "
            f"The documented handoff is {connector}. Never change, omit, reverse, or "
            f"reinterpret those facts. The segment directions are {_directions(metadata)}. "
            "Tool-returned fares are authoritative."
        ),
        actor_goal=(
            "Use up to three turns. Start with the supplied price request. After the "
            "first answer, ask TollChat to confirm the junction and travel directions. "
            "Then ask it to confirm every fare item, show the arithmetic, and verify "
            "that the connector is untolled rather than a separate billed fare. Never "
            "state a direction other than the exact directions in your context or "
            "request another route, time, live traffic, or source documentation."
        ),
    )


def build_helpfulness_evaluator(model_id: str) -> HelpfulnessEvaluator[str, str]:
    evaluation_date = datetime.now(ZoneInfo("America/New_York")).date()
    evaluator: HelpfulnessEvaluator[str, str] = HelpfulnessEvaluator(model=model_id)
    evaluator.system_prompt += (
        "\n\n# Evaluation context\n"
        f"The evaluation date in America/New_York is "
        f"{evaluation_date:%B} {evaluation_date.day}, {evaluation_date.year}. "
        "TollChat is a pricing-only assistant. Its planner-provided I-66/I-495 and "
        "I-495/Route 267 connectors are untolled handoffs, not billed $0 fares. "
        "Do not reward alternate routing, live-traffic advice, or source requests."
    )
    return evaluator


def evaluate_conversation_calls(
    calls: list[dict[str, Any]], metadata: dict[str, Any]
) -> list[EvaluationOutput]:
    """Grade every complete lookup, independent of parallel completion order."""
    groups: list[list[dict[str, Any]]] = []
    for call in calls:
        if call["name"] == "plan_toll_route":
            groups.append([])
        if not groups:
            return evaluate_junction_calls(calls, metadata)
        groups[-1].append(call)

    expected = cast(list[str], metadata.get("expected_tools", []))
    if not groups or len(expected) != 3:
        return evaluate_junction_calls(calls, metadata)
    for group in groups:
        by_name = {call["name"]: call for call in group}
        if set(by_name) != set(expected) or len(group) != len(expected):
            return evaluate_junction_calls(group, metadata)
        result = evaluate_junction_calls([by_name[name] for name in expected], metadata)
        if not result[0].test_pass:
            return result
    return [
        EvaluationOutput(
            score=1.0,
            test_pass=True,
            reason=f"{len(groups)} complete junction lookup(s) are grounded",
            label="trace_grounded",
        )
    ]


class JunctionSimulationTraceEvaluator(Evaluator[str, str]):
    """Code-grade unique agent tool executions across all conversation turns."""

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
        metadata = evaluation_case.metadata or {}
        return evaluate_conversation_calls(calls, metadata)


def main() -> None:
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

    with controlled_pricing():
        report = Experiment[str, str](
            cases=load_cases(),
            evaluators=[
                JunctionSimulationTraceEvaluator(),
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
    assert len(cases) == 16
    assert _MAX_TURNS == 3
    assert len({case.name for case in cases}) == 16
    assert all(case.expected_assertion for case in cases)
    assert all("immutable" in build_actor_profile(case).context for case in cases)
    assert all("three turns" in build_actor_profile(case).actor_goal for case in cases)
    assert all(
        _directions(case.metadata or {}) in str(case.expected_assertion)
        for case in cases
    )
    evaluator = JunctionSimulationTraceEvaluator()
    bad = evaluator.evaluate(
        EvaluationData[str, str](
            input="x", actual_output="", actual_trajectory=[], metadata={}
        )
    )
    assert bad[0].label == "bad_trajectory"
    empty = evaluator.evaluate(
        EvaluationData[str, str](
            input="x",
            actual_output="",
            actual_trajectory=Session(session_id="x", traces=[]),
            metadata=cast(dict[str, Any], cases[0].metadata),
        )
    )
    assert empty[0].label == "tool_sequence"
    metadata = cast(dict[str, Any], cases[0].metadata)
    calls = fixture_calls(metadata)
    parallel = [calls[0], calls[2], calls[1]]
    assert evaluate_conversation_calls(parallel, metadata)[0].test_pass
    assert evaluate_conversation_calls(parallel * 2, metadata)[0].test_pass
    assert not evaluate_conversation_calls(calls[:-1], metadata)[0].test_pass
    print("self-check ok (16 three-turn profiles and telemetry guards; no network)")


if __name__ == "__main__":
    if "--check" in sys.argv:
        _self_check()
    else:
        main()
