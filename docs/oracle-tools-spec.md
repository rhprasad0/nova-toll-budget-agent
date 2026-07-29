# Oracle Route Tools — Spec

Status: implemented · Owner: Ryan Prasad · Last updated: 2026-07-29

Five Strands Agents SDK `@tool` functions, `i66_route`, `i95_route`,
`i95_junction_leg`, `i495_route`, and `dulles_route`, resolve a human trip ("from X to Y", at an
optional time) to its route and its price. `agent/toll_agent.py` embeds the
priceable labels from the same committed route oracles in its system prompt,
so it can match vague or misspelled user locations before calling one of the
tools. Companion docs:
`docs/oracle-findings.md` (what the i66/i95/i495 oracles are and their
known gaps, including §8 on why i95_route/i495_route don't resolve
cross-corridor trips), `docs/poller-spec.md` (the pricing tables and the
`pricing_reader` role i66_route/i95_route/i495_route query),
`scripts/build_dulles_oracle.py`'s docstring (sourcing and documented
assumptions behind the Dulles oracles).

`dulles_route` differs from the other three in one structural way worth
stating up front: the Dulles Toll Road and Dulles Greenway are fixed-toll
roads with no price history, so pricing lives directly in the committed
oracles (`oracles/dulles_toll_road.json`, `oracles/dulles_greenway.json`)
rather than RDS -- this tool never opens a database connection. Route
resolution, error shapes, and the `at_time` parameter otherwise follow the
same conventions as `i66_route`/`i95_route`/`i495_route`, documented below
alongside them; sections that are i66/i95/i495-specific say so.

## 1. Scope

This repo previously had a much larger agent tool layer — free-form
read-only SQL access plus a curated, cross-feed toll graph with multi-hop
routing (`lambdas/agent/*`, deleted in commit `4eb5341`). That layer was
removed because the team reversed course on letting an agent query Postgres
directly. These tools reopen DB access, but narrowly and deliberately, not
a return to that surface:

- **DB access uses fixed, parameterized SELECT queries against known VDOT
  relations** (`current_trip_pricing_i66`/`trip_pricing_i66` for
  i66, `current_trip_pricing_i95`/`trip_pricing_i95` for both i95 and i495),
  via a SELECT-only role (`pricing_reader`, `db/roles.sql`)
  with no INSERT/UPDATE and no access to anything else in the database —
  never free-form SQL, never a schema the caller can explore.
- **No multi-hop routing, and no cross-corridor trips.** All three oracles
  are fare calculators, not adjacency lists — VDOT and Transurban already
  enumerate every valid direction+entry+exit trip directly. i95 and i495
  both filter the same committed `oracles/i95.json` (685 published pairs,
  107 ramps) down to their own facility at import time: i95_route.py keeps
  the 307 pairs that start and end on the 95/395 Express Lanes, i495_route.py
  keeps the 78 that start and end on the 495 Express Lanes. The other 300
  pairs — trips that cross between the two facilities — are resolvable by
  **neither** ordinary route tool. `i95_junction_leg` selects the usable
  direction-specific 95 segment; `i495_route` prices independently from or
  to I-495 Near Braddock Road. The caller must not combine those prices
  because the junction between them is unpriced. This was a
  deliberate split (not the original design — see
  `docs/oracle-findings.md` §8 for why), and it means every within-facility
  trip either tool ever resolves has exactly one leg: there is no
  composite/multi-leg concept left in either tool.
- **Pricing is a second stage, run only after a successful route
  resolution.** An omitted `at_time` reads the current VDOT view; an explicit
  time reads VDOT history. See §3.
- **`at_time` is optional, defaulting to now (America/New_York).** Neither
  oracle encodes time-of-day, so it plays no role in route resolution — it
  only selects which published price row to use.
- **Shared scaffolding lives in `agent_tools/_oracle_route.py`**, used by
  i95_route.py and i495_route.py: label lookup/matching, `at_time` parsing,
  the RDS connection, and the response envelope are byte-identical between
  the two, so they're extracted once rather than duplicated a third time
  (i66_route.py still carries its own copy — it predates this split, isn't
  part of it, and migrating it buys nothing beyond DRY-ness).

## 2. Resolution rules

All three tools accept `origin`/`destination` as either:
- the oracle's own `label` field, matched case-insensitively (e.g.
  `"Route 267"`, `"i-66 west"`), or
- the oracle's raw node id as a fallback (e.g. `"182NO"`, `"4"`).

A pair matches when `entry` resolves into the origin's candidate node ids and
`exit` resolves into the destination's. Verified directly against each
tool's own oracle subset:

- i66: `(entry, exit)` node-id pairs are unique across all 96 pairs.
- i95/i495: `(entry, exit)` id pairs **and** `(entry_label, exit_label)`
  casefolded pairs are both unique within each facility's subset — even
  though most labels are each carried by more than one node id (e.g.
  `"Westpark Drive"` maps to 5 ids on the 495 side, `"I-395 Near Edsall
  Road"` to 4 on the 95/395 side), the label pair alone still resolves a
  trip unambiguously today. No label is shared between the two facilities
  (verified: zero overlap), so filtering the shared oracle at import time
  introduces no new ambiguity risk.

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
  are exit-only (e.g. i66's `Westmoreland St`, i495's `495 Express Lanes
  End/George Wash. Mem. Pkwy.`); suggesting one of those as an origin would
  guarantee the caller's next call also fails. (Found by adversarial review,
  2026-07-25 — the first version of this tool suggested the full,
  role-unfiltered label list here.) A cross-corridor destination on the
  *other* tool's facility is simply not a label either tool's oracle subset
  knows about, so it falls into this same "unknown identifier" path, not a
  distinct error.
- unknown destination → the mirror image: labels that appear as some pair's
  `exit` only.
- a known origin with no direct trip to a known destination → only the
  labels actually reachable from that origin
- (unreachable today) ambiguous match → the candidate node ids
- a malformed `at_time`, or a pricing miss (§3) → `valid_options` is empty —
  neither failure has a self-correction candidate list, and retrying the
  same inputs won't fix either.
- `direction` always comes from the oracle pair's own `direction` field,
  **never** inferred from a node id's suffix — `182NO`/`181ND` etc. are
  suffixed `NO`/`ND`/`SO`/`SD`, but that suffix does not reliably match the
  node's own `direction`. Verified: the one real-data case where this
  suffix/direction mismatch ever occurred was exclusively on a
  cross-corridor pair, so it can't arise within either facility's subset
  today — but the rule (read `direction` off the pair, never the id) stays,
  since it's cheap and the invariant isn't permanently guaranteed either.

## 3. Pricing and output shape

Once a route resolves, the leg's key is looked up in Postgres, connecting
as `pricing_reader` (`db/roles.sql`, `docs/poller-spec.md`). With no
`at_time`, the price comes from the VDOT current-price view; with an explicit
`at_time`, it is **the most recently published row at or before that time**.
Neither is "the price this instant." VDOT's own feed trails real-time by
roughly 10–20 minutes (`docs/oracle-findings.md` §7), so even a default
request answers "what did VDOT last publish," not "what is it right now."
`priced_as_of` is the selected pricing interval end and
`observed_at` is VDOT's source `calculated_at` timestamp for that fare;
the agent reports both in `America/New_York` rather than papering over the lag.

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
     "corridor_name": "I-66-EB", "priced_as_of": "2026-07-26T14:20:00-04:00",
     "observed_at": "2026-07-26T14:10:00-04:00"}
  ],
  "total_usd": "4.50"
}
```

i95 success:
```json
{
  "origin": "US-1",
  "destination": "I-395 Near Edsall Road",
  "direction": "Northbound",
  "entry": {"node_id": "210NO", "label": "US-1"},
  "exit": {"node_id": "201ND", "label": "I-395 Near Edsall Road"},
  "at_time": "2026-07-26T14:32:00-04:00",
  "legs": [
    {"od_pair_id": 1132, "price_usd": "7.20", "corridor_name": "I-95-NB",
     "priced_as_of": "2026-07-26T14:20:00-04:00",
     "observed_at": "2026-07-26T14:10:00-04:00"}
  ],
  "total_usd": "7.20"
}
```

i495 success (same shape, `corridor_name` is `I-495-NB`/`I-495-SB` instead):
```json
{
  "origin": "Route 267",
  "destination": "495 Express Lanes End/George Wash. Mem. Pkwy.",
  "direction": "Northbound",
  "entry": {"node_id": "182NO", "label": "Route 267"},
  "exit": {"node_id": "181ND", "label": "495 Express Lanes End/George Wash. Mem. Pkwy."},
  "at_time": "2026-07-26T14:32:00-04:00",
  "legs": [
    {"od_pair_id": 1038, "price_usd": "2.60", "corridor_name": "I-495-NB",
     "priced_as_of": "2026-07-26T14:20:00-04:00",
     "observed_at": "2026-07-26T14:10:00-04:00"}
  ],
  "total_usd": "2.60"
}
```

- `origin`/`destination` echo the caller's raw input strings (audit
  clarity — what was asked, versus `entry`/`exit`, what actually matched).
- `legs` has exactly one entry for every tool now — no composite/multi-leg
  shape anywhere. `price_usd`/`total_usd` values are decimal strings, never
  `float`. Every VDOT-backed leg additionally has `observed_at`, an
  ISO-8601 timestamp sourced from the row's `calculated_at` column. Dulles
  legs have no `observed_at` because they do not query VDOT data.
- There is no `source` or `facility_group` field on any tool's leg — each
  tool only ever prices from one table/corridor pair now, so both would be
  constants. (Before the i495 split, i95_route carried both, plus
  `facility_totals`, to support cross-corridor trips and a live-table
  fallback for VDOT's unpublished gap ids — all removed along with that
  capability. See `docs/oracle-findings.md` §8.)

**i95's row is only usable if its lane is actually open, not just because
it has a rate** (`docs/poller-spec.md`'s "Rate/status independence"
warning — rows can be `CLOSED` with a stale nonzero rate). `link_status`
must exactly match the row's own corridor's `"{DIRECTION}_OPEN"`
(`CLOSED`/`NO_DETERMINATION`/any `*_CLOSING`/`*_OPENING` all fail, and a
`corridor_name` outside `{I-95-NB, I-95-SB}` is a hard error — schema
drift, since this tool's oracle filter should never produce anything
else). A missing or unavailable row is a hard error for the whole call;
there's no fallback source. This is the exact mechanism that flags a
genuinely closed lane (e.g. `I-395 Near Edsall Road → US-1` southbound)
instead of silently pricing it — the error message names the corridor and
`link_status`, so a caller can tell "closed" apart from "no data at all."

**i495 applies no availability gate at all** — verified live against RDS,
100% of `I-495-NB`/`I-495-SB` history reports `link_status`
`NO_DETERMINATION`/`UNKNOWN`, never a real `*_OPEN` value, despite carrying
real fluctuating nonzero rates. The 495 Express Lanes aren't reversible,
so VDOT simply never publishes a meaningful open/closed signal for that
corridor; gating on it would hard-error every 495 trip, unconditionally.
A missing row is still a hard error — there's no live-fallback source here
either.

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
  Dumping a large label list into every failed-lookup log line is noise,
  not signal; the error string already names what didn't match.

This is the audit trail *today*. If/when these tools deploy behind Strands
on Bedrock AgentCore Runtime, native OpenTelemetry traces — the same answer
the deleted agent-tools-spec gave to this question — supersede these log
lines as the actual audit record. Stated here so the log lines aren't
mistaken for the final story.

## 5. Contracts and tests

- The contract of record is each tool's own docstring — that is literally
  what Strands turns into the tool spec the model sees, so it cannot drift
  from what ships. A parallel `schemas/tools/*.json` set used to exist
  alongside it; it was deleted, along with `tests/test_tool_schemas.py`,
  because nothing read those files at runtime and that test only asserted
  the schema files' own shape (present, semver'd, has `input`/`output`) —
  never a tool's actual output against a schema. A hand-maintained
  duplicate guarded only by a test of itself is a closed loop: two things
  to update, one source of truth, no check that they agree. If an
  external consumer ever needs a published JSON Schema, generate it from
  `tool_spec` rather than hand-writing a second copy. The tests do assert
  `tool_spec["name"]` and `tool_spec["inputSchema"]["json"]["required"]`
  for every tool — parametrized over the three ordinary RDS-backed route
  tools in `test_route_tools.py`, plus focused junction and Dulles assertions
  in their own test modules — as a cheap check that Strands actually parsed the
  docstring (required stays `{"origin", "destination"}` for the route tools
  — `at_time` is optional).
- `agent_tools/tests/test_route_tools.py`: the behaviour all three
  RDS-backed tools share, table-driven over one `Case` per tool — label
  lookup, case-insensitivity, node-id fallback, unknown-identifier errors,
  known-but-unconnected-pair errors, the synthetic ambiguous-match case,
  logging assertions for both outcomes, `at_time` pass-through, and a
  price-not-found hard error. It replaced three near-identical per-tool
  modules once the shared tool body moved into `_oracle_route.run()`;
  adding a fourth RDS-backed tool means adding a `Case`, not a file.
  `test_i95_route.py` keeps only what is genuinely i95-specific: the
  availability gate's branches (a closed and a wrong-direction
  `I-95-NB`/`I-95-SB` row each hard-erroring, an unrecognized
  `corridor_name` hard-erroring) and a label-shared-by-multiple-node-ids
  case. It also covers `i95_junction_leg` selecting Edsall or
  Franconia-Springfield, and failing safe for closed, transitional,
  ambiguous, missing, or misaligned status rows. `test_oracle_route.py` covers `resolve_at_time`'s
  parsing/defaulting once, where the one implementation lives.
  Pricing tests use a duck-typed fake connection/cursor
  (`agent_tools/tests/conftest.py`'s `FakeConnection`) via `monkeypatch`,
  not real RDS — no `live` marker. Each tool module still aliases
  `_oracle_route.env_connect` to a local `_env_connect`, and
  `_oracle_route.run()` takes that alias as its `connect` argument
  specifically so this monkeypatch convention keeps working even though
  the implementation lives in the shared module.
  `agent_tools/tests/test_no_psycopg_at_import.py` guards that importing
  any RDS tool module never pulls in `psycopg` (it's a real
  dependency now, but `_oracle_route.env_connect()` imports it lazily).
- Existing `tests/test_i66_oracle.py`/`test_i95_oracle.py` (shape/scale
  guards on the oracle files themselves) are unchanged and relied upon, not
  duplicated.
- `tests/test_route_tools_live_crosscheck.py` (marked `live`, run explicitly
  with `-m live`): walks every oracle pair each tool's own facility subset
  through `_lookup()` (route resolution only, not the now-pricing-aware
  decorated tools — see the file's own docstring for why) and cross-checks
  the returned keys against live RDS in both directions — every
  tool-producible key has a priced row, and every priced row on that tool's
  own corridor is tool-producible (except a small known oracle-drift set
  per tool, documented inline and verified by querying `corridor_name`
  directly rather than guessed). Connects as `pricing_reader`. A small
  separate set of tests in the same file calls the actual, pricing-aware
  `i66_route()`/`i95_route()`/`i495_route()` end to end against live RDS:
  one ordinary pair each, plus a direct live regression check that i95's
  currently-closed southbound direction (the original bug report) comes
  back as a named error, never a price.

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

Both oracles carry ordered nonzero `charges` on every pair, each with
`price_peak_usd`/`price_off_peak_usd` (the Dulles Toll Road's two values are
always equal). This preserves the individual charge facts instead of storing
a pre-summed fare. Every leg carries a
`rate_period` field: `"peak"`/`"off_peak"` for a `dulles_greenway` leg,
`null` for a `dulles_toll_road` leg (reporting `"off_peak"` there would
imply a peak rate exists, which it doesn't).

**Cross-facility trips.** The two roads are one continuous physical
corridor, connected at Route 28 — a node with the identical label in both
oracles. A trip confined to one facility resolves as a single leg, same as
`i66_route`. A trip starting on one facility and ending on the other
resolves as **two legs, split at Route 28** — origin→Route 28 on the first
facility, Route 28→destination on the second. The success response returns
route `legs` plus a flat, travel-ordered `tolls` list; each item has
`facility`, `label`, and decimal-string `price_usd`. It omits zero-dollar
segments; an empty `tolls` list explicitly means no toll applies. It
intentionally has no `total_usd` or `facility_totals`, so the calling agent
can show the addition (or `$0.00 = $0.00`). This matches real billing: the two
operators charge independently, never one combined fare.

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
unlike i66/i95/i495's test files.
