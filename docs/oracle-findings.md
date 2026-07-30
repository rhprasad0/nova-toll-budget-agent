# Oracle Findings

Status: findings record and current route-tool rationale · Owner: Ryan Prasad · Last updated: 2026-07-30

The original curated toll graph and free-form database tools were removed.
This document preserves what that work found and records the rationale behind
the narrower oracle-backed route tools that replaced them.
Sections 1-8 were true as of 2026-07-25; section 9 was added 2026-07-28 and
supersedes part of section 7. Each section carries its own date. Commit hashes
are `git log --oneline` short forms on `main`.

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
carries only the **price key** into `trip_pricing_i95` — a list of
`od_pair_ids` for i95 — or `trip_pricing_i66` — a `(start_zone, end_zone)`
pair for i66 — never a price. They are route maps, not price feeds; refreshed
by `scripts/fetch_i95_oracle.py` and `scripts/fetch_i66_oracle.py`.

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

**Historical update:** `toll-express-fetcher` captured Transurban's live
snapshot from 2026-07-25 until its retirement on 2026-07-30. That source had
no history, no zone/corridor identity, and only reliably priced an id while
its lane direction was open. Its retained rows and raw objects do not change
the current VDOT-only limitation.

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

## 7. VDOT's price and Transurban's live price disagree -- but by lag, not by a bug

*(2026-07-25, found manually testing `i95_route` against the newly-deployed
`trip_pricing_i95_live`)*

Querying "US-1 to Westpark Drive" turned up a composite trip (`od_pair_id`s
1131 and 1089) priced at $10.40 + $9.95 = $20.35 in `trip_pricing_i95` (VDOT).
The live `expresslanes.com` API, and the actual quote a driver sees on the
Express Lanes site, showed $6.60 + $9.15 = $15.75 for the same two ids at
essentially the same moment -- a $4.60 gap, not explained by the already-known
16-id gap (section 2) or the reverse-drift ids (section 6): 1131 and 1089 are
ordinary oracle ids, not on either list.

This was not documented by either source. The repository's old live
crosscheck only asserted that Transurban's price was nonnegative; this
investigation was the first comparison against stored VDOT values.

**Root cause, evidenced rather than assumed:** every `trip_pricing_i95` row
carries `calculated_at`, and it consistently trails `interval_end_at` by
~10 minutes (e.g. an `interval_end_at` 23:30 row's price was `calculated_at`
23:20) -- on top of our own 10-minute poll cadence, "VDOT's latest row" is
never truly "right now," it's a snapshot from 10-20 minutes ago. Combined with
genuinely volatile dynamic pricing (VDOT's own row history for `od_pair_id`
1131 alone swung $8.60 -> $7.80 -> $7.15 -> $10.40 -> $6.60 within 40 minutes;
VDOT has publicly attributed exactly this kind of swing to demand-responsive
pricing when explaining a driver's $18 I-64 toll complaint), a several-dollar
gap between "VDOT's latest row" and Transurban's instantaneous quote is
exactly what lag-plus-volatility predicts.

Re-checked minutes later: VDOT's *next* poll for both 1131 and 1089 converged
to within $0.10 of Transurban's live price. Checked four more random ids
(1011, 1016, 1002, 1304) against the live feed at the same moment: gaps of
$0.30-$1.30, in **both directions** (VDOT sometimes higher, sometimes lower)
-- a directionless, moderate spread is consistent with lag-plus-volatility
noise, not a systematic bias one source or the other would produce if this
were a real data-quality defect.

**Conclusion: not a discrepancy in the bug sense.** VDOT is the active source
for current and historical dynamic prices, but its latest value trails the
operator by about ten minutes. Answers must report VDOT's observed timestamp
rather than imply minute-level freshness.

**Superseded in part by section 9 (2026-07-28):** the "~10 minutes" and
"10-20 minutes" figures above were read off `calculated_at` and the poll
cadence. They are now measured directly against Transurban's own series, and
the relationship is far tighter than "converges": VDOT's published price for
interval *t* is *identical to the cent* to Transurban's live price from 10
minutes earlier, in 100% of 59,217 comparisons. The conclusion here is
unchanged and strengthened -- read section 9 for the numbers.

## 8. Splitting i95_route into i95_route + i495_route: cross-corridor trips are out of scope

*(2026-07-26)*

`i95_route` originally covered both the 495 Express Lanes and the 95/395
Express Lanes as one tool, joining a 495 leg and a 95/395 leg into a 2-leg
"composite" trip for any origin/destination pair that crossed between the
two. That joint was the exact source of the 16-id VDOT gap (section 2
above): every one of the 107 oracle pairs touching those ids crosses the
physical break between the two facilities at the Springfield interchange —
confirmed by walking `oracles/i95.json`, there is no dedicated
Express-to-Express ramp there, so a driver making that transition uses
general-purpose lanes for a stretch. Two rounds of special-casing (a
live-table fallback, then a `$0.00` gap placeholder) patched around that
joint without removing it.

A live bug report (a currently-`CLOSED` southbound leg still pricing
normally) led to re-examining the joint itself rather than adding a third
special case. expresslanes.com already treats the 495 Express Lanes and
the 95/395 Express Lanes as separate products, billed as separate tolls
with a general-purpose gap whose junction price is unavailable — the code's own
docstring said as much before this change. Splitting the *tools* to match
that product split removes the joint entirely, rather than patching around
it again:

- Of the 685 published pairs, 78 are within-495 only, 307 are within-95/395
  only, and 300 cross between the two facilities. Of those 300,
  107 touch one of the 16 gap ids; the other 193 have a real,
  already-VDOT-published second leg (e.g. `od_pair_id` 1263–1265) and
  priced correctly even before this change — they're dropped anyway, since
  a tool boundary drawn around "no gap ids" rather than "no cross-corridor
  trips" would still need this same seam revisited the next time VDOT
  drops coverage for some other cross-corridor leg.
- Zero within-facility pair is ever multi-leg — every trip either split
  tool resolves has exactly one leg. There is no composite-trip concept
  left in either tool.
- Zero node label is shared between the two facilities, so filtering the
  one committed `oracles/i95.json` down to each tool's own facility at
  import time introduces no new lookup ambiguity.
- The "direction must come from the pair, never the node id suffix"
  footgun (section basis for a standing code rule in both tools) turns out
  to be exclusively a cross-corridor phenomenon — every real
  suffix/direction mismatch checked against the full 685-pair oracle sits
  on a cross-corridor pair. It cannot occur within either split facility.
- `trip_pricing_i95` rows priced but unreachable via any oracle lookup
  split cleanly by corridor: `od_pair_id` 1316 (`I-95-SB`) stays i95's
  drift; 1000/1093 (`I-495-NB`/`I-495-SB`, both permanently
  `NO_DETERMINATION`/`UNKNOWN` dead links) plus 16 more real, actively
  priced `I-495` rows (1001–1008, and 1039/1047/1054/1061/1067/1073/1078/
  1084) become i495's drift — that second group is real Transurban
  billing for the *same* on-ramps as several within-495 ids, just under a
  distinct `od_pair_id` reserved for continuing past the junction into a
  cross-corridor trip (e.g. `od_pair_id` 1039 is "495 Express Lanes
  Start"'s own id when its trip continues cross-corridor, distinct from
  1040, the id the identical physical on-ramp gets for a trip that
  terminates at the junction itself — a within-495 trip `i495_route` does
  produce). Neither drift set was fully known before writing
  `tests/test_route_tools_live_crosscheck.py`'s corridor-scoped version of
  this check; both are asserted as exact sets there, not guessed.
- The one previously-working case this drops silently affects is the
  16-id gap's sole "trip terminates exactly at the junction" member,
  `od_pair_id` 1374 (`I-495 Near Braddock Road` → `I-395 Near Edsall
  Road`) — its destination *is* the first tollable point after the gap,
  so there's no cross-corridor second leg to drop in the first place. It
  keeps resolving, just now only via `i495_route` (not as a "cross-corridor
  trip" at all — it was always a same-facility trip once you notice the
  destination sits on the 495 side of the junction node).

Net effect on `i95_route`: the availability gate added for the bug report
(`link_status` must match the row's own `I-95-NB`/`I-95-SB` corridor's
`"{DIRECTION}_OPEN"`) is unchanged and is now the *only* pricing-stage
logic left in that tool — no live-table fallback, no gap placeholder, no
facility classification. `i495_route` is new, and structurally the
simplest of the three tools: single leg, no availability gate (verified
live, `I-495-NB`/`I-495-SB` never report a real `link_status`), no
live-fallback source.

### Direction-aware junction pricing boundary (2026-07-29)

The split remains, but the agent no longer treats Springfield/Van Dorn as a
free connector or adds the two ordinary boundary fares. A dedicated
`i95_junction_leg` reads both VDOT reversible-lane states at one requested
time. Southbound 95 pricing ends or begins at Edsall; northbound pricing ends
or begins at Franconia-Springfield. I-495 pricing independently begins or
ends at I-495 Near Braddock Road. The road between those boundaries is
unpriced, so cross-junction answers list known segment prices without a
subtotal or complete total.

## 9. VDOT republishes Transurban's price on a 10-minute delay

*(Measured 2026-07-28 over retained S3 payloads; the completed one-off
analysis script was retired 2026-07-30.)*

Section 7 inferred lag from `calculated_at` alone. This measures it against the
other source, over every retained raw payload -- 949 `i95` and 283 `i95-live`
objects -- with no new requests to either operator.

**A 10-minute shift makes the two sources identical.** VDOT's capture at tick
*t* against Transurban's at *t+offset*, over the 250 od pairs in both feeds.
"Movers only" keeps just the cases where Transurban's price changed at that
tick -- the answer to "do prices simply not move?":

| Transurban offset | exact match | movers only | p90 abs diff |
|---|---|---|---|
| -20 min | 35.3% of 58,967 | 11.8% of 31,525 | $1.15 |
| **-10 min** | **100.0% of 59,217** | **100.0% of 31,732** | **$0.00** |
| +0 min | 35.0% of 59,467 | **0.0% of 31,939** | $1.15 |
| +10 min | 33.4% of 59,467 | 9.1% of 31,939 | $1.85 |

The `+0 min` row is the clincher: VDOT *never* matches Transurban's concurrent
capture in the moment a price moves, and *always* matches the one from ten
minutes earlier. No shared od pair is flat (median 84 distinct values each), so
this is not a matching-everything artifact. Same result on two disjoint date
sub-ranges, and hand-checked through prod RDS: `trip_pricing_i95` at
`interval_end_at` 2026-07-28 10:10Z holds 1020=$7.20/1040=$9.20/1062=$4.90,
exactly the 10:00Z Transurban capture; the 10:10Z capture holds $7.00/$8.80/$4.60.

**These are not two independent sources** -- one price series published twice,
ten minutes apart. Crosschecking them validates transport, not pricing: once
aligned they agree by construction, and a "discrepancy" only measures delay.
That redundancy is why the live crosscheck and polling path were retired.

Supporting measurements:

- **VDOT's I-95 feed publishes every 10 minutes, on the mark, without fail** --
  949 objects, zero carrying more than one interval, zero repeating the
  previous one. I-66 is different: 6-minute intervals with a variable
  1–4-minute lag, so it has its own tick.
- **Transurban changes every 10 minutes too, around the clock** -- 272
  comparisons, zero unchanged, median 185 of 347 od pairs per tick. Its `time`
  field is nonetheless hourly, which is why `trip_pricing_i95_live` was
  re-keyed on `captured_at` in schema 4.0.0.
- **Our own capture added 3.5 minutes of pure staleness, now removed.**
  `rate(10 minutes)` had drifted to a steady 212s past each boundary;
  `cron(0/10)` cut capture staleness to 10m40s, the rest being VDOT's own lag.

One trap worth recording: raw object *keys* are the fetcher's clock floored by
whatever cadence it ran at, and that has already changed once -- on 2026-07-26
the express fetcher ran a 30-minute tick, so its `0000Z` key holds a payload
fetched at 00:23:31. Aligning the two feeds by key name manufactures a spurious
30-minute lag. The measurement therefore aligned captures on S3
`LastModified`.

## What was deleted, and what remains

The deleted surface was `db/graph.sql`, free-form SQL/schema tools, their
hand-maintained JSON contracts, and their graph audits. The current surface is
the poller and per-feed pricing tables, four committed route oracles, and five
narrow tools documented in `docs/oracle-tools-spec.md`.
