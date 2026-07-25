"""i95_route: resolve a human trip between two 95/395/495 Express Lanes ramps
to its Transurban price-lookup key(s).

Pure route-map lookup against the committed oracles/i95.json -- no DB, no
network, no multi-hop chaining. Transurban's own published network already
enumerates every valid direction+entry+exit combination directly (685 pairs
over 107 ramps), so this is a single flat lookup, never pathfinding: "where
an oracle exists, prefer reading it over re-deriving it"
(docs/oracle-findings.md section 3). A cross-corridor trip is billed as two
whole separate tolls, never a summed sub-segment -- the oracle already
flattens that into one pair carrying two od_pair_ids in billed order, so this
tool never chains two separate pairs together to synthesize a trip. Price
itself is out of scope here; the legs this returns are the exact
od_pair_id(s) into trip_pricing_i95, for a separate, future pricing tool to
query.

Known limitation: 16 od_pair_ids (1374-1389) appear in this oracle but have
never been priced by VDOT's feed (docs/oracle-findings.md section 2) -- a
returned leg means "this trip exists and this is its key", never "a price
exists for it". See docs/oracle-tools-spec.md for the full contract.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from strands import tool

logger = logging.getLogger(__name__)

# ponytail: path assumes agent_tools/ sits one level under the repo root next
# to oracles/, matching its current committed location. If this ever ships in
# a deployment zip, the build step must land oracles/i95.json at this same
# relative path, or this constant needs to change with it.
_ORACLE_PATH = Path(__file__).resolve().parent.parent / "oracles" / "i95.json"
_ORACLE = json.loads(_ORACLE_PATH.read_text())
_NODES: dict = _ORACLE["nodes"]
_PAIRS: list = _ORACLE["pairs"]


def _label_index(nodes: dict) -> dict[str, list[str]]:
    idx: dict[str, list[str]] = {}
    for node_id, node in nodes.items():
        idx.setdefault(node["label"].casefold(), []).append(node_id)
    return idx


_LABEL_INDEX = _label_index(_NODES)


def _resolve(query: str) -> list[str]:
    """Candidate node ids for a caller-supplied label (case-insensitive) or raw node id."""
    if query in _NODES:
        return [query]
    return _LABEL_INDEX.get(query.casefold(), [])


# ponytail: resolution/matching logic duplicated with i66_route.py; extract
# if a third oracle-backed tool needs the same shape.
def _lookup(origin: str, destination: str) -> dict:
    # Some ramps are entry-only or exit-only (e.g. the 495 Express Lanes End
    # ramp can never be an origin), so the two suggestion lists are
    # role-filtered -- suggesting a label that can never fill the role being
    # asked about would guarantee the caller's next call also fails.
    origin_labels = sorted({_NODES[p["entry"]]["label"] for p in _PAIRS})
    destination_labels = sorted({_NODES[p["exit"]]["label"] for p in _PAIRS})

    origin_ids = _resolve(origin)
    if not origin_ids:
        return {
            "error": f"unknown origin {origin!r}: no matching label or node id in the i95 oracle",
            "valid_options": origin_labels,
        }
    destination_ids = _resolve(destination)
    if not destination_ids:
        return {
            "error": f"unknown destination {destination!r}: no matching label or node id in the i95 oracle",
            "valid_options": destination_labels,
        }

    matches = [
        p for p in _PAIRS if p["entry"] in origin_ids and p["exit"] in destination_ids
    ]

    if not matches:
        reachable = sorted(
            {_NODES[p["exit"]]["label"] for p in _PAIRS if p["entry"] in origin_ids}
        )
        return {
            "error": f"no direct trip from {origin!r} to {destination!r} in the i95 oracle",
            "valid_options": reachable,
        }

    if len(matches) > 1:
        # Unreachable today -- verified 685/685 pairs unique on (entry, exit)
        # and on (entry_label, exit_label). Guarded for when
        # scripts/fetch_i95_oracle.py next refreshes oracles/i95.json and
        # that invariant might not hold.
        return {
            "error": f"ambiguous trip: {origin!r} to {destination!r} matches {len(matches)} entry/exit combinations",
            "valid_options": sorted(
                {p["entry"] for p in matches} | {p["exit"] for p in matches}
            ),
        }

    p = matches[0]
    return {
        "origin": origin,
        "destination": destination,
        # p["direction"] is the only reliable direction source -- node ids
        # are suffixed NO/ND/SO/SD but that suffix does not reliably match
        # the node's own "direction" field, so it must never be inferred
        # from the id.
        "direction": p["direction"],
        "entry": {"node_id": p["entry"], "label": _NODES[p["entry"]]["label"]},
        "exit": {"node_id": p["exit"], "label": _NODES[p["exit"]]["label"]},
        # Order preserved from the oracle's own "ods" list: a two-entry leg
        # list is a cross-corridor trip billed as two sequential whole tolls,
        # never a summed sub-segment.
        "legs": [{"od_pair_id": od} for od in p["ods"]],
    }


@tool
def i95_route(origin: str, destination: str) -> dict:
    """Resolve a trip on Transurban's 95/395/495 Express Lanes network to its price-lookup key(s).

    Looks up origin/destination against oracles/i95.json's 685 published
    entry/exit trips (107 ramps) -- a flat, direct lookup, never multi-hop
    routing. Every valid direction+entry+exit combination is already
    enumerated by Transurban itself, including cross-corridor trips billed as
    two whole separate tolls.

    Args:
        origin: Ramp label (e.g. 'Route 267'), case-insensitive, or the
            oracle's raw node id (e.g. '182NO') as a fallback.
        destination: Same rules as origin.

    Returns:
        dict: On success, {"origin", "destination",
        "direction": "Northbound"|"Southbound", "entry": {"node_id", "label"},
        "exit": {"node_id", "label"}, "legs": [{"od_pair_id": int}, ...]} --
        legs has one entry for a within-corridor trip or two for a
        cross-corridor trip, in billed order, each the exact lookup key into
        trip_pricing_i95.od_pair_id. Some od_pair_ids in the oracle (1374-1389)
        have never had a priced row from VDOT's feed -- a returned leg means
        the trip exists, not that a price exists for it. No price is
        returned; that is a separate, future tool over Postgres. On failure,
        {"error": str, "valid_options": [str, ...]} -- the full ramp label
        list on an unknown identifier, or the reachable destination labels on
        a known origin with no direct trip to the given destination -- so the
        caller can self-correct without another round trip.
    """
    result = _lookup(origin, destination)
    if "error" in result:
        logger.info(
            "i95_route miss origin=%r destination=%r error=%r",
            origin,
            destination,
            result["error"],
        )
    else:
        logger.info(
            "i95_route ok origin=%r destination=%r entry=%s exit=%s direction=%s legs=%s",
            origin,
            destination,
            result["entry"]["node_id"],
            result["exit"]["node_id"],
            result["direction"],
            result["legs"],
        )
    return result
