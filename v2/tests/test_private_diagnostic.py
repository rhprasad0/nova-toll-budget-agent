"""Synthetic continuation: reservations survive; release gates stay closed."""

import asyncio
import json
from argparse import Namespace
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest

from eval import golden_run as run
from eval import private_holdout as private
from eval.holdout_container import guide, guide_data
from tests.test_holdout_guide_data import freeze, preparation, workstation
from tests.test_private_holdout import synthetic_bundle


def unknown_run(tmp_path: Path) -> tuple[run.Journal, list[dict[str, Any]]]:
    journal = run.Journal(tmp_path / "prep-001", 5, soft_fail=True)
    attempt = run.Attempt(id="synthetic-1", case_id="synthetic", trial=1)
    reserve = journal.reserve(attempt, "judge", 100)
    journal.finish(attempt, "judge", reserve, None, 1)
    private.write(journal.directory / "manifest.json", {"diagnostic": False})
    return journal, [{"directory": str(journal.directory)}]


def test_diagnostic_keeps_unknown_reservations_and_budget(tmp_path: Path) -> None:
    journal, history = unknown_run(tmp_path)
    spent, unknown = private.preparation_spending(
        history, (0.9, False), diagnostic=True
    )
    assert unknown and spent == pytest.approx(0.9 + journal.spent)
    with pytest.raises(ValueError, match="unknown prior usage"):
        private.preparation_spending(history, (0.9, False), diagnostic=False)
    with pytest.raises(ValueError, match="unbounded"):
        private.preparation_spending(history, (0.9, True), diagnostic=True)
    with pytest.raises(ValueError, match="exhausted"):
        private.preparation_spending(history, (25, False), diagnostic=True)
    attempt = run.Attempt(id="synthetic-2", case_id="synthetic", trial=1)
    journal.reserve(attempt, "judge", 100)
    assert journal.unknown_usage
    journal.limit = journal.spent + journal.reserved
    with pytest.raises(run.StopRun):
        journal.reserve(attempt, "judge", 100)
    with pytest.raises(ValueError, match="unfinished calls"):
        private.preparation_spending(history, (0, False), diagnostic=True)


def test_diagnostic_refuses_reduced_unknown_reservation(tmp_path: Path) -> None:
    journal, history = unknown_run(tmp_path)
    events = private.events(journal.directory)
    events[-1]["cost_usd"] = 0
    (journal.directory / "events.jsonl").write_text(
        "\n".join(map(json.dumps, events)) + "\n"
    )
    with pytest.raises(ValueError, match="full reservation"):
        private.preparation_spending(history, (0, False), diagnostic=True)


def test_diagnostic_cannot_qualify_even_with_complete_measurements(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    journal, history = unknown_run(tmp_path)
    private.write(journal.directory / "manifest.json", {"diagnostic": True})
    with pytest.raises(ValueError, match="diagnostic history"):
        private.preparation_spending(history, (0, False), diagnostic=False)
    with pytest.raises(ValueError, match="diagnostic history"):
        private.summary(journal.directory, history, None)
    monkeypatch.setattr(
        private, "preparation_report", Mock(return_value={"complete": True})
    )
    with pytest.raises(ValueError, match="incomplete or changed"):
        private.calibration_admission(
            journal.directory, tmp_path, tmp_path, "unused", "unused"
        )
    with pytest.raises(ValueError, match="preparation-only"):
        private.execute(Namespace(diagnostic=True, mode="run"), [])


def test_guide_requires_explicit_diagnostic_and_retains_history(tmp_path: Path) -> None:
    paths = workstation(tmp_path)
    frozen = freeze(paths)

    def dispatch(request: dict[str, Any]) -> dict[str, Any]:
        return guide_data.dispatch(request, **paths)

    dispatch(
        {"action": "init_history", "prior_cost_usd": 0.9, "prior_unknown_usage": False}
    )
    private.write(
        paths["inputs"] / "context.json",
        synthetic_bundle(paths["inputs"] / "release.zip"),
    )
    private.write(
        paths["inputs"] / "policy.json",
        private.read(private.golden.V2 / "eval/results/golden/policy-4.0.0.json"),
    )
    preparation(paths, frozen)
    directory = paths["output"] / "prep-001"
    with (directory / "events.jsonl").open("a") as stream:
        stream.write(
            json.dumps(
                {
                    "event": "model_started",
                    "attempt": "bad",
                    "role": "judge",
                    "reserved_usd": 0.05,
                }
            )
            + "\n"
        )
        stream.write(
            json.dumps(
                {
                    "event": "model_finished",
                    "attempt": "bad",
                    "role": "judge",
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cached_tokens": 0,
                    "written_tokens": 0,
                    "cost_usd": 0.05,
                    "seconds": 0,
                    "complete": False,
                }
            )
            + "\n"
        )
    request = {
        "action": "evaluation_plan",
        "mode": "prepare",
        "note": "Authorize synthetic diagnostic preparation.",
    }
    with pytest.raises(ValueError, match="unknown prior usage"):
        dispatch(request)
    with pytest.raises(ValueError, match="review the incomplete"):
        dispatch({**request, "diagnostic": True})
    dispatch({"action": "review_result", "kind": "calibration", "run": "prep-001"})
    before = (paths["output"] / "history.json").read_bytes()
    plan = dispatch({**request, "diagnostic": True})
    assert plan["diagnostic"] and plan["unknown_usage"]
    assert plan["spent_usd"] == pytest.approx(0.95)
    assert plan["execution_limit_usd"] == 5 and "--diagnostic" in plan["arguments"]
    assert (paths["output"] / "history.json").read_bytes() == before
    for value in ("true", 1, None):
        with pytest.raises(ValueError, match="preparation-only"):
            dispatch({**request, "diagnostic": value})
    with pytest.raises(ValueError, match="preparation-only"):
        dispatch({**request, "mode": "run", "diagnostic": True})
    assert (
        guide.request_action(
            {"action": "prepare", "note": "authorized", "diagnostic": True}
        )
        == "prepare"
    )
    with pytest.raises(ValueError):
        guide.request_action(
            {"action": "run", "note": "authorized", "diagnostic": True}
        )


def test_failure_metadata_is_bounded_and_preserves_reservation(tmp_path: Path) -> None:
    class Failure(Exception):
        status_code = 503
        request_id = "req_synthetic"

    async def stream(*args: object, **kwargs: object) -> AsyncIterator[dict[str, Any]]:
        raise Failure("private response body must not be logged")
        yield {}

    native = Mock()
    native.client_args = {}
    native.stream = stream
    journal = run.Journal(tmp_path / "run", 5, soft_fail=True)
    attempt = run.Attempt(id="synthetic", case_id="synthetic", trial=1)
    model = journal.model(native, "judge", attempt, 1)

    async def consume() -> None:
        async for _ in model.stream([]):
            pass

    with pytest.raises(Failure):
        asyncio.run(consume())
    rows = private.events(journal.directory)
    failed = next(row for row in rows if row["event"] == "model_failed")
    assert failed["http_status"] == 503 and failed["request_id"] == "req_synthetic"
    assert (
        "private response body" not in (journal.directory / "events.jsonl").read_text()
    )
    assert journal.unknown_usage and rows[-1]["cost_usd"] == rows[0]["reserved_usd"]


@pytest.mark.parametrize("soft_fail", [False, True])
def test_preparation_failure_stops_only_strict_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, soft_fail: bool
) -> None:
    from concurrent.futures import ThreadPoolExecutor

    from eval import golden, golden_actor_check
    from tests.golden_support import case as golden_case

    case = golden_case(1)
    example = golden.Example(
        case_id=case.id,
        label="synthetic",
        turns=[golden.Turn(user=case.prompt, response="synthetic", calls=[])],
        expected=golden.ExpectedVerdicts(outcome=True, grounding=True, rules=True),
        expected_failures=[],
        rationale="synthetic failure",
    )
    monkeypatch.setattr(golden, "load_cases", lambda: [case])
    monkeypatch.setattr(golden, "grade_assertions", Mock(return_value=[]))
    monkeypatch.setattr(run, "judge", Mock(side_effect=RuntimeError("synthetic")))
    journal = run.Journal(tmp_path / "calibration", 5, soft_fail=soft_fail)
    with ThreadPoolExecutor(max_workers=1) as pool:
        rows = run.calibrate(journal, pool, [example])
    assert rows[0]["status"] == "infrastructure"
    assert journal.stop_requested is not soft_fail
    monkeypatch.setattr(
        run, "build_eval_model", Mock(side_effect=RuntimeError("synthetic"))
    )
    actors = run.Journal(tmp_path / "actors", 5, soft_fail=soft_fail)
    result = golden_actor_check.check(example, 1, actors)
    assert result.status == "infrastructure"
    assert actors.stop_requested is not soft_fail
