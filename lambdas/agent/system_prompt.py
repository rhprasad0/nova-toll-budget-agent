"""System prompt for the NOVA toll budget agent.

Stub: the instruction body below is a placeholder. What *is* settled here is
the time-injection contract, because `route()` requires `at_time` and a model
left to infer "now" will answer from its training cutoff and return
confidently stale prices with no error. See docs/agent-tools-spec.md §2.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

# The corridors are in Northern Virginia, so "now" means Eastern wall-clock
# time to every user. Use the IANA zone, never a literal EST offset: EST is
# UTC-5 year round, but the region runs on EDT (UTC-4) from March to November.
# A hardcoded EST stamp is silently an hour off for most of the year, and
# express lane prices move every few minutes -- an hour is a different price.
EASTERN = ZoneInfo("America/New_York")

SYSTEM_PROMPT = """\
TODO: agent role, tool-use guidance, and beta framing.

## Current time

{now_iso} ({now_human})

This is the authoritative clock. Pass `{now_iso}` verbatim as `route()`'s
`at_time` argument when the user asks about current prices, and derive any
other instant from it. Never guess the date or time, and never substitute your
own -- you do not otherwise know what day it is.

Talk to the user in Eastern time ({now_human}); send the offset-qualified form
to the tools.
"""


def render_system_prompt(now: datetime | None = None) -> str:
    """Render the system prompt with the current Eastern time injected.

    Args:
        now: Instant to inject. Defaults to now. A naive datetime is
            interpreted as Eastern; an aware one is converted to Eastern.

    Returns:
        str: the prompt with both an ISO-8601 stamp carrying an explicit UTC
        offset (unambiguous for `at_time`) and a human Eastern rendering.
    """
    now = datetime.now(EASTERN) if now is None else now
    now = now.replace(tzinfo=EASTERN) if now.tzinfo is None else now.astimezone(EASTERN)
    return SYSTEM_PROMPT.format(
        now_iso=now.isoformat(timespec="seconds"),
        now_human=now.strftime("%A %B %-d, %Y at %-I:%M %p %Z"),
    )


if __name__ == "__main__":
    # The bug this module exists to prevent: a fixed EST offset is wrong for
    # ~8 months of the year. Same wall clock, two different real instants.
    winter = render_system_prompt(datetime(2026, 1, 15, 14, 30))
    summer = render_system_prompt(datetime(2026, 7, 15, 14, 30))
    assert "2026-01-15T14:30:00-05:00" in winter, winter
    assert "EST" in winter, winter
    assert "2026-07-15T14:30:00-04:00" in summer, summer
    assert "EDT" in summer, summer

    # An aware UTC instant must land on the same Eastern wall clock.
    from datetime import timezone

    utc = render_system_prompt(datetime(2026, 7, 15, 18, 30, tzinfo=timezone.utc))
    assert "2026-07-15T14:30:00-04:00" in utc, utc

    print(summer)
    print("ok")
