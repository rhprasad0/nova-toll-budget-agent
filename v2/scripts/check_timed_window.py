"""Reject scheduled live checks that start too late for their expected state."""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from timed_checks import (
    MAX_DELAY_SECONDS,
    NEW_YORK,
    scheduled_run_is_fresh,
)


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
