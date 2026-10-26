# Muse MCP Evals

Status: **specification only**. Nothing here runs yet; it defines the evals to
build for the TollChat MCP server (`v2/lambdas/mcp_server/`) and for Muse, Meta's
personal agent, using it.

These evals are separate from the TollChat agent's evaluation suite. The MCP
tools deliberately drift from the agent's tools, so they share no cases, judges,
harness digests, or release gates with `v2/eval/`.

## 1. Tool evals: `find_toll_ramps`

Deterministic checks of the tool alone, with no model in the loop. They run
against the development server, so they see live reversible-lane data. The tool
takes coordinates; geocoding place names is Muse's job and is graded in the Muse
evals below.

**Cases.** Each case is an origin and destination as coordinates of public
landmarks, labeled by a person (from operator maps) with the set of acceptable
entry/exit pairs and the expected `status`. Cover:

- landmarks, towns and neighborhoods, and intersections;
- airports (IAD, DCA) as either end;
- cross-facility trips (Greenway → Dulles Toll Road, Dulles Toll Road → I-495
  or I-66);
- straight-line traps, where the nearest ramp is across a river or highway from
  the place;
- ranking trade-offs, where a closer ramp means one more toll road (for
  example Ashburn → Tysons: Greenway then Dulles Toll Road, or a farther Dulles
  Toll Road entry); the server counts each extra toll road as 2 access miles;
- I-95/I-395 reversible-lane trips in both directions, with the lanes open,
  closed, and with missing or stale lane data;
- out-of-area places (Baltimore, Richmond, Manassas), same-place trips, and
  swapped latitude and longitude.

**Metrics.**

| Metric | Target to set after the first run |
| --- | --- |
| An acceptable pair is the top option | top-1 rate |
| An acceptable pair is among the options | top-3 rate |
| `status` matches the label | status accuracy |
| Returned routes that fail `oracle.validate_pricing_route` when re-checked | **must be 0** |
| Latency | p50 and p99 |
| Cost | dollars per 100 calls |

**`estimate_annual_tolls`.** Same harness, one case per labeled option and
schedule. Cover Dulles Toll Road and Greenway commutes (exact amounts from the
published rates, peak and off-peak), I-66 and I-95/I-495 commutes against the
agent's `get_annual_toll_ballpark` on the same inputs, I-95/I-395 reversible
commutes (northbound out, southbound back), hybrid weekdays, and schedules too
thin to estimate. Metrics: status accuracy, amounts within one cent of the
agent's, the chosen return route's facilities, and latency p50 and p99.

## 2. Muse evals

Conversation-level checks of Muse using the server.

**Harness.** Scripted scenarios in Muse Code with the server configured under
`mcp_servers`, plus a manual onboarding check in the Muse app. Each scenario is
a short user script, such as a commuter who knows only "I live near Reston Town
Center and work at Tysons", graded on the transcript and tool calls.

**Behaviors to grade.**

- Geocodes the user's places correctly, and asks when a name is ambiguous
  (Tysons, "Washington" / DC, Springfield vs. Franconia, Pentagon vs. Pentagon
  City) instead of guessing.
- Confirms the chosen option before relying on it.
- Offers a landmark or intersection instead of pressing for an exact address.
- Uses returned point IDs verbatim and never invents or edits one.
- Reports `same_location`, `currently_unavailable`, `outside_coverage`, and
  errors honestly, never as zero tolls.
- Makes no redundant calls for the same coordinates.
- Presents options with their access miles and says results are estimates.
- Quotes an annual estimate as a range with its typical value, passes the
  user's own schedule when given, and never reports `too_few_recent_prices`
  as zero tolls.

**Onboarding.** From the runbook's connect message, does the Muse app build a
working Custom Connector from `https://mcp.tollchat.ai/`, and does it save it
for reuse? Record the success rate and the number of turns to connect.

**Metrics.** pass^k over 3 trials per scenario, plus tool calls per conversation.

## 3. Ground rules

- Use synthetic or public places only. Never use a real person's home or work
  address.
- Keep granular output (transcripts, per-case results) in ignored
  `v2/eval/private/`. Record each campaign in the experiment journal's weekly
  page with its purpose, versions, aggregate result, limitations, and cost.
- Each campaign needs a budget approved by Ryan before it runs. Tool evals
  share the server's 2 requests per second with users, so pace them.

## 4. Open questions

- Can Muse Code run these scenarios headless in CI, and what does that cost in
  Muse Spark usage?
- Which judge model grades transcripts?
- Does a Muse Connector Platform review want eval evidence?
