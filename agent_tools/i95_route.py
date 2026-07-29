"""i95_route: resolve a human trip between two 95/395 Express Lanes ramps
to its route and its price, as of a given time.

Route resolution is a pure route-map lookup against the committed
oracles/i95.json -- the same shared source i495_route.py loads, filtered
here to the 307 of 685 published pairs that start and end on the 95/395
Express Lanes (a node's own "path" field does not start with "495"). VDOT
doesn't split 395 into its own corridor_name -- I-95-NB/SB covers both,
matching expresslanes.com's own "95 Express Lanes" facility bundling 395
too. "Where an oracle exists, prefer reading it over re-deriving it"
(docs/oracle-findings.md section 3), and this tool never chains a 95/395
leg onto a 495 leg to synthesize a cross-corridor trip -- see i495_route's
module docstring and docs/oracle-findings.md section 8 for why: they're
billed as genuinely separate tolled facilities with an untolled
general-purpose-lanes gap between them, so a caller wanting a full
cross-corridor journey makes two calls, one to each tool.

Pricing is a second stage, run only after a successful route resolution: an
omitted at_time reads the current VDOT view, while an explicit at_time reads
trip_pricing_i95 history. Neither is "the price this instant"; see the
at_time Args entry below and docs/oracle-findings.md section 7 for why. A row only
counts as priceable if its lane is actually open: link_status must exactly
match its own corridor's "{DIRECTION}_OPEN" (CLOSED/NO_DETERMINATION/
*_CLOSING/*_OPENING all fail) -- docs/poller-spec.md's "Rate/status
independence" warning: rows can be CLOSED with a stale nonzero rate, and
availability lives in link_status, never in rate > 0. A missing or
unavailable price is a hard error for the whole call; there is no
live-fallback source for this table (that fallback existed solely to cover
the 16 od_pair_ids that only ever appeared on a now-unsupported
cross-corridor leg -- see i495_route.py and docs/oracle-findings.md
section 8).

The calling agent matches vague locations to this tool's committed oracle
labels before calling it.

See docs/oracle-tools-spec.md for the full contract and known limitations.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

from strands import tool

# agent_tools/ has no __init__.py (flat siblings) and this module is
# imported both as a flat top-level module (agent_tools/tests/conftest.py's
# sys.path insert) and as agent_tools.i95_route (dotted) -- neither form
# puts agent_tools/ itself on sys.path, so a plain "import _oracle_route"
# would fail under the dotted form. Ensuring our own directory is on
# sys.path here works under both.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _oracle_route

# ponytail: path assumes agent_tools/ sits one level under the repo root next
# to oracles/, matching its current committed location. If this ever ships in
# a deployment zip, the build step must land oracles/i95.json at this same
# relative path, or this constant needs to change with it.
_ORACLE_PATH = Path(__file__).resolve().parent.parent / "oracles" / "i95.json"
_ALL_ORACLE = json.loads(_ORACLE_PATH.read_text())
_ALL_NODES: dict = _ALL_ORACLE["nodes"]
_ALL_PAIRS: list = _ALL_ORACLE["pairs"]


def _is_95_395(node_id: str) -> bool:
    return not _ALL_NODES[node_id]["path"].startswith("495")


# Every within-95/395 pair is single-leg (verified: 0/307 have more than
# one od_pair_id) -- there's no composite-trip concept in this tool at all.
_PAIRS = [p for p in _ALL_PAIRS if _is_95_395(p["entry"]) and _is_95_395(p["exit"])]
_NODES = {nid: _ALL_NODES[nid] for p in _PAIRS for nid in (p["entry"], p["exit"])}

_LABEL_INDEX = _oracle_route.label_index(_NODES)

# Local alias so tests can monkeypatch the connection by name on this module
# (the established convention here and in i66_route.py), even though the
# implementation lives in the shared _oracle_route module.
_env_connect = _oracle_route.env_connect


def _lookup(origin: str, destination: str) -> dict:
    return _oracle_route.lookup(
        origin,
        destination,
        nodes=_NODES,
        pairs=_PAIRS,
        label_idx=_LABEL_INDEX,
        oracle_name="i95",
        build_legs=lambda p: [{"od_pair_id": p["ods"][0]}],
    )


# Verified live against RDS (2026-07-26): these are the only corridor_name
# values seen on a within-95/395 od_pair_id, and the only ones for which
# link_status carries a real open/closed signal.
_REQUIRED_LINK_STATUS = {
    "I-95-NB": "NORTHBOUND_OPEN",
    "I-95-SB": "SOUTHBOUND_OPEN",
}

_CURRENT_I95_PRICE_SQL = """
SELECT od_pair_id, corridor_name, zone_toll_rate_usd, interval_end_at,
       calculated_at, link_status
FROM current_trip_pricing_i95
WHERE od_pair_id = %(od_pair_id)s
"""

_I95_PRICE_SQL = """
SELECT od_pair_id, corridor_name, zone_toll_rate_usd, interval_end_at,
       calculated_at, link_status
FROM trip_pricing_i95
WHERE od_pair_id = %(od_pair_id)s
  AND interval_end_at <= %(at_time)s
ORDER BY interval_end_at DESC
LIMIT 1
"""


def _price_i95_leg(cur, leg_key: dict, at_time: datetime | None) -> dict:
    """Current VDOT price, or VDOT history at an explicit time.

    Raises PricingError if there's no row at all, if corridor_name isn't
    one of the two this tool's oracle filter should ever produce (schema
    drift), or if the row's lane isn't open for its own corridor/direction.
    """
    od_pair_id = leg_key["od_pair_id"]
    cur.execute(
        _I95_PRICE_SQL if at_time is not None else _CURRENT_I95_PRICE_SQL,
        {
            "od_pair_id": od_pair_id,
            **({"at_time": at_time} if at_time is not None else {}),
        },
    )
    row = cur.fetchone()
    if row is None:
        source = (
            f"at or before {at_time.isoformat()} in trip_pricing_i95"
            if at_time is not None
            else "in current_trip_pricing_i95"
        )
        raise _oracle_route.PricingError(
            f"no price found for od_pair_id {od_pair_id} {source}"
        )

    _, corridor_name, rate, interval_end_at, calculated_at, link_status = row
    required_status = _REQUIRED_LINK_STATUS.get(corridor_name)
    if required_status is None:
        raise _oracle_route.PricingError(
            f"unrecognized corridor_name {corridor_name!r} for od_pair_id {od_pair_id}"
        )
    if link_status != required_status:
        raise _oracle_route.PricingError(
            f"od_pair_id {od_pair_id} is not currently available: "
            f"link_status={link_status!r} for corridor {corridor_name!r} "
            f"(requires {required_status!r})"
        )

    return {
        "od_pair_id": od_pair_id,
        "price_usd": str(rate),
        "corridor_name": corridor_name,
        "priced_as_of": interval_end_at.isoformat(),
        "observed_at": calculated_at.isoformat(),
    }


@tool
def i95_route(origin: str, destination: str, at_time: str | None = None) -> dict:
    """Resolve a trip on Transurban's 95/395 Express Lanes network to its route and price.

    Looks up origin/destination against oracles/i95.json's within-95/395
    published entry/exit trips -- a flat, direct lookup, never multi-hop
    routing. A trip that crosses into the 495 Express Lanes is out of scope
    for this tool (see i495_route for that facility); this tool never
    synthesizes a cross-corridor combined price. The resolved leg is then
    priced against VDOT data over RDS -- a row only counts if its
    lane is actually open (link_status), never just because it has a rate.

    Args:
        origin: Ramp label (e.g. 'US-1'), case-insensitive, or the
            oracle's raw node id as a fallback.
        destination: Same rules as origin.
        at_time: ISO-8601 timestamp (e.g. '2026-07-26T14:32:00' or with an
            explicit UTC offset); a value with no offset is assumed
            America/New_York. Defaults to now (America/New_York) if omitted.
            If omitted, the current VDOT view is used; if supplied, the price
            is the most recently *published* row at or before this time.
            Neither is "the price this instant" -- VDOT's own
            feed trails real-time by roughly 10-20 minutes
            (docs/oracle-findings.md section 7), and this tool reports that
            lag honestly via priced_as_of and observed_at rather than
            papering over it.

    Returns:
        dict: On success, {"origin", "destination",
        "direction": "Northbound"|"Southbound", "entry": {"node_id", "label"},
        "exit": {"node_id", "label"}, "at_time": str (the resolved,
        ISO-8601 time actually used), "legs": [{"od_pair_id", "price_usd":
        str, "corridor_name", "priced_as_of": str, "observed_at": str}], "total_usd": str} --
        legs has exactly one entry. price_usd/total_usd are decimal strings
        (never float). observed_at is VDOT's source-calculated timestamp for
        the returned fare. On failure, {"error": str, "valid_options":
        [str, ...]} -- the full ramp label list on an unknown identifier,
        the reachable destination labels on a known origin with no direct
        trip to the given destination (including a cross-corridor
        destination on the 495 side, which this tool never resolves), or a
        pricing/at_time failure, so the caller can self-correct where
        possible; valid_options is empty for a pricing miss or a bad
        at_time, since retrying the same inputs won't fix either. A
        pricing failure includes a leg whose only known row is
        closed/unavailable for its lane -- the error message names the
        corridor and link_status, distinguishing "found but closed" from a
        true data miss.
    """
    return _oracle_route.run(
        "i95_route",
        origin,
        destination,
        at_time,
        lookup_fn=_lookup,
        connect=_env_connect,
        price_fn=_price_i95_leg,
    )
