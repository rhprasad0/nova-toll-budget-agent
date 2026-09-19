"""Scheduled live checks for v2 current toll route validation."""

import os

import pytest

from timed_checks import run_route_checks

pytestmark = pytest.mark.live


def test_live_route_checks_match_timed_window() -> None:
    window_id = os.environ["TIMED_WINDOW_ID"]
    run_route_checks(window_id)
