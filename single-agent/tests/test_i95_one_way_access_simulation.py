from datetime import UTC, datetime

from strands_evals.types.evaluation import EvaluationData
from strands_evals.types.trace import (
    Session,
    SpanInfo,
    ToolCall,
    ToolExecutionSpan,
    ToolResult,
    Trace,
)

from agent.toll_agent import _DUPLICATE_TOOL_MESSAGE
from eval.simulated.simulated_user_i95_one_way_access import (
    OneWaySimulationTraceEvaluator,
    load_cases,
)


def _span(
    span_id: str,
    name: str,
    arguments: dict[str, object],
    content: str,
    *,
    trace_id: str = "turn-2",
    error: str | None = None,
) -> ToolExecutionSpan:
    now = datetime.now(UTC)
    return ToolExecutionSpan(
        span_info=SpanInfo(
            trace_id=trace_id,
            span_id=span_id,
            session_id="session-1",
            start_time=now,
            end_time=now,
        ),
        tool_call=ToolCall(
            name=name,
            arguments=arguments,
            tool_call_id=f"call-{span_id}",
        ),
        tool_result=ToolResult(
            content=content,
            error=error,
            tool_call_id=f"call-{span_id}",
        ),
        agent_span_id=trace_id,
    )


def _evaluate(spans: list[ToolExecutionSpan]):
    case = load_cases()[2]
    session = Session(
        session_id="session-1",
        traces=[Trace(trace_id="session", session_id="session-1", spans=spans)],
    )
    return OneWaySimulationTraceEvaluator().evaluate(
        EvaluationData(
            input=case.input,
            actual_output="priced",
            actual_trajectory=session,
            metadata=case.metadata,
        )
    )[0]


def _planner_spans() -> list[ToolExecutionSpan]:
    original = {
        "origin_corridor": "i95",
        "origin": "I-95 Near Joplin Road/Quantico",
        "destination_corridor": "i495",
        "destination": "Westpark Drive",
    }
    selected = {**original, "origin": "I-95 Near Dumfries Road/Route 234"}
    return [
        _span(
            "mismatch",
            "plan_toll_route",
            original,
            '{"status":"one_way_mismatch"}',
            trace_id="turn-1",
        ),
        _span(
            "plan",
            "plan_toll_route",
            selected,
            '{"at_time":"","steps":['
            '{"kind":"junction","tool":"i95_junction_leg",'
            '"location":"I-95 Near Dumfries Road/Route 234",'
            '"movement":"i95_to_i495"},'
            '{"kind":"priced","tool":"i495_route",'
            '"origin":"191NO","destination":"Westpark Drive"}]}',
        ),
        _span(
            "junction",
            "i95_junction_leg",
            {
                "location": "I-95 Near Dumfries Road/Route 234",
                "movement": "i95_to_i495",
                "at_time": "",
            },
            '{"pricing_status":"priced"}',
        ),
        _span(
            "i495",
            "i495_route",
            {"origin": "191NO", "destination": "Westpark Drive", "at_time": ""},
            '{"total_usd":"5.00"}',
        ),
    ]


def test_cross_corridor_recovery_allows_guard_suppression_and_requires_completion():
    spans = _planner_spans()
    cancellation = _span(
        "duplicate",
        "plan_toll_route",
        spans[1].tool_call.arguments,
        _DUPLICATE_TOOL_MESSAGE,
        error=_DUPLICATE_TOOL_MESSAGE,
    )

    assert _evaluate([*spans[:2], cancellation, *spans[2:]]).label == "recovered"
    wrong_turn_cancellation = cancellation.model_copy(
        update={"agent_span_id": "turn-3"}
    )
    assert (
        _evaluate([*spans[:2], wrong_turn_cancellation, *spans[2:]]).label
        == "orphan_suppression"
    )
    duplicate_success = spans[1].model_copy(
        update={
            "span_info": spans[1].span_info.model_copy(update={"span_id": "plan-2"})
        }
    )
    assert _evaluate([*spans, duplicate_success]).label == "duplicate_success"
    assert _evaluate(spans[:-1]).label == "tool_order"
