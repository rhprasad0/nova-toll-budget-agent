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

import os
import sys

import boto3
import pytest

from conftest import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT / "agent_tools"))

from _oracle_route import env_connect  # noqa: E402

pytestmark = pytest.mark.live

AWS_REGION = "us-east-1"
DB_IDENTIFIER = "nova-toll-db"  # infra/rds.tf identifier


def test_can_select_1_over_the_tailscale_bridge():
    instance = boto3.client("rds", region_name=AWS_REGION).describe_db_instances(
        DBInstanceIdentifier=DB_IDENTIFIER
    )["DBInstances"][0]
    os.environ["DB_HOST"] = instance["Endpoint"]["Address"]
    os.environ["DB_PORT"] = str(instance["Endpoint"]["Port"])

    with env_connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT 1")
        assert cur.fetchone() == (1,)
