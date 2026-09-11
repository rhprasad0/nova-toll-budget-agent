import logging
import subprocess
import sys
from dataclasses import FrozenInstanceError
from datetime import datetime
from pathlib import Path
from typing import Any, cast

import pytest
from strands_evals import Case
from strands_evals.evaluators import Evaluator
from strands_evals.types.evaluation import EvaluationData, EvaluationOutput

from eval import run_evaluation
from lambdas.timed_checks import handler as runner
from timed_checks import SCHEDULE_WINDOW_PAIRS


def _records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "timed_checks_result"
    ]


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
    assert _record_field(records[0], "freshness") == "fresh"
    assert _record_field(records[0], "route") == "succeeded"
    assert _record_field(records[0], "annual") == "succeeded"
    assert _record_field(records[0], "evaluation") == "succeeded"
    assert _record_field(records[0], "schedule") == _schedule("i95_northbound")
    assert _record_field(records[0], "scheduled_time").endswith(("-05:00", "-04:00"))


def test_scheduled_time_is_the_latest_reviewed_new_york_occurrence() -> None:
    actual = datetime(2026, 9, 9, 1, 49, tzinfo=runner.NEW_YORK)
    assert runner._scheduled_time(  # pyright: ignore[reportPrivateUsage]
        "47 1 * * 3", actual
    ).isoformat() == ("2026-09-09T01:47:00-04:00")
    assert runner._scheduled_time(  # pyright: ignore[reportPrivateUsage]
        "17 14 * * 3", actual
    ).isoformat() == ("2026-09-02T14:17:00-04:00")


def test_stale_invocation_short_circuits_and_records_once(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(runner, "scheduled_run_is_fresh", _always_stale)
    monkeypatch.setattr(runner, "run_route_checks", _unexpected_call)
    monkeypatch.setattr(runner, "run_annual_checks", _unexpected_call)
    monkeypatch.setattr(runner.run_evaluation, "main", _unexpected_call)
    with caplog.at_level(logging.INFO), pytest.raises(runner.TimedChecksStaleError):
        runner.handler(
            {
                "window_id": "greenway_eb_peak",
                "schedule": _schedule("greenway_eb_peak"),
            },
            object(),
        )
    records = _records(caplog)
    assert len(records) == 1
    assert _record_field(records[0], "status") == "stale"
    assert _record_field(records[0], "freshness") == "stale"
    assert _record_field(records[0], "failure_type") == "TimedChecksStaleError"


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
    assert _record_field(records[0], "failure_type") == type(failure).__name__
    assert _record_field(records[0], stage) == "failed"
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


def test_evaluation_failure_keeps_report_output_and_immutable_details(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    events: list[str] = []

    class FakeReport:
        def __init__(
            self,
            cases: list[dict[str, str]],
            test_passes: list[bool],
            reasons: list[str],
        ) -> None:
            self.cases = cases
            self.test_passes = test_passes
            self.reasons = reasons
            self.detailed_results = [["scored"] for _ in cases]

        def to_file(self, path: str) -> None:
            events.append("write")
            Path(path).write_text("report")

        def display(self, *, include_input: bool) -> None:
            assert include_input is False
            events.append("display")

    whitespace_reason = "\n  first\t failure  \n" + "x " * 400
    single_report = FakeReport(
        [{"name": "passed"}, {"name": "single"}],
        [True, False],
        ["passed", whitespace_reason],
    )
    multiple_report = FakeReport(
        [{"name": "duplicate"}, {"name": "passed"}, {"name": "duplicate"}],
        [False, True, False],
        ["first", "passed", "last"],
    )
    reports = [single_report, multiple_report]

    class FakeExperiment:
        @classmethod
        def __class_getitem__(cls, _item: object) -> type["FakeExperiment"]:
            return cls

        def __init__(self, **_: object) -> None: ...

        def run_evaluations(self, _task: object) -> FakeReport:
            return reports.pop(0)

    monkeypatch.setattr(run_evaluation, "_configure_database", lambda: None)
    monkeypatch.setattr(run_evaluation, "load_cases", _no_cases)
    monkeypatch.setattr(run_evaluation, "Experiment", FakeExperiment)

    with pytest.raises(run_evaluation.EvaluationFailed) as raised:
        run_evaluation.main("i95_northbound", output_dir=tmp_path / "one")
    failure = raised.value
    assert isinstance(failure, SystemExit)
    assert failure.code not in (None, 0)
    assert isinstance(failure.passed_count, int)
    assert isinstance(failure.case_count, int)
    assert isinstance(failure.failures, tuple)
    assert isinstance(failure.failures[0], tuple)
    assert failure.passed_count == 1
    assert failure.case_count == 2
    assert failure.failures == (("single", "first failure " + "x " * 143),)
    assert len(failure.failures[0][1]) == 300
    assert "\n" not in failure.failures[0][1]
    assert "\t" not in failure.failures[0][1]
    assert whitespace_reason == single_report.reasons[1]
    assert events == ["write", "display"]
    assert len(list((tmp_path / "one").glob("*.json"))) == 1
    with pytest.raises(FrozenInstanceError):
        cast(Any, failure).passed_count = 0
    with pytest.raises(FrozenInstanceError):
        cast(Any, failure).case_count = 0
    with pytest.raises(FrozenInstanceError):
        cast(Any, failure).failures = ()
    with pytest.raises(TypeError):
        cast(Any, failure.failures)[0] = ()
    with pytest.raises(TypeError):
        cast(Any, failure.failures[0])[0] = "changed"
    assert not hasattr(failure, "report")

    with pytest.raises(run_evaluation.EvaluationFailed) as raised:
        run_evaluation.main("i95_northbound", output_dir=tmp_path / "multiple")
    assert raised.value.passed_count == 1
    assert raised.value.case_count == 3
    assert raised.value.failures == (("duplicate", "first"), ("duplicate", "last"))
    assert events == ["write", "display", "write", "display"]


def test_evaluation_failure_is_reraised_by_timed_handler(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    failure = run_evaluation.EvaluationFailed(0, 1, (("case", "secret details"),))
    monkeypatch.setattr(runner, "scheduled_run_is_fresh", _always_fresh)
    monkeypatch.setattr(runner, "run_route_checks", _noop)
    monkeypatch.setattr(runner, "run_annual_checks", _noop)

    def raise_failure(**_: object) -> None:
        raise failure

    monkeypatch.setattr(runner.run_evaluation, "main", raise_failure)

    with caplog.at_level(logging.INFO), pytest.raises(run_evaluation.EvaluationFailed):
        runner.handler(
            {"window_id": "i95_reversal", "schedule": _schedule("i95_reversal")},
            object(),
        )

    records = _records(caplog)
    assert len(records) == 1
    assert _record_field(records[0], "status") == "failed"
    assert _record_field(records[0], "evaluation") == "failed"
    assert _record_field(records[0], "route") == "succeeded"
    assert _record_field(records[0], "annual") == "succeeded"
    assert _record_field(records[0], "failure_type") == "EvaluationFailed"
    assert "secret details" not in caplog.text


@pytest.mark.parametrize("source", ["task", "evaluator"])
def test_unscored_experiment_errors_use_generic_handler_path_without_sns(
    source: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    tmp_path: Path,
) -> None:
    events: list[str] = []
    monkeypatch.setattr(run_evaluation, "_configure_database", lambda: None)

    def load_cases(**_: object) -> list[Case[str, str]]:
        return [Case[str, str](name="case", input="input")]

    monkeypatch.setattr(run_evaluation, "load_cases", load_cases)
    monkeypatch.setattr(runner, "scheduled_run_is_fresh", _always_fresh)
    monkeypatch.setattr(runner, "run_route_checks", _noop)
    monkeypatch.setattr(runner, "run_annual_checks", _noop)
    monkeypatch.setattr(runner, "_EVAL_OUTPUT_DIR", tmp_path)
    monkeypatch.setenv("TIMED_CHECK_ALERTS_ENABLED", "true")
    monkeypatch.setenv("ALERTS_TOPIC_ARN", "arn:aws:sns:us-east-1:123:alerts")
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setattr(runner.boto3, "client", _unexpected_call)

    from strands_evals.types.evaluation_report import EvaluationReport

    original_to_file = EvaluationReport.to_file

    def to_file(report: Any, path: str) -> None:
        events.append("write")
        original_to_file(report, path)

    def display(_report: Any, *, include_input: bool) -> None:
        assert include_input is False
        events.append("display")

    monkeypatch.setattr(EvaluationReport, "to_file", to_file)
    monkeypatch.setattr(EvaluationReport, "display", display)

    if source == "task":

        def task(_case: Case[str, str]) -> str:
            raise RuntimeError("task secret details")

        monkeypatch.setattr(run_evaluation, "task_function", task)
        secret = "task secret details"
    else:

        class ExplodingEvaluator(Evaluator[str, str]):
            def evaluate(
                self, evaluation_case: EvaluationData[str, str]
            ) -> list[EvaluationOutput]:
                del evaluation_case
                raise RuntimeError("evaluator secret details")

        def task(_case: Case[str, str]) -> str:
            return "ok"

        monkeypatch.setattr(run_evaluation, "TollChatEvaluator", ExplodingEvaluator)
        monkeypatch.setattr(run_evaluation, "task_function", task)
        secret = "evaluator secret details"

    with (
        caplog.at_level(logging.INFO),
        pytest.raises(
            run_evaluation.EvaluationExecutionError,
            match=r"^TollChat evaluation execution failed$",
        ),
    ):
        runner.handler(_alert_event(), _AlertContext())

    assert events == ["write", "display"]
    assert len(list(tmp_path.glob("*.json"))) == 1
    records = _records(caplog)
    assert len(records) == 1
    assert _record_field(records[0], "evaluation") == "failed"
    assert _record_field(records[0], "failure_type") == "EvaluationExecutionError"
    assert secret not in records[0].getMessage()


class _AlertContext:
    aws_request_id = "request-123"
    log_group_name = "/aws/lambda/nova-toll-v2-timed-checks-dev"
    log_stream_name = "2026/09/11/[$LATEST]stream"


def _raise_evaluation_failure(**_: object) -> None:
    raise run_evaluation.EvaluationFailed(
        1, 3, (("case-one", "wrong toll"), ("case-two", "wrong route"))
    )


def _prepare_evaluation_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner, "scheduled_run_is_fresh", _always_fresh)
    monkeypatch.setattr(runner, "run_route_checks", _noop)
    monkeypatch.setattr(runner, "run_annual_checks", _noop)
    monkeypatch.setattr(runner.run_evaluation, "main", _raise_evaluation_failure)


def _alert_event() -> dict[str, str]:
    return {"window_id": "i95_reversal", "schedule": _schedule("i95_reversal")}


def test_evaluation_failure_publishes_one_safe_alert_and_is_handled(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _prepare_evaluation_failure(monkeypatch)
    monkeypatch.setenv("TIMED_CHECK_ALERTS_ENABLED", "true")
    monkeypatch.setenv("ALERTS_TOPIC_ARN", "arn:aws:sns:us-east-1:123:alerts")
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    published: list[dict[str, str]] = []

    class Client:
        def publish(self, **kwargs: str) -> None:
            published.append(kwargs)

    def client(name: str, *, region_name: str) -> Client:
        assert (name, region_name) == ("sns", "us-east-1")
        return Client()

    monkeypatch.setattr(cast(Any, runner.boto3), "client", client)

    with caplog.at_level(logging.INFO):
        result = runner.handler(_alert_event(), _AlertContext())

    assert result == {"status": "failed", "window_id": "i95_reversal"}
    assert published == [
        {
            "TopicArn": "arn:aws:sns:us-east-1:123:alerts",
            "Subject": "TollChat development eval failed: i95_reversal (1/3 passed)",
            "Message": "\n".join(
                (
                    "Environment: development",
                    "Window: i95_reversal",
                    "Passed: 1/3",
                    "Failed cases:",
                    "- case-one: wrong toll",
                    "- case-two: wrong route",
                    "Request ID: request-123",
                    "Log stream: https://us-east-1.console.aws.amazon.com/cloudwatch/home?region=us-east-1#logsV2:log-groups/log-group/$252Faws$252Flambda$252Fnova-toll-v2-timed-checks-dev/log-events/2026$252F09$252F11$252F$255B$2524LATEST$255Dstream",
                )
            ),
        }
    ]
    records = _records(caplog)
    assert len(records) == 1
    assert _record_field(records[0], "status") == "failed"
    assert _record_field(records[0], "evaluation") == "failed"
    assert _record_field(records[0], "failure_type") == "EvaluationFailed"
    assert _record_field(records[0], "notification") == "sent"
    assert "wrong toll" not in caplog.text
    assert "arn:aws:sns" not in caplog.text


def test_tool_price_is_excluded_from_evaluation_failure_and_alert(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, tmp_path: Path
) -> None:
    metadata = next(
        row
        for row in run_evaluation.load_rows()
        if row["id"] == "reagan-airport-to-westpark"
    )
    expected = cast(dict[str, str], metadata["expected_call"])
    price = "9876.54"
    output = run_evaluation.evaluate_westpark_turn(
        [
            {
                "name": "get_current_toll_price",
                "input": expected,
                "tool_result": {
                    "origin_point_id": expected["origin_point_id"],
                    "destination_point_id": expected["destination_point_id"],
                    "total_usd": price,
                },
            }
        ],
        "### 🚗 Current toll\n\nNo price is shown.",
        metadata,
    )
    assert output[0].reason == "response omitted the current toll"

    class FakeReport:
        def __init__(self) -> None:
            self.cases = [{"name": "reagan-airport-to-westpark"}]
            self.test_passes = [False]
            self.reasons = [output[0].reason]
            self.detailed_results = [output]

        def to_file(self, path: str) -> None:
            Path(path).write_text("report")

        def display(self, *, include_input: bool) -> None:
            assert include_input is False

    class FakeExperiment:
        @classmethod
        def __class_getitem__(cls, _item: object) -> type["FakeExperiment"]:
            return cls

        def __init__(self, **_: object) -> None: ...

        def run_evaluations(self, _task: object) -> FakeReport:
            return FakeReport()

    monkeypatch.setattr(run_evaluation, "_configure_database", lambda: None)
    monkeypatch.setattr(run_evaluation, "Experiment", FakeExperiment)
    with pytest.raises(run_evaluation.EvaluationFailed) as raised:
        run_evaluation.main("i95_southbound", output_dir=tmp_path / "direct")
    assert raised.value.failures == (
        ("reagan-airport-to-westpark", "response omitted the current toll"),
    )
    assert price not in str(raised.value.failures)

    main = run_evaluation.main
    _prepare_evaluation_failure(monkeypatch)
    monkeypatch.setattr(runner.run_evaluation, "main", main)
    monkeypatch.setenv("TIMED_CHECK_ALERTS_ENABLED", "true")
    monkeypatch.setenv("ALERTS_TOPIC_ARN", "arn:aws:sns:us-east-1:123:alerts")
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    published: list[dict[str, str]] = []

    class Client:
        def publish(self, **kwargs: str) -> None:
            published.append(kwargs)

    def client(*_args: object, **_kwargs: object) -> Client:
        return Client()

    monkeypatch.setattr(cast(Any, runner.boto3), "client", client)

    with caplog.at_level(logging.INFO):
        assert runner.handler(_alert_event(), _AlertContext()) == {
            "status": "failed",
            "window_id": "i95_reversal",
        }

    assert len(published) == 1
    assert "response omitted the current toll" in published[0]["Message"]
    assert price not in published[0]["Message"]
    assert price not in _records(caplog)[0].getMessage()


def test_evaluation_failure_alert_disabled_is_handled_without_client(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _prepare_evaluation_failure(monkeypatch)
    monkeypatch.setenv("TIMED_CHECK_ALERTS_ENABLED", "false")
    monkeypatch.setattr(runner.boto3, "client", _unexpected_call)

    with caplog.at_level(logging.INFO):
        result = runner.handler(_alert_event(), object())

    assert result == {"status": "failed", "window_id": "i95_reversal"}
    records = _records(caplog)
    assert len(records) == 1
    assert _record_field(records[0], "notification") == "disabled"


def test_evaluation_failure_alert_missing_flag_preserves_legacy_reraise(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _prepare_evaluation_failure(monkeypatch)
    monkeypatch.delenv("TIMED_CHECK_ALERTS_ENABLED", raising=False)
    monkeypatch.setattr(runner.boto3, "client", _unexpected_call)

    with caplog.at_level(logging.INFO), pytest.raises(run_evaluation.EvaluationFailed):
        runner.handler(_alert_event(), object())

    records = _records(caplog)
    assert len(records) == 1
    assert _record_field(records[0], "notification") == "legacy"


@pytest.mark.parametrize(
    ("flag", "topic", "context"),
    [
        ("TRUE", "arn:aws:sns:us-east-1:123:alerts", _AlertContext()),
        ("true", "", _AlertContext()),
        ("true", "arn:aws:sns:us-east-1:123:alerts", object()),
    ],
)
def test_evaluation_failure_invalid_alert_configuration_reraises_without_client(
    flag: str,
    topic: str,
    context: object,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _prepare_evaluation_failure(monkeypatch)
    monkeypatch.setenv("TIMED_CHECK_ALERTS_ENABLED", flag)
    monkeypatch.setenv("ALERTS_TOPIC_ARN", topic)
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setattr(runner.boto3, "client", _unexpected_call)

    with caplog.at_level(logging.INFO), pytest.raises(ValueError):
        runner.handler(_alert_event(), context)

    records = _records(caplog)
    assert len(records) == 1
    assert _record_field(records[0], "evaluation") == "failed"
    assert _record_field(records[0], "notification") == "failed"


def test_evaluation_failure_publish_error_reraises_and_records_failed_notification(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _prepare_evaluation_failure(monkeypatch)
    monkeypatch.setenv("TIMED_CHECK_ALERTS_ENABLED", "true")
    monkeypatch.setenv("ALERTS_TOPIC_ARN", "arn:aws:sns:us-east-1:123:alerts")
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("AWS_REGION", "us-east-1")

    class Client:
        def publish(self, **_: str) -> None:
            raise RuntimeError("SNS unavailable")

    def client(*_args: object, **_kwargs: object) -> Client:
        return Client()

    monkeypatch.setattr(cast(Any, runner.boto3), "client", client)

    with (
        caplog.at_level(logging.INFO),
        pytest.raises(RuntimeError, match="SNS unavailable"),
    ):
        runner.handler(_alert_event(), _AlertContext())

    records = _records(caplog)
    assert len(records) == 1
    assert _record_field(records[0], "notification") == "failed"


def test_evaluation_failure_alert_rejects_oversized_subject_before_client(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _prepare_evaluation_failure(monkeypatch)
    monkeypatch.setenv("TIMED_CHECK_ALERTS_ENABLED", "true")
    monkeypatch.setenv("ALERTS_TOPIC_ARN", "arn:aws:sns:us-east-1:123:alerts")
    monkeypatch.setenv("ENVIRONMENT", "x" * 100)
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setattr(runner.boto3, "client", _unexpected_call)

    with caplog.at_level(logging.INFO), pytest.raises(ValueError):
        runner.handler(_alert_event(), _AlertContext())

    assert _record_field(_records(caplog)[0], "notification") == "failed"


def test_evaluation_failure_alert_rejects_oversized_body_before_client(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _prepare_evaluation_failure(monkeypatch)
    failure = run_evaluation.EvaluationFailed(
        0, 1000, tuple((f"case-{index}", "x" * 300) for index in range(1000))
    )

    def raise_failure(**_: object) -> None:
        raise failure

    monkeypatch.setattr(runner.run_evaluation, "main", raise_failure)
    monkeypatch.setenv("TIMED_CHECK_ALERTS_ENABLED", "true")
    monkeypatch.setenv("ALERTS_TOPIC_ARN", "arn:aws:sns:us-east-1:123:alerts")
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setattr(runner.boto3, "client", _unexpected_call)

    with caplog.at_level(logging.INFO), pytest.raises(ValueError):
        runner.handler(_alert_event(), _AlertContext())

    assert _record_field(_records(caplog)[0], "notification") == "failed"


@pytest.mark.parametrize("failure_stage", ["write", "display"])
def test_evaluation_report_io_errors_are_not_wrapped(
    failure_stage: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class FakeReport:
        def __init__(self) -> None:
            self.cases = [{"name": "failed"}]
            self.test_passes = [False]
            self.reasons = ["failed"]

        def to_file(self, path: str) -> None:
            if failure_stage == "write":
                raise RuntimeError("write failed")
            Path(path).write_text("report")

        def display(self, *, include_input: bool) -> None:
            assert include_input is False
            if failure_stage == "display":
                raise RuntimeError("display failed")

    class FakeExperiment:
        @classmethod
        def __class_getitem__(cls, _item: object) -> type["FakeExperiment"]:
            return cls

        def __init__(self, **_: object) -> None: ...

        def run_evaluations(self, _task: object) -> FakeReport:
            return FakeReport()

    monkeypatch.setattr(run_evaluation, "_configure_database", lambda: None)
    monkeypatch.setattr(run_evaluation, "load_cases", _no_cases)
    monkeypatch.setattr(run_evaluation, "Experiment", FakeExperiment)

    with pytest.raises(RuntimeError, match=f"{failure_stage} failed"):
        run_evaluation.main("i95_northbound", output_dir=tmp_path)


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
