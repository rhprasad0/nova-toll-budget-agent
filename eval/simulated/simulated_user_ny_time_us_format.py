"""Observational ActorSimulator evaluation for relative-date/time phrasing
and US-format reporting.

Track 1 (eval/deterministic/ny_time_us_format/) only asserts against
absolute dates, since the agent has no injected notion of "today" to
resolve a relative phrase like "tomorrow afternoon" against. This scenario
covers that relative phrasing instead, judged rather than exact-matched:
does the agent interpret "tomorrow afternoon, around 3" as an
America/New_York time without silently defaulting to another zone, and does
it report the returned VDOT timestamp in US Standard format
(M/D/YYYY h:MM AM/PM ET) rather than the tool's raw ISO-8601 string.
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
    """ "Tomorrow" only means something relative to the real current date, so
    the simulated user needs to know today's actual date to name a concrete
    one if asked -- exactly what a real user would do without being handed
    the answer. `today` is a fixed-date injection point for `--check`; a
    live run always uses the real date.
    """
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
                "o'clock. If asked to clarify AM/PM, an exact time, or the "
                f"calendar date, says 3:00 PM on {tomorrow_label}. Does not "
                "volunteer a full calendar date unless asked."
            )
        },
        expected_assertion=(
            "The agent interprets 'tomorrow afternoon, around 3' as an "
            "America/New_York date and time -- never silently defaulting to "
            "UTC or another zone or guessing a wrong calendar date. Any "
            "clarifying question it asks is about the ambiguous time or "
            "date, not the (unambiguous) locations. Once it has a specific "
            "time, it prices the trip and reports the VDOT observed "
            "timestamp in US Standard format (M/D/YYYY h:MM AM/PM ET), "
            "never as a raw ISO-8601 string."
        ),
    )
    profile = ActorProfile(
        traits={
            "communication_style": "casual, gives relative time references",
            "domain_knowledge": "ordinary driver, thinks in local wall-clock time",
            "disclosure": "gives an exact time (3:00 PM) and, if separately "
            f"asked for the calendar date, names {tomorrow_label} -- only "
            "when asked, never volunteered upfront",
        },
        context=(
            f"Today is {resolved_today:%B} {resolved_today.day}, "
            f"{resolved_today.year}. The driver means 3:00 PM Eastern Time "
            f"tomorrow ({tomorrow_label}), driving from Jones Branch "
            "Drive/Route 123 to Westpark Drive."
        ),
        actor_goal=(
            f"Get an accurate toll quote for 3:00 PM Eastern Time on "
            f"{tomorrow_label} from Jones Branch Drive/Route 123 to "
            "Westpark Drive."
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
