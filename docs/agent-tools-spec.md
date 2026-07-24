# Agent Query Tools — Spec

Status: approved design, pre-implementation · Owner: Ryan Prasad · Last updated: 2026-07-22

The toolset for the NOVA toll budget agent: a Strands Agents SDK agent
(deployed on Bedrock AgentCore Runtime) with free-form **read-only SQL
access** to the poller's database, plus a deterministic routing tool. This
replaces the earlier curated-views direction: instead of encoding our guesses
about how users want the data shaped, the open beta lets users query however
they like and we learn the real access patterns from traces. Companion specs:
`docs/poller-spec.md` (data, schema v2.0.0, roles), `docs/toll-graph-spec.md`
(topology, graph schema v1.0.1, traversal contract).

## 1. Design ethos

- **The LLM writes SQL freely; the database enforces safety.** Every guard
  that matters is a Postgres grant, a role setting, or deterministic code.
  The system prompt guides behavior but is never a security boundary — no
  prompt injection can override a `GRANT`.
- **Every answer shows the SQL it ran.** The executed statement is part of
  the tool result and the agent is instructed to surface it. This is the
  audit trail and the honesty story in one: users can verify instead of
  trust.
- **Beta framing is honest.** The UI states answers are generated and may
  contain errors — never "verified accurate." Traces are collected and users
  are told so.
- **The LLM never traverses the graph.** Routing is the deterministic
  `route()` tool per toll-graph-spec's traversal contract; only the ~60-node
  name list ever enters model context, never bulk edge or pricing data.

## 2. Toolset

Four Strands `@tool` functions. Type hints and docstrings are the tool
schema — Strands parses them into the JSON the model sees, so the docstrings
below are load-bearing contract, not decoration.

This section is the design rationale; the contract of record for each tool
is `schemas/tools/<tool>.json` (Draft 2020-12, `input`/`output` shapes with
examples, semver'd — *major* on breaking shape change, *minor* additive,
*patch* wording — CI-validated by `tests/test_tool_schemas.py`). When the
agent ships, a follow-up test compares the Strands-generated tool spec
against these files so code and contract can't drift.

### `list_tables() -> dict`

Returns the three queryable tables with a one-line purpose each:

| Table | Purpose |
|---|---|
| `trip_pricing` | Toll rates per 10-min poll (i95 history from 2026-04-17; i66 from cloud go-live) |
| `graph_node` | 60 named toll-network access points (curated) |
| `graph_edge` | 342 priced trips / free connectors linking nodes |

Static hand-written content. No `information_schema` query — the schema is
versioned and frozen (2.0.0 / 1.0.1, both test-enforced), so a live
introspection query buys nothing but latency.

### `describe_table(table: str) -> dict`

Columns, types, and — the actual value of this tool — the **semantic
footguns** the model must know to write correct SQL:

- **Availability lives in `link_status`, never `rate > 0`.** A row can be
  `CLOSED` with a stale nonzero rate, or legitimately open at `$0.00` (I-66
  off-peak). (toll-graph-spec §3.)
- **Latest price** = `ORDER BY interval_end_at DESC LIMIT 1` per key, or
  `DISTINCT ON (od_pair_id) … ORDER BY od_pair_id, interval_end_at DESC`
  for all-at-once.
- **Keys are numeric.** i95/i495 edges price by `od_pair_id`; i66 by the
  `start_zone_id`/`end_zone_id` pair (`od_pair_id` is NULL for i66). Never
  join or filter on `od_pair_name`/`*_zone_name` — raw names are dirty.
- **Trips, not segments.** Each `trip_pricing` row / dynamic edge is a
  complete priced trip; summing edges that cover the same pavement produces
  wrong numbers.

Hand-curated text, one block per table, sourced from `db/schema.sql` /
`db/graph.sql`. Drift protection is the existing schema-version tests, not a
new mechanism. Unknown table name → error listing the valid three.

### `execute_sql(sql: str) -> dict`

One read-only SQL statement in, capped rows out.

- **Input**: a single statement. Anything else (empty, multiple statements)
  is rejected before touching the DB.
- **Execution**: fresh connection per call as `agent_readonly` (reuse the
  loader's `_connect()` recipe — IAM token, `sslmode=verify-full`, RDS CA
  bundle; `lambdas/loader/handler.py:103`). Executed as a **server-side
  prepared statement** (psycopg `prepare=True`), which enforces
  single-statement at the wire protocol level — see §4.
- **Output**: `{"sql": <as executed>, "columns": [...], "rows": [...],
  "row_count": n, "truncated": bool}`. Row cap **500** (fetch 501, set
  `truncated`, drop the extra). Values serialized to JSON-safe types
  (`Decimal` → str, timestamps → ISO-8601).
- **Errors**: Postgres errors are returned in the tool result (message
  string, truncated to ~500 chars), not raised — the model reads the error
  and self-corrects. A failed query is a normal beta trace, not an incident.
- **Versioning note**: raising the row cap is a *minor* schema bump;
  lowering it is *major* (the model's memory of the cap is contract).

### `route(origin: str, destination: str, at_time: datetime | None = None) -> dict`

The deterministic router promised by toll-graph-spec's traversal contract.

- Loads the **whole graph in one query** (60 nodes, 342 edges — trivially
  small) plus latest prices for every dynamic edge (`DISTINCT ON` per key,
  or the latest row at/before `at_time` when given).
- Runs plain-code **Dijkstra** weighted by `zone_toll_rate_usd`; free
  connector edges (`feed IS NULL`) weigh $0.00. A visited-set in code makes
  looping routes structurally impossible — no recursive SQL exists to run
  away.
- **Edges whose latest row is `CLOSED` are excluded** (availability per
  `link_status`, exactly as §3/§6 of toll-graph-spec demand — a $0.00 open
  edge is traversable, a CLOSED edge is not, regardless of rate).
- Inputs are `node_id` slugs; unknown slug → error containing the full valid
  node list (it's ~60 short strings — cheaper to return than to make the
  model guess again).
- **Output**: ordered path of `{from, to, price_usd, link_status, priced_at}`
  hops, total price, and the oldest `interval_end_at` used (so the agent can
  say how fresh the quote is). No path → explicit "no route" result, again
  with the node list.
- **Determinism**: equal-cost ties break on lexicographic `node_id` so
  identical inputs return identical paths (traces stay comparable).
  `origin == destination` is an error, not a zero-hop path.

**Rejected: more tools.** No `explain_query` (the 5s timeout is the cost
guard; EXPLAIN plans in model context are noise at this DB size), no search
tool, no per-question convenience wrappers — the whole point of the beta is
to learn which wrappers to build from traces.

## 3. The `agent_readonly` role

Ships in the same PR as the agent, as promised in poller-spec (§Roles).
Appended to `db/roles.sql`, applied as master:

```sql
-- agent_readonly: the beta agent's execute_sql/route tools. RDS IAM auth
-- only, SELECT only, read-only + 5s timeout enforced at the role level.
CREATE ROLE agent_readonly WITH LOGIN;
GRANT rds_iam TO agent_readonly;
GRANT SELECT ON trip_pricing, graph_node, graph_edge TO agent_readonly;
ALTER ROLE agent_readonly SET default_transaction_read_only = on;
ALTER ROLE agent_readonly SET statement_timeout = '5s';
```

- The IAM side mirrors the loader's `ConnectRdsIam` statement in
  `infra/iam.tf`: `rds-db:connect` on
  `…dbuser:<resource_id>/agent_readonly`, attached to whatever principal
  runs the agent (AgentCore Runtime execution role).
- **`db/graph.sql` rebuilds drop the grants.** The rebuild is
  `DROP TABLE … CREATE … INSERT`, and grants die with the dropped tables —
  so re-applying `roles.sql` (idempotent-ify the `GRANT`s; `CREATE ROLE`
  guarded or run selectively) is part of the graph-rebuild runbook. Cheaper
  than teaching `graph.sql` about roles it can't assume exist.
- `statement_timeout` at the role level (not per-session code) so even a
  code-path bug can't run an unbounded query.

## 4. SQL guards, layered

Defense in depth, informed by the SQL-injection case study against the
original Postgres MCP reference server (its `BEGIN READ ONLY … ROLLBACK`
wrapper was escaped with a stacked `COMMIT; DROP SCHEMA …` — transaction
semantics alone are not a boundary):

1. **The boundary: the role.** `SELECT`-only grants on exactly three
   tables. Everything below is belt-and-suspenders; this layer alone is
   sufficient — no SQL string that reaches the DB can write, whatever it
   says.
2. **Single statement, enforced by the wire protocol.** Server-side
   prepared statements (psycopg `prepare=True`) cannot contain multiple
   statements — `COMMIT; anything` fails at parse, killing the statement-
   stacking class outright. A pre-flight check that the text is one
   statement gives a friendlier tool error, but the protocol is the
   enforcement.
3. **Session hygiene + caps.** Fresh connection per `execute_sql` call
   (t4g.micro tolerates this fine at beta scale; no pool to pollute, no
   `SET statement_timeout TO 1`-style state leaking between users), 500-row
   cap, role-level 5s timeout.

**Rejected: SQL keyword blocklists as a security layer.** A blocklist can't
enumerate every dangerous construct, and the role already makes writes
impossible. A minimal SELECT/WITH prefix check exists only to give the model
a clean error message instead of a Postgres permission error — UX, not
security.

## 5. Abuse guards

- **Tool-call ceiling per turn** (~10): configured on the Strands agent
  loop. An unbounded agent loop is a self-inflicted DoS; a user turn that
  needs more than ten tool calls has gone wrong.
- **Runaway queries** die at the role-level 5s `statement_timeout` — that is
  the kill-switch for pathological joins and any "weird looping" SQL a user
  coaxes out of the model. `route()` can't loop by construction (visited
  set, no recursion).
- **Per-user request budget** is an AgentCore-layer concern (identity +
  throttling live where the users do), deferred to the deployment spec —
  the DB-side guards above already bound the per-request blast radius.

## 6. Toxicity & traces (chosen direction, detail deferred)

- **Toxicity: Bedrock Guardrails**, attached to the Strands `BedrockModel`
  via guardrail ID — input *and* output screened on every request (Hate,
  Insults, Sexual, Violence, Misconduct, Prompt Attack categories, plus
  denied topics) with zero agent-code changes. Policy configuration
  (thresholds, denied-topic list, blocked-message wording) belongs to the
  deployment spec. Flagged inputs still land in traces — abuse patterns are
  beta data too.
- **Traces: AgentCore observability.** Strands emits OpenTelemetry natively;
  AgentCore ships those traces to CloudWatch. Every turn — user text, tool
  calls, executed SQL, results, guardrail interventions — is the beta's
  actual product. No custom trace table, no third-party tracing vendor.

## 7. YAGNI ledger

Explicitly rejected, revisit only with evidence:

- **Curated views / semantic layer** — the pivot this spec exists for.
  Traces first; views only when the same query shape shows up repeatedly.
- **Custom trace storage** — AgentCore/CloudWatch is the store until an
  analysis it can't do is actually attempted.
- **Secondary indexes** — per `db/schema.sql`: wait until a real agent
  query is measurably slow. The 5s timeout will tell us loudly.
- **Connection pooling** — fresh connection per query is the *safety*
  choice (session hygiene) and beta scale never notices. Revisit only if
  connect latency measurably hurts.
- **`explain_query` / query-cost pre-flight** — timeout + row cap bound the
  damage at this DB size.
- **Custom moderation code** — Bedrock Guardrails is managed and
  model-agnostic (`ApplyGuardrail` works standalone if the model ever
  moves).
