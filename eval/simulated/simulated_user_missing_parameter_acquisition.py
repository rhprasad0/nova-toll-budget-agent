"""Two-turn simulated-user evaluation for missing trip parameters."""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from strands_evals import ActorSimulator, Case, Experiment  # noqa: E402
from strands_evals.evaluators import Evaluator, GoalSuccessRateEvaluator  # noqa: E402
from strands_evals.types.evaluation import (  # noqa: E402
    EvaluationData,
    EvaluationOutput,
)
from strands_evals.types.simulation import ActorProfile  # noqa: E402
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
)

_CASES_PATH = (
    Path(__file__).resolve().parent
    / "missing_parameter_acquisition"
    / "test-cases.jsonl"
)
_RESULTS_DIR = _REPO_ROOT / "eval" / "results"
_MODEL_ID_ENV = "NOVA_TOLL_EVAL_MODEL_ID"
_DEFAULT_MODEL_ID = "us.anthropic.claude-haiku-4-5-20251001-v1:0"


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


def build_actor_profile(case: Case[str, str]) -> ActorProfile:
    metadata = case.metadata or {}
    missing = ", ".join(cast(list[str], metadata["missing_parameters"]))
    reply = cast(str, metadata["actor_reply"])
    return ActorProfile(
        traits={
            "communication_style": "concise and direct",
            "domain_knowledge": "ordinary driver unfamiliar with tool parameter rules",
        },
        context=(
            f"The immutable trip origin is {metadata['origin']} and destination is "
            f"{metadata['destination']}. The initial request intentionally omits "
            f"only {missing}. Do not change either endpoint or add a travel time."
        ),
        actor_goal=(
            "Use exactly two turns and never stop after the first response. Always "
            f"reply exactly {reply!r} after the agent's first response, even if its "
            "request was wrong. Stop after the agent's second response."
        ),
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
    missing = cast(list[str], metadata["missing_parameters"])
    request_passed = (
        response.count("?") == 1
        and response.strip().endswith("?")
        and all(parameter.casefold() in response.casefold() for parameter in missing)
        and "at_time" not in response.casefold()
        and not first["calls"]
    )
    outputs = [
        _output(
            request_passed,
            "first turn asks one question for every missing parameter without tools"
            if request_passed
            else f"unexpected first turn: response={response!r}, calls={first['calls']!r}",
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

    report = Experiment[str, str](
        cases=load_cases(),
        evaluators=[
            MissingParameterTraceEvaluator(),
            GoalSuccessRateEvaluator(model=model_id),
        ],
    ).run_evaluations(task_function)
    _RESULTS_DIR.mkdir(exist_ok=True)
    report.to_file(str(_RESULTS_DIR / f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"))
    print(f"Overall score: {report.overall_score:.2f}")
    report.display(include_input=False)
    raise_for_evaluation_errors(report)


def _self_check() -> None:
    cases = load_cases()
    assert len(cases) == 3
    assert len({case.name for case in cases}) == 3
    assert all(case.expected_assertion for case in cases)
    assert all(
        "exactly two turns" in build_actor_profile(case).actor_goal for case in cases
    )

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
                        agent_response="What are your origin and destination?",
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
