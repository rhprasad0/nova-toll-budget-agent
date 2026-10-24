# Muse MCP Evals

Status: **specification only**. Nothing here runs yet; it defines the evals to
build for the TollChat MCP server (`v2/lambdas/mcp_server/`) and for Muse, Meta's
personal agent, using it.

These evals are separate from the TollChat agent's evaluation suite. The MCP
tools deliberately drift from the agent's tools, so they share no cases, judges,
harness digests, or release gates with `v2/eval/`.

## 1. Tool evals: `find_toll_ramps`

Deterministic checks of the tool alone, with no model in the loop. They run
against the development server with real Amazon Location lookups, because the
e2e suite replaces SearchText with canned answers and so never tests lookup
quality.

**Cases.** Each case is an origin and destination as a user might phrase them,
labeled by a person (from operator maps) with the set of acceptable entry/exit
pairs and the expected `status`. Cover:

- landmarks, towns and neighborhoods, intersections, and synthetic or
  public-building street addresses;
- ambiguous names: Tysons, "Washington" / DC, Springfield vs. Franconia,
  Pentagon vs. Pentagon City, Reston;
- airports (IAD, DCA) as either end;
- cross-facility trips (Greenway → Dulles Toll Road, Dulles Toll Road → I-495
  or I-66);
- straight-line traps, where the nearest ramp is across a river or highway from
  the place;
- out-of-area places (Baltimore, Richmond, Manassas) and misspellings.

**Metrics.**

| Metric | Target to set after the first run |
| --- | --- |
| An acceptable pair is the top option | top-1 rate |
| An acceptable pair is among the options | top-3 rate |
| `status` matches the label | status accuracy |
| Returned routes that fail `oracle.validate_pricing_route` when re-checked | **must be 0** |
| Lookups per call | 2, always |
| Latency | p50 and p99 |
| Cost | dollars per 100 calls |

## 2. Muse evals

Conversation-level checks of Muse using the server.

**Harness.** Scripted scenarios in Muse Code with the server configured under
`mcp_servers`, plus a manual onboarding check in the Muse app. Each scenario is
a short user script, such as a commuter who knows only "I live near Reston Town
Center and work at Tysons", graded on the transcript and tool calls.

**Behaviors to grade.**

- Confirms the matched places before relying on them.
- Asks the user on `ambiguous` instead of guessing.
- Offers a landmark or intersection instead of pressing for an exact address.
- Uses returned point IDs verbatim and never invents or edits one.
- Reports `daily_lookup_limit`, `currently_unavailable`, `outside_coverage`,
  and errors honestly.
- Makes no redundant calls for the same places.
- Presents options with their access miles and says results are estimates.

**Onboarding.** From the runbook's connect message, does the Muse app build a
working Custom Connector from `https://mcp.tollchat.ai/`, and does it save it
for reuse? Record the success rate and the number of turns to connect.

**Metrics.** pass^k over 3 trials per scenario, plus tool calls and lookups per
conversation.

## 3. Ground rules

- Use synthetic or public places only. Never use a real person's home or work
  address.
- Keep granular output (transcripts, per-case results) in ignored
  `v2/eval/private/`. Record each campaign in the experiment journal's weekly
  page with its purpose, versions, aggregate result, limitations, and cost.
- Each campaign needs a budget approved by Ryan before it runs. Tool evals use
  the shared daily lookup limit, so schedule them to leave room for users.

## 4. Open questions

- Can Muse Code run these scenarios headless in CI, and what does that cost in
  Muse Spark usage?
- Which judge model grades transcripts?
- Does a Muse Connector Platform review want eval evidence?
