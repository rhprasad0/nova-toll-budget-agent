"""Reject scheduled live checks that start too late for their expected state."""

import sys
from datetime import datetime
from zoneinfo import ZoneInfo

MAX_DELAY_SECONDS = 600
NEW_YORK = ZoneInfo("America/New_York")


def scheduled_run_is_fresh(schedule: str, now: datetime) -> bool:
    if not schedule:
        return True

    minute, hour, _, _, weekday = schedule.split()
    if now.isoweekday() != int(weekday):
        return False

    scheduled_at = now.replace(
        hour=int(hour), minute=int(minute), second=0, microsecond=0
    )
    return 0 <= (now - scheduled_at).total_seconds() <= MAX_DELAY_SECONDS


def main() -> int:
    schedule = sys.argv[1]
    now = datetime.now(NEW_YORK)
    if scheduled_run_is_fresh(schedule, now):
        return 0

    print(
        f"{schedule!r} is outside its {MAX_DELAY_SECONDS}-second freshness window "
        f"at {now.isoformat(timespec='seconds')}"
    )
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
