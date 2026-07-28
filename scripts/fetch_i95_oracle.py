"""Extract Transurban's published entry/exit topology into a committed JSON snapshot.

expresslanes.com's "Map your trip" page ships its whole entry/exit network as a
static theme asset -- not an API -- and it is the same territory as our curated
graph: every entry point, every exit reachable from it, and the exact VDOT OD
pair(s) billed for that trip. The page's own JS looks the prices up by those
ids against /maps-api/infra-price-confirmed-all (see
tests/test_expresslanes_crosscheck.py), so the ids are VDOT's ODPAIRID verbatim.

We commit the *derived* JSON rather than the 221KB of theme source: it's what
agent_tools/i95_route.py and i495_route.py read at import, and re-running this
script is the one-command refresh. Never fetch at runtime -- the URL carries a ?v= cache
buster and the asset is third-party.

    uv run python scripts/fetch_i95_oracle.py
"""

import json
import re
import urllib.request
from pathlib import Path

SOURCE_URL = (
    "https://www.expresslanes.com/themes/custom/transurbangroup/js/"
    "on-the-road/entry_exit.js?v=1.x"
)
OUT_PATH = Path(__file__).resolve().parent.parent / "oracles" / "i95.json"

NODE_FIELDS = ("label", "latitude", "longitude", "path", "index")


def parse_entry_exits(js: str) -> dict:
    """Parse the `var entryExits = {...};` literal out of the theme asset.

    It's JS, not JSON: `//` line comments sit inside the object (some of them
    commenting out a description string) and a few arrays carry trailing
    commas. Both are stripped before json.loads. Comments only ever appear on
    their own line here, so a line filter is enough -- no need to tokenize
    around the "https://" and "/images/..." strings that a naive `//` strip
    would corrupt.
    """
    body = "\n".join(
        line for line in js.split("\n") if not line.strip().startswith("//")
    )
    start = body.index("var entryExits =") + len("var entryExits =")
    literal = body[start : body.rindex("};") + 1]
    return json.loads(re.sub(r",(\s*[}\]])", r"\1", literal))


def to_snapshot(entry_exits: dict) -> dict:
    """Flatten to {nodes, pairs}: the two things the topology check needs.

    Node ids are direction-suffixed (182NO = northbound origin, 181ND =
    northbound destination), so an entry and an exit at the same physical ramp
    are distinct records -- kept as-is, since the pairs reference them.
    """
    nodes: dict[str, dict] = {}
    pairs: list[dict] = []
    for direction, sides in sorted(entry_exits.items()):
        for side in ("entries", "exits"):
            for node_id, node in sides[side].items():
                nodes[node_id] = {
                    "direction": direction,
                    "side": side,
                    **{f: node[f] for f in NODE_FIELDS},
                }
        for entry_id, entry in sorted(sides["entries"].items()):
            for exit_ in entry["exits"]:
                pairs.append(
                    {
                        "direction": direction,
                        "entry": entry_id,
                        "exit": exit_["id"],
                        "ods": [int(od) for od in exit_["ods"]],
                    }
                )
    return {
        "source_url": SOURCE_URL,
        "nodes": dict(sorted(nodes.items())),
        "pairs": sorted(pairs, key=lambda p: (p["direction"], p["entry"], p["exit"])),
    }


def main() -> None:
    with urllib.request.urlopen(SOURCE_URL, timeout=60) as resp:
        js = resp.read().decode("utf-8")
    snapshot = to_snapshot(parse_entry_exits(js))
    OUT_PATH.parent.mkdir(exist_ok=True)
    OUT_PATH.write_text(json.dumps(snapshot, indent=1, sort_keys=True) + "\n")
    ods = {od for p in snapshot["pairs"] for od in p["ods"]}
    print(
        f"{OUT_PATH.relative_to(Path.cwd())}: {len(snapshot['nodes'])} nodes, "
        f"{len(snapshot['pairs'])} pairs, {len(ods)} distinct od pair ids"
    )


if __name__ == "__main__":
    main()
