"""Confirms CI can reach the current RDS pricing surface over Tailscale, using
the same IAM-auth code path production uses
(`agent_tools._oracle_route.env_connect`).

Deliberately narrower than the other live tests: they hardcode
AWS_PROFILE="nova-toll" (a local named profile that doesn't exist under the
GitHub OIDC role this runs as), and one calls live Bedrock, which this
connectivity check has no business paying for. Marked
`live` like the others -- excluded from the default `pytest` run (see
pyproject.toml addopts) -- and only ever invoked explicitly by the CI
`integration` job (see .github/workflows/ci.yml), which provides AWS
credentials via the nova-toll-github-ci OIDC role (infra/iam.tf) after
joining the tailnet.

DB_HOST/DB_PORT are resolved at runtime via `describe_db_instances` rather
than hardcoded; SECURITY.md asks that database endpoints not be committed.

Run explicitly (with AWS credentials and DB_USER/DB_NAME/DB_CA_BUNDLE_PATH set):

    uv run pytest -m live tests/test_ci_rds_connectivity.py -v
"""

from datetime import timedelta

import pytest

from agent_tools._oracle_route import env_connect
from rds_ci_test_support import configure_pricing_reader_rds_env

pytestmark = pytest.mark.live


def test_can_select_1_over_the_tailscale_bridge():
    configure_pricing_reader_rds_env()

    with env_connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT 1")
        assert cur.fetchone() == (1,)


def test_pricing_reader_sees_current_vdot_views():
    configure_pricing_reader_rds_env()

    with env_connect() as conn, conn.cursor() as cur:
        cur.execute("SHOW TimeZone")
        assert cur.fetchone() == ("America/New_York",)

        cur.execute("SELECT current_timestamp")
        row = cur.fetchone()
        assert row is not None
        assert row[0].utcoffset() in (
            timedelta(hours=-5),
            timedelta(hours=-4),
        )

        for view in ("current_trip_pricing_i95", "current_trip_pricing_i66"):
            cur.execute(f"SELECT 1 FROM {view} LIMIT 1")
            assert cur.fetchone() == (1,), view
