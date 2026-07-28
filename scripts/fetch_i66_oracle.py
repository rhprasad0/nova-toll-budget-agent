"""Capture VDOT's published I-66 Inside-the-Beltway interchange/toll-zone map.

The i66 half of the toll graph (8 zone nodes, 20 zone-pair edges in
db/graph.sql) has never had an independent source to check it against:
Transurban operates only 95/395/495, so oracles/i95.json
covers none of it. VDOT's own toll calculator does.

vai66tolls.com is an ASP.NET Razor app whose handlers are plain GETs on /Index:

    BeginIntPartial(rbEastVal)              -> entry interchange <option> list
    ExitIntPartial(bIntId, rbEastVal)       -> exits reachable from that entry
    TollCalcPartial(bIntId, eIntId, ...)    -> {"decToll": .., "jsToRun": ".."}

The prize is inside jsToRun: it calls runChartMake(weekday, beginZone, endZone,
...), so for every interchange pair VDOT names the toll zone the trip starts
and ends in -- the ramp-to-gantry mapping we have no other source for.

Output mirrors oracles/i95.json: {source_url, nodes,
pairs}, where each pair carries the price *key* into trip_pricing and no price.
For the express lanes that key is a list of od_pair_ids; for I-66 ITB, which
prices by zone pair, it is (start_zone, end_zone). Deliberately no toll
amounts, no averages -- this is route-mapping data, and prices live in
trip_pricing where they have history.

TollCalcPartial is still the only handler that attributes zones, so it is
called with a fixed past weekday/time inside each direction's tolled window
(I-66 ITB tolls EB 5:30-9:30am, WB 3-7pm only; isCurrent=true errors here).
Its decToll is read and discarded.

Nothing consumes this yet -- it is committed evidence, not a feed. Never fetch
it at runtime.

    uv run python scripts/fetch_i66_oracle.py
"""

import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "https://vai66tolls.com/Index"
OUT_PATH = Path(__file__).resolve().parent.parent / "oracles" / "i66.json"

# A Thursday, and a time inside each direction's tolling window. Fixed so the
# archived prices -- and therefore this whole file -- are reproducible.
REF_DATE = "07/23/2026"
REF_TIME = {"EB": "7:00 AM", "WB": "5:00 PM"}
DIRECTIONS = {"EB": "true", "WB": "false"}  # rbEastVal

# Public VDOT site: sequential, one pass, spaced out. docs/poller-spec.md
# already commits us to WAF etiquette and this is ~190 requests.
DELAY_S = 1.0

# Gantry ids in travel order per direction, from the feed itself
# (vdot_sample_data/tollingTripPricing-I66-refreshed.xml): EB runs
# 3100 Capital Beltway Beginning -> 3130 Spout Run Pkwy, WB runs
# 3200 Glebe Rd -> 3230 Capital Beltway End. The calculator indexes 0-3 for EB
# and 4-7 for WB; the anchors below prove the correspondence rather than
# assuming it.
GANTRIES = {"EB": [3100, 3110, 3120, 3130], "WB": [3200, 3210, 3220, 3230]}
INDEX_BASE = {"EB": 0, "WB": 4}
# runChartMake's 2nd/3rd args are NOT entry/exit -- they are geographic, the
# western zone then the eastern one, in both directions. Measured: EB
# I-66 West -> Washington yields (0, 3) but WB Washington -> I-66 West yields
# (7, 4), and WB Washington -> Glebe (one zone) yields (4, 4). Since the feed
# numbers each direction's gantries in travel order (EB 3100->3130 ascending,
# WB 3200->3230 ascending), the smaller index is always the trip's start and
# the larger its end -- which is exactly the feed's own convention.
#
# Anchored on the two full-corridor trips, so a reordering upstream fails loud.
ANCHORS = {
    "EB": ("I-66 West", "Washington", (3100, 3130)),
    "WB": ("Washington", "I-66 West", (3200, 3230)),
}

OPTION_RE = re.compile(r'<option[^>]*value="([^"]*)"[^>]*>([^<]*)')
CHART_RE = re.compile(
    r'runChartMake\((\d+),\s*(\d+),\s*(\d+),\s*"([^"]*)",\s*"([^"]*)"'
)


def _get(**params) -> str:
    time.sleep(DELAY_S)
    url = f"{BASE}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=60) as resp:
            return resp.read().decode("utf-8", "replace")
    except OSError:
        time.sleep(5)  # single backoff, then give up rather than hammer
        with urllib.request.urlopen(url, timeout=60) as resp:
            return resp.read().decode("utf-8", "replace")


def _options(html: str) -> dict[str, str]:
    """value -> label, dropping the placeholder row (empty value)."""
    return {v: label.strip() for v, label in OPTION_RE.findall(html) if v}


def zone_of(direction: str, index: int) -> int:
    return GANTRIES[direction][index - INDEX_BASE[direction]]


def trip_zones(direction: str, a: int, b: int) -> tuple[int, int]:
    """(start_zone, end_zone) in travel order from a (west, east) index pair."""
    return zone_of(direction, min(a, b)), zone_of(direction, max(a, b))


def main() -> None:
    nodes: dict[str, dict] = {}
    pairs: list[dict] = []
    missing: list[tuple[str, str, str]] = []

    for direction, east_val in DIRECTIONS.items():
        entries = _options(_get(handler="BeginIntPartial", rbEastVal=east_val))
        for entry_id, entry_label in entries.items():
            node = nodes.setdefault(
                entry_id, {"label": entry_label, "entry_in": [], "exit_in": []}
            )
            node["entry_in"].append(direction)

            exits = _options(
                _get(handler="ExitIntPartial", bIntId=entry_id, rbEastVal=east_val)
            )
            for exit_id, exit_label in exits.items():
                ex = nodes.setdefault(
                    exit_id, {"label": exit_label, "entry_in": [], "exit_in": []}
                )
                if direction not in ex["exit_in"]:
                    ex["exit_in"].append(direction)

                payload = json.loads(
                    _get(
                        handler="TollCalcPartial",
                        bIntId=entry_id,
                        eIntId=exit_id,
                        datePicked=REF_DATE,
                        timePicked=REF_TIME[direction],
                        rbEastVal=east_val,
                        isCurrent="false",
                    )
                )
                m = CHART_RE.search(payload.get("jsToRun", ""))
                if not m:  # no zone attribution -> record, don't guess
                    missing.append((direction, entry_id, exit_id))
                    continue
                start_zone, end_zone = trip_zones(
                    direction, int(m.group(2)), int(m.group(3))
                )
                pairs.append(
                    {
                        "direction": direction,
                        "entry": entry_id,
                        "exit": exit_id,
                        "start_zone": start_zone,
                        "end_zone": end_zone,
                    }
                )

    # Prove the index space rather than trusting it.
    for direction, (entry_label, exit_label, expected) in ANCHORS.items():
        seen = {
            (p["start_zone"], p["end_zone"])
            for p in pairs
            if p["direction"] == direction
            and nodes[p["entry"]]["label"] == entry_label
            and nodes[p["exit"]]["label"] == exit_label
        }
        assert seen == {expected}, (
            f"{direction} full-corridor anchor {entry_label!r}->{exit_label!r} "
            f"mapped to {seen}, expected {{{expected}}} -- the calculator's "
            "zone index space moved"
        )
    for direction in DIRECTIONS:
        used = {
            z
            for p in pairs
            if p["direction"] == direction
            for z in (p["start_zone"], p["end_zone"])
        }
        assert used <= set(GANTRIES[direction]), (direction, used)

    # Every pair must get a zone. A miss means thinner data than it looks, so
    # fail rather than commit a snapshot with silent holes in it.
    assert not missing, f"no zone attribution for {len(missing)} pairs: {missing[:5]}"

    snapshot = {
        "source_url": BASE,
        "nodes": dict(sorted(nodes.items(), key=lambda kv: int(kv[0]))),
        "pairs": sorted(
            pairs, key=lambda p: (p["direction"], int(p["entry"]), int(p["exit"]))
        ),
    }
    OUT_PATH.parent.mkdir(exist_ok=True)
    OUT_PATH.write_text(json.dumps(snapshot, indent=1, sort_keys=True) + "\n")

    zone_pairs = {(p["start_zone"], p["end_zone"]) for p in pairs}
    print(
        f"{OUT_PATH.name}: {len(nodes)} interchanges, {len(pairs)} pairs, "
        f"{len(zone_pairs)} distinct zone pairs"
    )


if __name__ == "__main__":
    main()
