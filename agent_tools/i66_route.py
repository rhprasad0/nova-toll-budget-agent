"""i66_route: resolve a human trip between two I-66 ITB interchanges to its
VDOT price-lookup key.

Pure route-map lookup against the committed oracles/i66.json -- no DB, no
network, no multi-hop chaining. VDOT's own calculator already enumerates
every valid direction+entry+exit combination directly (96 pairs over 17
interchanges), so this is a single flat lookup, never pathfinding: "where an
oracle exists, prefer reading it over re-deriving it" (docs/oracle-findings.md
section 3). Price itself is out of scope here; the leg this returns is the
exact (start_zone_id, end_zone_id) key into trip_pricing_i66, for a separate,
future pricing tool to query.

See docs/oracle-tools-spec.md for the full contract and known limitations.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from strands import tool

logger = logging.getLogger(__name__)

# ponytail: path assumes agent_tools/ sits one level under the repo root next
# to oracles/, matching its current committed location. If this ever ships in
# a deployment zip, the build step must land oracles/i66.json at this same
# relative path, or this constant needs to change with it.
_ORACLE_PATH = Path(__file__).resolve().parent.parent / "oracles" / "i66.json"
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


# ponytail: resolution/matching logic duplicated with i95_route.py; extract
# if a third oracle-backed tool needs the same shape.
def _lookup(origin: str, destination: str) -> dict:
    # Some interchanges are entry-only or exit-only (e.g. Westmoreland St can
    # never be an origin), so the two suggestion lists are role-filtered --
    # suggesting a label that can never fill the role being asked about would
    # guarantee the caller's next call also fails.
    origin_labels = sorted({_NODES[p["entry"]]["label"] for p in _PAIRS})
    destination_labels = sorted({_NODES[p["exit"]]["label"] for p in _PAIRS})

    origin_ids = _resolve(origin)
    if not origin_ids:
        return {
            "error": f"unknown origin {origin!r}: no matching label or node id in the i66 oracle",
            "valid_options": origin_labels,
        }
    destination_ids = _resolve(destination)
    if not destination_ids:
        return {
            "error": f"unknown destination {destination!r}: no matching label or node id in the i66 oracle",
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
            "error": f"no direct trip from {origin!r} to {destination!r} in the i66 oracle",
            "valid_options": reachable,
        }

    if len(matches) > 1:
        # Unreachable today -- verified 96/96 pairs unique on (entry, exit).
        # Guarded for when scripts/fetch_i66_oracle.py next refreshes
        # oracles/i66.json and that invariant might not hold.
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
        "direction": p["direction"],
        "entry": {"node_id": p["entry"], "label": _NODES[p["entry"]]["label"]},
        "exit": {"node_id": p["exit"], "label": _NODES[p["exit"]]["label"]},
        "legs": [{"start_zone_id": p["start_zone"], "end_zone_id": p["end_zone"]}],
    }


@tool
def i66_route(origin: str, destination: str) -> dict:
    """Resolve a trip on VDOT's I-66 Inside-the-Beltway toll calculator to its price-lookup key.

    Looks up origin/destination against oracles/i66.json's 96 published
    entry/exit trips (17 interchanges) -- a flat, direct lookup, never
    multi-hop routing. Every valid direction+entry+exit combination is
    already enumerated by VDOT itself.

    Args:
        origin: Interchange label (e.g. 'Fairfax Drive'), case-insensitive,
            or the oracle's raw node id (e.g. '4') as a fallback.
        destination: Same rules as origin.

    Returns:
        dict: On success, {"origin", "destination", "direction": "EB"|"WB",
        "entry": {"node_id", "label"}, "exit": {"node_id", "label"},
        "legs": [{"start_zone_id": int, "end_zone_id": int}]} -- legs has
        exactly one entry for i66, the exact lookup key into trip_pricing_i66
        (columns start_zone_id, end_zone_id). No price is returned; that is a
        separate, future tool over Postgres. On failure, {"error": str,
        "valid_options": [str, ...]} -- the full interchange label list on an
        unknown identifier, or the reachable destination labels on a known
        origin with no direct trip to the given destination -- so the caller
        can self-correct without another round trip.
    """
    result = _lookup(origin, destination)
    if "error" in result:
        logger.info(
            "i66_route miss origin=%r destination=%r error=%r",
            origin,
            destination,
            result["error"],
        )
    else:
        logger.info(
            "i66_route ok origin=%r destination=%r entry=%s exit=%s direction=%s legs=%s",
            origin,
            destination,
            result["entry"]["node_id"],
            result["exit"]["node_id"],
            result["direction"],
            result["legs"],
        )
    return result
