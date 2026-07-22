"""Cross-checks our ingested i95 trip_pricing against the Express Lanes
(Transurban) public live API -- a free, always-on second source for the same
OD pairs, unlike VDOT itself whose bulk/historical access is WAF-blocked (see
docs/poller-spec.md). Confirmed by hand: its od_XXXX ids are VDOT's ODPAIRID
verbatim.

Hits live network + live RDS -- deliberately marked `live` and excluded from
the default `pytest` run (see pyproject.toml addopts), so CI never depends on
either being reachable. Run explicitly:

    uv run pytest -m live tests/test_expresslanes_crosscheck.py -v
"""

import json
import re
import urllib.request
from decimal import Decimal

import boto3
import pytest

from conftest import REPO_ROOT

pytestmark = pytest.mark.live

LIVE_URL = "https://www.expresslanes.com/maps-api/infra-price-confirmed-all"
AWS_PROFILE = "nova-toll"  # matches scripts/smoke.sh
AWS_REGION = "us-east-1"
DB_IDENTIFIER = "nova-toll-db"  # infra/rds.tf identifier
CA_BUNDLE_PATH = REPO_ROOT / "infra" / "build" / "loader" / "rds-ca-bundle.pem"

OD_RE = re.compile(r"^od_(\d+)$")


def _fetch_live_snapshot() -> list[dict]:
    with urllib.request.urlopen(LIVE_URL, timeout=30) as resp:
        payload = json.load(resp)
    return payload["response"]


def _connect_as_master():
    # Lazy import: dev venv now has psycopg (added for this suite), but
    # lambdas/loader/tests/test_loader_handler.py asserts psycopg never lands
    # in sys.modules during a plain (non-`live`) pytest run, to catch
    # accidental top-level imports creeping into the production handler. A
    # module-level import here would poison that check for the whole session
    # -- pytest imports every test module at collection time, even ones later
    # deselected by marker.
    import psycopg

    session = boto3.Session(profile_name=AWS_PROFILE)
    instance = session.client("rds", region_name=AWS_REGION).describe_db_instances(
        DBInstanceIdentifier=DB_IDENTIFIER
    )["DBInstances"][0]
    secret_arn = instance["MasterUserSecret"]["SecretArn"]
    secret = json.loads(
        session.client("secretsmanager", region_name=AWS_REGION).get_secret_value(
            SecretId=secret_arn
        )["SecretString"]
    )  # managed secret only carries {"username", "password"} -- endpoint/dbname
    # come from the instance description, not the secret.
    return psycopg.connect(
        host=instance["Endpoint"]["Address"],
        port=instance["Endpoint"]["Port"],
        dbname=instance["DBName"],
        user=secret["username"],
        password=secret["password"],
        sslmode="verify-full",
        sslrootcert=str(CA_BUNDLE_PATH),
    )


@pytest.fixture(scope="module")
def live_snapshot() -> list[dict]:
    try:
        return _fetch_live_snapshot()
    except OSError as e:
        pytest.skip(f"Express Lanes live endpoint unreachable: {e}")


@pytest.fixture(scope="module")
def rds_i95_rows() -> list[tuple[int, str, Decimal]]:
    if not CA_BUNDLE_PATH.exists():
        pytest.skip(
            f"{CA_BUNDLE_PATH} missing -- run scripts/build_zips.sh at least once"
        )
    try:
        conn = _connect_as_master()
    except Exception as e:  # noqa: BLE001 -- any auth/network failure -> skip, not fail
        pytest.skip(f"could not connect to nova-toll-db as master: {e}")
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT ON (od_pair_id) od_pair_id, link_status, zone_toll_rate_usd
                FROM trip_pricing
                WHERE feed = 'i95'
                ORDER BY od_pair_id, interval_end_at DESC
                """
            )
            return cur.fetchall()
    finally:
        conn.close()


def test_live_snapshot_is_well_formed(live_snapshot):
    assert len(live_snapshot) > 300, (
        "unexpectedly small response -- feed may have changed shape"
    )
    for row in live_snapshot:
        assert OD_RE.match(row["od"]), f"unexpected od id format: {row['od']!r}"
        if row["price"] != "null":
            Decimal(row["price"])


def test_live_ids_cover_active_rds_od_pairs(live_snapshot, rds_i95_rows):
    live_ids = {
        int(m.group(1)) for row in live_snapshot if (m := OD_RE.match(row["od"]))
    }
    active_ids = {
        od_pair_id
        for od_pair_id, link_status, _rate in rds_i95_rows
        if link_status != "NO_DETERMINATION"
    }
    missing = active_ids - live_ids
    assert not missing, (
        f"{len(missing)} active od_pair_id(s) in trip_pricing are absent from the "
        f"live Express Lanes snapshot: {sorted(missing)[:20]}"
    )


def test_overlap_price_sanity(live_snapshot, rds_i95_rows):
    rds_ids = {od_pair_id for od_pair_id, _status, _rate in rds_i95_rows}
    for row in live_snapshot:
        m = OD_RE.match(row["od"])
        if not m or int(m.group(1)) not in rds_ids:
            continue
        if row["status"] == "open" and row["price"] != "null":
            assert Decimal(row["price"]) >= 0, f"negative live price for {row['od']}"
