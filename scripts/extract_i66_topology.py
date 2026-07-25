#!/usr/bin/env python3
"""Capture VDOT's published I-66 Inside-the-Beltway interchange/toll-zone map.

The i66 half of the toll graph (8 zone nodes, 20 zone-pair edges in
db/graph.sql) has never had an independent source to check it against:
Transurban operates only 95/395/495, so expresslanes_sample_data/entry_exits.json
covers none of it. VDOT's own toll calculator does.

vai66tolls.com is an ASP.NET Razor app whose handlers are plain GETs on /Index:

    BeginIntPartial(rbEastVal)              -> entry interchange <option> list
    ExitIntPartial(bIntId, rbEastVal)       -> exits reachable from that entry
    TollCalcPartial(bIntId, eIntId, ...)    -> {"decToll": .., "jsToRun": ".."}

The prize is inside jsToRun: it calls runChartMake(weekday, beginZone, endZone,
...), so for every interchange pair VDOT names the toll zone the trip starts
and ends in -- the ramp-to-gantry mapping we have no other source for. The
landing page additionally ships a 4-week average toll table inline.

Prices are requested at a FIXED past weekday/time inside each direction's
tolled window (I-66 ITB tolls EB 5:30-9:30am, WB 3-7pm only), so the topology
and ref_toll values reproduce exactly on a re-run. isCurrent=true errors on
this handler. The `averages` block is the exception: it is a rolling 4-week
mean VDOT recomputes, so it drifts with the calendar even though everything
else here does not.

Nothing consumes this yet -- it is committed evidence, not a feed. Never fetch
it at runtime.

    uv run python scripts/extract_i66_topology.py
"""

import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "https://vai66tolls.com/Index"
OUT_PATH = (
    Path(__file__).resolve().parent.parent
    / "vai66tolls_sample_data"
    / "interchanges.json"
)

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
PUSH_RE = re.compile(r"([ew])wdv\[(\d+)\]\[(\d+)\]\[(\d+)\]\.push\(([-\d.]+)\)")
SLOT_RE = re.compile(r"([ew])tNames\.push\('([^']*)'\)")


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


def fetch_landing() -> str:
    time.sleep(DELAY_S)
    with urllib.request.urlopen("https://vai66tolls.com", timeout=60) as resp:
        return resp.read().decode("utf-8", "replace")


def parse_averages(html: str) -> dict:
    """The inline 4-week average table, built by .push() calls on one line.

    ewdv[weekday][beginZone][endZone] holds eastbound series and wwdv the
    westbound ones; etNames/wtNames label the 30-minute slots. Zone indices are
    the same 0-3 / 4-7 space runChartMake uses, so they are translated to
    gantry ids by the caller's derived mapping.
    """
    slots: dict[str, list[str]] = {"EB": [], "WB": []}
    for kind, label in SLOT_RE.findall(html):
        slots["EB" if kind == "e" else "WB"].append(label)

    series: dict[tuple[str, int, int, int], list[float]] = {}
    for kind, weekday, begin, end, value in PUSH_RE.findall(html):
        key = ("EB" if kind == "e" else "WB", int(weekday), int(begin), int(end))
        series.setdefault(key, []).append(float(value))
    return {"slots": slots, "series": series}


def zone_of(direction: str, index: int) -> int:
    return GANTRIES[direction][index - INDEX_BASE[direction]]


def trip_zones(direction: str, a: int, b: int) -> tuple[int, int]:
    """(start_zone, end_zone) in travel order from a (west, east) index pair."""
    return zone_of(direction, min(a, b)), zone_of(direction, max(a, b))


def main() -> None:
    landing = fetch_landing()
    averages = parse_averages(landing)

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
                        "ref_toll": payload["decToll"],
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

    snapshot = {
        "source_url": BASE,
        "reference_trip": {"date": REF_DATE, "times": REF_TIME},
        "gantries": GANTRIES,
        "nodes": dict(sorted(nodes.items(), key=lambda kv: int(kv[0]))),
        "pairs": sorted(
            pairs, key=lambda p: (p["direction"], int(p["entry"]), int(p["exit"]))
        ),
        "averages": {
            "slots": averages["slots"],
            # ewdv/wwdv use the same (west, east) index convention as
            # runChartMake, so the same travel-order normalisation applies.
            "series": sorted(
                (
                    {
                        "direction": d,
                        "weekday": w,
                        "start_zone": trip_zones(d, b, e)[0],
                        "end_zone": trip_zones(d, b, e)[1],
                        "tolls": v,
                    }
                    for (d, w, b, e), v in averages["series"].items()
                ),
                key=lambda s: (
                    s["direction"],
                    s["weekday"],
                    s["start_zone"],
                    s["end_zone"],
                ),
            ),
        },
        "pairs_without_zone_attribution": sorted(missing),
    }
    OUT_PATH.parent.mkdir(exist_ok=True)
    OUT_PATH.write_text(json.dumps(snapshot, indent=1, sort_keys=True) + "\n")

    zone_pairs = {(p["start_zone"], p["end_zone"]) for p in pairs}
    print(
        f"{OUT_PATH.name}: {len(nodes)} interchanges, {len(pairs)} pairs, "
        f"{len(zone_pairs)} distinct zone pairs, "
        f"{len(snapshot['averages']['series'])} average series"
        + (f", {len(missing)} pairs without zones" if missing else "")
    )


if __name__ == "__main__":
    main()
