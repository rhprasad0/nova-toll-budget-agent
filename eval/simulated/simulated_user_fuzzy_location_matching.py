"""Observational ActorSimulator evaluation for fuzzy location matching."""

from __future__ import annotations

import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from strands_evals import Case  # noqa: E402
from strands_evals.types.simulation import ActorProfile  # noqa: E402

from agent.dev_chat import configure_local_pricing_env  # noqa: E402
from agent.toll_agent import build_agent  # noqa: E402
from eval.simulation_support import run_simulated_evaluation  # noqa: E402

_RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"

_MODEL_ID_ENV = "NOVA_TOLL_EVAL_MODEL_ID"
_DEFAULT_MODEL_ID = "us.anthropic.claude-haiku-4-5-20251001-v1:0"

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

_ACTOR_PROFILE = ActorProfile(
    traits={
        "communication_style": "concise and direct",
        "domain_knowledge": "ordinary driver unfamiliar with toll-system labels",
        "disclosure": "identifies the intended McLean interchange only when asked",
    },
    context=(
        "The driver is traveling from the I-495 McLean interchange at Jones Branch "
        "Drive/Route 123 to Westpark Drive, not from the I-66 Inside the Beltway "
        "McLean interchange."
    ),
    actor_goal=(
        "Get an accurate toll quote from Jones Branch Drive/Route 123 to Westpark "
        "Drive after clarifying which McLean interchange is intended."
    ),
)


def main() -> None:
    configure_local_pricing_env()
    model_id = os.environ.get(_MODEL_ID_ENV, _DEFAULT_MODEL_ID)
    if not model_id:
        raise ValueError(f"{_MODEL_ID_ENV} must not be empty")
    run_simulated_evaluation(_CASE, _ACTOR_PROFILE, model_id, _RESULTS_DIR, build_agent)


def _self_check() -> None:
    """Assert the static Case and actor profile without network calls."""
    assert _CASE.name == "ambiguous-alias-mclean-simulated"
    assert _CASE.input
    assert _CASE.expected_assertion
    assert "McLean" in _CASE.input
    assert "Jones Branch Drive/Route 123" in _ACTOR_PROFILE.actor_goal
    print("self-check ok (Case and actor profile shapes; live integrations excluded)")


if __name__ == "__main__":
    if "--check" in sys.argv:
        _self_check()
    else:
        main()
