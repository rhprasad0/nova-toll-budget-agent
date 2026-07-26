# Oracle Route Tools — Spec

Status: implemented · Owner: Ryan Prasad · Last updated: 2026-07-26

Three Strands Agents SDK `@tool` functions, `i66_route`, `i95_route`, and
`dulles_route`, that resolve a human trip ("from X to Y", at an optional
time) to its route and its price. Companion docs: `docs/oracle-findings.md`
(what the i66/i95 oracles are and their known gaps), `docs/poller-spec.md`
(the pricing tables and the `pricing_reader` role i66_route/i95_route
query), `scripts/build_dulles_oracle.py`'s docstring (sourcing and
documented assumptions behind the Dulles oracles).

`dulles_route` differs from the other two in one structural way worth
stating up front: the Dulles Toll Road and Dulles Greenway are fixed-toll
roads with no price history, so pricing lives directly in the committed
oracles (`oracles/dulles_toll_road.json`, `oracles/dulles_greenway.json`)
rather than RDS -- this tool never opens a database connection. Route
resolution, error shapes, and the `at_time` parameter otherwise follow the
same conventions as `i66_route`/`i95_route`, documented below alongside
them; sections that are i66/i95-specific say so.

## 1. Scope

This repo previously had a much larger agent tool layer — free-form
read-only SQL access plus a curated, cross-feed toll graph with multi-hop
routing (`lambdas/agent/*`, deleted in commit `4eb5341`). That layer was
removed because the team reversed course on letting an agent query Postgres
directly. These two tools reopen DB access, but narrowly and deliberately,
not a return to that surface:

- **DB access is two fixed, parameterized SELECT queries against three known
  tables** (`trip_pricing_i66`, `trip_pricing_i95`, `trip_pricing_i95_live`),
  via a SELECT-only role (`pricing_reader`, `db/roles.sql`) with no
  INSERT/UPDATE and no access to anything else in the database — never
  free-form SQL, never a schema the caller can explore.
- **No multi-hop routing.** Both oracles are fare calculators, not adjacency
  lists — VDOT and Transurban already enumerate every valid
  direction+entry+exit trip directly (96 pairs / 17 interchanges for i66,
  685 pairs / 107 ramps for i95). Route resolution is a single flat lookup:
  resolve origin/destination, find the one matching pair, take its price
  key(s). Chaining two oracle pairs to synthesize a trip is never correct —
  i95's 295 cross-corridor trips are already flattened into one pair
  carrying two `od_pair_id`s in billed order, because Transurban bills them
  as two whole separate tolls, never a summed sub-segment.
- **Pricing is a second stage, run only after a successful route
  resolution.** Each resolved key is looked up in Postgres as of `at_time`;
  see §3.
- **`at_time` is optional, defaulting to now (America/New_York).** Neither
  oracle encodes time-of-day, so it plays no role in route resolution — it
  only selects which published price row to use.
- **Combining the two tools into one cross-corridor 495↔95/395 trip is out
  of scope.** That junction has no dedicated Express-to-Express ramp — a
  driver physically crosses through general-purpose lanes at the Springfield
  Interchange — so a caller needing a full multi-facility trip calls both
  tools and combines their results itself; this repo doesn't do that
  combining for them (unscoped, future agent's job).

## 2. Resolution rules

Both tools accept `origin`/`destination` as either:
- the oracle's own `label` field, matched case-insensitively (e.g.
  `"Route 267"`, `"i-66 west"`), or
- the oracle's raw node id as a fallback (e.g. `"182NO"`, `"4"`).

A pair matches when `entry` resolves into the origin's candidate node ids and
`exit` resolves into the destination's. Verified directly against both
committed oracles:

- i66: `(entry, exit)` node-id pairs are unique across all 96 pairs.
- i95: `(entry, exit)` id pairs **and** `(entry_label, exit_label)`
  casefolded pairs are both unique across all 685 pairs — even though 32 of
  i95's 44 distinct labels are each carried by more than one node id (95 of
  107 ids in total; e.g. `"Westpark Drive"` maps to 5 ids), the label pair
  alone still resolves a trip unambiguously today.

An `len(matches) > 1` ambiguous-match guard exists in code but is
unreachable against today's data — it's covered by a synthetic-data test in
each tool's test file, not a real-data case, because the oracles do get
refreshed and this invariant isn't permanently guaranteed.

A route-resolution failure never touches the database — pricing only runs
after `_lookup()` succeeds. Errors never raise; they return `{"error": str,
"valid_options": [str, ...]}` so a calling agent can self-correct without
another round trip where that's possible:
- unknown origin → labels that can actually serve as an origin (appear as
  some pair's `entry`) — **not** the full label list. Some interchanges/ramps
  are exit-only (e.g. i66's `Westmoreland St`, i95's `495 Express Lanes
  End/George Wash. Mem. Pkwy.`); suggesting one of those as an origin would
  guarantee the caller's next call also fails. (Found by adversarial review,
  2026-07-25 — the first version of this tool suggested the full,
  role-unfiltered label list here.)
- unknown destination → the mirror image: labels that appear as some pair's
  `exit` only.
- a known origin with no direct trip to a known destination → only the
  labels actually reachable from that origin
- (unreachable today) ambiguous match → the candidate node ids
- a malformed `at_time`, or a pricing miss (§3) → `valid_options` is empty —
  neither failure has a self-correction candidate list, and retrying the
  same inputs won't fix either.

## 3. Pricing and output shape

Once a route resolves, each leg's key is looked up in Postgres, connecting
as `pricing_reader` (`db/roles.sql`, `docs/poller-spec.md`). The price
returned for each leg is **the most recently published row at or before
`at_time`** — never "the price this instant." VDOT's own feed trails
real-time by roughly 10–20 minutes (`docs/oracle-findings.md` §7), so even a
default `at_time` of "now" answers "what did VDOT/Transurban last publish,"
not "what is it right now" — each leg's `priced_as_of` exposes exactly how
stale the number is, rather than papering over the lag.

i66 success:
```json
{
  "origin": "I-66 West",
  "destination": "Westmoreland St",
  "direction": "EB",
  "entry": {"node_id": "1", "label": "I-66 West"},
  "exit": {"node_id": "10", "label": "Westmoreland St"},
  "at_time": "2026-07-26T14:32:00-04:00",
  "legs": [
    {"start_zone_id": 3100, "end_zone_id": 3110, "price_usd": "4.50",
     "corridor_name": "I-66-EB", "priced_as_of": "2026-07-26T14:20:00-04:00"}
  ],
  "total_usd": "4.50"
}
```

i95 success, a composite trip spanning both an ordinary VDOT-priced leg and
a known-gap leg:
```json
{
  "origin": "I-495 Near Braddock Road",
  "destination": "I-395 Near Edsall Road",
  "direction": "Northbound",
  "entry": {"node_id": "191NO", "label": "I-495 Near Braddock Road"},
  "exit": {"node_id": "201ND", "label": "I-395 Near Edsall Road"},
  "at_time": "2026-07-26T14:32:00-04:00",
  "legs": [
    {"od_pair_id": 1083, "price_usd": "6.60", "source": "trip_pricing_i95",
     "facility_group": "495", "corridor_name": "I-495-NB",
     "priced_as_of": "2026-07-26T14:20:00-04:00"},
    {"od_pair_id": 1374, "price_usd": "3.45", "source": "trip_pricing_i95_live",
     "facility_group": "495", "corridor_name": null,
     "priced_as_of": "2026-07-26T14:30:00-04:00"}
  ],
  "facility_totals": {"495": "10.05", "95_395": "0.00"},
  "total_usd": "10.05"
}
```

- `origin`/`destination` echo the caller's raw input strings (audit
  clarity — what was asked, versus `entry`/`exit`, what actually matched).
- `direction` always comes from the oracle pair's own `direction` field,
  **never** inferred from an i95 node id's suffix — `182NO`/`181ND` etc. are
  suffixed `NO`/`ND`/`SO`/`SD`, but that suffix does not reliably match the
  node's own `direction` (a real node in the oracle carries an `ND` suffix
  with `direction: "Southbound"`). Reading direction off the suffix is the
  exact footgun this rule exists to prevent.
- `legs` has exactly one entry for i66; one for an i95 within-corridor trip,
  two for a cross-corridor trip, in the oracle's own billed order.
  `price_usd`/`total_usd`/`facility_totals` values are decimal strings,
  never `float`.
- i95's `facility_group` — `"495"` or `"95_395"` — mirrors
  expresslanes.com's own split of the 495 Express Lanes from the 95/395
  Express Lanes as separate products, classified from `trip_pricing_i95`'s
  `corridor_name` (`I-495-NB`/`I-495-SB` vs `I-95-NB`/`I-95-SB` — VDOT
  doesn't split 395 into its own corridor_name, which matches
  expresslanes.com's own "95 Express Lanes" facility bundling 395 too) or
  `trip_pricing_i95_live`'s `road` (`"495"` vs `"95"`/`"395"`) depending on
  which source priced the leg. An unrecognized value (schema drift beyond
  what's been verified live) is a hard error, not a silent guess.
- `facility_totals` always carries both keys (`"0.00"` if a group has no
  legs) — a stable shape, no branching on key presence.

**A leg means the trip is published, not that a real price was found for
it.** 16 of i95's `od_pair_id`s (1374–1389, spanning roughly 107 of
Transurban's 562 billed trips) have never appeared in VDOT's feed
(`docs/oracle-findings.md` §2). For those, the tool falls back to
Transurban's own live snapshot (`trip_pricing_i95_live`,
`docs/poller-spec.md`'s "Secondary live source"); if even that has no row
for the requested `at_time` (e.g. a time before the live table's own
ingestion start, or a moment the relevant lane direction was closed with no
stored row), the leg prices at `"0.00"` with `"source": "unpriced_gap"`
instead of failing the whole call — a flagged placeholder, never a claim
that the trip is actually free. Any other missing price — a non-gap
`od_pair_id`, or any i66 zone pair, neither of which has a live-fallback
source — is a hard error for the whole call, discarding any other leg's
already-found price rather than returning a partial result. Evals for
whether `$0.00` is the right stand-in for the gap case are future work; this
is a v1 default.

Confirmed (2026-07-26, walking `oracles/i95.json`): all 107 oracle pairs
touching the 16 gap ids cross the physical break between the 495 Express
Lanes and the 95/395 Express Lanes at the Springfield Interchange — there is
no dedicated Express-to-Express ramp there, so a driver making that
transition uses general-purpose lanes for a stretch (this is also why
cross-corridor trips are billed as two whole separate tolls at all: they are
genuinely two separate tolled facilities with an untolled gap between them).
Every gap id therefore defaults to the `"495"` facility group when unpriced
— `facility_group` reflects which toll product is billing, not literally
which road the destination sits on, and this is the one place that
distinction is visible.

## 4. Audit logging

The user-facing requirement for these tools is auditability: every call
needs to be traceable to what was asked, what matched, and what came back.
Each tool logs one `INFO` line per call via `logging.getLogger(__name__)`
(never the root logger, and no `setLevel()` call at import — these are
library modules imported into a future host process, not entrypoints, so
they must not stomp the host's logging configuration):

- success: origin, destination, resolved entry/exit node ids, direction,
  `at_time`, `total_usd`, legs
- failure (route resolution, malformed `at_time`, or a pricing miss):
  origin, destination, the error string — **never** `valid_options`.
  Dumping a 17–107-item label list into every failed-lookup log line is
  noise, not signal; the error string already names what didn't match.

This is the audit trail *today*. If/when these tools deploy behind Strands
on Bedrock AgentCore Runtime, native OpenTelemetry traces — the same answer
the deleted agent-tools-spec gave to this question — supersede these log
lines as the actual audit record. Stated here so the log lines aren't
mistaken for the final story.

## 5. Contracts and tests

- `schemas/tools/i66_route.json` / `i95_route.json`: JSON Schema Draft
  2020-12, `input`/`output` (`oneOf` success/error), examples, semver'd.
  Bumped `1.0.0` → `2.0.0` for the pricing addition (breaking output-shape
  change). Structural shape (file exists, has `input`/`output`, semver'd
  version, `at_time` declared as an optional input property) is guarded by
  `tests/test_tool_schemas.py`. No drift test against the live
  Strands-generated tool spec — that was worthwhile for the deleted 4-tool
  SQL surface; two fixed tools don't earn a second CI-enforced contract
  layer. Each tool's own test file does assert `tool_spec["name"]` and
  `tool_spec["inputSchema"]["json"]["required"]` once, as a cheap check that
  Strands actually parsed the docstring (required stays `{"origin",
  "destination"}` — `at_time` is optional).
- `agent_tools/tests/test_i66_route.py` / `test_i95_route.py`: label lookup,
  case-insensitivity, node-id fallback, unknown-identifier errors,
  known-but-unconnected-pair errors, the synthetic ambiguous-match case, the
  i95 composite two-leg case, the direction-vs-suffix footgun, a
  label-shared-by-multiple-node-ids case, logging assertions for both
  outcomes, and (new) the pricing stage's every branch — primary-table hit,
  i95's live-table fallback, the known-gap-id `$0.00` default, a non-gap
  price miss as a hard error, a two-leg partial failure, every facility
  classification value plus the unrecognized-value hard error, and
  `at_time` parsing/defaulting. Pricing tests use a duck-typed fake
  connection/cursor (`agent_tools/tests/conftest.py`'s `FakeConnection`) via
  `monkeypatch`, not real RDS — no `live` marker.
  `agent_tools/tests/test_no_psycopg_at_import.py` guards that importing
  either module never pulls in `psycopg` (it's a real dependency now, but
  `_env_connect()` imports it lazily).
- Existing `tests/test_i66_oracle.py`/`test_i95_oracle.py` (shape/scale
  guards on the oracle files themselves) are unchanged and relied upon, not
  duplicated.
- `tests/test_route_tools_live_crosscheck.py` (marked `live`, run explicitly
  with `-m live`): walks every oracle pair through `_lookup()` (route
  resolution only, not the now-pricing-aware decorated tools — see the
  file's own docstring for why) and cross-checks the returned keys against
  live RDS in both directions — every tool-producible key has a priced row
  (except the known VDOT gap), and every priced row is tool-producible
  (except a small known oracle-drift set, documented inline). Connects as
  `pricing_reader`. A small separate set of tests in the same file calls the
  actual, pricing-aware `i66_route()`/`i95_route()` end to end against live
  RDS for one ordinary pair each plus one gap-id pair, confirming a real
  connection succeeds and the gap id never errors.

## 6. `dulles_route` specifics

The Dulles Toll Road (MWAA) and Dulles Greenway (TRIP II) are fixed-toll
roads, not dynamically priced — so `dulles_route` deliberately breaks from
§1-§5 in one respect: **no RDS**. Pricing lives directly in the committed
oracles (`oracles/dulles_toll_road.json`, `oracles/dulles_greenway.json`),
hand-authored (not scraped — neither operator publishes a machine-readable
feed) by `scripts/build_dulles_oracle.py`. Everything else — flat-lookup
route resolution, `{"error", "valid_options"}` failure shape,
`at_time` accepted as ISO-8601 defaulting to now (America/New_York) — follows
§1-§2 as written.

**Two operators, two real pricing designs — not unified into one model:**
- **Dulles Toll Road: additive.** A $4.00 mainline-plaza toll (crossed
  between Exit 16 and Exit 17) plus a $2.00 ramp toll at each tolled
  interchange actually used, summed. No time-of-day variation. Exit 16's
  ramp toll applies to the eastbound exit only (quoted from source) — the
  westbound movement there is free.
- **Dulles Greenway: alternative flat fare, never summed.** "The Greenway
  does not offer a discount for partial usage" (its own published FAQ
  language) — a trip crossing the mainline plaza (between Exit 8 and Route
  28) pays the mainline rate ($5.80 peak / $5.25 off-peak); a trip confined
  to Exits 1-8 pays the lower secondary rate ($5.10 peak / $4.55 off-peak).
  Peak hours are 6:30-9:00am eastbound, 4:00-6:30pm westbound, **assumed
  weekday-only** — "rush hour" framing and industry convention support this,
  but no source explicitly excluded weekends; worth confirming before
  relying on it for a weekend trip.

Both oracles carry `price_peak_usd`/`price_off_peak_usd` on every pair (the
Dulles Toll Road's two values are always equal) so the tool has one pricing
code path instead of a per-facility branch. Every leg carries a
`rate_period` field: `"peak"`/`"off_peak"` for a `dulles_greenway` leg,
`null` for a `dulles_toll_road` leg (reporting `"off_peak"` there would
imply a peak rate exists, which it doesn't).

**Cross-facility trips.** The two roads are one continuous physical
corridor, connected at Route 28 — a node with the identical label in both
oracles. A trip confined to one facility resolves as a single leg, same as
`i66_route`. A trip starting on one facility and ending on the other
resolves as **two legs, split at Route 28 and summed** — origin→Route 28 on
the first facility, Route 28→destination on the second — mirroring how
`i95_route` handles a 495↔95/395 cross-corridor trip. This matches real
billing: the two operators charge independently, never one combined fare.
`facility_totals` always carries both `"dulles_toll_road"` and
`"dulles_greenway"` keys (`"0.00"` if a facility has no legs), same
stable-shape rule as i95's `facility_totals`.

**Data provenance and known limitations** — recorded in full in
`scripts/build_dulles_oracle.py`'s docstring and each oracle's `notes`
field, not duplicated here: rates are 2-axle E-ZPass only (no pay-by-plate,
no 3+ axle); the exit list and per-ramp toll amounts were cross-referenced
across public sources (no official machine-readable rate table exists to
verify against automatically) rather than confirmed against a single
authoritative source; Exit 16's directional asymmetry and the weekday-only
peak assumption are flagged explicitly as assumptions, not quoted facts.
Refresh by re-running `python scripts/build_dulles_oracle.py` after
updating its hand-transcribed rate constants — never at runtime.

Tests: `tests/test_dulles_toll_road_oracle.py` / `test_dulles_greenway_oracle.py`
(shape/scale guards mirroring `test_i66_oracle.py`, plus the
additive-vs-alternative pricing invariants above) and
`agent_tools/tests/test_dulles_route.py` (label lookup, case-insensitivity,
node-id fallback, unknown-identifier errors, single-facility trips on each
road, the cross-facility composite both directions, peak/off-peak/weekend
classification, the synthetic ambiguous-match guard, logging assertions) —
no RDS, so no `FakeConnection`/`monkeypatch` needed for the happy paths,
unlike i66/i95's test files.
