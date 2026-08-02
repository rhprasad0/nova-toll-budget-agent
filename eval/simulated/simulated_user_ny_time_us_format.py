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
from strands_evals.types.simulation import ActorProfile  # noqa: E402

from agent.dev_chat import configure_local_pricing_env  # noqa: E402
from agent.toll_agent import build_agent  # noqa: E402
from eval.simulation_support import (  # noqa: E402
    build_telemetry,
    run_case_with_simulator,
)

_RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"

_MODEL_ID_ENV = "NOVA_TOLL_EVAL_MODEL_ID"
_DEFAULT_MODEL_ID = "us.anthropic.claude-haiku-4-5-20251001-v1:0"

_CASE = Case[str, str](
    name="relative-time-tomorrow-afternoon-simulated",
    input=(
        "How much would it cost to drive from Pentagon/Eads Street to I-95 "
        "Near Dumfries Road/Route 234 tomorrow afternoon, around 3?"
    ),
    metadata={
        "task_description": (
            "Wants a toll price quote for tomorrow afternoon around 3 "
            "o'clock. If asked to clarify AM/PM or an exact time, says "
            "3:00 PM. If asked to confirm 'tomorrow' means the day after "
            "today's date, confirms that plainly. Does not volunteer a "
            "full calendar date unless asked."
        )
    },
    expected_assertion=(
        "The agent interprets 'tomorrow afternoon, around 3' as an "
        "America/New_York date and time -- never silently defaulting to "
        "UTC or another zone. Any clarifying question it asks is about the "
        "ambiguous time or date, not the (unambiguous) locations. Once it "
        "has a specific time, it prices the trip and reports the VDOT "
        "observed timestamp in US Standard format (M/D/YYYY h:MM AM/PM "
        "ET), never as a raw ISO-8601 string."
    ),
)

_ACTOR_PROFILE = ActorProfile(
    traits={
        "communication_style": "casual, gives relative time references",
        "domain_knowledge": "ordinary driver, thinks in local wall-clock time",
        "disclosure": "gives an exact time (3:00 PM) or confirms 'tomorrow' "
        "means the day after today only when asked",
    },
    context=(
        "The driver means 3:00 PM Eastern Time on the calendar day after "
        "today, driving from Pentagon/Eads Street to I-95 Near Dumfries "
        "Road/Route 234."
    ),
    actor_goal=(
        "Get an accurate toll quote for 3:00 PM Eastern Time tomorrow from "
        "Pentagon/Eads Street to I-95 Near Dumfries Road/Route 234."
    ),
)


def main() -> None:
    configure_local_pricing_env()
    telemetry, mapper = build_telemetry()
    model_id = os.environ.get(_MODEL_ID_ENV, _DEFAULT_MODEL_ID)
    if not model_id:
        raise ValueError(f"{_MODEL_ID_ENV} must not be empty")

    def task_function(case: Case[str, str]) -> dict[str, object]:
        simulator = ActorSimulator(
            actor_profile=_ACTOR_PROFILE,
            initial_query=str(case.input),
            model=model_id,
            max_turns=2,
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
            HelpfulnessEvaluator(model=model_id),
            GoalSuccessRateEvaluator(model=model_id),
        ],
    )
    report = experiment.run_evaluations(task_function)

    _RESULTS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    report.to_file(str(_RESULTS_DIR / f"{stamp}.json"))

    print(f"Overall score: {report.overall_score:.2f}")
    report.display(include_input=False)


def _self_check() -> None:
    """Assert the static Case and actor profile without network calls."""
    assert _CASE.name == "relative-time-tomorrow-afternoon-simulated"
    assert _CASE.input
    assert _CASE.expected_assertion
    assert "tomorrow" in _CASE.input
    assert "3:00 PM Eastern" in _ACTOR_PROFILE.actor_goal
    print("self-check ok (Case and actor profile shapes; live integrations excluded)")


if __name__ == "__main__":
    if "--check" in sys.argv:
        _self_check()
    else:
        main()
