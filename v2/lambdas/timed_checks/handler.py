"""Lambda boundary for the reusable timed checks."""

from __future__ import annotations

import logging
from datetime import datetime
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


def _emit_result(result: dict[str, object]) -> None:
    logger.info("timed_checks_result", extra=result)


def handler(event: object, _context: object) -> dict[str, str]:
    """Validate and run one timed-check window."""
    window_id: str | None = None
    terminal: dict[str, object] | None = None
    try:
        window_id, schedule = _validate_event(event)
        if not scheduled_run_is_fresh(schedule, datetime.now(NEW_YORK)):
            terminal = {"status": "stale", "window_id": window_id}
            return {"status": "stale", "window_id": window_id}

        run_route_checks(window_id)
        run_annual_checks()
        run_evaluation.main(window=window_id, output_dir=_EVAL_OUTPUT_DIR)
        terminal = {"status": "succeeded", "window_id": window_id}
        return {"status": "succeeded", "window_id": window_id}
    except TimedChecksValidationError:
        terminal = {"status": "invalid", "reason": "invalid_event"}
        raise
    except (Exception, SystemExit) as error:
        terminal = {
            "status": "failed",
            **({"window_id": window_id} if window_id is not None else {}),
            "error_type": type(error).__name__,
        }
        raise
    finally:
        if terminal is not None:
            _emit_result(terminal)
