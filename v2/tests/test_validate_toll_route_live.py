"""Scheduled live checks for v2 current toll route validation."""

import os

import pytest

from timed_checks import run_route_checks

pytestmark = pytest.mark.live


def test_live_i95_state_matches_timed_window() -> None:
    window_id = os.environ["TIMED_WINDOW_ID"]
    if not window_id.startswith("i95_"):
        pytest.skip("not an I-95 timed window")
    run_route_checks(window_id)


def test_live_i95_northbound_restart_is_state_independent() -> None:
    window_id = os.environ["TIMED_WINDOW_ID"]
    if not window_id.startswith("i95_"):
        pytest.skip("not an I-95 timed window")
    run_route_checks(window_id)


def test_live_greenway_to_dca_matches_timed_i95_state() -> None:
    window_id = os.environ["TIMED_WINDOW_ID"]
    if not window_id.startswith("i95_"):
        pytest.skip("not an I-95 timed window")
    run_route_checks(window_id)


def test_live_greenway_peak_price() -> None:
    window_id = os.environ["TIMED_WINDOW_ID"]
    if not window_id.startswith("greenway_"):
        pytest.skip("not a Greenway timed window")
    run_route_checks(window_id)
