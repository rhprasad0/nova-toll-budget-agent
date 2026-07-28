"""Confirms CI can actually reach RDS over the Tailscale bridge, using the
same IAM-auth code path production uses (agent_tools/_oracle_route.py's
env_connect()).

Deliberately narrower than tests/test_expresslanes_crosscheck.py and friends:
those hardcode AWS_PROFILE="nova-toll" (a local named profile that doesn't
exist under the GitHub OIDC role this runs as) and one of them calls live
Bedrock, which this connectivity check has no business paying for. Marked
`live` like the others -- excluded from the default `pytest` run (see
pyproject.toml addopts) -- and only ever invoked explicitly by the CI
`integration` job (see .github/workflows/ci.yml), which provides AWS
credentials via the nova-toll-github-ci OIDC role (infra/iam.tf) after
joining the tailnet.

DB_HOST/DB_PORT are resolved at runtime via describe_db_instances rather
than hardcoded, matching test_expresslanes_crosscheck.py -- SECURITY.md
asks that database endpoints not be committed to the repo.

Run explicitly (with AWS credentials and DB_USER/DB_NAME/DB_CA_BUNDLE_PATH set):

    uv run pytest -m live tests/test_ci_rds_connectivity.py -v
"""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from rds_ci_test_support import configure_pricing_reader_rds_env

sys.path.insert(0, str(REPO_ROOT / "agent_tools"))

from _oracle_route import env_connect

pytestmark = pytest.mark.live


def test_can_select_1_over_the_tailscale_bridge():
    configure_pricing_reader_rds_env()

    with env_connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT 1")
        assert cur.fetchone() == (1,)
