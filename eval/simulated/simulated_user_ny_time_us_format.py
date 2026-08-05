"""Observational ActorSimulator evaluation for future relative dates.

The agent receives today's New York calendar date in its prompt, so it must
recognize "tomorrow" as future travel and decline without calling a tool.
"""

from __future__ import annotations

import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

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
_EASTERN = ZoneInfo("America/New_York")


def build_case_and_profile(
    today: date | None = None,
) -> tuple[Case[str, str], ActorProfile]:
    """Build a relative-future request against a fixed or live New York date."""
    resolved_today = today or datetime.now(_EASTERN).date()
    tomorrow = resolved_today + timedelta(days=1)
    tomorrow_label = f"{tomorrow:%B} {tomorrow.day}, {tomorrow.year}"

    case = Case[str, str](
        name="relative-time-tomorrow-afternoon-simulated",
        input=(
            "How much would it cost to drive from Jones Branch Drive/Route 123 "
            "to Westpark Drive tomorrow afternoon, around 3?"
        ),
        metadata={
            "task_description": (
                "Wants a toll price quote for tomorrow afternoon around 3 "
                f"o'clock ({tomorrow_label})."
            )
        },
        expected_assertion=(
            "The user supplied a relative future travel date. The agent has a "
            "current New York calendar-date anchor, recognizes 'tomorrow' as "
            "future, clearly says historical VDOT data cannot price future "
            "travel, and makes no planner, access, junction, or pricing tool call."
        ),
    )
    profile = ActorProfile(
        traits={
            "communication_style": "casual, gives relative time references",
            "domain_knowledge": "ordinary driver, thinks in local wall-clock time",
            "disclosure": "does not provide extra details after a future-date refusal",
        },
        context=(
            f"Today is {resolved_today:%B} {resolved_today.day}, "
            f"{resolved_today.year}. The driver means 3:00 PM Eastern Time "
            f"tomorrow ({tomorrow_label}), driving from Jones Branch "
            "Drive/Route 123 to Westpark Drive."
        ),
        actor_goal=(
            f"Ask for a toll quote on {tomorrow_label} from Jones Branch "
            "Drive/Route 123 to Westpark Drive."
        ),
    )
    return case, profile


def main() -> None:
    configure_local_pricing_env()
    model_id = os.environ.get(_MODEL_ID_ENV, _DEFAULT_MODEL_ID)
    if not model_id:
        raise ValueError(f"{_MODEL_ID_ENV} must not be empty")

    case, actor_profile = build_case_and_profile()
    run_simulated_evaluation(case, actor_profile, model_id, _RESULTS_DIR, build_agent)


def _self_check() -> None:
    """Assert the Case/profile shapes for a fixed date, without network calls."""
    case, profile = build_case_and_profile(today=date(2026, 8, 2))
    assert case.name == "relative-time-tomorrow-afternoon-simulated"
    assert case.input
    assert case.expected_assertion
    assert "tomorrow" in case.input
    assert "Jones Branch Drive/Route 123" in case.input
    assert "August 3, 2026" in profile.context
    assert "August 3, 2026" in profile.actor_goal
    print("self-check ok (Case and actor profile shapes; live integrations excluded)")


if __name__ == "__main__":
    if "--check" in sys.argv:
        _self_check()
    else:
        main()
