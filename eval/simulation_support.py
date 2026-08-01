"""Reusable scaffolding for driving a strands_evals.ActorSimulator-based
conversation against an agent under test, for future evals that need an
LLM-simulated user instead of a scripted conversation turn (see eval-plan.md
Track 2). Not used by eval/run_evaluation.py, which stays fully
deterministic on purpose -- this module is inherently non-deterministic
(both the simulated user and, downstream, any session-level judge are LLMs)
and is not a regression gate.

Two things a real ActorSimulator run gets wrong if you don't do them this
specific way:

1. StrandsEvalsTelemetry() sets the *global* OpenTelemetry tracer provider,
   so every strands.Agent in the process emits spans -- including
   ActorSimulator's own internal actor agent and its profile-generation
   agent, not just the agent under test. Baggage (session.id,
   gen_ai.conversation.id) is stamped onto whatever span starts while that
   baggage is the active context, so attaching it once for the whole
   conversation would fold the simulated user's own turns into the judged
   trajectory. run_case_with_simulator attaches baggage around each
   agent(...) call only, never around simulator.act() or simulator
   construction.
2. build_telemetry() must be called once from a script's main(), never at
   import time: StrandsEvalsTelemetry() mutates process-global OTel state
   (set_tracer_provider, which OpenTelemetry only honors on the first call
   in a process), so doing it at module import would be a surprising side
   effect of merely importing this file (e.g. under --check) and could race
   any other code in the same process that sets up its own telemetry.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, cast

from opentelemetry import baggage, context
from strands import Agent
from strands_evals import StrandsEvalsTelemetry
from strands_evals.mappers.strands_in_memory_session_mapper import (
    StrandsInMemorySessionMapper,
)
from strands_evals.types.simulation import ActorResponse
from strands_evals.types.trace import AgentInvocationSpan, Session


class Case(Protocol):
    """Structural subset of strands_evals.Case this module needs."""

    session_id: str


class _ActResult(Protocol):
    """Structural subset of AgentResult: the loop only ever reads
    .structured_output off whatever act() returns. Declared as a read-only
    property (not a plain attribute) so implementers can narrow the type --
    a plain Protocol attribute is invariant under strict pyright and would
    reject any _structured_output type narrower than `object`."""

    @property
    def structured_output(self) -> object: ...


class Simulator(Protocol):
    """Structural subset of ActorSimulator this module needs. A real
    ActorSimulator's __init__ always makes a Bedrock call (profile
    generation) with no way to override that -- --check substitutes a fake
    satisfying this Protocol instead, so the loop logic is exercised with
    zero network calls."""

    def has_next(self) -> bool: ...
    def act(self, agent_message: str) -> _ActResult: ...


def run_simulated_conversation(
    agent_turn: Callable[[str], str],
    simulator: Simulator,
    first_message: str,
) -> str:
    """Drive agent_turn/simulator.act back and forth until the simulator
    stops (goal completed or max_turns exhausted). Mirrors ActorSimulator's
    own documented loop shape exactly. Returns the final agent response
    text. Pure control flow, no telemetry -- this is what --check exercises."""
    user_message = first_message
    response = ""
    while simulator.has_next():
        response = agent_turn(user_message)
        result = simulator.act(response)
        actor_response = cast(ActorResponse, result.structured_output)
        message = actor_response.message
        # v1 of ActorResponse.message only supports the str | None variants
        # -- list[ContentBlock] raises until multimodal simulator output is
        # supported (see ActorSimulator.__init__ docstring).
        user_message = message if isinstance(message, str) else ""
    return response


def build_telemetry() -> tuple[StrandsEvalsTelemetry, StrandsInMemorySessionMapper]:
    """Call exactly once per process, from main() -- never at import time
    (see module docstring, point 2)."""
    telemetry = StrandsEvalsTelemetry().setup_in_memory_exporter()
    return telemetry, StrandsInMemorySessionMapper()


def run_case_with_simulator(
    case: Case,
    agent: Agent,
    simulator: Simulator,
    first_message: str,
    telemetry: StrandsEvalsTelemetry,
    mapper: StrandsInMemorySessionMapper,
) -> dict[str, object]:
    """task_function-shaped: {"output": str, "trajectory": Session}. Baggage
    is attached/detached around each agent(...) call only, never around
    simulator.act() or construction (see module docstring, point 1) -- that
    is what keeps the simulated user's own spans out of the judged Session."""

    def traced_turn(message: str) -> str:
        ctx = baggage.set_baggage("session.id", case.session_id)
        ctx = baggage.set_baggage("gen_ai.conversation.id", case.session_id, ctx)
        token = context.attach(ctx)
        try:
            return str(agent(message))
        finally:
            context.detach(token)

    output = run_simulated_conversation(traced_turn, simulator, first_message)

    exporter = telemetry.in_memory_exporter
    assert exporter is not None, "telemetry.setup_in_memory_exporter() was never called"
    spans = list(exporter.get_finished_spans())
    session: Session = mapper.map_to_session(spans, case.session_id)
    turn_spans = [
        s for t in session.traces for s in t.spans if isinstance(s, AgentInvocationSpan)
    ]
    if not turn_spans:
        raise RuntimeError(
            f"no agent-invocation spans captured for session {case.session_id!r} -- "
            "telemetry wasn't installed before the first agent call, or every span "
            "leaked into a different session"
        )
    return {"output": output, "trajectory": session}


@dataclass
class _FakeAgentResult:
    """Minimal double for AgentResult -- the loop only reads
    .structured_output, so that's all this needs."""

    structured_output: ActorResponse


class _FakeSimulator:
    """--check double for Simulator: has_next() true for `turns` calls, then
    false; act() always signals stop on the last turn."""

    def __init__(self, turns: int) -> None:
        self._remaining = turns

    def has_next(self) -> bool:
        return self._remaining > 0

    def act(self, agent_message: str) -> _FakeAgentResult:
        self._remaining -= 1
        stop = self._remaining <= 0
        structured_output = ActorResponse(
            reasoning="fake",
            stop=stop,
            message=None if stop else "next question",
            stop_reason="goal_completed" if stop else None,
        )
        return _FakeAgentResult(structured_output=structured_output)


def _self_check() -> None:
    """No Bedrock/OpenAI/RDS calls -- just run_simulated_conversation's pure
    turn-loop logic against a fake Simulator, covering both the
    goal-completed and max-turns-exhausted stop conditions."""
    calls: list[str] = []

    def fake_agent_turn(message: str) -> str:
        calls.append(message)
        return f"response to {message!r}"

    # Goal-completed path: simulator reports stop after 2 turns.
    result = run_simulated_conversation(
        fake_agent_turn, _FakeSimulator(turns=2), "hello"
    )
    assert len(calls) == 2, calls
    assert result == "response to 'next question'", result

    # Max-turns-exhausted path: same shape, just a different turn count --
    # run_simulated_conversation itself doesn't distinguish why has_next()
    # went false, only that it did.
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
