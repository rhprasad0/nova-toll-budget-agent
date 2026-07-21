# NOVA Toll Road Graph — Spec

Status: approved design, seed committed · Owner: Ryan Prasad · Last updated: 2026-07-21

A traversable model of the NOVA toll network, built on top of the poller's
`trip_pricing` table (see `docs/poller-spec.md`). Answers "what does driving
X→Y cost right now" by giving a future routing tool a graph to walk: nodes are
named access points, edges are priced trips looked up live from
`trip_pricing`. `db/graph.sql` mirrors this doc, never the other way around.

## 1. What the graph is

The graph covers **only the corridors we have live feed data for**: the
I-95/395/495 Express Lanes (one combined feed, `feed='i95'`) and I-66 Inside
the Beltway (`feed='i66'`). Three corridor values distinguish nodes
physically on I-95/395 Express Lanes vs. the I-495 Capital Beltway Express
Lanes vs. I-66 ITB, even though the first two share one upstream feed.

- **i95_express** (34 nodes): curated access points from Garrisonville
  (Stafford County) north to the Pentagon/DC, on the I-95/395 Express Lanes.
- **i495_express** (18 nodes): curated access points on the I-495 Capital
  Beltway Express Lanes, from the Springfield interchange north to the 495
  NEXT extension near the Maryland line.
- **i66_itb** (8 nodes): the eight I-66 Inside-the-Beltway toll zones — four
  eastbound (Beltway → Rosslyn), four westbound (Rosslyn → Beltway). Zone
  names are clean in the source feed, so nodes map 1:1 to zone IDs.

Every dynamic edge is a **complete priced trip, not a segment** — an i95_express
edge is one OD pair, an i66_itb edge is one zone pair. Never sum edges to
approximate a trip that isn't itself in the feed; two OD pairs can share a
gantry zone pair at different prices (e.g. 1006 vs 1007), so summing segments
silently produces the wrong number.

Two junction points connect the three corridors with free (untolled)
connector edges — the express-lane ramps and interchange gores themselves
carry no toll:

- **Springfield**: the direct express-to-express ramps between the I-95/395
  Express Lanes and the I-495 Express Lanes, wired to the OD families the feed
  actually prices for through movements. Northbound:
  `i95x:i495-springfield` → `i495x:i395-95-hov` (the "I-395-95 HOV TO …"
  495-NB family starts at gantry TP1NB — the express entry; the similarly
  named "I-395-95-495" family starts at TP2NB and is GP-lane entry, not this
  movement). Southbound: `i495x:i95-hov` → `i95x:i495-springfield` (continue
  south on 95 Express) and `i495x:i395-495-hov` → `i95x:i495-springfield`
  (continue north on the reversible 395 lanes, availability per
  `link_status`) — both continue as i95-corridor trips from the bare "I-495"
  origin.
- **Beltway/66 interchange**: `i495x:i66-jct` → `i66:capital-beltway-begin`
  (entering I-66 EB from the Beltway) and `i66:capital-beltway-end` →
  `i495x:i66-jct` (exiting I-66 WB onto the Beltway) — one-way, matching the
  zone names themselves (there's no ramp from the *end* of EB or into the
  *start* of WB).

That's the whole topology: **60 nodes, 342 edges** (317 i95/495 dynamic + 20
i66 dynamic + 5 free junction).

## 2. How it's stored in Postgres

```sql
CREATE TABLE graph_node (
    node_id  text PRIMARY KEY,   -- stable slug: 'i95x:garrisonville', 'i66:fairfax-dr'
    name     text NOT NULL,      -- canonical display name (hand-curated)
    corridor text NOT NULL CHECK (corridor IN ('i95_express','i495_express','i66_itb'))
);

CREATE TABLE graph_edge (
    from_node     text NOT NULL REFERENCES graph_node,
    to_node       text NOT NULL REFERENCES graph_node,
    feed          text CHECK (feed IN ('i95','i66')),   -- NULL = free junction connector
    od_pair_id    int,                                   -- i95 price key
    start_zone_id int, end_zone_id int                   -- i66 price key
);
```

Topology is static seed data, not something applications mutate — VDOT adds
or retires OD pairs rarely, and when they do the fix is regenerating the seed,
not an UPDATE statement. `db/graph.sql` is therefore an **idempotent atomic
rebuild**: `BEGIN; DROP TABLE IF EXISTS graph_edge, graph_node; CREATE …;
INSERT …; COMMIT;`. Applied as master, the same way as `db/schema.sql`.

`graph.sql` is a **separate file from `db/schema.sql`** on purpose: the
poller's `trip_pricing` contract (schema version 2.0.0, guarded by
`lambdas/loader/tests/test_schema_contract.py`) must stay frozen and
untouched by graph changes. No foreign key exists from `graph_edge` into
`trip_pricing` — the two tables are joined at query time (see §3), not at
the schema level, so the frozen poller contract and the graph's own
versioning never collide.

No surrogate primary key on `graph_edge` (nothing references an edge by ID),
no `pricing`/`rate` column (`feed IS NULL` already means "free connector" —
adding a rate column for a still-nonexistent flat corridor would be pure
YAGNI), no per-edge `corridor` column (a node's corridor already says which
physical facility it sits on; an edge's corridor, if ever needed, is
`from_node`'s).

**Node-slug convention**: `<corridor-prefix>:<kebab-case-name>` —
`i95x:`, `i495x:`, `i66:`. Slugs are short and stable (`i95x:garrisonville`,
not `i95x:garrisonville-rd-610`); the descriptive form — road name, VDOT exit
number — lives in `name`, which is what a prompt or UI actually shows.

**Graph schema version: 1.0.0** (semver, same pattern as the poller schema).
Bump *major* on a DDL change or a change to what an edge key means, *minor*
on additive columns/nodes/corridors (e.g. DTR graduating in), *patch* on seed
corrections or comments. The version header in `db/graph.sql` and the version
declared here must match — enforced by `tests/test_graph.py`.

## 3. How edges link to live data

`graph_edge` carries no price; it carries the *key* to look one up. A dynamic
edge's current price is the latest matching row in `trip_pricing`:

```sql
-- i95_express / i495_express edge, keyed by od_pair_id:
SELECT zone_toll_rate_usd, link_status
FROM trip_pricing
WHERE feed = 'i95' AND od_pair_id = :od_pair_id
ORDER BY interval_end_at DESC
LIMIT 1;

-- i66_itb edge, keyed by the zone pair:
SELECT zone_toll_rate_usd, link_status
FROM trip_pricing
WHERE feed = 'i66'
  AND start_zone_id = :start_zone_id AND end_zone_id = :end_zone_id
ORDER BY interval_end_at DESC
LIMIT 1;
```

A dynamic edge carries **exactly one** of these keys (`od_pair_id` xor the
`start_zone_id`/`end_zone_id` pair) — never both, and a free connector edge
(`feed IS NULL`) has neither and no price lookup at all.

**Honor `link_status`.** A row can be `CLOSED` with a stale nonzero rate, or
legitimately open at `$0.00` (I-66 off-peak). Availability lives in
`link_status`, never in `rate > 0` — a router must not skip an edge just
because its latest rate happens to be zero, and must not treat a nonzero rate
as "open" without checking status.

**Trips, not segments.** The price for an edge is the `trip_pricing` row for
*that exact OD pair or zone pair* — never the sum of some other edges that
happen to cover the same physical distance. The feed prices complete trips;
there is no per-segment rate to sum in the first place.

## 4. Corridor inventories

### i66_itb zones (8)

| Zone ID | Name | Direction |
|---|---|---|
| 3100 | Capital Beltway Beginning | EB |
| 3110 | Lee Highway | EB |
| 3120 | Fairfax Drive | EB |
| 3130 | Spout Run Parkway | EB |
| 3200 | Glebe Road | WB |
| 3210 | Sycamore Street | WB |
| 3220 | Leesburg Pike | WB |
| 3230 | Capital Beltway End | WB |

Edges are the triangular set of zone pairs within each direction (10 EB + 10
WB = 20), including same-zone pairs (e.g. 3100→3100) — a short trip that
starts and ends at the same gantry is still a priced product in the feed.

### i95_express access nodes (34)

Garrisonville Rd (610) · Dale Blvd · Dumfries Rd (234) · Joplin Rd (619) ·
Quantico · Prince William Pkwy (294) · Gordon Blvd (123) · Opitz ·
Cardinal · Turkeycock · Newington · Lorton · US 1 · Fairfax County Pkwy (286) ·
Franconia-Springfield Pkwy (289) · Franconia Rd (644) · Old Courthouse Rd ·
Russell Rd · Telegraph Rd · Rt 17 / 95 NB · Rt 17 / 95 SB · Seminary Rd ·
Shirlington Circle · Alban · I-95 S / Ft Belvoir · I-95 S near Dale Blvd ·
I-95 S near Backlick Rd · I-395/95 · I-395 N · Washington Blvd / Pentagon ·
DC/Pentagon/Washington Blvd · Pentagon · Washington DC ·
I-495 (Springfield) — the Springfield junction node.

### i495_express access nodes (18)

I-495 (Springfield-adjacent): I-395-95-495 · I-395-95 HOV · I-395-495 HOV ·
I-95 HOV · I-495 HOV — then heading north: Braddock Rd · Gallows Rd ·
I-66 (junction node) · Route 7 · Rt 267 · Westpark Dr · Westpark Dr (B) ·
Westpark Dr (C) · Jones Branch Dr · Jones Branch Dr / Rt 267 · Lee Hwy ·
I-495 N · I-495 near MD (the 495 NEXT extension's northern end, opened Nov
2025 — already present in the feed as TP9 zones; no special handling needed).

### Junction points (2, 5 edges)

See §1 — Springfield (`i95x:i495-springfield` → `i495x:i395-95-hov`;
`i495x:i95-hov` / `i495x:i395-495-hov` → `i95x:i495-springfield`) and the
Beltway/66 interchange (`i495x:i66-jct` → `i66:capital-beltway-begin`,
`i66:capital-beltway-end` → `i495x:i66-jct`).

## 5. Corridors outside the graph

*(Prompt-ready — paste verbatim into the agent's system prompt. All rates
as-of July 2026; re-verify before relying on them for anything beyond a
rough estimate.)*

> **Dulles Toll Road (DTR)** — flat-rate, not in the toll graph. $4.00 at the
> main Tysons/Dulles plaza, $2.00 per ramp. Rate next scheduled to increase in
> 2028. No live feed exists; if asked for a current DTR price, quote these
> flat rates and note they're not live-metered.
>
> **Dulles Greenway** — flat-rate, not in the toll graph. $5.25 off-peak,
> $5.80 peak. A rate case is currently pending before the SCC, so these
> numbers may change; note that when quoting.
>
> **I-66 Outside the Beltway (OTB) Express Lanes** — dynamic pricing (managed
> by Transurban), not in the toll graph — no public feed exists for it. If
> asked for a current OTB price, say the rate is variable and unknown; do not
> estimate or guess a number.

If any of these ever needs live routing, it graduates into `graph.sql` as a
new `corridor` value (additive, minor version bump) — not a bespoke system.

## 6. Data quality & invariants

- **Numeric IDs only at runtime.** OD-pair and zone names in the raw feeds
  are dirty — the same physical exit spelled three ways (e.g.
  `FRAN-SPRINGFIELD (289)` / `…PKWY (289)` / `…PKWY (RT 289)`), stray
  whitespace, both `" TO "` and `" to "` as delimiters. Every raw spelling
  was hand-curated once into the ~50 canonical `i95x:`/`i495x:` node slugs
  above (84 raw OD-pair endpoint tokens → 52 nodes, plus the 8 already-clean
  i66 zones = 60). Nothing in this graph, or in any future consumer,
  re-parses a name at runtime — join on `od_pair_id` /
  `start_zone_id`+`end_zone_id`, never on `od_pair_name`/`start_zone_name`.
- **Reversibility lives in `link_status`, not in the graph.** I-95/395 lane
  reversal schedules change (VDOT moved the switch to 10 a.m. in May 2026);
  the graph doesn't encode a schedule. Both directions exist as edges
  year-round; whether a given edge is usable *right now* comes from
  `link_status` on the latest `trip_pricing` row, per §3.
- **`$0` is not the same as closed.** I-66 ITB is legitimately free
  off-peak. A `CLOSED` row can carry a stale nonzero rate. Only
  `link_status` determines availability.
- **What `tests/test_graph.py` enforces:** every `od_pair_id` in the sample
  feed has exactly one graph edge and vice versa (and likewise for i66 zone
  pairs) — this is the drift alarm that fails loudly the day VDOT adds or
  retires an OD pair; every edge endpoint resolves to a real node; every
  dynamic edge carries exactly one price key; no duplicate dynamic keys;
  BFS spot-checks confirm the graph is actually connected end-to-end; and
  the schema-version header in `db/graph.sql` matches the version declared
  in §2 of this doc.

## Traversal contract (for the future routing tool)

The LLM never traverses the graph itself. A deterministic `route(origin,
destination, at_time)` tool loads the full graph in one query (trivially
small — 60 nodes, 341 edges), runs plain-code BFS/Dijkstra, prices each edge
from `trip_pricing` per §3, and returns the complete priced path; the LLM
only picks endpoints from the node list and narrates the result. Only the
~60-node name list ever needs to enter the model's context — never edge or
pricing data — which keeps a cheap model viable. The longest realistic route
is about 4 hops, since dynamic edges are already whole priced trips, not
segments.

## I-66 sample data note

The committed `vdot_sample_data/tollingTripPricing-I66.xml` (18 `<opt>` rows,
one interval) predates this graph and is left as-is — it's exercised by
`lambdas/loader/tests/test_parse_xml.py`, which asserts its exact row count
and field values. A second file,
`vdot_sample_data/tollingTripPricing-I66-refreshed.xml`, was pulled read-only
from the production raw bucket (`s3://nova-toll-raw-920534282028/raw/feed=i66/`,
2026-07-21 21:48 UTC interval) specifically for this graph: it's a single,
complete interval covering all 20 real zone pairs, versus the original
sample's 18 (missing the two same-zone-to-itself trips at each direction's
terminal zone, `3130→3130` and `3230→3230`). `tests/test_graph.py`'s feed
coverage check reads the refreshed file, so the graph's 20 i66 edges are
verified against the complete feed rather than the partial original. See the
final implementation report for why the file wasn't overwritten in place.

Note also that the production feed appears to sometimes bundle two
consecutive 6-minute intervals into a single raw S3 object (observed: 40
rows across two `IntervalDateTime` values, 20 pairs each) — likely the
source of `docs/poller-spec.md`'s "~44 rows/poll" estimate for I-66. The
*distinct* zone-pair count is 20, not ~44; this graph's edge count reflects
that corrected figure.
