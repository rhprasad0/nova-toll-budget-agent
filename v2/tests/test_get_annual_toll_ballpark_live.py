"""Opt-in live checks for the annual toll ballpark tool."""

import pytest

from timed_checks import run_annual_checks

pytestmark = pytest.mark.live


def test_live_annual_checks() -> None:
    result = run_annual_checks()
    assert result["cases"] == 4
