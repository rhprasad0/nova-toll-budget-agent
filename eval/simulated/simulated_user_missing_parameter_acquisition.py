"""Two-turn simulated-user evaluation for missing trip parameters."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from strands_evals import Case, Experiment  # noqa: E402
from strands_evals.evaluators import Evaluator  # noqa: E402
from strands_evals.types.evaluation import (  # noqa: E402
    EvaluationData,
    EvaluationOutput,
)
from strands_evals.types.simulation import ActorResponse  # noqa: E402
from strands_evals.types.trace import (  # noqa: E402
    AgentInvocationSpan,
    Session,
    SpanInfo,
    ToolCall,
    ToolExecutionSpan,
    ToolResult,
    Trace,
)

from agent.dev_chat import configure_local_pricing_env  # noqa: E402
from agent.toll_agent import build_agent  # noqa: E402
from eval.simulation_support import (  # noqa: E402
    build_telemetry,
    raise_for_evaluation_errors,
    run_case_with_simulator,
    run_simulated_conversation,
)

_CASES_PATH = (
    Path(__file__).resolve().parent
    / "missing_parameter_acquisition"
    / "test-cases.jsonl"
)
_RESULTS_DIR = _REPO_ROOT / "eval" / "results"


def load_rows() -> list[dict[str, Any]]:
    return [json.loads(line) for line in _CASES_PATH.read_text().splitlines() if line]


def load_cases() -> list[Case[str, str]]:
    cases: list[Case[str, str]] = []
    for row in load_rows():
        missing = ", ".join(row["missing_parameters"])
        cases.append(
            Case[str, str](
                name=f"{row['id']}-simulated",
                input=row["initial_message"],
                metadata={
                    **row,
                    "task_description": (
                        "Get a toll quote for the fixed trip after supplying only "
                        f"the genuinely missing required parameters: {missing}."
                    ),
                },
                expected_assertion=(
                    "The first agent response asks exactly one clarification "
                    f"question for all and only these missing parameters: {missing}. "
                    "It does not call a tool, re-request a supplied endpoint, or ask "
                    "for optional at_time. After the user supplies the missing "
                    "information, it prices the fixed trip without guessing or "
                    "changing either endpoint."
                ),
            )
        )
    return cases


class ScriptedUserSimulator:
    """Supply one fixed clarification reply, then stop after the second turn."""

    def __init__(self, reply: str) -> None:
        self._reply = reply
        self._remaining = 2

    def has_next(self) -> bool:
        return self._remaining > 0

    def act(self, agent_message: str) -> object:
        self._remaining -= 1
        stop = self._remaining == 0
        return SimpleNamespace(
            structured_output=ActorResponse(
                reasoning="scripted fixture",
                stop=stop,
                message=None if stop else self._reply,
                stop_reason="goal_completed" if stop else None,
            )
        )


def _output(passed: bool, reason: str, label: str) -> EvaluationOutput:
    return EvaluationOutput(
        score=float(passed), test_pass=passed, reason=reason, label=label
    )


def _tool_result(value: object) -> dict[str, Any] | None:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return None
    return cast(dict[str, Any], value) if isinstance(value, dict) else None


def _ordered_turns(session: Session) -> list[dict[str, Any]]:
    turns: list[dict[str, Any]] = []
    pending_calls: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for trace_index, trace in enumerate(session.traces):
        for span_index, span in enumerate(trace.spans):
            span_id = span.span_info.span_id or f"{trace_index}:{span_index}"
            key = (trace.trace_id, span_id)
            if key in seen:
                continue
            seen.add(key)
            if isinstance(span, ToolExecutionSpan):
                pending_calls.append(
                    {
                        "name": span.tool_call.name,
                        "input": cast(
                            dict[str, Any],
                            span.tool_call.arguments,  # pyright: ignore[reportUnknownMemberType]
                        ),
                        "tool_result": span.tool_result.content,
                    }
                )
            elif isinstance(span, AgentInvocationSpan):
                turns.append(
                    {
                        "response": span.agent_response,
                        "calls": pending_calls,
                    }
                )
                pending_calls = []
    return turns


def evaluate_turns(
    turns: list[dict[str, Any]], metadata: dict[str, Any]
) -> list[EvaluationOutput]:
    if not turns:
        return [_output(False, "no agent turns were captured", "missing_turns")]

    first = turns[0]
    response = str(first["response"])
    expected_questions: dict[tuple[str, ...], str] = {
        ("origin",): "What is the origin?",
        ("destination",): "What is the destination?",
        ("origin", "destination"): "What are the origin and destination?",
    }
    missing = tuple(cast(list[str], metadata["missing_parameters"]))
    expected_question = expected_questions.get(missing)
    request_passed = response.strip() == expected_question and not first["calls"]
    outputs = [
        _output(
            request_passed,
            "first turn asks the exact question for only the missing parameters"
            if request_passed
            else (
                f"expected {expected_question!r}; got response={response!r}, "
                f"calls={first['calls']!r}"
            ),
            "parameter_request",
        )
    ]

    second_calls = (
        cast(list[dict[str, Any]], turns[1]["calls"]) if len(turns) == 2 else []
    )
    completed: bool = len(second_calls) == 1 and second_calls[0]["name"] == "i495_route"
    if completed:
        call = second_calls[0]
        tool_input = cast(dict[str, Any], call["input"])
        result = _tool_result(call["tool_result"])
        completed = (
            tool_input.get("origin") == metadata["origin"]
            and tool_input.get("destination") == metadata["destination"]
            and tool_input.get("at_time") in (None, "")
            and result is not None
            and result.get("origin") == metadata["origin"]
            and result.get("destination") == metadata["destination"]
            and "error" not in result
        )
    outputs.append(
        _output(
            completed,
            "second turn priced the fixed route exactly once"
            if completed
            else f"unexpected second-turn calls: {second_calls!r}",
            "completed_route",
        )
    )
    return outputs


class MissingParameterTraceEvaluator(Evaluator[str, str]):
    """Code-grade clarification shape and the completed pricing call."""

    def evaluate(
        self, evaluation_case: EvaluationData[str, str]
    ) -> list[EvaluationOutput]:
        session = evaluation_case.actual_trajectory
        if not isinstance(session, Session):
            return [_output(False, "trajectory was not a Session", "bad_trajectory")]
        return evaluate_turns(_ordered_turns(session), evaluation_case.metadata or {})


def _raise_for_failed_verdicts(test_passes: list[bool]) -> None:
    failed = test_passes.count(False)
    if failed:
        suffix = "" if failed == 1 else "s"
        raise RuntimeError(f"{failed} deterministic evaluation verdict{suffix} failed")


def main() -> None:
    configure_local_pricing_env()
    telemetry, mapper = build_telemetry()

    def task_function(case: Case[str, str]) -> dict[str, object]:
        simulator = ScriptedUserSimulator(
            cast(str, (case.metadata or {})["actor_reply"])
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
        evaluators=[MissingParameterTraceEvaluator()],
    ).run_evaluations(task_function)
    _RESULTS_DIR.mkdir(exist_ok=True)
    report.to_file(str(_RESULTS_DIR / f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"))
    print(f"Overall score: {report.overall_score:.2f}")
    report.display(include_input=False)
    raise_for_evaluation_errors(report)
    _raise_for_failed_verdicts(report.test_passes)


def _self_check() -> None:
    _raise_for_failed_verdicts([True, True])
    try:
        _raise_for_failed_verdicts([True, False])
    except RuntimeError as error:
        assert str(error) == "1 deterministic evaluation verdict failed"
    else:
        raise AssertionError("failed verdict did not raise")

    cases = load_cases()
    assert len(cases) == 3
    assert len({case.name for case in cases}) == 3
    assert all(case.expected_assertion for case in cases)
    calls: list[str] = []
    scripted_output = run_simulated_conversation(
        lambda message: calls.append(message) or "agent response",
        ScriptedUserSimulator("fixed reply"),
        "initial request",
    )
    assert calls == ["initial request", "fixed reply"]
    assert scripted_output == "agent response\n\nagent response"

    row = load_rows()[0]
    now = datetime.now(UTC)

    def span_info(span_id: str) -> SpanInfo:
        return SpanInfo(
            trace_id="trace",
            span_id=span_id,
            session_id="session",
            start_time=now,
            end_time=now,
        )

    session = Session(
        session_id="session",
        traces=[
            Trace(
                trace_id="trace",
                session_id="session",
                spans=[
                    AgentInvocationSpan(
                        span_info=span_info("first"),
                        user_prompt=row["initial_message"],
                        agent_response="What are the origin and destination?",
                        available_tools=[],
                    ),
                    ToolExecutionSpan(
                        span_info=span_info("tool"),
                        tool_call=ToolCall(
                            name="i495_route",
                            arguments={
                                "origin": row["origin"],
                                "destination": row["destination"],
                                "at_time": "",
                            },
                        ),
                        tool_result=ToolResult(
                            content=json.dumps(
                                {
                                    "origin": row["origin"],
                                    "destination": row["destination"],
                                    "total_usd": "1.00",
                                }
                            )
                        ),
                    ),
                    AgentInvocationSpan(
                        span_info=span_info("second"),
                        user_prompt=row["actor_reply"],
                        agent_response="The trip is priced.",
                        available_tools=[],
                    ),
                ],
            )
        ],
    )
    good = MissingParameterTraceEvaluator().evaluate(
        EvaluationData[str, str](
            input=row["initial_message"],
            actual_output="The trip is priced.",
            actual_trajectory=session,
            metadata=row,
        )
    )
    assert [result.label for result in good] == [
        "parameter_request",
        "completed_route",
    ]
    assert all(result.test_pass for result in good)

    bad_request = evaluate_turns(
        [
            {
                "response": (
                    "What are your origin and destination? You may add at_time."
                ),
                "calls": [],
            }
        ],
        row,
    )
    assert not bad_request[0].test_pass
    supplied_parameter_request = evaluate_turns(
        [
            {
                "response": "What are the origin and destination?",
                "calls": [],
            }
        ],
        load_rows()[1],
    )
    assert not supplied_parameter_request[0].test_pass
    bad_trajectory = MissingParameterTraceEvaluator().evaluate(
        EvaluationData[str, str](input="x", actual_output="", actual_trajectory=[])
    )
    assert bad_trajectory[0].label == "bad_trajectory"
    print("self-check ok (3 fixtures and evaluator branches; live systems excluded)")


if __name__ == "__main__":
    if "--check" in sys.argv:
        _self_check()
    else:
        main()
