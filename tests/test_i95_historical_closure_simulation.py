from datetime import UTC, date, datetime

from strands_evals.types.evaluation import EvaluationData
from strands_evals.types.trace import (
    AgentInvocationSpan,
    Session,
    SpanInfo,
    ToolCall,
    ToolExecutionSpan,
    ToolResult,
    Trace,
)

from eval.deterministic.i95_historical_closures.deterministic_i95_historical_closures import (
    ClosureSourceResponseEvaluator,
)
from eval.simulated.simulated_user_i95_historical_closures import (
    ClosureSimulationTraceEvaluator,
    build_actor_profile,
    build_helpfulness_context,
    load_cases,
)


def _tool_span(span_id: str, *, access: bool = False) -> ToolExecutionSpan:
    now = datetime.now(UTC)
    arguments = {
        "origin": "US-1",
        "destination": "I-395 Near Edsall Road",
        **({} if access else {"at_time": "2026-07-29T15:40:00-04:00"}),
    }
    content = (
        '{"status":"supported","direction":"Northbound"}'
        if access
        else (
            '{"error":"od_pair_id 1132 is not currently available: '
            'link_status=\'CLOSED\'","valid_options":[]}'
        )
    )
    return ToolExecutionSpan(
        span_info=SpanInfo(
            trace_id="trace-1",
            span_id=span_id,
            session_id="session-1",
            start_time=now,
            end_time=now,
        ),
        tool_call=ToolCall(
            name="i95_access_options" if access else "i95_route",
            arguments=arguments,
            tool_call_id=f"call-{span_id}",
        ),
        tool_result=ToolResult(
            content=content,
            tool_call_id=f"call-{span_id}",
        ),
    )


def _evaluate(spans: list[ToolExecutionSpan]):
    case = load_cases()[0]
    session = Session(
        session_id="session-1",
        traces=[Trace(trace_id="trace-1", session_id="session-1", spans=spans)],
    )
    return ClosureSimulationTraceEvaluator().evaluate(
        EvaluationData(
            input=case.input,
            actual_output="unavailable",
            actual_trajectory=session,
            metadata=case.metadata,
        )
    )[0]


def test_trace_evaluator_counts_unique_execution_spans():
    access = _tool_span("access", access=True)
    price = _tool_span("price")

    assert _evaluate([access, price, access, price]).label == "closed"
    assert _evaluate([access, price, _tool_span("price-2")]).label == "tool_mismatch"


def test_cases_use_response_only_assertions_and_immutable_actor_profiles():
    for case in load_cases():
        assertion = case.expected_assertion or ""
        assert "exactly once" not in assertion
        assert "calls i95_route" not in assertion

        metadata = case.metadata or {}
        expected_input = next(
            call["input"]
            for call in metadata["expected_trajectory"][0]["calls"]
            if call["tool"] == "i95_route"
        )
        profile = build_actor_profile(case)
        assert all(str(value) in profile.context for value in expected_input.values())
        assert "never change" in profile.context.casefold()
        assert "official proof" in profile.actor_goal.casefold()
        assert "reimbursement documentation" in profile.actor_goal.casefold()


def test_helpfulness_context_has_evaluation_date_and_pricing_scope():
    context = build_helpfulness_context(today=date(2026, 8, 2))

    assert "August 2, 2026" in context
    assert "pricing-only" in context
    assert "live traffic" in context.casefold()


def test_source_followup_evaluator_allows_only_the_approved_referral():
    evaluator = ClosureSourceResponseEvaluator()

    def evaluate(output: str):
        return evaluator.evaluate(
            EvaluationData(
                input="Can you prove that closure?",
                actual_output=output,
                actual_trajectory=[],
                metadata={},
            )
        )[0]

    approved = (
        "The registered pricing tool reported the Express Lanes unavailable for "
        "the requested trip and time, but it did not provide an official closure "
        "notice or source metadata. TollChat is not affiliated with VDOT or Virginia "
        "511. You can verify through official VDOT or Virginia 511 channels."
    )
    assert evaluate(approved).label == "grounded_source_referral"
    assert (
        evaluate(f"{approved} I can price covered Northern Virginia toll trips.").label
        == "source_followup_ungrounded"
    )
    assert evaluate(f"{approved} Visit https://vdot.example.").label == "url_exposed"
    assert evaluate(f"{approved} Call 555-555-5555.").label == "contact_exposed"
    assert evaluate(f"{approved} Request archival records.").label == "records_claimed"
    assert (
        evaluate(f"{approved} File a reimbursement claim.").label
        == "reimbursement_advice"
    )
    assert (
        evaluate("TollChat is an official VDOT service.").label == "affiliation_claimed"
    )


def test_source_followup_evaluator_checks_every_source_turn():
    now = datetime.now(UTC)
    approved = (
        "The registered pricing tool reported the Express Lanes unavailable for "
        "the requested trip and time, but it did not provide an official closure "
        "notice or source metadata. TollChat is not affiliated with VDOT or Virginia "
        "511. You can verify through official VDOT or Virginia 511 channels."
    )

    def evaluate(last_response: str):
        session = Session(
            session_id="session-1",
            traces=[
                Trace(
                    trace_id="trace-1",
                    session_id="session-1",
                    spans=[
                        AgentInvocationSpan(
                            span_info=SpanInfo(
                                trace_id="trace-1",
                                span_id="initial",
                                session_id="session-1",
                                start_time=now,
                                end_time=now,
                            ),
                            user_prompt="Price this trip.",
                            agent_response="The lanes are unavailable.",
                            available_tools=[],
                        ),
                        AgentInvocationSpan(
                            span_info=SpanInfo(
                                trace_id="trace-1",
                                span_id="proof",
                                session_id="session-1",
                                start_time=now,
                                end_time=now,
                            ),
                            user_prompt="Can you provide official proof?",
                            agent_response=approved,
                            available_tools=[],
                        ),
                        AgentInvocationSpan(
                            span_info=SpanInfo(
                                trace_id="trace-1",
                                span_id="reimbursement",
                                session_id="session-1",
                                start_time=now,
                                end_time=now,
                            ),
                            user_prompt="What reimbursement documentation is needed?",
                            agent_response=last_response,
                            available_tools=[],
                        ),
                    ],
                )
            ],
        )
        return ClosureSourceResponseEvaluator().evaluate(
            EvaluationData(
                input="Price this trip.",
                actual_output=f"The lanes are unavailable. {approved} {last_response}",
                actual_trajectory=session,
                metadata={},
            )
        )[0]

    assert evaluate(approved).label == "grounded_source_referral"
    assert (
        evaluate("I can price covered Northern Virginia toll trips.").label
        == "source_followup_ungrounded"
    )
