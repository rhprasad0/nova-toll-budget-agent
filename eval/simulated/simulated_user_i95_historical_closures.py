"""Observational simulated-user eval for Issue #17's four I-95 closures."""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from strands_evals import ActorSimulator, Case, Experiment  # noqa: E402
from strands_evals.evaluators import (  # noqa: E402
    GoalSuccessRateEvaluator,
    HelpfulnessEvaluator,
)

from agent.dev_chat import configure_local_pricing_env  # noqa: E402
from agent.toll_agent import build_agent  # noqa: E402
from eval.simulation_support import (  # noqa: E402
    build_telemetry,
    raise_for_evaluation_errors,
    run_case_with_simulator,
)

_CASES_PATH = (
    _REPO_ROOT
    / "eval"
    / "deterministic"
    / "i95_historical_closures"
    / "test-cases.jsonl"
)
_RESULTS_DIR = _REPO_ROOT / "eval" / "results"
_MODEL_ID_ENV = "NOVA_TOLL_EVAL_MODEL_ID"
_DEFAULT_MODEL_ID = "us.anthropic.claude-haiku-4-5-20251001-v1:0"


def load_cases(path: Path = _CASES_PATH) -> list[Case[str, str]]:
    cases: list[Case[str, str]] = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        row: dict[str, Any] = json.loads(line)
        expected = row["expected_trajectory"][0]
        cases.append(
            Case[str, str](
                name=f"{row['id']}-simulated",
                input=row["conversation"][0]["content"],
                metadata={
                    "task_description": (
                        "The driver wants only the requested historical I-95 Express "
                        "Lanes fare. The origin, destination, and time are complete and "
                        "must not be changed. If those lanes are closed, they need a "
                        "safe alternative suggestion without an invented toll quote."
                    )
                },
                expected_assertion=(
                    f"The agent calls i95_route exactly once with origin "
                    f"{expected['input']['origin']!r}, destination "
                    f"{expected['input']['destination']!r}, and at_time "
                    f"{expected['input']['at_time']!r}. After the tool reports "
                    f"OD {row['expected_od_pair_id']} CLOSED, the agent says the "
                    "requested I-95 Express Lanes trip is unavailable, quotes no "
                    "fare, suggests the I-95 general-purpose lanes as an unpriced "
                    "alternative, and does not call a substitute pricing tool."
                ),
            )
        )
    return cases


def main() -> None:
    configure_local_pricing_env()
    model_id = os.environ.get(_MODEL_ID_ENV, _DEFAULT_MODEL_ID)
    if not model_id:
        raise ValueError(f"{_MODEL_ID_ENV} must not be empty")
    telemetry, mapper = build_telemetry()

    def task_function(case: Case[str, str]) -> dict[str, object]:
        simulator = ActorSimulator.from_case_for_user_simulator(  # pyright: ignore[reportUnknownMemberType]
            case=case, model=model_id, max_turns=3
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
        cases=load_cases(),
        evaluators=[
            GoalSuccessRateEvaluator(model=model_id),
            HelpfulnessEvaluator(model=model_id),
        ],
    ).run_evaluations(task_function)
    _RESULTS_DIR.mkdir(exist_ok=True)
    report.to_file(str(_RESULTS_DIR / f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"))
    print(f"Overall score: {report.overall_score:.2f}")
    report.display(include_input=False)
    raise_for_evaluation_errors(report)


def _self_check() -> None:
    cases = load_cases()
    assert len(cases) == 4
    assert len({case.name for case in cases}) == 4
    assert all(case.input for case in cases)
    assert all(case.expected_assertion for case in cases)
    assert all((case.metadata or {}).get("task_description") for case in cases)
    print(
        "self-check ok (Case shapes only; live simulator, telemetry, and judges excluded)"
    )


if __name__ == "__main__":
    if "--check" in sys.argv:
        _self_check()
    else:
        main()
