"""Tests for _oracle_route helpers that every route tool shares.

at_time parsing used to be asserted separately in each tool's own test
module against a per-module alias; there is one implementation, so it is
tested once here.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from agent_tools import _oracle_route

_EASTERN = ZoneInfo("America/New_York")


def test_resolve_at_time_defaults_to_now_eastern():
    sentinel = datetime(2026, 7, 26, 12, 0, tzinfo=_EASTERN)
    assert _oracle_route.resolve_at_time(None, now=lambda: sentinel) == sentinel
    assert _oracle_route.resolve_at_time("", now=lambda: sentinel) == sentinel


def test_resolve_at_time_assumes_eastern_for_a_naive_string():
    result = _oracle_route.resolve_at_time("2026-07-26T12:00:00")
    assert result == datetime(2026, 7, 26, 12, 0, tzinfo=_EASTERN)


def test_resolve_at_time_keeps_an_explicit_offset():
    result = _oracle_route.resolve_at_time("2026-07-26T12:00:00+00:00")
    assert result.utcoffset() == timedelta(0)


def test_resolve_at_time_rejects_future_instants():
    def now():
        return datetime(2026, 8, 5, 12, 0, tzinfo=_EASTERN)

    assert _oracle_route.resolve_at_time("2026-08-05T12:00:00", now=now) == now()

    for at_time in ("2026-08-05T12:01:00", "2026-08-06T00:00:00"):
        with pytest.raises(ValueError, match="future at_time"):
            _oracle_route.resolve_at_time(at_time, now=now)
