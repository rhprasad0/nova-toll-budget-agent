"""find_toll_locations: progressive-disclosure search over every corridor's
committed interchange labels, so a caller can go from a vague human location
("Springfield", "Tysons") or a partial/misspelled label straight to the
exact label string i95_route/i495_route/i66_route/dulles_route expect --
without the reactive, error-driven discovery those four tools default to
today (reading `valid_options` off a failed lookup).

Reads the same committed oracle files those tools already load -- never RDS,
never a live source. This tool prices nothing; it only helps a caller pick
the right origin/destination string before calling one of the pricing tools.

Corridors: oracles/i95.json split into "i95"/"i495" by each node's own
`path` field, mirroring i95_route.py/i495_route.py's own pair filters
exactly -- a label in the raw file that never appears in a corridor's own
resolved pairs is not returned as belonging to that corridor, since the
matching pricing tool could never resolve it (dropped cross-corridor trips,
docs/oracle-findings.md section 8). Also oracles/i66.json ("i66_itb", mirrors
i66_route.py), oracles/dulles_toll_road.json / dulles_greenway.json
("dulles_toll_road"/"dulles_greenway", mirror dulles_route.py's two
facilities), and oracles/i66_otb.json ("i66_otb" -- verified entrance labels
only, unpriced: no pricing tool exists for I-66 Outside the Beltway in this
repo yet; see that file's own source_note for exactly what is and isn't
verified).

Matching, cheapest rung first: normalize (casefold, strip non-alphanumerics)
then substring-match against every label -- this alone resolves most human
place names, since they're usually already embedded in the official
interchange name ("Franconia-Springfield Parkway" contains "springfield",
"Washington D.C." normalizes to match "Washington DC"). A small hardcoded
locality-alias table covers the handful of common NoVA place names that
never appear in any label text (Tysons, McLean, Arlington, ...) by
re-running the same substring match against a curated set of nearby label
fragments -- these are search hints, not claims; the caller still confirms
the real answer via a pricing-tool call. difflib.get_close_matches is a
last-resort typo-tolerant fallback (stdlib, no new dependency).

See docs/oracle-tools-spec.md for the contract convention this follows.
"""

from __future__ import annotations

import difflib
import json
import logging
import re
from pathlib import Path

from strands import tool

logger = logging.getLogger(__name__)

# ponytail: path assumes agent_tools/ sits one level under the repo root next
# to oracles/, matching the other four tools' existing assumption.
_ORACLE_DIR = Path(__file__).resolve().parent.parent / "oracles"


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.casefold())


def _corridor_from_pairs(nodes: dict, pairs: list) -> dict[str, dict]:
    entry_ids = {p["entry"] for p in pairs}
    exit_ids = {p["exit"] for p in pairs}
    return {
        node_id: {
            "label": nodes[node_id]["label"],
            "entry_capable": node_id in entry_ids,
            "exit_capable": node_id in exit_ids,
        }
        for node_id in entry_ids | exit_ids
    }


def _load_i95_and_i495() -> tuple[dict[str, dict], dict[str, dict]]:
    oracle = json.loads((_ORACLE_DIR / "i95.json").read_text())
    nodes, pairs = oracle["nodes"], oracle["pairs"]

    def is_495(node_id: str) -> bool:
        return nodes[node_id]["path"].startswith("495")

    i95_pairs = [p for p in pairs if not is_495(p["entry"]) and not is_495(p["exit"])]
    i495_pairs = [p for p in pairs if is_495(p["entry"]) and is_495(p["exit"])]
    return (
        _corridor_from_pairs(nodes, i95_pairs),
        _corridor_from_pairs(nodes, i495_pairs),
    )


def _load_pairs_facility(filename: str) -> dict[str, dict]:
    oracle = json.loads((_ORACLE_DIR / filename).read_text())
    return _corridor_from_pairs(oracle["nodes"], oracle["pairs"])


def _load_otb() -> dict[str, dict]:
    oracle = json.loads((_ORACLE_DIR / "i66_otb.json").read_text())
    return {
        node_id: {
            "label": node["label"],
            # Only "entry" role has ever been observed for this facility
            # (see oracles/i66_otb.json's source_note) -- exit-capability
            # is genuinely unknown, not false, so it stays None rather than
            # a guessed bool.
            "entry_capable": True if node["role"] == "entry" else None,
            "exit_capable": None,
        }
        for node_id, node in oracle["nodes"].items()
    }


_i95_nodes, _i495_nodes = _load_i95_and_i495()

_CORRIDORS: dict[str, dict] = {
    "i95": {"pricing_tool": "i95_route", "priced": True, "nodes": _i95_nodes},
    "i495": {"pricing_tool": "i495_route", "priced": True, "nodes": _i495_nodes},
    "i66_itb": {
        "pricing_tool": "i66_route",
        "priced": True,
        "nodes": _load_pairs_facility("i66.json"),
    },
    "i66_otb": {"pricing_tool": None, "priced": False, "nodes": _load_otb()},
    "dulles_toll_road": {
        "pricing_tool": "dulles_route",
        "priced": True,
        "nodes": _load_pairs_facility("dulles_toll_road.json"),
    },
    "dulles_greenway": {
        "pricing_tool": "dulles_route",
        "priced": True,
        "nodes": _load_pairs_facility("dulles_greenway.json"),
    },
}

# Locality names that never appear literally in any label (verified against
# the committed oracles) -- everything else (Springfield, Reston, Leesburg,
# Quantico, Dumfries, Washington D.C., Pentagon, Rosslyn, Fairfax, ...) is
# already found by the plain normalized-substring match, no entry needed
# here. Values are label fragments to re-run that same substring match
# against -- search hints, not claims about what serves a given place.
_TYSONS = [
    "Jones Branch Drive",
    "Route 123 - Dolley Madison Blvd",
    "I-495 Express Lanes N",
    "Westpark Drive",
]
_LOCALITY_ALIASES: dict[str, list[str]] = {
    "tysons": _TYSONS,
    "tysonscorner": _TYSONS,
    "mclean": ["Route 123 - Dolley Madison Blvd", "Jones Branch Drive"],
    "arlington": [
        "Exit 73 - Rosslyn",
        "Exit 75 - Pentagon/Alexandria",
        "Fairfax Drive",
        "Glebe Road",
        "Washington Blvd",
        "Shirlington Circle",
    ],
    "ballston": ["Fairfax Drive", "Glebe Road"],
    "vienna": ["Route 123 - Dolley Madison Blvd", "Fairfax Drive"],
    "herndon": ["SR 674 (Hunter Mill Rd)", "SR 676 (Wolf Trap)"],
    "nationalairport": ["Pentagon/Eads Street"],
    "reaganairport": ["Pentagon/Eads Street"],
    "gainesville": ["Western Entry", "University Boulevard"],
    "manassas": ["Sudley Road", "Rt 28"],
    "centreville": ["Rt 28", "EB Slip Ramp Rt 28"],
}


def _corridor_ids() -> list[str]:
    return sorted(_CORRIDORS)


def _all_entries(
    corridor: str | None,
) -> list[tuple[str, str, str, bool | None, bool | None]]:
    corridor_ids = [corridor] if corridor is not None else _corridor_ids()
    return [
        (cid, node_id, node["label"], node["entry_capable"], node["exit_capable"])
        for cid in corridor_ids
        for node_id, node in _CORRIDORS[cid]["nodes"].items()
    ]


def _substring_matches(normalized_query: str, candidates: list[tuple]) -> list[tuple]:
    return [
        c
        for c in candidates
        if normalized_query in _normalize(c[2]) or _normalize(c[2]) in normalized_query
    ]


def _search(query: str, corridor: str | None) -> list[tuple]:
    candidates = _all_entries(corridor)

    # Raw node id, exact match -- same "reliable source" tier as
    # _oracle_route.resolve()'s own "if query in nodes: return [query]"
    # check. Node ids are opaque identifiers ("206SO", "1", "418"), so this
    # must be exact-equality, never substring: "418" is itself a full id in
    # one corridor and, without this early return, a spurious substring hit
    # inside an unrelated id ("1819") in another.
    node_id_matches = [c for c in candidates if c[1] == query]
    if node_id_matches:
        node_id_matches.sort(key=lambda c: (c[0], c[2]))
        return node_id_matches[:20]

    normalized_query = _normalize(query)
    matches = (
        _substring_matches(normalized_query, candidates) if normalized_query else []
    )

    if not matches:
        for fragment in _LOCALITY_ALIASES.get(normalized_query, []):
            matches.extend(_substring_matches(_normalize(fragment), candidates))

    if not matches:
        # Whole-label difflib comparison would penalize a short misspelled
        # query against long compound labels on length alone ("Sprinfield"
        # vs "Franconia-Springfield Parkway/Route 289" scores lower than an
        # unrelated short label) -- comparing against individual label
        # words instead keeps the ratio meaningful regardless of how long
        # the rest of the label is.
        words: dict[str, list[tuple]] = {}
        for c in candidates:
            for word in re.findall(r"[a-z0-9]+", c[2].casefold()):
                words.setdefault(word, []).append(c)
        close_words = difflib.get_close_matches(
            query.casefold(), words, n=5, cutoff=0.72
        )
        matches = [c for word in close_words for c in words[word]]

    seen: set[tuple[str, str]] = set()
    deduped = []
    for c in matches:
        key = (c[0], c[1])
        if key not in seen:
            seen.add(key)
            deduped.append(c)
    deduped.sort(key=lambda c: (c[0], c[2]))
    return deduped[:20]


@tool
def find_toll_locations(query: str = "", corridor: str | None = None) -> dict:
    """Search every corridor's committed interchange labels for the exact
    string a pricing tool (i95_route/i495_route/i66_route/dulles_route)
    expects, from a vague human location or a partial/misspelled label.

    Two levels: call with no query first to see what corridors exist
    (cheap -- 6 entries, not a label dump), then call again with a query to
    get actual candidate labels. This never returns a full label list
    without a query, even when `corridor` narrows it to one -- that keeps
    the tool's own output small regardless of how large a corridor is (i95
    alone has over 60 nodes).

    Args:
        query: Free text -- an interchange label substring, a common NoVA
            place/locality name (e.g. "Springfield", "Tysons", "Washington
            DC"), a raw node id, or a misspelling of any of those.
            Case/punctuation-insensitive. Omit (or pass "") to get the
            corridor menu instead of a label search.
        corridor: Restrict the search to one corridor id -- "i95", "i495",
            "i66_itb", "i66_otb", "dulles_toll_road", or "dulles_greenway".
            Omit to search every corridor. An unknown id is an error, not a
            silent empty result.

    Returns:
        dict: One of three shapes.

        Corridor menu (query omitted/blank): {"corridors":
        [{"corridor": str, "pricing_tool": str | None, "priced": bool,
        "label_count": int}, ...]} -- pricing_tool is None and priced is
        False only for "i66_otb", the one corridor with no pricing tool in
        this repo.

        Search result (query given, at least one match): {"query": str,
        "matches": [{"corridor": str, "label": str, "node_id": str,
        "pricing_tool": str | None, "priced": bool,
        "entry_capable": bool | None, "exit_capable": bool | None}, ...]}
        (at most 20, sorted by corridor then label). entry_capable/
        exit_capable are None only for "i66_otb" nodes, where exit-capability
        was never observed (see oracles/i66_otb.json's source_note) --
        None means unverified, not false.

        On failure (unknown corridor, or a query that matches nothing even
        after the locality-alias and typo-tolerant fallback), {"error": str,
        "valid_options": [str, ...]} -- the list of valid corridor ids, so
        the caller can retry narrower or broader.
    """
    if corridor is not None and corridor not in _CORRIDORS:
        return {
            "error": f"unknown corridor {corridor!r}",
            "valid_options": _corridor_ids(),
        }

    if not query.strip():
        corridors = [corridor] if corridor is not None else _corridor_ids()
        return {
            "corridors": [
                {
                    "corridor": cid,
                    "pricing_tool": _CORRIDORS[cid]["pricing_tool"],
                    "priced": _CORRIDORS[cid]["priced"],
                    "label_count": len(_CORRIDORS[cid]["nodes"]),
                }
                for cid in corridors
            ]
        }

    matches = _search(query, corridor)
    if not matches:
        logger.info("find_toll_locations miss query=%r corridor=%r", query, corridor)
        return {"error": f"no labels match {query!r}", "valid_options": _corridor_ids()}

    result = {
        "query": query,
        "matches": [
            {
                "corridor": cid,
                "label": label,
                "node_id": node_id,
                "pricing_tool": _CORRIDORS[cid]["pricing_tool"],
                "priced": _CORRIDORS[cid]["priced"],
                "entry_capable": entry_capable,
                "exit_capable": exit_capable,
            }
            for cid, node_id, label, entry_capable, exit_capable in matches
        ],
    }
    logger.info(
        "find_toll_locations ok query=%r corridor=%r matches=%d",
        query,
        corridor,
        len(result["matches"]),
    )
    return result
