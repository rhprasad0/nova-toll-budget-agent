# Oracle Route Tools — Spec

Status: implemented · Owner: Ryan Prasad · Last updated: 2026-07-26

Two Strands Agents SDK `@tool` functions, `i66_route` and `i95_route`, that
resolve a human trip ("from X to Y", at an optional time) to its route and
its price. Companion docs: `docs/oracle-findings.md` (what the oracles are
and their known gaps), `docs/poller-spec.md` (the pricing tables and the
`pricing_reader` role these tools query).

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

**A row is only usable if its lane is actually open, not just because it
has a rate** (`docs/poller-spec.md`'s "Rate/status independence" warning —
rows can be `CLOSED` with a stale nonzero rate). For `trip_pricing_i95`,
this only gates the reversible `I-95-NB`/`I-95-SB` corridor: `link_status`
must exactly match that row's own corridor's `"{DIRECTION}_OPEN"`
(`CLOSED`/`NO_DETERMINATION`/any `*_CLOSING`/`*_OPENING` all fail).
`I-495-NB`/`I-495-SB` rows are exempt — verified live, 100% of that
corridor's history reports `NO_DETERMINATION`/`UNKNOWN`, never `*_OPEN`,
because the 495 Express Lanes aren't reversible and VDOT never populates a
meaningful status there; gating them would hard-error every 495 trip. For
`trip_pricing_i95_live`, a row is gated uniformly: usable unless `status` is
case-insensitively `"closed"`. A row that fails its gate is treated exactly
like a missing row — same fallthrough as below, never a separate branch.

**A leg means the trip is published, not that a real price was found for
it.** 16 of i95's `od_pair_id`s (1374–1389, spanning roughly 107 of
Transurban's 562 billed trips) have never appeared in VDOT's feed
(`docs/oracle-findings.md` §2). For those, the tool falls back to
Transurban's own live snapshot (`trip_pricing_i95_live`,
`docs/poller-spec.md`'s "Secondary live source"); if even that has no
*usable* row for the requested `at_time` (e.g. a time before the live
table's own ingestion start, a moment the relevant lane direction was
closed with no stored row, or a stored row that fails the availability gate
above), the leg prices at `"0.00"` with `"source": "unpriced_gap"` instead
of failing the whole call — a flagged placeholder, never a claim that the
trip is actually free. Any other missing or unavailable price — a non-gap
`od_pair_id` whose only known row(s) are closed/unavailable, or any i66
zone pair, neither of which has a live-fallback source — is a hard error
for the whole call (the message names the corridor and `link_status`, so a
caller can tell "closed" apart from "no data at all"), discarding any other
leg's already-found price rather than returning a partial result. Evals for
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
  classification value plus the unrecognized-value hard error, `at_time`
  parsing/defaulting, and the availability gate's own branches (a closed
  and a wrong-direction `I-95-NB`/`I-95-SB` primary row each hard-erroring,
  an `I-495` row bypassing the gate under `NO_DETERMINATION`, a closed
  primary row falling through to an open live row, and a closed live
  `status` falling through to the gap placeholder). Pricing tests use a duck-typed fake
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
