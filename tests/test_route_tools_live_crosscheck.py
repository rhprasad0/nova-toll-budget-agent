"""Cross-checks agent_tools/i66_route.py and i95_route.py against live RDS.

Walks every entry/exit pair in oracles/i66.json and oracles/i95.json, calls
the actual tool (not the raw oracle data) for each, and verifies the
returned leg(s) resolve to a row that has actually been priced in
trip_pricing_i66/trip_pricing_i95 -- not just internally-consistent JSON
(that's covered by agent_tools/tests/test_i66_route.py and test_i95_route.py).
Also checks the reverse direction: every priced key in those tables should be
reachable through the tools, which would otherwise indicate the oracles have
drifted from what's actually being billed.

Hits live RDS -- deliberately marked `live` and excluded from the default
`pytest` run (see pyproject.toml addopts), so CI never depends on it being
reachable. Run explicitly:

    uv run pytest -m live tests/test_route_tools_live_crosscheck.py -v
"""

import sys

import boto3
import pytest

from conftest import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT / "agent_tools"))

import i66_route as i66_mod  # noqa: E402
import i95_route as i95_mod  # noqa: E402

pytestmark = pytest.mark.live

AWS_PROFILE = "nova-toll"  # matches scripts/smoke.sh
AWS_REGION = "us-east-1"
DB_IDENTIFIER = "nova-toll-db"  # infra/rds.tf identifier
CA_BUNDLE_PATH = REPO_ROOT / "infra" / "build" / "loader" / "rds-ca-bundle.pem"

# docs/oracle-findings.md section 2: VDOT's feed has never published these 16
# od_pair_ids, even though Transurban's own network (this oracle) bills them.
# Verified directly against live RDS while writing this test, not just copied
# from the doc: trip_pricing_i95 holds zero rows for exactly this set.
KNOWN_UNPRICED_OD_PAIR_IDS = frozenset(range(1374, 1390))

# od_pair_ids priced in trip_pricing_i95 that oracles/i95.json does not
# enumerate under any label pair, so no oracle-driven tool can ever produce
# them -- discovered while writing this test (2026-07-25), not yet reflected
# in docs/oracle-findings.md. 1000 and 1093 are permanently link_status
# NO_DETERMINATION/UNKNOWN (dead links); 1316 ("TURKEYCOCK to Old Courthouse
# Rd") has ~3,800 rows of genuine SOUTHBOUND_OPEN/CLOSED history and neither
# ramp appears anywhere in the oracle's node list -- a real gap, not a data
# artifact. Asserting the exact set (not a subset) means a fourth id joining
# this list fails the test instead of going unnoticed.
KNOWN_ORACLE_DRIFT_OD_PAIR_IDS = frozenset({1000, 1093, 1316})


def _connect_as_loader_writer():
    # Lazy import: see tests/test_expresslanes_crosscheck.py's identical
    # comment -- lambdas/loader/tests/test_loader_handler.py asserts psycopg
    # never lands in sys.modules during a plain (non-`live`) pytest run, and a
    # module-level import here would poison that check at collection time
    # even for a deselected test.
    import psycopg

    session = boto3.Session(profile_name=AWS_PROFILE)
    rds = session.client("rds", region_name=AWS_REGION)
    instance = rds.describe_db_instances(DBInstanceIdentifier=DB_IDENTIFIER)[
        "DBInstances"
    ][0]
    host = instance["Endpoint"]["Address"]
    port = instance["Endpoint"]["Port"]
    # loader_writer (SELECT/INSERT/UPDATE on just the two trip_pricing tables,
    # not superuser -- db/roles.sql) is least-privilege and sufficient for a
    # read-only crosscheck. agent_readonly was dropped along with the agent
    # tool surface (db/drop_agent_surface.sql); master would work too but is
    # unnecessary extra privilege for a SELECT. IAM auth needs no secret
    # fetch, just a locally signed token.
    token = rds.generate_db_auth_token(
        DBHostname=host, Port=port, DBUsername="loader_writer"
    )
    return psycopg.connect(
        host=host,
        port=port,
        dbname=instance["DBName"],
        user="loader_writer",
        password=token,
        sslmode="verify-full",
        sslrootcert=str(CA_BUNDLE_PATH),
    )


@pytest.fixture(scope="module")
def rds_live_keys() -> tuple[set[tuple[int, int]], set[int]]:
    if not CA_BUNDLE_PATH.exists():
        pytest.skip(
            f"{CA_BUNDLE_PATH} missing -- run scripts/build_zips.sh at least once"
        )
    try:
        conn = _connect_as_loader_writer()
    except Exception as e:  # noqa: BLE001 -- any auth/network failure -> skip, not fail
        pytest.skip(f"could not connect to nova-toll-db as loader_writer: {e}")
    try:
        with conn.cursor() as cur:
            # One bulk query per table, in-memory set comparison against
            # everything the tools can produce -- 96+685 individual round
            # trips would be needlessly slow and WAF/connection-limit-fragile
            # for the same answer.
            cur.execute(
                "SELECT DISTINCT start_zone_id, end_zone_id FROM trip_pricing_i66"
            )
            i66_zone_pairs = {(row[0], row[1]) for row in cur.fetchall()}
            cur.execute("SELECT DISTINCT od_pair_id FROM trip_pricing_i95")
            i95_od_pair_ids = {row[0] for row in cur.fetchall()}
    finally:
        conn.close()
    return i66_zone_pairs, i95_od_pair_ids


def _i66_tool_zone_pairs() -> set[tuple[int, int]]:
    """Every (start_zone_id, end_zone_id) i66_route can ever return, driven
    by feeding each oracle pair's own labels through the tool (not by reading
    start_zone/end_zone off the oracle directly) -- this is what exercises
    the tool, not just the oracle file."""
    zone_pairs = set()
    for p in i66_mod._PAIRS:
        origin = i66_mod._NODES[p["entry"]]["label"]
        destination = i66_mod._NODES[p["exit"]]["label"]
        result = i66_mod.i66_route(origin, destination)
        assert "error" not in result, (
            f"i66_route({origin!r}, {destination!r}) unexpectedly errored: {result}"
        )
        leg = result["legs"][0]
        zone_pairs.add((leg["start_zone_id"], leg["end_zone_id"]))
    return zone_pairs


def _i95_tool_od_pair_ids() -> set[int]:
    """Every od_pair_id i95_route can ever return, driven by feeding each
    oracle pair's own labels through the tool."""
    od_pair_ids = set()
    for p in i95_mod._PAIRS:
        origin = i95_mod._NODES[p["entry"]]["label"]
        destination = i95_mod._NODES[p["exit"]]["label"]
        result = i95_mod.i95_route(origin, destination)
        assert "error" not in result, (
            f"i95_route({origin!r}, {destination!r}) unexpectedly errored: {result}"
        )
        od_pair_ids.update(leg["od_pair_id"] for leg in result["legs"])
    return od_pair_ids


def test_i66_every_tool_route_is_priced(rds_live_keys):
    i66_zone_pairs, _ = rds_live_keys
    missing = _i66_tool_zone_pairs() - i66_zone_pairs
    assert not missing, (
        f"{len(missing)} zone pair(s) returned by i66_route have zero rows "
        f"in trip_pricing_i66: {sorted(missing)}"
    )


def test_i95_every_tool_route_is_priced_except_known_vdot_gap(rds_live_keys):
    _, i95_od_pair_ids = rds_live_keys
    missing = _i95_tool_od_pair_ids() - i95_od_pair_ids
    assert missing == KNOWN_UNPRICED_OD_PAIR_IDS, (
        f"od_pair_id(s) returned by i95_route with zero trip_pricing_i95 rows "
        f"changed from the known VDOT gap: got {sorted(missing)}, expected "
        f"{sorted(KNOWN_UNPRICED_OD_PAIR_IDS)}"
    )


def test_i66_no_priced_zone_pair_is_unreachable(rds_live_keys):
    i66_zone_pairs, _ = rds_live_keys
    drift = i66_zone_pairs - _i66_tool_zone_pairs()
    assert not drift, (
        f"{len(drift)} zone pair(s) priced in trip_pricing_i66 aren't "
        f"reachable via i66_route -- oracle drift: {sorted(drift)}"
    )


def test_i95_no_priced_od_pair_is_unreachable_except_known_drift(rds_live_keys):
    _, i95_od_pair_ids = rds_live_keys
    drift = i95_od_pair_ids - _i95_tool_od_pair_ids()
    assert drift == KNOWN_ORACLE_DRIFT_OD_PAIR_IDS, (
        f"od_pair_id(s) priced in trip_pricing_i95 but unreachable via "
        f"i95_route changed from the known oracle-drift set: got "
        f"{sorted(drift)}, expected {sorted(KNOWN_ORACLE_DRIFT_OD_PAIR_IDS)}"
    )
