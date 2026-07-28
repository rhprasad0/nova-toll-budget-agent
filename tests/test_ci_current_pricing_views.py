"""Post-migration verification for current VDOT views and pricing_reader.

Run manually after db/add_current_pricing_views.sql succeeds, with the same
environment as the CI RDS integration tests:

    uv run pytest -m live tests/test_ci_current_pricing_views.py -v

This file is intentionally not in CI before the migration: production does
not yet have the views, and a pre-migration failure would say nothing useful.
"""

import sys
from datetime import timedelta
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from rds_ci_test_support import configure_pricing_reader_rds_env

sys.path.insert(0, str(REPO_ROOT / "agent_tools"))

from _oracle_route import env_connect

pytestmark = pytest.mark.live


def test_current_views_are_eastern_and_vdot_only():
    configure_pricing_reader_rds_env()

    with env_connect() as conn, conn.cursor() as cur:
        cur.execute("SHOW TimeZone")
        assert cur.fetchone() == ("America/New_York",)

        cur.execute("SELECT current_timestamp")
        now_row = cur.fetchone()
        assert now_row is not None
        now = now_row[0]
        assert now.utcoffset() in (timedelta(hours=-5), timedelta(hours=-4))

        for view in ("current_trip_pricing_i95", "current_trip_pricing_i66"):
            cur.execute(f"SELECT 1 FROM {view} LIMIT 1")
            assert cur.fetchone() == (1,), view

        cur.execute(
            "SELECT has_table_privilege(current_user, 'trip_pricing_i95_live', 'SELECT')"
        )
        assert cur.fetchone() == (False,)
