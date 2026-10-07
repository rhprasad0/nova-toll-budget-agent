from collections.abc import Callable
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast

import pytest

from eval import dashboard
from eval.simulated import ACTOR_SETTINGS, JUDGE_SETTINGS
from lambdas.timed_checks import handler


def test_projection_publishes_evidence_once_and_omits_internal_fields() -> None:
    trajectory: dict[str, Any] = {
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
    assert "model" not in result and "models" not in result
    trajectory["traces"][0]["spans"][0]["metadata"] = {
        "policy_version": "scheduled-critical-v1",
        "models": {
            "application": {
                "model": "deployed-model",
                "reasoning_effort": "low",
                "max_output_tokens": 2048,
            },
            "actor": ACTOR_SETTINGS.model_dump(),
            "judge": JUDGE_SETTINGS.model_dump(),
        },
        "deployment": {
            "release_id": "application-release",
            "runtime_version": "7",
            "api_key": "private",
        },
    }
    recorded = dashboard.project_report(report)
    assert recorded["models"]["application"]["model"] == "deployed-model"
    assert recorded["models"]["actor"]["reasoning_effort"] == "low"
    assert recorded["models"]["judge"]["reasoning_effort"] == "xhigh"
    assert recorded["policy_version"] == "scheduled-critical-v1"
    assert recorded["deployment"] == {
        "release_id": "application-release",
        "runtime_version": "7",
    }
    assert "private" not in str(recorded)
    trajectory["traces"][0]["spans"][0]["metadata"]["policy_version"] = "unknown"
    with pytest.raises(ValueError, match="Unknown scheduled evaluation policy"):
        dashboard.project_report(report)
    trajectory["traces"][0]["spans"][0]["metadata"]["policy_version"] = (
        "scheduled-critical-v1"
    )
    report.detailed_results[1] = []
    with pytest.raises(ValueError, match="incomplete"):
        dashboard.project_report(report)


def test_projection_preserves_availability_and_fallback_evidence() -> None:
    facts = {
        "status": "unknown_availability",
        "reason": {"code": "i95_stale_evidence", "internal_diagnostic": "private"},
        "i95_evidence": {
            "availability": "unknown",
            "northbound_link_status": "CLOSED",
            "observed_at": "2026-10-07T00:00:00Z",
            "s3_key": "private",
        },
        "general_purpose_gaps": [
            {
                "role": "prefix",
                "boundary_point_id": "i495:192NO",
                "fallback_required": None,
                "i95_direction": "NB",
                "storage_key": "private",
            }
        ],
    }
    public = cast(dict[str, Any], dashboard.public_facts(facts))
    assert public["reason"] == {"code": "i95_stale_evidence"}
    assert public["i95_evidence"]["availability"] == "unknown"
    assert public["i95_evidence"]["northbound_link_status"] == "CLOSED"
    assert public["general_purpose_gaps"][0]["fallback_required"] is None
    assert public["general_purpose_gaps"][0]["boundary_point_id"] == "i495:192NO"
    assert "private" not in str(public)


@pytest.mark.parametrize(
    "failure,scored",
    [
        (None, False),
        (RuntimeError("private exception"), False),
        (RuntimeError("notification failed"), True),
    ],
)
@pytest.mark.parametrize("start_snapshot_failure", [False, True])
def test_handler_records_execution_and_publishes_after_completion(
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception | None,
    scored: bool,
    start_snapshot_failure: bool,
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
            if start_snapshot_failure and events.count("publish") == 1:
                raise RuntimeError("snapshot unavailable")

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
