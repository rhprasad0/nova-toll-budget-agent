"""Lambda boundary for the reusable timed checks."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import cast

from eval import run_evaluation
from timed_checks import (
    NEW_YORK,
    SCHEDULE_WINDOW_PAIRS,
    WINDOW_IDS,
    run_annual_checks,
    run_route_checks,
    scheduled_run_is_fresh,
)

logger = logging.getLogger()
logger.setLevel(logging.INFO)

_EVAL_OUTPUT_DIR = Path("/tmp/tollchat-timed-checks")


class TimedChecksValidationError(ValueError):
    """A malformed invocation event rejected at the Lambda boundary."""


class TimedChecksStaleError(RuntimeError):
    """The invocation arrived outside its reviewed freshness window."""


def _validate_event(event: object) -> tuple[str, str]:
    if not isinstance(event, dict):
        raise TimedChecksValidationError("invalid timed-check event")
    data = cast(dict[str, object], event)
    if (
        set(data) - {"window_id", "schedule"}
        or "window_id" not in data
        or "schedule" not in data
    ):
        raise TimedChecksValidationError("invalid timed-check event")
    window_id = data["window_id"]
    schedule = data.get("schedule", "")
    if not isinstance(window_id, str) or window_id not in WINDOW_IDS:
        raise TimedChecksValidationError("invalid timed-check event")
    if not isinstance(schedule, str) or not schedule:
        raise TimedChecksValidationError("invalid timed-check event")
    if (schedule, window_id) not in SCHEDULE_WINDOW_PAIRS:
        raise TimedChecksValidationError("invalid timed-check event")
    return window_id, schedule


def _scheduled_time(schedule: str, actual_start: datetime) -> datetime:
    """Derive the local scheduled timestamp without expanding the event contract."""
    minute, hour, _, _, weekday = schedule.split()
    scheduled = (
        actual_start - timedelta(days=(actual_start.isoweekday() - int(weekday)) % 7)
    ).replace(hour=int(hour), minute=int(minute), second=0, microsecond=0)
    return scheduled if scheduled <= actual_start else scheduled - timedelta(days=7)


def _emit_result(result: dict[str, object]) -> None:
    record = {"event": "timed_checks_result", **result}
    logger.info(json.dumps(record, sort_keys=True, separators=(",", ":")), extra=record)


def handler(event: object, _context: object) -> dict[str, str]:
    """Validate and run one timed-check window."""
    window_id: str | None = None
    schedule: str | None = None
    actual_start = datetime.now(NEW_YORK)
    terminal: dict[str, object] = {
        "status": "invalid",
        "window_id": None,
        "schedule": None,
        "scheduled_time": None,
        "actual_start_time": actual_start.isoformat(),
        "freshness": "not_checked",
        "route": "not_run",
        "annual": "not_run",
        "evaluation": "not_run",
    }
    phase: str | None = None
    try:
        window_id, schedule = _validate_event(event)
        terminal.update(
            {
                "window_id": window_id,
                "schedule": schedule,
                "scheduled_time": _scheduled_time(schedule, actual_start).isoformat(),
            }
        )
        fresh = scheduled_run_is_fresh(schedule, actual_start)
        terminal["freshness"] = "fresh" if fresh else "stale"
        if not fresh:
            terminal.update(
                {
                    "status": "stale",
                    "failure_type": "TimedChecksStaleError",
                }
            )
            raise TimedChecksStaleError("timed-check window is stale")

        phase = "route"
        run_route_checks(window_id)
        terminal["route"] = "succeeded"
        phase = "annual"
        run_annual_checks()
        terminal["annual"] = "succeeded"
        phase = "evaluation"
        run_evaluation.main(window=window_id, output_dir=_EVAL_OUTPUT_DIR)
        terminal["evaluation"] = "succeeded"
        terminal["status"] = "succeeded"
        return {"status": "succeeded", "window_id": window_id}
    except TimedChecksValidationError:
        terminal.update(
            {"status": "invalid", "failure_type": "TimedChecksValidationError"}
        )
        raise
    except TimedChecksStaleError:
        raise
    except (Exception, SystemExit) as error:
        if phase is not None:
            terminal[phase] = "failed"
        terminal.update(
            {
                "status": "failed",
                "failure_type": type(error).__name__,
            }
        )
        raise
    finally:
        _emit_result(terminal)
