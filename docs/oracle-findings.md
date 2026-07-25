# Oracle Findings

Status: findings record, graph/tools deleted · Owner: Ryan Prasad · Last updated: 2026-07-25

The curated toll graph, the four agent tools, and their specs and audits were
removed from this repo in the same change that added this file (see closing
section). Before that evidence disappeared, this document preserves what the
graph work found by checking itself against the operators' own route maps. Everything below
was true as of 2026-07-25; commit hashes are `git log --oneline` short forms
on `main`.

## 1. What the oracles are

Both toll operators publish their own entry/exit route maps, independent of
anything VDOT feeds the poller. `oracles/i95.json` vendors Transurban's
(expresslanes.com) entire 95/395/495 Express Lanes network — 107 nodes, 685
entry→exit pairs, 330 distinct OD pair ids, 295 of the pairs needing two OD
ids because a cross-corridor trip is billed as two whole tolls, never a
summed sub-segment. `oracles/i66.json` vendors VDOT's own I-66 Inside-the-
Beltway calculator (vai66tolls.com) — 17 interchanges, 96 entry→exit pairs,
20 distinct toll-zone pairs.

Both files share one shape, `{source_url, nodes, pairs}`, and each pair
carries only the **price key** into `trip_pricing` — a list of `od_pair_ids`
for i95, a `(start_zone, end_zone)` pair for i66 — never a price. They are
route maps, not price feeds; refreshed by `scripts/fetch_i95_oracle.py` and
`scripts/fetch_i66_oracle.py`.

## 2. The 107-trip VDOT gap

*(2026-07-25, commit `13f468b` "Record why 1374-1389 aren't a renumbering of
ids we already hold", building on `4acc04f`)*

This is the most important finding. Transurban bills 562 distinct trips.
107 of them require one of 16 OD pair ids — 1374 through 1389 — that VDOT's
public feed has never published.

Evidence: live RDS holds exactly 317 distinct i95 `od_pair_id`s across the
entire backfill (2026-04-17 through 2026-07-25), spanning 1000–1352, and zero
rows for 1374–1389. Transurban, meanwhile, prices all 16 at the time of
checking (`od_1374` $3.45 on 495 N, `od_1388` $17.00 on 395 S). Roughly 19% of
real express-lane trips simply cannot be priced from VDOT's public feed.

**Update, 2026-07-25:** a narrower fix now exists — `toll-express-fetcher`
captures Transurban's own live snapshot into `trip_pricing_i95_live` (see
`docs/poller-spec.md`'s "Secondary live source" section), so these 16 ids do
get priced going forward. This does not close the gap described above: the
live source has no history (current snapshot only, so 2026-04-17 through
2026-07-25 for these ids stays permanently unpriced), no zone/corridor
identity (can't feed `trip_pricing_i95` itself), and only prices an id
reliably when its lane direction is actually open. The 19%-of-trips finding
above remains true for anyone asking about the historical record; it's now
false only for "can this be priced right now."

The destination names invite a trap: 1378 → "Old Keene Mill Rd" lines up with
VDOT's 1158 → "I-495 TO FRANCONIA RD (644)", the same road. Do not build an
alias table. Transurban bills **both** 1158 and 1378 to that destination from
different origins — 1158 as a sole toll entering at Springfield from the I-95
side, 1378 as the second leg for a driver already on the 495 Express Lanes.
Distinct products, distinct prices.

## 3. The Springfield over-merge

*(2026-07-25, commit `4acc04f` "Split the Springfield node by arrival road;
audit graph against Transurban")*

The curated graph had one node, `i95x:i495-springfield`, merging four
distinct VDOT toll zones: 3N-6 NB/SB (the I-95 side) and 4-1 SB/NB (the
I-395 side). VDOT's own zone ids prove these are different places, and
Transurban's entry/exit network independently confirms it: all 13 I-95
arrivals chain into the "I-495 HOV TO …" OD family, all 3 I-395 arrivals
chain into "I-395-95 HOV TO …", with zero overlap between the two families.

While merged, `route()` could compose 240 journeys no operator bills (picking
whichever OD family was cheaper regardless of which road a driver actually
arrived on), and could not express 104 journeys Transurban does bill (the
over-merge blocked, e.g., Garrisonville→I-495 chaining into the correct 495
continuation). Splitting the node into `i95x:i495-springfield` /
`i95x:i495-i395`, with one connector per zone pairing, took the curation gap
to zero. Verified end to end against live prices: Garrisonville now yields OD
chain `[1098, 1085]` and Seminary Rd `[1216, 1001]` — the families Transurban
actually bills.

The general lesson: every bug here came from the graph inferring topology
that the operator already publishes. Where an oracle exists, prefer reading
it over re-deriving it.

## 4. I-66 ITB validated

*(2026-07-25, commit `534ed0b` "Capture VDOT's I-66 ITB interchange/toll-zone
map as an oracle")*

VDOT's own calculator attributes every interchange pair to a toll-zone pair.
The 20 distinct zone pairs it produces — 10 eastbound (3100/3110/3120/3130),
10 westbound (3200/3210/3220/3230) — matched the hand-curated i66 graph edges
exactly, derived from two independent parts of the calculator site (the zone
table and the chart-generation calls).

Cross-checked further against an independent 2019 ramp-to-zone map
(`github.com/ViennaMike/I-66-Tolls`, `tolls.py`): 24 of 25 entries agree. The
one disagreement is I-495 S, which that map folds into a single combined
I-495 key at zone 3100; VDOT's calculator puts it at 3110, a zone cheaper and
consistently so ($0.90 vs $1.85 to Westmoreland, $5.45 vs $6.40 to
Washington) — corroborating the finer, calculator-derived mapping over the
coarser one.

## 5. A parsing trap in the I-66 calculator

*(2026-07-25, commits `534ed0b` and `d0147a9`)*

Worth recording for anyone who refreshes the i66 oracle: the calculator's
`runChartMake(weekday, beginZone, endZone, ...)` arguments are **not**
entry/exit — they are geographic, western zone then eastern, in both travel
directions. Eastbound "I-66 West" → "Washington" yields `(0, 3)`, but
westbound "Washington" → "I-66 West" yields `(7, 4)`. Because the feed
numbers each direction's gantries in travel order, the smaller index is
always the trip's start, regardless of which end a driver enters. Read the
arguments as entry/exit and the pair comes out backwards.

`fetch_i66_oracle.py` normalizes on that rule and anchors on both
full-corridor trips (bumper-to-bumper each direction), so a reordering
upstream fails loudly instead of silently swapping origin and destination.

## 6. The gap runs both ways: od_pair_id 1316 is priced but not in the oracle

*(2026-07-25, found while building `tests/test_route_tools_live_crosscheck.py`)*

Section 2 is one direction of drift: ids the oracle publishes that VDOT never
prices. This is the other direction — a trip VDOT actively prices that the
oracle doesn't know about at all. `trip_pricing_i95` holds `od_pair_id` 1316,
`od_pair_name` "TURKEYCOCK to Old Courthouse Rd", with ~1,972
`SOUTHBOUND_OPEN` rows and ~1,830 `CLOSED` rows spanning the full backfill
(2026-04-17 through today) — genuine, currently-active billing history, not a
dead link. Neither "Turkeycock" nor "Old Courthouse" appears anywhere in
`oracles/i95.json`'s node labels; no entry/exit pair produces this id under
any lookup.

Two other ids in the same "priced but unreachable via the oracle" set,
`1000` ("WESTPARK (B) TO I-495 N") and `1093` ("I-495 NEAR MD TO WESTPARK
(C)"), are not the same kind of gap — both are permanently
`NO_DETERMINATION`/`UNKNOWN` with no real rate history, i.e. dead links VDOT
carries but never actually bills. 1316 is the one that matters: a real,
priced trip with no oracle-derivable route.

Not yet root-caused (unclear whether Transurban's entry/exit feed has simply
never listed this ramp pair, or whether `fetch_i95_oracle.py` is dropping it
during capture) and not fixed here — flagging so it doesn't silently
regress. `tests/test_route_tools_live_crosscheck.py` asserts the exact
three-id set `{1000, 1093, 1316}` for "priced but unreachable," so a fourth
id joining it, or 1316 dropping out of it, fails that test loudly instead of
going unnoticed.

## What was deleted, and what remains

Alongside this write-up: `db/graph.sql` (the curated toll graph), the four
agent tools (`route`, `execute_sql`, `list_tables`, `describe_table`) and their
JSON schema contracts, and their specs and audits (`docs/toll-graph-spec.md`, `docs/agent-tools-spec.md`,
`docs/graph-connectivity-audit.md`, `docs/graph-network-audit.md`,
`docs/implementation-plan.md`) — along with their tests and the DOT graph
generator. What remains is the poller/`trip_pricing` pipeline
(`docs/poller-spec.md`) and the two route-map oracles, `oracles/i95.json` and
`oracles/i66.json`, which this document exists to explain now that the code
that motivated capturing them is gone.
