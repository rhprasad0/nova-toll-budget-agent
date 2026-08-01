"""Demo of the Track 2 (simulated-user) eval pattern from eval-plan.md:
drives TollChat through the McLean ambiguous-alias scenario with an
strands_evals.ActorSimulator-played user instead of a scripted second turn,
then judges the resulting session with HelpfulnessEvaluator (final-answer
quality) and GoalSuccessRateEvaluator in assertion mode (did the whole
trajectory satisfy expected_assertion below).

Unlike eval/run_evaluation.py, this is NOT a regression gate: both the
simulated user and both judges are LLMs, so results are not deterministic
run to run. Its job is to prove eval/simulation_support.py's scaffolding
works end-to-end, once, not to assert pass/fail on every run.

Requires AWS_PROFILE=nova-toll (OpenAI key via SSM, Bedrock for the
simulator + judges) and tailnet RDS access to actually invoke the agent --
run explicitly, same convention as tests/test_toll_agent_live.py. main()
calls agent.dev_chat.configure_local_pricing_env() first, the same
DB_HOST/DB_PORT-via-describe_db_instances + pricing_reader-defaults setup
the local dev console already uses, instead of expecting the caller's shell
to have exported those itself. `--check` only validates the demo Case's
shape, no network calls, and does not call configure_local_pricing_env().
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from strands_evals import (  # noqa: E402
    ActorSimulator,
    Case,
    Experiment,
    StrandsEvalsTelemetry,
)
from strands_evals.evaluators import (  # noqa: E402
    GoalSuccessRateEvaluator,
    HelpfulnessEvaluator,
)
from strands_evals.mappers.strands_in_memory_session_mapper import (  # noqa: E402
    StrandsInMemorySessionMapper,
)

from agent.dev_chat import configure_local_pricing_env  # noqa: E402
from agent.toll_agent import build_agent  # noqa: E402
from eval.simulation_support import (  # noqa: E402
    build_telemetry,
    run_case_with_simulator,
)

_RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"

# Cross-region Bedrock inference profile for Claude Haiku 4.5, same ID this
# repo used for the agent itself before its OpenAI Luna migration (see
# eval/tollchat-i95-single-leg:agent/toll_agent.py) and confirmed still live
# via `aws bedrock list-inference-profiles` under the nova-toll profile.
# Applies to the simulator's ongoing conversational turns and both judges --
# NOT to ActorSimulator's internal profile-generation step, which is always
# a bare `Agent(callback_handler=None)` with no model override available
# (see eval-plan.md's Track 2 section).
_ACTOR_JUDGE_MODEL_ID = "us.anthropic.claude-haiku-4-5-20251001-v1:0"

# Reuses the McLean scenario from test-cases.jsonl's
# ambiguous-alias-mclean-multiturn (same real oracle data: McLean fans out to
# "Route 123 - Dolley Madison Blvd" on I-66 ITB vs "Jones Branch Drive/Route
# 123" on I-495; "Westpark Drive" is a verified direct I-495 pair with the
# latter) but lets a simulated user answer the clarifying question instead
# of a scripted follow-up line.
_CASE = Case[str, str](
    name="ambiguous-alias-mclean-simulated",
    input="Price a trip from McLean to Westpark Drive.",
    metadata={
        "task_description": (
            "Wants a toll price quote from McLean to Westpark Drive. McLean "
            "is ambiguous between two interchanges; the user means the "
            "I-495 one (Jones Branch Drive) and should say so plainly if "
            "asked which McLean they mean, without volunteering it "
            "unprompted."
        )
    },
    expected_assertion=(
        "The agent does not price any trip on its first response; it asks "
        "which McLean interchange is meant. After the user identifies the "
        "I-495 one, it prices Jones Branch Drive/Route 123 to Westpark "
        "Drive. It never quotes a price for the I-66 ITB interchange and "
        "never substitutes a different corridor."
    ),
)


def _make_task_function(
    telemetry: StrandsEvalsTelemetry, mapper: StrandsInMemorySessionMapper
) -> Callable[[Case[str, str]], dict[str, object]]:
    def task_function(case: Case[str, str]) -> dict[str, object]:
        agent = build_agent()
        simulator = ActorSimulator.from_case_for_user_simulator(  # pyright: ignore[reportUnknownMemberType]
            case=case, model=_ACTOR_JUDGE_MODEL_ID, max_turns=2
        )
        return run_case_with_simulator(
            case, agent, simulator, str(case.input), telemetry, mapper
        )

    return task_function


def main() -> None:
    configure_local_pricing_env()
    telemetry, mapper = build_telemetry()
    experiment = Experiment[str, str](
        cases=[_CASE],
        evaluators=[
            HelpfulnessEvaluator(model=_ACTOR_JUDGE_MODEL_ID),
            GoalSuccessRateEvaluator(model=_ACTOR_JUDGE_MODEL_ID),
        ],
    )
    report = experiment.run_evaluations(_make_task_function(telemetry, mapper))

    _RESULTS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    report.to_file(str(_RESULTS_DIR / f"{stamp}.json"))

    print(f"Overall score: {report.overall_score:.2f}")
    report.display(include_input=False)


def _self_check() -> None:
    """No Bedrock/OpenAI/RDS calls -- just asserts the demo Case is
    well-formed, same 'static fixture is well-formed' pattern as
    run_evaluation.py's self-check. Cannot cover profile generation,
    span-to-session mapping, or either judge -- those only run live."""
    assert _CASE.name == "ambiguous-alias-mclean-simulated"
    assert _CASE.input
    assert _CASE.expected_assertion
    assert "McLean" in _CASE.input
    print("self-check ok (Case shape only -- see module docstring for what")
    print("is not covered without a live run)")


if __name__ == "__main__":
    if "--check" in sys.argv:
        _self_check()
    else:
        main()
