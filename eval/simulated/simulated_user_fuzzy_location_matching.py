"""Observational ActorSimulator evaluation for fuzzy location matching."""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from strands_evals import ActorSimulator, Case, Experiment  # noqa: E402
from strands_evals.types.simulation import ActorProfile  # noqa: E402

from agent.dev_chat import configure_local_pricing_env  # noqa: E402
from agent.toll_agent import build_agent  # noqa: E402
from eval.simulation_support import (  # noqa: E402
    PendingBatchJudgeEvaluator,
    build_telemetry,
    raise_for_evaluation_errors,
    run_case_with_simulator,
)

_RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"
_MODEL_ID_ENV = "NOVA_TOLL_EVAL_MODEL_ID"
_DEFAULT_MODEL_ID = "us.anthropic.claude-haiku-4-5-20251001-v1:0"

_MCLEAN_CASE = Case[str, str](
    name="ambiguous-alias-mclean-simulated",
    input="Price a trip from McLean to Westpark Drive.",
    metadata={
        "batch_judge_suite": "fuzzy_location_matching",
        "task_description": (
            "Wants a toll price quote from McLean to Westpark Drive. McLean "
            "is ambiguous between two interchanges; the user means the "
            "I-495 one (Jones Branch Drive) and should say so plainly if "
            "asked which McLean they mean, without volunteering it unprompted."
        ),
    },
    expected_assertion=(
        "The agent does not price any trip on its first response; it asks "
        "which McLean interchange is meant. After the user identifies the "
        "I-495 one, it prices Jones Branch Drive/Route 123 to Westpark Drive. "
        "It never quotes a price for the I-66 ITB interchange."
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
        "Drive/Route 123 to Westpark Drive, not from I-66 Inside the Beltway."
    ),
    actor_goal=(
        "Get an accurate toll quote from Jones Branch Drive/Route 123 to Westpark "
        "Drive after clarifying which McLean interchange is intended."
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
        evaluators=[PendingBatchJudgeEvaluator()],
    ).run_evaluations(task_function)
    _RESULTS_DIR.mkdir(exist_ok=True)
    report.to_file(str(_RESULTS_DIR / f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"))
    print(f"Overall score: {report.overall_score:.2f}")
    report.display(include_input=False)
    raise_for_evaluation_errors(report)


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
    for case in _WASHINGTON_CASES:
        profile = build_actor_profile(case)
        assert "only after being asked" in profile.traits["disclosure"]
        assert "reply exactly" in profile.actor_goal
    print("self-check ok (three Case/profile shapes; live integrations excluded)")


if __name__ == "__main__":
    _self_check() if "--check" in sys.argv else main()
