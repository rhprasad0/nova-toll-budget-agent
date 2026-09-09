"""Opt-in live checks for the annual toll ballpark tool."""

import pytest

from timed_checks import run_annual_checks

pytestmark = pytest.mark.live


def test_live_fixed_rate_round_trip() -> None:
    result = run_annual_checks()
    assert result["cases"] == 4


def test_live_dynamic_smoke_routes_have_complete_samples() -> None:
    result = run_annual_checks()
    assert result["cases"] == 4
