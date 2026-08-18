from datetime import datetime
from zoneinfo import ZoneInfo

from scripts.check_timed_window import scheduled_run_is_fresh

NEW_YORK = ZoneInfo("America/New_York")
REVERSAL_SCHEDULE = "47 1 * * 2"


def test_fresh_scheduled_run():
    now = datetime(2026, 8, 18, 1, 55, tzinfo=NEW_YORK)
    assert scheduled_run_is_fresh(REVERSAL_SCHEDULE, now)


def test_stale_scheduled_run():
    now = datetime(2026, 8, 18, 2, 16, tzinfo=NEW_YORK)
    assert not scheduled_run_is_fresh(REVERSAL_SCHEDULE, now)


def test_stale_scheduled_run_after_date_rollover():
    now = datetime(2026, 8, 21, 14, 25, tzinfo=NEW_YORK)
    assert not scheduled_run_is_fresh("17 14 * * 4", now)


def test_manual_dispatch():
    now = datetime(2026, 8, 18, 2, 16, tzinfo=NEW_YORK)
    assert scheduled_run_is_fresh("", now)
