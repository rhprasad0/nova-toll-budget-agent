# Oracle Route Tools — Spec

Status: implemented · Owner: Ryan Prasad · Last updated: 2026-07-25

Two Strands Agents SDK `@tool` functions, `i66_route` and `i95_route`, that
resolve a human trip ("from X to Y") to the exact price-lookup key a future
agent would use to query `trip_pricing_i66`/`trip_pricing_i95`. Companion
docs: `docs/oracle-findings.md` (what the oracles are and their known gaps),
`docs/poller-spec.md` (the pricing tables these keys look up into).

## 1. Scope, deliberately narrow

This repo previously had a much larger agent tool layer — free-form
read-only SQL access plus a curated, cross-feed toll graph with multi-hop
routing (`lambdas/agent/*`, deleted in commit `4eb5341`). That layer was
removed because the team reversed course on letting an agent query Postgres
directly. These two tools do not reopen that door:

- **No database access.** They read only the two committed oracle files,
  `oracles/i66.json` and `oracles/i95.json`.
- **No multi-hop routing.** Both oracles are fare calculators, not adjacency
  lists — VDOT and Transurban already enumerate every valid
  direction+entry+exit trip directly (96 pairs / 17 interchanges for i66,
  685 pairs / 107 ramps for i95). Each tool is a single flat lookup: resolve
  origin/destination, find the one matching pair, return its price key(s).
  Chaining two oracle pairs to synthesize a trip is never correct — i95's
  295 cross-corridor trips are already flattened into one pair carrying two
  `od_pair_id`s in billed order, because Transurban bills them as two whole
  separate tolls, never a summed sub-segment.
- **No pricing.** A returned leg is a key, never a rate. Looking that key up
  in `trip_pricing_i66`/`trip_pricing_i95` is a separate, future tool.
- **No date/time parameter.** Neither oracle encodes any time-of-day
  information — that lives only in comments in the fetch scripts
  (`scripts/fetch_i66_oracle.py`, `scripts/fetch_i95_oracle.py`), never as
  structured data. A `at_time` argument here would be dead passthrough, so
  it was dropped rather than carried for a future step that doesn't exist
  yet.

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

Errors never raise; they return `{"error": str, "valid_options": [str, ...]}`
so a calling agent can self-correct without another round trip:
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

## 3. Output shape

Both tools return the same envelope, differing only in `legs`:

```json
{
  "origin": "Route 267",
  "destination": "495 Express Lanes End/George Wash. Mem. Pkwy.",
  "direction": "Northbound",
  "entry": {"node_id": "182NO", "label": "Route 267"},
  "exit": {"node_id": "181ND", "label": "495 Express Lanes End/George Wash. Mem. Pkwy."},
  "legs": [{"od_pair_id": 1038}]
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
- `legs` is a list so both feeds share one shape for a future pricing tool
  to iterate over: i66 always returns exactly one
  `{"start_zone_id", "end_zone_id"}` leg (the key into
  `trip_pricing_i66`); i95 returns one or two `{"od_pair_id"}` legs, in the
  oracle's own billed order, the key into `trip_pricing_i95.od_pair_id`
  alone (start/end zone columns also exist on that table but are not
  sufficient keys by themselves — see `docs/poller-spec.md`).

**A leg means the trip is published, not that it's priced.** 16 of i95's
`od_pair_id`s (1374–1389, spanning roughly 107 of Transurban's 562 billed
trips) have never appeared in VDOT's feed, so `trip_pricing_i95` holds zero
rows for them (`docs/oracle-findings.md` §2). This tool still returns those
ids — existence in the oracle is the contract, not priceability. No
`priceable` field was added to signal this; it would bake a frozen-today
upstream gap into the tool's output contract. The gap is documented here and
covered by a named test (`test_composite_leg_includes_the_known_vdot_pricing_gap`)
instead.

## 4. Audit logging

The user-facing requirement for these tools is auditability: every call
needs to be traceable to what was asked, what matched, and what came back.
Each tool logs one `INFO` line per call via `logging.getLogger(__name__)`
(never the root logger, and no `setLevel()` call at import — these are
library modules imported into a future host process, not entrypoints, so
they must not stomp the host's logging configuration):

- success: origin, destination, resolved entry/exit node ids, direction, legs
- failure: origin, destination, the error string — **never** `valid_options`.
  Dumping a 17–107-item label list into every failed-lookup log line is
  noise, not signal; the error string already names what didn't match.

This is the audit trail *today*. If/when these tools deploy behind Strands
on Bedrock AgentCore Runtime, native OpenTelemetry traces — the same answer
the deleted agent-tools-spec gave to this question — supersede these log
lines as the actual audit record. Stated here so the log lines aren't
mistaken for the final story.

## 5. Contracts and tests

- `schemas/tools/i66_route.json` / `i95_route.json`: JSON Schema Draft
  2020-12, `input`/`output` (`oneOf` success/error), examples, semver'd
  starting `1.0.0`. Structural shape (file exists, has `input`/`output`,
  semver'd version) is guarded by `tests/test_tool_schemas.py`. No drift
  test against the live Strands-generated tool spec — that was worthwhile
  for the deleted 4-tool SQL surface; two fixed 2-string-argument tools
  don't earn a second CI-enforced contract layer. Each tool's own test file
  does assert `tool_spec["name"]` and `tool_spec["inputSchema"]["json"]["required"]`
  once, as a cheap check that Strands actually parsed the docstring.
- `agent_tools/tests/test_i66_route.py` / `test_i95_route.py`: label lookup,
  case-insensitivity, node-id fallback, unknown-identifier errors,
  known-but-unconnected-pair errors, the synthetic ambiguous-match case, the
  i95 composite two-leg case (including the VDOT-gap-id case above), the
  direction-vs-suffix footgun, a label-shared-by-multiple-node-ids case, and
  logging assertions for both outcomes. All local JSON, no `live` marker.
- Existing `tests/test_i66_oracle.py`/`test_i95_oracle.py` (shape/scale
  guards on the oracle files themselves) are unchanged and relied upon, not
  duplicated.
- `tests/test_route_tools_live_crosscheck.py` (marked `live`, run explicitly
  with `-m live`): walks every oracle pair through the actual tools and
  cross-checks the returned keys against live RDS in both directions --
  every tool-producible key has a priced row (except the known VDOT gap,
  `docs/oracle-findings.md` §2), and every priced row is tool-producible
  (except a small known oracle-drift set, documented inline).
