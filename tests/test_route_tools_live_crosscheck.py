"""Cross-checks agent_tools/i66_route.py, i95_route.py and i495_route.py
against live RDS.

Walks every entry/exit pair each tool's own oracle subset through _lookup()
(route resolution only -- what these tools have always done, before pricing
existed) and verifies the returned leg(s) resolve to a row that has
actually been priced in trip_pricing_i66/trip_pricing_i95 -- not just
internally-consistent JSON (that's covered by agent_tools/tests/
test_i66_route.py, test_i95_route.py, test_i495_route.py). Also checks the
reverse direction: every priced key in those tables should be reachable
through _lookup(), which would otherwise indicate the oracles have drifted
from what's actually being billed.

i95_route.py and i495_route.py both draw from the same oracles/i95.json,
filtered to disjoint facilities (95/395 vs 495) -- neither tool resolves a
cross-corridor trip (docs/oracle-findings.md section 8), so every
od_pair_id that used to require a live-fallback/gap-placeholder (the 16 ids
1374-1389) has disappeared from both tools' producible sets entirely: those
ids only ever appeared on a cross-corridor leg.

Deliberately calls _lookup() rather than the decorated i66_route()/
i95_route()/i495_route() tools for this bulk walk: those now also price
every leg over RDS, and 96+307+78 oracle pairs would mean ~500 fresh
IAM-token psycopg connections in a loop against a db.t4g.micro (~85-
connection ceiling) for a question this file was never about ("is every
tool-producible route priced somewhere", not "what's today's rate"). A
small, separate set of live pricing assertions below exercises the actual
priced tool functions end-to-end instead.

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
import i495_route as i495_mod  # noqa: E402

pytestmark = pytest.mark.live

AWS_PROFILE = "nova-toll"  # matches scripts/smoke.sh
AWS_REGION = "us-east-1"
DB_IDENTIFIER = "nova-toll-db"  # infra/rds.tf identifier
CA_BUNDLE_PATH = REPO_ROOT / "infra" / "build" / "loader" / "rds-ca-bundle.pem"

# od_pair_ids priced in trip_pricing_i95, on each tool's own corridor, that
# oracles/i95.json does not enumerate under any within-facility label pair,
# so no oracle-driven tool can ever produce them. Verified live against RDS
# while writing this test (2026-07-26), filtered by corridor_name, not
# guessed:
# - i95: 1316 ("TURKEYCOCK to Old Courthouse Rd") has ~3,800 rows of
#   genuine SOUTHBOUND_OPEN/CLOSED history and neither ramp appears
#   anywhere in the oracle's node list -- a real gap, not a data artifact.
# - i495: 1000/1093 are permanently link_status NO_DETERMINATION/UNKNOWN
#   (dead links VDOT carries but never actually bills). The other 16
#   (1001-1008, 1039/1047/1054/1061/1067/1073/1078/1084) are real, actively
#   priced I-495 rows that exist *only* as one leg of a now-unsupported
#   cross-corridor oracle pair -- e.g. 1039 is "495 Express Lanes Start"'s
#   own leg-1 id when continuing into a cross-corridor composite trip,
#   distinct from 1040, the id the same physical on-ramp gets when its
#   *own* trip terminates at the I-495/I-95 junction (a within-495 trip
#   i495_route does produce). Both id families are real Transurban billing,
#   just for different products from the same on-ramp.
# Asserting the exact set (not a subset) means a new id joining either list
# fails the test instead of going unnoticed.
KNOWN_ORACLE_DRIFT_OD_PAIR_IDS_I95 = frozenset({1316})
KNOWN_ORACLE_DRIFT_OD_PAIR_IDS_I495 = frozenset(
    {
        1000,
        1001,
        1002,
        1003,
        1004,
        1005,
        1006,
        1007,
        1008,
        1039,
        1047,
        1054,
        1061,
        1067,
        1073,
        1078,
        1084,
        1093,
    }
)


def _describe_instance() -> dict:
    session = boto3.Session(profile_name=AWS_PROFILE)
    rds = session.client("rds", region_name=AWS_REGION)
    return rds.describe_db_instances(DBInstanceIdentifier=DB_IDENTIFIER)["DBInstances"][
        0
    ]


def _connect_as_pricing_reader(instance: dict):
    # Lazy import: see tests/test_expresslanes_crosscheck.py's identical
    # comment -- lambdas/loader/tests/test_loader_handler.py asserts psycopg
    # never lands in sys.modules during a plain (non-`live`) pytest run, and a
    # module-level import here would poison that check at collection time
    # even for a deselected test.
    import psycopg

    host = instance["Endpoint"]["Address"]
    port = instance["Endpoint"]["Port"]
    session = boto3.Session(profile_name=AWS_PROFILE)
    token = session.client("rds", region_name=AWS_REGION).generate_db_auth_token(
        DBHostname=host, Port=port, DBUsername="pricing_reader"
    )
    return psycopg.connect(
        host=host,
        port=port,
        dbname=instance["DBName"],
        user="pricing_reader",
        password=token,
        sslmode="verify-full",
        sslrootcert=str(CA_BUNDLE_PATH),
    )


@pytest.fixture(scope="module")
def rds_live_keys() -> tuple[set[tuple[int, int]], set[int], set[int]]:
    """(i66 zone pairs, i95-corridor od_pair_ids, i495-corridor od_pair_ids).

    Split by corridor_name at the query itself -- I-95-NB/I-95-SB vs
    I-495-NB/I-495-SB -- rather than post-hoc set arithmetic against each
    tool's producible ids, since an od_pair_id can be real and priced on
    its own corridor while still being unreachable via either tool's
    single-leg lookup (drift), and corridor is the one signal that
    unambiguously says which tool *should* be able to reach it.
    """
    if not CA_BUNDLE_PATH.exists():
        pytest.skip(
            f"{CA_BUNDLE_PATH} missing -- run scripts/build_zips.sh at least once"
        )
    try:
        conn = _connect_as_pricing_reader(_describe_instance())
    except Exception as e:  # noqa: BLE001 -- any auth/network failure -> skip, not fail
        pytest.skip(f"could not connect to nova-toll-db as pricing_reader: {e}")
    try:
        with conn.cursor() as cur:
            # One bulk query per table, in-memory set comparison against
            # everything _lookup() can produce -- 96+307+78 individual round
            # trips would be needlessly slow and WAF/connection-limit-fragile
            # for the same answer.
            cur.execute(
                "SELECT DISTINCT start_zone_id, end_zone_id FROM trip_pricing_i66"
            )
            i66_zone_pairs = {(row[0], row[1]) for row in cur.fetchall()}
            cur.execute(
                "SELECT DISTINCT od_pair_id, corridor_name FROM trip_pricing_i95"
            )
            rows = cur.fetchall()
            i95_od_pair_ids = {
                od for od, corridor in rows if corridor in ("I-95-NB", "I-95-SB")
            }
            i495_od_pair_ids = {
                od for od, corridor in rows if corridor in ("I-495-NB", "I-495-SB")
            }
    finally:
        conn.close()
    return i66_zone_pairs, i95_od_pair_ids, i495_od_pair_ids


@pytest.fixture
def live_pricing_env(monkeypatch):
    """Points agent_tools/*.py's _env_connect() at live RDS as pricing_reader.

    Only used by the small end-to-end pricing tests below -- the bulk
    _lookup()-driven crosscheck above never touches the DB through the tools
    at all, by design (see module docstring).
    """
    if not CA_BUNDLE_PATH.exists():
        pytest.skip(
            f"{CA_BUNDLE_PATH} missing -- run scripts/build_zips.sh at least once"
        )
    try:
        instance = _describe_instance()
    except Exception as e:  # noqa: BLE001 -- any auth/network failure -> skip, not fail
        pytest.skip(f"could not describe nova-toll-db: {e}")
    monkeypatch.setenv("DB_HOST", instance["Endpoint"]["Address"])
    monkeypatch.setenv("DB_PORT", str(instance["Endpoint"]["Port"]))
    monkeypatch.setenv("DB_NAME", instance["DBName"])
    monkeypatch.setenv("DB_USER", "pricing_reader")
    monkeypatch.setenv("DB_CA_BUNDLE_PATH", str(CA_BUNDLE_PATH))
    # generate_db_auth_token inside _env_connect() uses the default boto3
    # session/credential chain, not a profile kwarg -- point it at the same
    # profile the rest of this file uses explicitly.
    monkeypatch.setenv("AWS_PROFILE", AWS_PROFILE)
    monkeypatch.setenv("AWS_DEFAULT_REGION", AWS_REGION)


def _i66_tool_zone_pairs() -> set[tuple[int, int]]:
    """Every (start_zone_id, end_zone_id) i66_route's route resolution can
    ever produce, driven by feeding each oracle pair's own labels through
    _lookup() (not by reading start_zone/end_zone off the oracle directly,
    and not through the pricing-aware i66_route() tool -- see module
    docstring)."""
    zone_pairs = set()
    for p in i66_mod._PAIRS:
        origin = i66_mod._NODES[p["entry"]]["label"]
        destination = i66_mod._NODES[p["exit"]]["label"]
        result = i66_mod._lookup(origin, destination)
        assert "error" not in result, (
            f"i66_route._lookup({origin!r}, {destination!r}) unexpectedly errored: {result}"
        )
        leg = result["legs"][0]
        zone_pairs.add((leg["start_zone_id"], leg["end_zone_id"]))
    return zone_pairs


def _i95_tool_od_pair_ids() -> set[int]:
    """Every od_pair_id i95_route's route resolution can ever produce, driven
    by feeding each oracle pair's own labels through _lookup()."""
    od_pair_ids = set()
    for p in i95_mod._PAIRS:
        origin = i95_mod._NODES[p["entry"]]["label"]
        destination = i95_mod._NODES[p["exit"]]["label"]
        result = i95_mod._lookup(origin, destination)
        assert "error" not in result, (
            f"i95_route._lookup({origin!r}, {destination!r}) unexpectedly errored: {result}"
        )
        od_pair_ids.update(leg["od_pair_id"] for leg in result["legs"])
    return od_pair_ids


def _i495_tool_od_pair_ids() -> set[int]:
    """Every od_pair_id i495_route's route resolution can ever produce, driven
    by feeding each oracle pair's own labels through _lookup()."""
    od_pair_ids = set()
    for p in i495_mod._PAIRS:
        origin = i495_mod._NODES[p["entry"]]["label"]
        destination = i495_mod._NODES[p["exit"]]["label"]
        result = i495_mod._lookup(origin, destination)
        assert "error" not in result, (
            f"i495_route._lookup({origin!r}, {destination!r}) unexpectedly errored: {result}"
        )
        od_pair_ids.update(leg["od_pair_id"] for leg in result["legs"])
    return od_pair_ids


def test_i66_every_tool_route_is_priced(rds_live_keys):
    i66_zone_pairs, _, _ = rds_live_keys
    missing = _i66_tool_zone_pairs() - i66_zone_pairs
    assert not missing, (
        f"{len(missing)} zone pair(s) returned by i66_route have zero rows "
        f"in trip_pricing_i66: {sorted(missing)}"
    )


def test_i95_every_tool_route_is_priced(rds_live_keys):
    # Unlike before the i495 split, this is now an exact-match assertion --
    # every od_pair_id i95_route can produce is within-95/395, and the
    # 16-id VDOT gap only ever occurred on a now-unsupported cross-corridor
    # leg, so there's no longer a known exception to carve out.
    _, i95_od_pair_ids, _ = rds_live_keys
    missing = _i95_tool_od_pair_ids() - i95_od_pair_ids
    assert not missing, (
        f"{len(missing)} od_pair_id(s) returned by i95_route have zero rows "
        f"in trip_pricing_i95: {sorted(missing)}"
    )


def test_i495_every_tool_route_is_priced(rds_live_keys):
    _, _, i495_od_pair_ids = rds_live_keys
    missing = _i495_tool_od_pair_ids() - i495_od_pair_ids
    assert not missing, (
        f"{len(missing)} od_pair_id(s) returned by i495_route have zero rows "
        f"in trip_pricing_i95: {sorted(missing)}"
    )


def test_i66_no_priced_zone_pair_is_unreachable(rds_live_keys):
    i66_zone_pairs, _, _ = rds_live_keys
    drift = i66_zone_pairs - _i66_tool_zone_pairs()
    assert not drift, (
        f"{len(drift)} zone pair(s) priced in trip_pricing_i66 aren't "
        f"reachable via i66_route -- oracle drift: {sorted(drift)}"
    )


def test_i95_no_priced_od_pair_is_unreachable_except_known_drift(rds_live_keys):
    _, i95_od_pair_ids, _ = rds_live_keys
    drift = i95_od_pair_ids - _i95_tool_od_pair_ids()
    assert drift == KNOWN_ORACLE_DRIFT_OD_PAIR_IDS_I95, (
        f"od_pair_id(s) priced in trip_pricing_i95 but unreachable via "
        f"i95_route changed from the known oracle-drift set: got "
        f"{sorted(drift)}, expected {sorted(KNOWN_ORACLE_DRIFT_OD_PAIR_IDS_I95)}"
    )


def test_i495_no_priced_od_pair_is_unreachable_except_known_drift(rds_live_keys):
    _, _, i495_od_pair_ids = rds_live_keys
    drift = i495_od_pair_ids - _i495_tool_od_pair_ids()
    assert drift == KNOWN_ORACLE_DRIFT_OD_PAIR_IDS_I495, (
        f"od_pair_id(s) priced in trip_pricing_i95 but unreachable via "
        f"i495_route changed from the known oracle-drift set: got "
        f"{sorted(drift)}, expected {sorted(KNOWN_ORACLE_DRIFT_OD_PAIR_IDS_I495)}"
    )


def test_i66_route_prices_a_known_pair_live(live_pricing_env):
    result = i66_mod.i66_route("I-66 West", "Westmoreland St")
    assert "error" not in result, result
    assert float(result["total_usd"]) >= 0


def test_i95_route_prices_a_known_pair_live(live_pricing_env):
    # Northbound: verified reliably open throughout this session, unlike
    # the southbound direction (see test_i95_route_reports_closed_lane_
    # clearly below, the direct live regression check for the original bug
    # report).
    result = i95_mod.i95_route("US-1", "I-395 Near Edsall Road")
    assert "error" not in result, result
    assert float(result["total_usd"]) >= 0


def test_i95_route_reports_closed_lane_clearly(live_pricing_env):
    # od_pair_id 1151 (I-395 Near Edsall Road -> US-1, southbound) is the
    # exact live repro for the original bug report: this corridor's
    # southbound direction has been consistently CLOSED throughout this
    # session. A closed lane must be a clear, named error, never a priced
    # result and never a bare KeyError/connection failure.
    result = i95_mod.i95_route("I-395 Near Edsall Road", "US-1")
    assert "error" in result, result
    assert "1151" in result["error"]


def test_i495_route_prices_a_known_pair_live(live_pricing_env):
    result = i495_mod.i495_route(
        "Route 267", "495 Express Lanes End/George Wash. Mem. Pkwy."
    )
    assert "error" not in result, result
    assert float(result["total_usd"]) >= 0
