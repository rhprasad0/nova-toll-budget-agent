"""ActorSimulator driver that traces only the agent under test.

Call ``build_telemetry`` once from ``main``; simulator runs are nondeterministic.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Protocol, cast

from opentelemetry import baggage, context
from strands import Agent
from strands_evals import ActorSimulator, Case, Experiment, StrandsEvalsTelemetry
from strands_evals.evaluators import Evaluator
from strands_evals.mappers.strands_in_memory_session_mapper import (
    StrandsInMemorySessionMapper,
)
from strands_evals.types.evaluation import EvaluationData, EvaluationOutput
from strands_evals.types.evaluation_report import EvaluationReport
from strands_evals.types.simulation import ActorProfile, ActorResponse
from strands_evals.types.trace import AgentInvocationSpan, Session, ToolExecutionSpan


class Simulator(Protocol):
    def has_next(self) -> bool: ...
    def act(self, agent_message: str) -> object: ...


class PendingBatchJudgeEvaluator(Evaluator[str, str]):
    """Preserve a runnable report row while asynchronous judges are pending."""

    def evaluate(
        self, evaluation_case: EvaluationData[str, str]
    ) -> list[EvaluationOutput]:
        return [
            EvaluationOutput(
                score=1.0,
                test_pass=True,
                reason="OpenAI Batch judgment pending",
                label="pending_batch_judge",
            )
        ]


def run_simulated_conversation(
    agent_turn: Callable[[str], str],
    simulator: Simulator,
    first_message: str,
) -> str:
    """Drive agent and simulator turns until the simulator stops."""
    user_message = first_message
    responses: list[str] = []
    while simulator.has_next():
        response = agent_turn(user_message)
        responses.append(response)
        result = cast(SimpleNamespace, simulator.act(response))
        actor_response = cast(ActorResponse, result.structured_output)
        message = actor_response.message
        user_message = message if isinstance(message, str) else ""
    return "\n\n".join(responses)


def build_telemetry() -> tuple[StrandsEvalsTelemetry, StrandsInMemorySessionMapper]:
    """Install the process-global in-memory exporter."""
    telemetry = StrandsEvalsTelemetry().setup_in_memory_exporter()
    return telemetry, StrandsInMemorySessionMapper()


def extract_unique_tool_calls(session: Session) -> list[dict[str, Any]]:
    """Return each raw agent tool execution once, in telemetry order."""
    calls: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for trace_index, trace in enumerate(session.traces):
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
                    "turn_id": span.span_info.trace_id,
                    "name": span.tool_call.name,
                    "input": cast(
                        dict[str, Any],
                        span.tool_call.arguments,  # pyright: ignore[reportUnknownMemberType]
                    ),
                    "tool_result": span.tool_result.content,
                    "tool_error": span.tool_result.error,
                }
            )
    return calls


def run_case_with_simulator(
    session_id: str,
    agent: Agent,
    simulator: Simulator,
    first_message: str,
    telemetry: StrandsEvalsTelemetry,
    mapper: StrandsInMemorySessionMapper,
) -> dict[str, object]:
    """Run one case with baggage scoped away from simulator calls."""

    def traced_turn(message: str) -> str:
        ctx = baggage.set_baggage("session.id", session_id)
        ctx = baggage.set_baggage("gen_ai.conversation.id", session_id, ctx)
        token = context.attach(ctx)
        try:
            return str(agent(message))
        finally:
            context.detach(token)

    output = run_simulated_conversation(traced_turn, simulator, first_message)

    exporter = telemetry.in_memory_exporter
    assert exporter is not None, "telemetry.setup_in_memory_exporter() was never called"
    spans = list(exporter.get_finished_spans())
    session: Session = mapper.map_to_session(spans, session_id)
    turn_spans = [
        s for t in session.traces for s in t.spans if isinstance(s, AgentInvocationSpan)
    ]
    if not turn_spans:
        raise RuntimeError(
            f"no agent-invocation spans captured for session {session_id!r} -- "
            "telemetry wasn't installed before the first agent call, or every span "
            "leaked into a different session"
        )
    return {"output": output, "trajectory": session}


def raise_for_evaluation_errors(report: EvaluationReport) -> None:
    """Raise for SDK-isolated task/evaluator errors, not ordinary verdicts."""
    errors: list[str] = []
    cases = cast(list[dict[str, Any]], cast(Any, report).cases)
    for index, case in enumerate(cases):
        details = (
            report.detailed_results[index]
            if index < len(report.detailed_results)
            else []
        )
        if not details:
            reason = report.reasons[index] if index < len(report.reasons) else ""
            errors.append(f"{case.get('name', f'case {index}')}: {reason}")
    if errors:
        raise RuntimeError("evaluation execution failed: " + "; ".join(errors))


def run_simulated_evaluation(
    case: Case[str, str],
    actor_profile: ActorProfile,
    model_id: str,
    results_dir: Path,
    agent_factory: Callable[[], Agent],
) -> None:
    """Run one simulated case and save its transcript for Batch judges."""
    telemetry, mapper = build_telemetry()

    def task_function(case: Case[str, str]) -> dict[str, object]:
        simulator = ActorSimulator(
            actor_profile=actor_profile,
            initial_query=str(case.input),
            model=model_id,
            max_turns=3,
        )
        return run_case_with_simulator(
            case.session_id,
            agent_factory(),
            simulator,
            str(case.input),
            telemetry,
            mapper,
        )

    experiment = Experiment[str, str](
        cases=[case],
        evaluators=[
            PendingBatchJudgeEvaluator(),
        ],
    )
    report = experiment.run_evaluations(task_function)
    results_dir.mkdir(exist_ok=True)
    report.to_file(str(results_dir / f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"))
    print(f"Overall score: {report.overall_score:.2f}")
    report.display(include_input=False)
    raise_for_evaluation_errors(report)


class _FakeSimulator:
    def __init__(self, turns: int) -> None:
        self._remaining = turns

    def has_next(self) -> bool:
        return self._remaining > 0

    def act(self, agent_message: str) -> object:
        self._remaining -= 1
        stop = self._remaining <= 0
        structured_output = ActorResponse(
            reasoning="fake",
            stop=stop,
            message=None if stop else "next question",
            stop_reason="goal_completed" if stop else None,
        )
        return SimpleNamespace(structured_output=structured_output)


def _self_check() -> None:
    calls: list[str] = []

    def fake_agent_turn(message: str) -> str:
        calls.append(message)
        return f"response to {message!r}"

    result = run_simulated_conversation(
        fake_agent_turn, _FakeSimulator(turns=3), "hello"
    )
    assert len(calls) == 3, calls
    assert result == (
        "response to 'hello'\n\n"
        "response to 'next question'\n\n"
        "response to 'next question'"
    ), result

    calls.clear()
    result = run_simulated_conversation(
        fake_agent_turn, _FakeSimulator(turns=1), "hello"
    )
    assert len(calls) == 1, calls

    print("self-check ok (loop logic only -- profile generation, span-to-session")
    print("mapping, and both judges are not covered here and only run live)")


if __name__ == "__main__":
    if "--check" in sys.argv:
        _self_check()
    else:
        print(__doc__)
