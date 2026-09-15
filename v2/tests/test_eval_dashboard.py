from collections.abc import Callable
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast

import pytest

from eval import dashboard
from lambdas.timed_checks import handler


def test_projection_publishes_evidence_once_and_omits_internal_fields() -> None:
    trajectory = {
        "traces": [
            {
                "spans": [
                    {
                        "user_prompt": "What is the toll?",
                        "agent_response": "$12.34 observed.",
                    },
                    {
                        "tool_call": {
                            "name": "get_current_toll_price",
                            "arguments": {
                                "origin_point_id": "airport_dca",
                                "password": "private",
                            },
                        },
                        "tool_result": {
                            "content": '{"total_usd":"12.34","s3_key":"private","source_kind":"observed"}'
                        },
                    },
                ]
            }
        ]
    }
    report = SimpleNamespace(
        cases=[
            {"evaluator": name, "actual_trajectory": trajectory}
            for name in dashboard.CHECKS
        ],
        test_passes=[True, False, True],
        detailed_results=[
            [{"reason": "Review user@example.com"}] for _ in dashboard.CHECKS
        ],
    )
    result = dashboard.project_report(report)
    assert len(result["turns"]) == 1
    assert len(result["checks"]) == 3
    assert result["turns"][0]["tools"][0]["result"] == {
        "total_usd": "12.34",
        "source_kind": "observed",
    }
    assert "private" not in str(result)
    assert "user@example.com" not in str(result)
    report.detailed_results[1] = []
    with pytest.raises(ValueError, match="incomplete"):
        dashboard.project_report(report)


@pytest.mark.parametrize(
    "failure,scored",
    [
        (None, False),
        (RuntimeError("private exception"), False),
        (RuntimeError("notification failed"), True),
    ],
)
def test_handler_records_execution_and_publishes_after_completion(
    monkeypatch: pytest.MonkeyPatch, failure: Exception | None, scored: bool
) -> None:
    events: list[object] = []

    class Store:
        def start(self, *_: object) -> bool:
            events.append("start")
            return True

        def finish(
            self,
            _window: str,
            _scheduled: datetime,
            status: str,
            evidence: dict[str, Any],
        ) -> None:
            assert bool(evidence) == scored
            events.append(status)

        def publish(self) -> None:
            events.append("publish")

    def run(*args: object) -> dict[str, str]:
        events.append("evaluate")
        if scored:
            cast(Callable[[object], None], args[2])(object())
        if failure:
            raise failure
        return {"status": "succeeded", "window_id": "i95_southbound"}

    monkeypatch.setenv("EVAL_DASHBOARD_BUCKET", "test")
    monkeypatch.setattr(dashboard, "Store", Store)

    def projected(_: object) -> dict[str, object]:
        return {"checks": [{"passed": False}]}

    monkeypatch.setattr(dashboard, "project_report", projected)

    def fresh(*_: object) -> bool:
        return True

    monkeypatch.setattr(handler, "scheduled_run_is_fresh", fresh)
    monkeypatch.setattr(handler, "_run_handler", run)
    event = {"window_id": "i95_southbound", "schedule": "17 14 * * 2"}
    if failure:
        with pytest.raises(RuntimeError):
            handler.handler(event, object())
    else:
        handler.handler(event, object())
    assert events == [
        "start",
        "publish",
        "evaluate",
        "failed" if scored else "error" if failure else "passed",
        "publish",
    ]


def test_duplicate_does_not_run_models(monkeypatch: pytest.MonkeyPatch) -> None:
    class Store:
        def start(self, *_: object) -> bool:
            return False

        def publish(self) -> None:
            pass

    monkeypatch.setenv("EVAL_DASHBOARD_BUCKET", "test")
    monkeypatch.setattr(dashboard, "Store", Store)

    def unexpected(*_: object) -> None:
        pytest.fail("Duplicate ran models")

    monkeypatch.setattr(handler, "_run_handler", unexpected)
    assert (
        handler.handler(
            {"window_id": "i95_southbound", "schedule": "17 14 * * 2"}, object()
        )["status"]
        == "duplicate"
    )


def test_saturday_scenario_uses_eastern_day() -> None:
    assert (
        dashboard.scenario_id(
            "i95_northbound", datetime(2026, 9, 19, 22, 17, tzinfo=UTC)
        )
        == "dulles-to-reagan-current-price"
    )
