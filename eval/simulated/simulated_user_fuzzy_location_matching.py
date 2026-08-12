"""Observational ActorSimulator evaluation for fuzzy location matching."""

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
from strands_evals.evaluators import Evaluator  # noqa: E402
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

_RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"
_MODEL_ID_ENV = "NOVA_TOLL_EVAL_MODEL_ID"
_DEFAULT_MODEL_ID = "us.anthropic.claude-haiku-4-5-20251001-v1:0"

_MCLEAN_CASE = Case[str, str](
    name="ambiguous-alias-mclean-simulated",
    input=("Price a trip from McLean to Westpark Drive at 7/15/2026 3:30 PM ET."),
    metadata={
        "batch_judge_suite": "fuzzy_location_matching",
        "task_description": (
            "Wants a toll price quote from McLean to Westpark Drive at "
            "7/15/2026 3:30 PM ET. McLean is ambiguous between two "
            "interchanges; the user means the I-495 one (Jones Branch Drive) "
            "and should say so plainly if asked which McLean they mean, "
            "without volunteering it unprompted."
        ),
        "expected_first_response_any": [
            "Route 123 - Dolley Madison Blvd",
            "Jones Branch Drive/Route 123",
        ],
        "expected_calls": [
            {
                "name": "i495_route",
                "input": {
                    "origin": "Jones Branch Drive/Route 123",
                    "destination": "Westpark Drive",
                    "at_time": "2026-07-15T15:30:00-04:00",
                },
            }
        ],
    },
    expected_assertion=(
        "The agent does not price any trip on its first response; it asks "
        "which McLean interchange is meant. After the user identifies the "
        "I-495 one, it prices Jones Branch Drive/Route 123 to Westpark Drive. "
        "It retains the destination and requested time and never quotes a "
        "price for the I-66 ITB interchange."
    ),
)

_MCLEAN_PROFILE = ActorProfile(
    traits={
        "communication_style": "concise and direct",
        "domain_knowledge": "ordinary driver unfamiliar with toll-system labels",
        "disclosure": "identifies the intended McLean interchange only when asked",
    },
    context=(
        "The driver is traveling from the I-495 McLean interchange at Jones Branch "
        "Drive/Route 123 to Westpark Drive at 7/15/2026 3:30 PM ET, not from "
        "I-66 Inside the Beltway. These route and time facts never change."
    ),
    actor_goal=(
        "Get an accurate toll quote from Jones Branch Drive/Route 123 to "
        "Westpark Drive at 7/15/2026 3:30 PM ET after clarifying which McLean "
        "interchange is intended."
    ),
)

_WASHINGTON_CASES = [
    Case[str, str](
        name="ambiguous-washington-origin-i66-simulated",
        input="Price a trip from Washington to Westpark Drive.",
        metadata={
            "batch_judge_suite": "fuzzy_location_matching",
            "task_description": (
                "The driver means the I-66 Washington endpoint and wants a toll "
                "quote to Westpark Drive, but reveals I-66 only after the agent "
                "asks which Washington corridor is intended."
            ),
            "expected_first_response_exact": "Do you mean I-66 or I-395?",
            "expected_calls": [
                {
                    "name": "plan_toll_route",
                    "input": {
                        "origin_corridor": "i66_itb",
                        "origin": "Washington",
                        "destination_corridor": "i495",
                        "destination": "Westpark Drive",
                    },
                },
                {
                    "name": "i66_route",
                    "input": {"origin": "Washington", "destination": "5"},
                },
                {
                    "name": "i495_route",
                    "input": {"origin": "187NO", "destination": "Westpark Drive"},
                },
            ],
        },
        expected_assertion=(
            "The agent asks whether Washington means I-66 or I-395 before pricing. "
            "After the user selects I-66, it retains Westpark Drive and prices a "
            "route beginning at the I-66 endpoint named Washington, without using "
            "the I-395 endpoint named Washington D.C."
        ),
    ),
    Case[str, str](
        name="ambiguous-washington-destination-i395-simulated",
        input="Price a trip from Westpark Drive to Washington.",
        metadata={
            "batch_judge_suite": "fuzzy_location_matching",
            "task_description": (
                "The driver means the I-395 Washington D.C. endpoint and wants a "
                "toll quote from Westpark Drive, but reveals I-395 only after the "
                "agent asks which Washington corridor is intended."
            ),
            "expected_first_response_exact": "Do you mean I-66 or I-395?",
            "expected_calls": [
                {
                    "name": "plan_toll_route",
                    "input": {
                        "origin_corridor": "i495",
                        "origin": "Westpark Drive",
                        "destination_corridor": "i95",
                        "destination": "Washington D.C.",
                    },
                },
                {
                    "name": "i495_route",
                    "input": {"origin": "Westpark Drive", "destination": "191SD"},
                },
                {
                    "name": "i95_junction_leg",
                    "input": {
                        "movement": "i495_to_i95",
                        "location": "Washington D.C.",
                    },
                },
            ],
        },
        expected_assertion=(
            "The agent asks whether Washington means I-66 or I-395 before pricing. "
            "After the user selects I-395, it retains Westpark Drive and plans to "
            "the I-395 endpoint named Washington D.C., without substituting the "
            "I-66 endpoint named Washington."
        ),
    ),
]
_CASES = [_MCLEAN_CASE, *_WASHINGTON_CASES]


def _result(passed: bool, reason: str, label: str) -> list[EvaluationOutput]:
    return [
        EvaluationOutput(
            score=float(passed), test_pass=passed, reason=reason, label=label
        )
    ]


def _matches_input(span: ToolExecutionSpan, expected: dict[str, Any]) -> bool:
    actual = cast(
        dict[str, Any],
        span.tool_call.arguments,  # pyright: ignore[reportUnknownMemberType]
    )
    return all(actual.get(key) == value for key, value in expected.items())


class FuzzyLocationSimulationTraceEvaluator(Evaluator[str, str]):
    """Code-grade clarification and selected canonical route across actor turns."""

    def evaluate(
        self, evaluation_case: EvaluationData[str, str]
    ) -> list[EvaluationOutput]:
        session = evaluation_case.actual_trajectory
        if not isinstance(session, Session):
            return _result(False, "missing telemetry session", "bad_trajectory")

        spans = [span for trace in session.traces for span in trace.spans]
        invocations = sorted(
            (span for span in spans if isinstance(span, AgentInvocationSpan)),
            key=lambda span: span.span_info.start_time,
        )
        if not invocations:
            return _result(False, "missing agent invocation", "bad_trajectory")

        metadata = evaluation_case.metadata or {}
        first = invocations[0]
        response = first.agent_response
        required_exact = metadata.get("expected_first_response_exact")
        required_any = metadata.get("expected_first_response_any", [])
        required_all = metadata.get("expected_first_response_all", [])
        if (
            "?" not in response
            or (required_exact and response.strip() != required_exact)
            or (required_any and not any(term in response for term in required_any))
            or (required_all and not all(term in response for term in required_all))
        ):
            return _result(
                False,
                "first response did not ask the expected location clarification",
                "clarification_mismatch",
            )

        tool_spans: list[ToolExecutionSpan] = []
        seen: set[tuple[str | None, str | None]] = set()
        for span in sorted(
            (span for span in spans if isinstance(span, ToolExecutionSpan)),
            key=lambda span: span.span_info.start_time,
        ):
            key = (span.span_info.trace_id, span.span_info.span_id)
            if key in seen:
                continue
            seen.add(key)
            tool_spans.append(span)

        first_span_id = first.span_info.span_id
        if any(span.agent_span_id == first_span_id for span in tool_spans):
            return _result(
                False,
                "a tool executed during the first clarification turn",
                "premature_tool_call",
            )

        expected_calls = metadata.get("expected_calls", [])
        if [span.tool_call.name for span in tool_spans] != [
            call["name"] for call in expected_calls
        ]:
            return _result(
                False,
                f"unexpected calls: {[span.tool_call.name for span in tool_spans]}",
                "tool_mismatch",
            )
        if any(
            not _matches_input(span, expected["input"])
            for span, expected in zip(tool_spans, expected_calls, strict=True)
        ):
            return _result(
                False,
                "tool inputs changed the selected location, endpoint, or time",
                "input_mismatch",
            )
        for span in tool_spans:
            if span.tool_result.error or not span.tool_result.content:
                return _result(False, "a required tool did not succeed", "tool_error")
            try:
                decoded: object = json.loads(span.tool_result.content)
            except json.JSONDecodeError:
                return _result(False, "a tool returned invalid JSON", "tool_error")
            if not isinstance(decoded, dict) or cast(dict[str, Any], decoded).get(
                "error"
            ):
                return _result(
                    False, "a tool returned an application error", "tool_error"
                )
        return _result(
            True,
            "clarification preceded the exact non-error canonical route calls",
            "clarified_route",
        )


def build_actor_profile(case: Case[str, str]) -> ActorProfile:
    if case.name == _MCLEAN_CASE.name:
        return _MCLEAN_PROFILE
    name = case.name or ""
    corridor = "I-66" if "origin-i66" in name else "I-395"
    role = "origin" if "origin-i66" in name else "destination"
    return ActorProfile(
        traits={
            "communication_style": "concise and direct",
            "domain_knowledge": "ordinary driver unfamiliar with toll-system labels",
            "disclosure": "states the intended corridor only after being asked",
        },
        context=(
            f"The driver's Washington {role} is on {corridor}; the other endpoint "
            "is Westpark Drive. These facts never change."
        ),
        actor_goal=(
            "Get the requested toll quote. Do not volunteer the Washington corridor "
            f"before the agent asks. When asked, reply exactly '{corridor}.' and "
            "continue until the agent completes or explains the route."
        ),
    )


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
        cases=_CASES,
        evaluators=[FuzzyLocationSimulationTraceEvaluator()],
    ).run_evaluations(task_function)
    _RESULTS_DIR.mkdir(exist_ok=True)
    report.to_file(str(_RESULTS_DIR / f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"))
    print(f"Overall score: {report.overall_score:.2f}")
    report.display(include_input=False)
    raise_for_evaluation_errors(report)
    if not all(report.test_passes):
        raise SystemExit("simulated fuzzy-location evaluation failed")


def _self_check() -> None:
    """Assert static Case and actor-profile shapes without network calls."""
    assert [case.name for case in _CASES] == [
        "ambiguous-alias-mclean-simulated",
        "ambiguous-washington-origin-i66-simulated",
        "ambiguous-washington-destination-i395-simulated",
    ]
    assert all(case.input and case.expected_assertion for case in _CASES)
    assert (
        "Jones Branch Drive/Route 123" in build_actor_profile(_MCLEAN_CASE).actor_goal
    )
    assert "7/15/2026 3:30 PM ET" in build_actor_profile(_MCLEAN_CASE).actor_goal
    for case in _WASHINGTON_CASES:
        profile = build_actor_profile(case)
        assert "only after being asked" in profile.traits["disclosure"]
        assert "reply exactly" in profile.actor_goal

    now = datetime.now(UTC)

    def span_info(span_id: str) -> SpanInfo:
        return SpanInfo(
            trace_id="trace",
            span_id=span_id,
            session_id="session",
            start_time=now,
            end_time=now,
        )

    expected_call = (_MCLEAN_CASE.metadata or {})["expected_calls"][0]

    def session(
        *,
        agent_span_id: str = "second",
        origin: str = "Jones Branch Drive/Route 123",
        tool_content: str = '{"total_usd":"1.10"}',
        first_response: str = (
            "Which McLean location: Route 123 - Dolley Madison Blvd or "
            "Jones Branch Drive/Route 123?"
        ),
    ) -> Session:
        return Session(
            session_id="session",
            traces=[
                Trace(
                    trace_id="trace",
                    session_id="session",
                    spans=[
                        AgentInvocationSpan(
                            span_info=span_info("first"),
                            user_prompt=str(_MCLEAN_CASE.input),
                            agent_response=first_response,
                            available_tools=[],
                        ),
                        AgentInvocationSpan(
                            span_info=span_info("second"),
                            user_prompt="Jones Branch Drive/Route 123.",
                            agent_response="The route is priced.",
                            available_tools=[],
                        ),
                        ToolExecutionSpan(
                            span_info=span_info("tool"),
                            agent_span_id=agent_span_id,
                            tool_call=ToolCall(
                                name=expected_call["name"],
                                arguments={**expected_call["input"], "origin": origin},
                            ),
                            tool_result=ToolResult(content=tool_content),
                        ),
                    ],
                )
            ],
        )

    def evaluate(
        trajectory: list[Any] | Session | None,
        metadata: dict[str, Any] | None = _MCLEAN_CASE.metadata,
    ) -> EvaluationOutput:
        return FuzzyLocationSimulationTraceEvaluator().evaluate(
            EvaluationData[str, str](
                input=str(_MCLEAN_CASE.input),
                actual_output="The route is priced.",
                actual_trajectory=trajectory,
                metadata=metadata,
            )
        )[0]

    assert evaluate(session()).label == "clarified_route"
    assert (
        evaluate(session(tool_content='{"error":"database unavailable"}')).label
        == "tool_error"
    )
    assert evaluate(session(tool_content="not JSON")).label == "tool_error"
    assert evaluate(session(agent_span_id="first")).label == "premature_tool_call"
    assert (
        evaluate(session(origin="Route 123 - Dolley Madison Blvd")).label
        == "input_mismatch"
    )
    assert evaluate([]).label == "bad_trajectory"
    misleading = session(first_response="I chose I-66. Want to compare I-395?")
    exact_metadata = {
        "expected_first_response_exact": "Do you mean I-66 or I-395?",
        "expected_calls": [expected_call],
    }
    assert evaluate(misleading, exact_metadata).label == "clarification_mismatch"
    print(
        "self-check ok (three profiles and trace-grader branches; live systems excluded)"
    )


if __name__ == "__main__":
    _self_check() if "--check" in sys.argv else main()
