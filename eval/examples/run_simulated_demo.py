"""Non-deterministic ActorSimulator demo; see ``eval/README.md`` to run it."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from strands_evals import (  # noqa: E402
    ActorSimulator,
    Case,
    Experiment,
)
from strands_evals.evaluators import (  # noqa: E402
    GoalSuccessRateEvaluator,
    HelpfulnessEvaluator,
)

from agent.dev_chat import configure_local_pricing_env  # noqa: E402
from agent.toll_agent import build_agent  # noqa: E402
from eval.simulation_support import (  # noqa: E402
    build_telemetry,
    run_case_with_simulator,
)

_RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"

_ACTOR_JUDGE_MODEL_ID = "us.anthropic.claude-haiku-4-5-20251001-v1:0"

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


def main() -> None:
    configure_local_pricing_env()
    telemetry, mapper = build_telemetry()

    def task_function(case: Case[str, str]) -> dict[str, object]:
        simulator = ActorSimulator.from_case_for_user_simulator(  # pyright: ignore[reportUnknownMemberType]
            case=case, model=_ACTOR_JUDGE_MODEL_ID, max_turns=2
        )
        return run_case_with_simulator(
            case.session_id,
            build_agent(),
            simulator,
            str(case.input),
            telemetry,
            mapper,
        )

    experiment = Experiment[str, str](
        cases=[_CASE],
        evaluators=[
            HelpfulnessEvaluator(model=_ACTOR_JUDGE_MODEL_ID),
            GoalSuccessRateEvaluator(model=_ACTOR_JUDGE_MODEL_ID),
        ],
    )
    report = experiment.run_evaluations(task_function)

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
