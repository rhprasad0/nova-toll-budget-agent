# Nova Toll Budget Agent

Ingest pipeline for Northern Virginia express-lane toll prices, plus the
published route maps needed to interpret them.

**What runs.** A fetcher Lambda polls VDOT's two SmarterRoads tolling feeds
every 10 minutes and lands the raw payloads in S3; a loader Lambda parses each
object and upserts it into `trip_pricing_i95`/`trip_pricing_i66` in RDS
(cutover from the old shared `trip_pricing` table pending — see
`docs/poller-spec.md`).

| Path | What |
|---|---|
| `lambdas/fetcher`, `lambdas/loader` | the pipeline |
| `db/` | the per-feed schema and the `loader_writer` role |
| `infra/` | Terraform for both Lambdas, S3, RDS and observability |
| `oracles/` | operator-published route maps (see below) |
| `vdot_sample_data/` | committed raw feed samples the parsers are tested against |

**Oracles.** `oracles/i95.json` and `oracles/i66.json` are route maps published
by the operators themselves — Transurban for the 95/395/495 Express Lanes, VDOT
for I-66 Inside the Beltway. They say which trips exist and which price key
each one bills against; they carry no prices, because prices live in
`trip_pricing_i95`/`trip_pricing_i66` where they have history. Refresh them with
`scripts/fetch_i95_oracle.py` / `scripts/fetch_i66_oracle.py` — rarely, and
never at runtime. `docs/oracle-findings.md` records what they told us.

**What was removed.** An agent tool layer (`route`, `execute_sql`,
`list_tables`, `describe_table`) and a hand-curated toll graph once sat on top
of this pipeline. We reversed course on letting an agent query the database
directly, and both are gone. `db/drop_agent_surface.sql` tears down what they
left behind in a live database.
