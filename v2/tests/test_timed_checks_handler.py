import logging
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

import pytest

from eval import run_evaluation
from lambdas.timed_checks import handler as runner
from timed_checks import SCHEDULE_WINDOW_PAIRS


def _records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [record for record in caplog.records if record.msg == "timed_checks_result"]


def _always_fresh(*_args: object, **_kwargs: object) -> bool:
    return True


def _always_stale(*_args: object, **_kwargs: object) -> bool:
    return False


def _noop(*_args: object, **_kwargs: object) -> None:
    return None


def _unexpected_call(*_args: object, **_kwargs: object) -> None:
    pytest.fail("unexpected call")


def _no_cases(**_kwargs: object) -> list[Any]:
    return []


def _record_field(record: logging.LogRecord, field: str) -> str:
    return cast(str, getattr(record, field))


def _schedule(window_id: str) -> str:
    return next(
        schedule for schedule, window in SCHEDULE_WINDOW_PAIRS if window == window_id
    )


def test_schedule_window_contract_has_28_unique_pairs() -> None:
    assert len(SCHEDULE_WINDOW_PAIRS) == 28
    assert len(set(SCHEDULE_WINDOW_PAIRS)) == 28
    assert {window for _, window in SCHEDULE_WINDOW_PAIRS} == set(runner.WINDOW_IDS)


def test_fresh_invocation_runs_in_order_and_uses_tmp(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    calls: list[Any] = []

    def route_check(window: str) -> dict[str, object]:
        calls.append(("route", window))
        return {}

    def annual_check() -> dict[str, object]:
        calls.append("annual")
        return {}

    def evaluate(*, window: str, output_dir: Path) -> None:
        calls.append(("eval", window, output_dir))

    monkeypatch.setattr(runner, "scheduled_run_is_fresh", _always_fresh)
    monkeypatch.setattr(runner, "run_route_checks", route_check)
    monkeypatch.setattr(runner, "run_annual_checks", annual_check)
    monkeypatch.setattr(runner.run_evaluation, "main", evaluate)
    with caplog.at_level(logging.INFO):
        result = runner.handler(
            {
                "window_id": "i95_northbound",
                "schedule": _schedule("i95_northbound"),
            },
            object(),
        )

    assert result == {"status": "succeeded", "window_id": "i95_northbound"}
    assert calls[:2] == [("route", "i95_northbound"), "annual"]
    assert calls[2][0:2] == ("eval", "i95_northbound")
    assert isinstance(calls[2][2], Path)
    assert str(calls[2][2]).startswith("/tmp/")
    records = _records(caplog)
    assert len(records) == 1
    assert _record_field(records[0], "status") == "succeeded"


def test_stale_invocation_short_circuits_and_records_once(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(runner, "scheduled_run_is_fresh", _always_stale)
    monkeypatch.setattr(runner, "run_route_checks", _unexpected_call)
    monkeypatch.setattr(runner, "run_annual_checks", _unexpected_call)
    monkeypatch.setattr(runner.run_evaluation, "main", _unexpected_call)
    with caplog.at_level(logging.INFO):
        result = runner.handler(
            {
                "window_id": "greenway_eb_peak",
                "schedule": _schedule("greenway_eb_peak"),
            },
            object(),
        )

    assert result == {"status": "stale", "window_id": "greenway_eb_peak"}
    records = _records(caplog)
    assert len(records) == 1
    assert _record_field(records[0], "status") == "stale"


@pytest.mark.parametrize(
    "event",
    [
        None,
        {},
        {"window_id": "i95_northbound"},
        {"window_id": 3},
        {"window_id": "unknown"},
        {"window_id": "i95_northbound", "schedule": ""},
        {"window_id": "i95_northbound", "schedule": 3},
        {"window_id": "i95_northbound", "schedule": _schedule("greenway_eb_peak")},
        {"window_id": "i95_northbound", "extra": "nope"},
    ],
)
def test_invalid_event_is_rejected_before_live_work(
    event: object, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(runner, "run_route_checks", _unexpected_call)
    with caplog.at_level(logging.INFO), pytest.raises(ValueError):
        runner.handler(event, object())
    records = _records(caplog)
    assert len(records) == 1
    assert _record_field(records[0], "status") == "invalid"
    assert not hasattr(records[0], "event_payload")


@pytest.mark.parametrize("stage", ["route", "annual", "evaluation"])
@pytest.mark.parametrize(
    "failure", [RuntimeError("secret details"), SystemExit("secret details")]
)
def test_failure_is_reraised_and_logged_once_without_exception_text(
    failure: BaseException,
    stage: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(runner, "scheduled_run_is_fresh", _always_fresh)
    monkeypatch.setattr(runner, "run_route_checks", _noop)
    monkeypatch.setattr(runner, "run_annual_checks", _noop)
    monkeypatch.setattr(runner.run_evaluation, "main", _noop)

    def explode(*_args: object, **_kwargs: object) -> None:
        raise failure

    if stage == "route":
        monkeypatch.setattr(runner, "run_route_checks", explode)
    elif stage == "annual":
        monkeypatch.setattr(runner, "run_annual_checks", explode)
    else:
        monkeypatch.setattr(runner.run_evaluation, "main", explode)
    with caplog.at_level(logging.INFO), pytest.raises(type(failure)):
        runner.handler(
            {"window_id": "i95_reversal", "schedule": _schedule("i95_reversal")},
            object(),
        )
    records = _records(caplog)
    assert len(records) == 1
    assert _record_field(records[0], "status") == "failed"
    assert _record_field(records[0], "error_type") == type(failure).__name__
    assert "secret details" not in caplog.text


def test_timed_check_imports_do_not_create_clients() -> None:
    source_root = Path(__file__).parents[1]
    code = """
import boto3
calls = []
boto3.client = lambda *args, **kwargs: calls.append((args, kwargs))
import timed_checks
import lambdas.timed_checks.handler
assert calls == []
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=source_root,
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout == ""


def test_evaluation_output_override_is_writable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class FakeReport:
        test_passes = (True,)

        def to_file(self, path: str) -> None:
            Path(path).write_text("{}")

        def display(self, *, include_input: bool) -> None:
            assert include_input is False

    class FakeExperiment:
        @classmethod
        def __class_getitem__(cls, _item: object) -> type["FakeExperiment"]:
            return cls

        def __init__(self, **_: object) -> None: ...

        def run_evaluations(self, _task: object) -> FakeReport:
            return FakeReport()

    default_dir = tmp_path / "default-results"
    output_dir = tmp_path / "nested" / "reports"
    monkeypatch.setattr(run_evaluation, "_configure_database", lambda: None)
    monkeypatch.setattr(run_evaluation, "load_cases", _no_cases)
    monkeypatch.setattr(run_evaluation, "Experiment", FakeExperiment)
    monkeypatch.setattr(run_evaluation, "_RESULTS_DIR", default_dir)

    run_evaluation.main("i95_northbound")
    assert len(list(default_dir.glob("*.json"))) == 1

    run_evaluation.main("i95_northbound", output_dir=output_dir)

    reports = list(output_dir.glob("*.json"))
    assert len(reports) == 1
    assert reports[0].read_text() == "{}"


def test_evaluation_default_destination_is_preserved_when_read_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class FakeReport:
        test_passes = (True,)

        def to_file(self, path: str) -> None:
            Path(path).write_text("{}")

        def display(self, *, include_input: bool) -> None:
            assert include_input is False

    class FakeExperiment:
        @classmethod
        def __class_getitem__(cls, _item: object) -> type["FakeExperiment"]:
            return cls

        def __init__(self, **_: object) -> None: ...

        def run_evaluations(self, _task: object) -> FakeReport:
            return FakeReport()

    default_dir = tmp_path / "repository-relative-results"
    override_dir = tmp_path / "lambda-tmp-results"
    original_mkdir = Path.mkdir

    def reject_default_mkdir(
        self: Path,
        mode: int = 0o777,
        parents: bool = False,
        exist_ok: bool = False,
    ) -> None:
        if self == default_dir:
            raise PermissionError("default results directory is read-only")
        original_mkdir(self, mode=mode, parents=parents, exist_ok=exist_ok)

    monkeypatch.setattr(run_evaluation, "_RESULTS_DIR", default_dir)
    monkeypatch.setattr(run_evaluation, "_configure_database", lambda: None)
    monkeypatch.setattr(run_evaluation, "load_cases", _no_cases)
    monkeypatch.setattr(run_evaluation, "Experiment", FakeExperiment)
    monkeypatch.setattr(Path, "mkdir", reject_default_mkdir)

    with pytest.raises(PermissionError):
        run_evaluation.main("i95_northbound")
    run_evaluation.main("i95_northbound", output_dir=override_dir)

    reports = list(override_dir.glob("*.json"))
    assert len(reports) == 1
    assert reports[0].read_text() == "{}"
