"""Observational simulated-user track for Issue #17's 95/495 junction cases."""

from __future__ import annotations

import json
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
from strands_evals.types.trace import Session, ToolExecutionSpan  # noqa: E402

from agent.dev_chat import configure_local_pricing_env  # noqa: E402
from agent.toll_agent import build_agent  # noqa: E402
from eval.deterministic.i95_i495_junctions.deterministic_i95_i495_junctions import (  # noqa: E402
    evaluate_junction_calls,
)
from eval.simulation_support import (  # noqa: E402
    build_telemetry,
    raise_for_evaluation_errors,
    run_case_with_simulator,
)

_CASES_PATH = (
    _REPO_ROOT / "eval" / "deterministic" / "i95_i495_junctions" / "test-cases.jsonl"
)
_RESULTS_DIR = _REPO_ROOT / "eval" / "results"
_MODEL_ID_ENV = "NOVA_TOLL_EVAL_MODEL_ID"
_DEFAULT_MODEL_ID = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
_MAX_TURNS = 3


def _assertion(row: dict[str, Any]) -> str:
    unavailable = row["expected_junction"]["pricing_status"] == "unavailable"
    i95_outcome = (
        "reports the I-95 leg unavailable without a fare"
        if unavailable
        else "reports the captured I-95 segment price"
    )
    i495_outcome = (
        "does not call or price I-495"
        if row.get("expect_unpriced_remainder")
        else "preserves the independently captured I-495 segment price"
    )
    return (
        f"Across the conversation, TollChat {i95_outcome}, {i495_outcome}, "
        "describes the 95/495 junction as unpriced rather than free, and never "
        "provides arithmetic, a subtotal, or a complete total."
    )


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
                        "Keep the assigned route and historical departure time fixed. "
                        "Confirm the known segment fares and the unpriced 95/495 gap "
                        "without asking TollChat to invent a complete price."
                    ),
                },
                expected_assertion=_assertion(row),
            )
        )
    return cases


def build_actor_profile(case: Case[str, str]) -> ActorProfile:
    metadata = case.metadata or {}
    plan_input = metadata["expected_calls"][0]["input"]
    return ActorProfile(
        traits={"communication_style": "concise and skeptical of missing prices"},
        context=(
            f"Your origin resolves to {plan_input['origin']}, destination resolves "
            f"to {plan_input['destination']}, and departure time is "
            f"{metadata['at_time']}. These facts are immutable. The road between "
            "the selected I-95 boundary and I-495 Near Braddock Road has no price."
        ),
        actor_goal=(
            "Get the assigned trip priced, then ask whether the known segment prices "
            "can be combined despite the unpriced gap. Accept a clear refusal to "
            "calculate a complete total. Never change the route, time, direction, "
            "or request live traffic or source documentation."
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
        "TollChat is a pricing-only assistant. The I-95/I-495 junction gap is "
        "intentionally unpriced, so refusing a subtotal or complete total is correct."
    )
    return evaluator


class JunctionSimulationTraceEvaluator(Evaluator[str, str]):
    """Grade unique raw tool spans rather than cumulative message history."""

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
        seen: set[tuple[str, str]] = set()
        for trace_index, trace in enumerate(trajectory.traces):
            for span_index, span in enumerate(trace.spans):
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
        return evaluate_junction_calls(calls, evaluation_case.metadata or {})


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
    assert len(cases) == 10
    assert _MAX_TURNS == 3
    assert len({case.name for case in cases}) == 10
    assert all(case.expected_assertion for case in cases)
    assert all("immutable" in build_actor_profile(case).context for case in cases)
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
    assert empty[0].label == "junction_call_required"
    print("self-check ok (10 profiles and synthetic trajectory failures)")


if __name__ == "__main__":
    if "--check" in sys.argv:
        _self_check()
    else:
        main()
