"""Live preparation reuses application execution without awarding its grades."""

import json
import sys
from pathlib import Path
from typing import Literal
from unittest.mock import Mock

import pytest

from eval import corpus, golden, golden_actor_check
from eval import golden_run as run


def test_live_actor_preparation_requires_explicit_preparation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "actor-check",
            "--live-application",
            "--output",
            str(tmp_path),
            "--budget-usd",
            "1",
        ],
    )
    with pytest.raises(SystemExit, match="2"):
        golden_actor_check.main()
    assert not (tmp_path / "manifest.json").exists()


@pytest.mark.parametrize("validity", ["valid", "invalid"])
def test_live_actor_checks_reuse_execution_and_preserve_actor_evidence(
    validity: Literal["valid", "invalid"],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    case = golden.load_cases(corpus.PUBLIC / "training")[0]
    example = next(
        golden.Example.model_validate(e)
        for e in json.loads((corpus.PUBLIC / "training" / "examples.json").read_text())
        if e["case_id"] == case.id and e["label"] == "passing"
    )
    row = run.Attempt(
        id=f"{case.id}-1",
        case_id=case.id,
        trial=1,
        status="scored" if validity == "valid" else "inconclusive",
        checks=["tool_arguments"],
        actor_validity=run.ActorAssessment(status=validity, evidence="Driver evidence"),
        actor_replies=[
            {"stop": True, "message": None, "stop_reason": "goal_completed"}
        ],
        verdicts={"outcome": run.Verdict(passed=False, evidence="Application failed")},
    )
    execute = Mock(return_value=row)
    monkeypatch.setattr(run, "execute", execute)
    monkeypatch.setattr(golden, "load_cases", lambda: [case])
    journal = run.Journal(tmp_path / "live", 1)
    result = golden_actor_check.live_check(example, 1, journal)
    execute.assert_called_once_with(case, 1, journal)
    assert result.verdicts == {}
    assert result.actor_validity == row.actor_validity
    assert result.status == ("scored" if validity == "valid" else "inconclusive")
    assert result.checks == ["tool_arguments"]
    event = json.loads(
        (journal.directory / "events.jsonl").read_text().splitlines()[-1]
    )
    assert event["event"] == "actor_check" and event["verdicts"] == {}


@pytest.mark.parametrize("application_stop", ["max_tokens", "TaskFailure"])
@pytest.mark.parametrize("status", ["scored", "infrastructure"])
def test_live_actor_checks_require_a_sampled_actor(
    application_stop: str,
    status: Literal["scored", "infrastructure"],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    case = golden.load_cases(corpus.PUBLIC / "training")[0]
    example = golden.Example.model_validate(
        json.loads((corpus.PUBLIC / "training" / "examples.json").read_text())[0]
    )
    row = run.Attempt(
        id=f"{case.id}-1",
        case_id=case.id,
        trial=1,
        status=status,
        application_stop=application_stop,
        actor_validity=run.ActorAssessment(status="valid", evidence="Approved opening"),
        error="missing_usage" if status == "infrastructure" else None,
    )
    monkeypatch.setattr(run, "execute", Mock(return_value=row))
    monkeypatch.setattr(golden, "load_cases", lambda: [case])
    journal = run.Journal(tmp_path / "live", 1)
    result = golden_actor_check.live_check(example, 1, journal)
    assert result.application_stop == application_stop
    if status == "scored":
        assert result.status == "inconclusive"
        assert result.actor_validity is not None
        assert result.actor_validity.status == "uncertain"
        assert result.error == "actor_not_sampled"
        assert result.failure_phase == "actor"
        assert result.failure_class == "actor_validity"
    else:
        assert result.status == "infrastructure"
        assert result.error == "missing_usage"
    event = json.loads(
        (journal.directory / "events.jsonl").read_text().splitlines()[-1]
    )
    assert event["status"] == result.status
    assert event["error"] == result.error


def test_supplied_schedule_and_days_allow_second_turn_replay() -> None:
    root = corpus.PUBLIC / "training"
    case = next(c for c in golden.load_cases(root) if c.id == "tr5-schedule-then-days")
    fixture = golden.load_fixture(case.steps[0].fixture, root)
    with pytest.raises(ValueError, match="premature_call"):
        golden.Replay(case, root).call(fixture.tool, fixture.input, [case.prompt])
    result = golden.Replay(case, root).call(
        fixture.tool,
        fixture.input,
        [case.prompt, "Monday, Wednesday and Friday; use my 102 planned days."],
    )
    assert result.result == fixture.result
