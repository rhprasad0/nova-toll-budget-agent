"""i495_route: resolve a human trip between two 495 Express Lanes ramps to
its route and its price, as of a given time.

Route resolution is a pure route-map lookup against the committed
oracles/i95.json -- the same shared source i95_route.py loads, filtered
here to the 78 of 685 published pairs that start and end on the 495
Express Lanes (a node's own "path" field starts with "495"). "Where an
oracle exists, prefer reading it over re-deriving it" (docs/oracle-findings.md
section 3), and this tool never chains a 495 leg onto a 95/395 leg to
synthesize a cross-corridor trip -- expresslanes.com itself markets the 495
Express Lanes as a separate product from the 95/395 Express Lanes, billed
as a separate toll with an untolled general-purpose-lanes gap between them
(docs/oracle-findings.md section 8). A caller wanting a full cross-corridor
journey makes two calls, one to this tool and one to i95_route -- neither
tool computes or claims a combined price.

Pricing is a second stage, run only after a successful route resolution: an
omitted at_time reads the current VDOT view, while an explicit at_time reads
trip_pricing_i95 history. Neither is "the price this instant"; see the
at_time Args entry below and docs/oracle-findings.md section 7 for why. Unlike
i95_route, no availability gate is applied here: verified live against RDS,
100% of I-495-NB/I-495-SB history reports link_status NO_DETERMINATION or
UNKNOWN, never a real "*_OPEN" value, despite carrying real fluctuating
nonzero rates -- VDOT simply never publishes a meaningful open/closed
signal for the 495 Express Lanes (they aren't reversible, unlike the
95/395 segment i95_route gates). A missing price is a hard error for the
whole call; there is no live-fallback source for this table.

Unsure of the exact interchange label? Call find_toll_locations first --
it turns a vague location or a misspelling into the exact label string
this tool expects, across all corridors, without a failing call here.

See docs/oracle-tools-spec.md for the full contract and known limitations.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

from strands import tool

# agent_tools/ has no __init__.py (flat siblings, like i66_route.py/
# i95_route.py) and this module is imported both as a flat top-level module
# (agent_tools/tests/conftest.py's sys.path insert) and as agent_tools.
# i495_route (dotted, e.g. a live smoke check run from the repo root) --
# neither form puts agent_tools/ itself on sys.path, so a plain
# "import _oracle_route" would fail under the dotted form. Ensuring our own
# directory is on sys.path here works under both.
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


def _is_495(node_id: str) -> bool:
    return _ALL_NODES[node_id]["path"].startswith("495")


# Every within-495 pair is single-leg (verified: 0/78 have more than one
# od_pair_id) -- there's no composite-trip concept in this tool at all.
_PAIRS = [p for p in _ALL_PAIRS if _is_495(p["entry"]) and _is_495(p["exit"])]
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
        oracle_name="i495",
        build_legs=lambda p: [{"od_pair_id": p["ods"][0]}],
    )


_CURRENT_I495_PRICE_SQL = """
SELECT od_pair_id, corridor_name, zone_toll_rate_usd, interval_end_at,
       calculated_at
FROM current_trip_pricing_i95
WHERE od_pair_id = %(od_pair_id)s
"""

_I495_PRICE_SQL = """
SELECT od_pair_id, corridor_name, zone_toll_rate_usd, interval_end_at,
       calculated_at
FROM trip_pricing_i95
WHERE od_pair_id = %(od_pair_id)s
  AND interval_end_at <= %(at_time)s
ORDER BY interval_end_at DESC
LIMIT 1
"""


def _price_i495_leg(cur, leg_key: dict, at_time: datetime | None) -> dict:
    """Current VDOT price, or VDOT history at an explicit time.

    No availability gate -- see the module docstring for why I-495-NB/
    I-495-SB never need one. A missing row is a hard error for the whole
    call; there is no live-fallback source for this table.
    """
    od_pair_id = leg_key["od_pair_id"]
    cur.execute(
        _I495_PRICE_SQL if at_time is not None else _CURRENT_I495_PRICE_SQL,
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
    _, corridor_name, rate, interval_end_at, calculated_at = row
    return {
        "od_pair_id": od_pair_id,
        "price_usd": str(rate),
        "corridor_name": corridor_name,
        "priced_as_of": interval_end_at.isoformat(),
        "observed_at": calculated_at.isoformat(),
    }


@tool
def i495_route(origin: str, destination: str, at_time: str | None = None) -> dict:
    """Resolve a trip on Transurban's 495 Express Lanes network to its route and price.

    Looks up origin/destination against oracles/i95.json's within-495
    published entry/exit trips -- a flat, direct lookup, never multi-hop
    routing. A trip that crosses into the 95/395 Express Lanes is out of
    scope for this tool (see i95_route for that facility); this tool never
    synthesizes a cross-corridor combined price. The resolved leg is then
    priced against VDOT data over RDS.

    Args:
        origin: Ramp label (e.g. 'Route 267'), case-insensitive, or the
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
        destination on the 95/395 side, which this tool never resolves),
        or a pricing/at_time failure, so the caller can self-correct where
        possible; valid_options is empty for a pricing miss or a bad
        at_time, since retrying the same inputs won't fix either.
    """
    return _oracle_route.run(
        "i495_route",
        origin,
        destination,
        at_time,
        lookup_fn=_lookup,
        connect=_env_connect,
        price_fn=_price_i495_leg,
    )
