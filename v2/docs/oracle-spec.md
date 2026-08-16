# TollChat v2 toll oracle specification

- **Status:** Proposed
- **Scope:** v2 only
- **Pricing:** Explicitly out of scope

## Decision summary

TollChat v2 will store a small, directed representation of supported toll-road
access in PostgreSQL. It will not store a turn-by-turn road network.

The oracle will answer two questions:

1. Can this Express Lane entry reach this Express Lane exit, including across
   supported toll facilities?
2. If an access movement is unavailable, which nearby Express Lane access
   movements have the same entry/exit function, are directionally usable, and
   can still complete the requested route when its counterpart is known?

The design separates three concerns:

- **Relational connectivity** proves directed travel within and between toll
  facilities.
- **Live availability** overlays the current I-95 reversible direction.
- **PostGIS proximity** ranks nearby access movements by physical distance.

The canonical data is pricing-independent. A missing price must never be
interpreted as an invalid route.

## Problem statement

The v1 frontend uses generalized map markers, and some markers represent more
than one oracle record. Those markers are appropriate for display but are not
precise enough for finding nearby alternatives. V1 also contains useful
directed route knowledge in code and JSON rather than in a database contract.

V2 needs an auditable oracle that can prove a route such as:

```text
Dulles Greenway
  -> Dulles Toll Road
  -> I-495 Express Lanes
  -> I-95/395 Express Lanes
```

It must also understand that a ramp is an **entry or exit access movement**.
An oracle record that does not permit tollway access is not a ramp merely
because it appears in routing or pricing topology.

## Goals

- Represent only Express Lane and toll-road access relevant to TollChat.
- Preserve entry/exit function and permitted travel direction per movement.
- Prove directed routes within a facility and across curated facility
  transfers.
- Overlay live I-95 direction without coupling validity to toll prices.
- Find nearby alternatives using precise access points and distances in meters.
- Return an ordered, inspectable proof rather than a bare Boolean.
- Fail safely when live availability is missing, stale, contradictory, or
  transitional.
- Keep all v2 schema, source snapshots, loaders, tests, and documentation under
  `v2/`.

## Non-goals

- Turn-by-turn navigation or general-purpose-road routing.
- Storing complete roadway centerlines or lane geometry.
- Predicting traffic, travel time, or the fastest route.
- Toll calculation, price joins, or treating price availability as route
  validity.
- Live incident ingestion for individual ramp closures in the first version.
- General-purpose-lane alternatives.
- Reusing v1 code at runtime. V2 may deliberately reintroduce curated facts as
  versioned v2 data.

## Terminology

### Access movement

A directed opportunity to **enter** or **exit** a toll facility. Each row has
one function and one permitted travel direction. Two movements at the same
interchange may share coordinates while remaining distinct records.

### Handoff

An internal boundary used to prove continuity between facilities, such as
Greenway to Dulles Toll Road or Dulles Toll Road to I-495. A handoff is not a
ramp and must not be returned as a nearby access alternative.

### Valid leg

A pricing-independent assertion that one oracle endpoint can reach another on
the same facility in a stated direction.

### Transfer

A curated, directed connection from an endpoint on one facility to an endpoint
on another facility.

### Structural validity

Whether the static directed legs and transfers connect the requested entry to
the requested exit.

### Current validity

Whether a structurally valid route is usable under the current operational
state. Initially, the only dynamic facility state is the I-95/395 reversible
direction.

## Architecture

```text
                         +---------------------------+
                         | current_i95_direction     |
                         | live status observations  |
                         +-------------+-------------+
                                       |
                                       v
+-------------------+       +----------+-----------+
| access movements  |------>| directed oracle edge |<------| handoffs |
| geography points  |       | view                  |       +----------+
+---------+---------+       +----------+-----------+
          |                            |
          | PostGIS proximity          | bounded recursive traversal
          v                            v
+-------------------+       +----------------------+
| nearby candidates |------>| route proof          |
| role + direction  |       | static + current     |
+-------------------+       +----------------------+
```

PostgreSQL recursive common table expressions support graph traversal and path
tracking. The traversal must explicitly prevent cycles and cap depth; it must
not rely on incidental row order. PostgreSQL documents both path arrays and the
SQL-standard `SEARCH`/`CYCLE` clauses for this purpose.[^postgres-recursive]

PostGIS is limited to point storage and proximity. `ST_DWithin` performs an
index-aware radius filter, while the `<->` operator supports GiST-assisted
nearest-neighbor ordering.[^postgis-dwithin][^postgis-knn]

### Why not pgRouting?

pgRouting is designed around vertices and roadway edges with traversal costs,
reverse costs, and often edge geometries.[^pgrouting-graph] TollChat does not
need shortest-path routing over a street network. Its graph is small, curated,
and concerned with reachability. A normalized edge relation and bounded
recursive query are simpler to audit and operate.

## Logical data model

The names below describe the intended contract. Exact DDL belongs in a future
v2 migration.

### `oracle.facility`

One row per supported facility.

| Column | Type | Rules |
| --- | --- | --- |
| `facility_id` | `text` | Primary key; stable machine identifier |
| `display_name` | `text` | User-facing name |
| `availability_mode` | `text` | `fixed` or `i95_reversible` |
| `active` | `boolean` | Defaults true |

Initial facilities are `dulles_greenway`, `dulles_toll_road`, `i66_itb`,
`i495`, and `i95`.

### `oracle.endpoint`

A graph endpoint. This is deliberately more general than a ramp.

| Column | Type | Rules |
| --- | --- | --- |
| `endpoint_id` | `text` | Primary key; stable v2 identifier |
| `facility_id` | `text` | Foreign key to `oracle.facility` |
| `endpoint_kind` | `text` | `access` or `handoff` |
| `label` | `text` | Canonical display label |
| `location` | `geography(Point,4326)` | Null only for a documented handoff |
| `source_system` | `text` | Operator, VDOT, county GIS, or curated source |
| `source_key` | `text` | Stable identifier in the source |
| `coordinate_method` | `text` | Point derivation method |
| `source_url` | `text` | Public provenance when available |
| `source_observed_at` | `timestamptz` | Optional upstream observation time |
| `active` | `boolean` | Defaults true |

The source identity must be unique within a facility. Generalized frontend
marker coordinates are not valid source coordinates.

`coordinate_method` is exactly `direct`, `derived_endpoint`, `curated`, or
`none`.

### `oracle.access_movement`

The one-to-one access subtype of `oracle.endpoint`.

| Column | Type | Rules |
| --- | --- | --- |
| `endpoint_id` | `text` | Primary/foreign key; kind is `access` |
| `access_function` | `text` | Exactly `entry` or `exit` |
| `travel_direction` | `text` | One cardinal travel direction |
| `express_access` | `boolean` | Must be true for agent-visible alternatives |
| `source_node_id` | `text` | Optional upstream oracle identifier |

There is one row per distinct source access movement, with **no cap per
interchange**. Label, function, and direction are not identity: the source may
publish multiple physically or topologically distinct movements sharing all
three. This avoids direction arrays and prevents a convenient map pin from
erasing movement semantics.

`travel_direction` is exactly `northbound`, `southbound`, `eastbound`, or
`westbound`.

### `oracle.handoff`

The one-to-one internal-boundary subtype of `oracle.endpoint`.

| Column | Type | Rules |
| --- | --- | --- |
| `endpoint_id` | `text` | Primary/foreign key; kind is `handoff` |
| `travel_direction` | `text` | One cardinal travel direction |

Handoffs are direction-bearing. A physical junction may therefore have
multiple handoff endpoint rows, including separate target handoffs for turns
such as eastbound Dulles Toll Road to northbound or southbound I-495. Handoffs
remain internal graph facts and are never returned as ramps or alternatives.

### `oracle.valid_leg`

A directed, pricing-independent reachability assertion within one facility.

| Column | Type | Rules |
| --- | --- | --- |
| `leg_id` | `bigint` | Primary key |
| `facility_id` | `text` | Foreign key |
| `from_endpoint_id` | `text` | Foreign key; same facility |
| `to_endpoint_id` | `text` | Foreign key; same facility; differs from origin |
| `travel_direction` | `text` | Direction required by the leg |
| `source_system` | `text` | Oracle or curated source |
| `source_key` | `text` | Pair identifier or deterministic pair key |
| `active` | `boolean` | Defaults true |

The directed pair is unique. B-tree indexes cover `from_endpoint_id` and
`to_endpoint_id`.

### `oracle.transfer`

A directed connection between facilities.

| Column | Type | Rules |
| --- | --- | --- |
| `transfer_id` | `text` | Primary key |
| `from_endpoint_id` | `text` | Foreign key |
| `to_endpoint_id` | `text` | Foreign key on a different facility |
| `label` | `text` | Auditable connector name |
| `from_travel_direction` | `text` | Required direction leaving the source |
| `to_travel_direction` | `text` | Required direction entering the target |
| `transfer_kind` | `text` | Connector classification |
| `source_system` | `text` | Operator, agency, oracle, or curated source |
| `source_key` | `text` | Stable source or curated identifier |
| `evidence` | `text` | Human-readable provenance note |
| `source_url` | `text` | Optional public source |
| `active` | `boolean` | Defaults true |

Greenway/DTR must be an explicit transfer in v2 even though v1 sometimes
resolves both through one Dulles lookup. The explicit handoff makes the
multi-facility proof honest.

`transfer_kind` is exactly `direct_toll_handoff`, `general_purpose_gap`, or
`untolled_connector`. Separate source and target directions are necessary for
turns such as eastbound Dulles Toll Road to southbound I-495. The I-495/I-95
transition must be classified as `general_purpose_gap`; a route proof must not
describe it as uninterrupted Express Lane continuity.

### `oracle.endpoint_alias`

Aliases support deterministic name resolution without fuzzy matching inside
the route query.

| Column | Type | Rules |
| --- | --- | --- |
| `endpoint_id` | `text` | Foreign key |
| `normalized_alias` | `text` | Case-folded, whitespace-normalized alias |
| `alias` | `text` | Original text |
| `source` | `text` | Canonical, operator, road-number, or curated |

Resolution may return multiple candidates. Ambiguity must be surfaced rather
than silently broken by proximity or insertion order. Callers may narrow a
same-label match by facility, access function, and travel direction without
already knowing the canonical endpoint ID.

### `oracle.directed_edge`

A read-only view unions eligible valid legs and transfers into a common shape:

```text
edge_id, edge_kind, from_endpoint_id, to_endpoint_id,
from_facility_id, to_facility_id,
from_travel_direction, to_travel_direction,
transfer_kind, evidence
```

For a facility leg, both facility IDs are the leg's facility, the source and
target directions are both the leg's travel direction, and `transfer_kind` is
null. The view is the only graph input used by route validation. It must join
and filter active edges, active source and target endpoints, and active source
and target facilities. Deactivating any of those records removes the edge from
traversal.

## Indexes

The initial schema requires:

- GiST on `oracle.endpoint(location)` where `location IS NOT NULL`.
- B-tree on `oracle.valid_leg(from_endpoint_id)`.
- B-tree on `oracle.valid_leg(to_endpoint_id)`.
- B-tree on `oracle.transfer(from_endpoint_id)`.
- B-tree on `oracle.access_movement(access_function, travel_direction)`.
- Unique index on each directed leg and transfer identity.
- Unique index on `(normalized_alias, endpoint_id)`.

AWS RDS for PostgreSQL supports PostGIS, but enabling the extension requires an
appropriately privileged deployment role. Only the core `postgis` extension is
needed; raster, topology, geocoder, and pgRouting extensions are not part of
this design.[^aws-postgis]

## Coordinate policy

The stored point represents the access movement at its Express Lane connection,
not an interchange centroid, label position, toll gantry, or generalized map
marker.

Source priority is:

1. Operator-published per-movement coordinates.
2. The endpoint of an authoritative ramp centerline where that directed
   movement joins the toll facility.
3. A manually curated point supported by documented evidence.

For derived GIS points, the importer must retain the source feature ID and the
derivation method. It must not use a line centroid or midpoint. Multiple
movements may share a point when the source genuinely provides the same
connection location.

Initial source strategy:

- **I-95/395/495:** Transurban per-entry/per-exit coordinates already captured
  in the v1 oracle, reintroduced as a versioned v2 source snapshot rather than
  read from v1 at runtime.[^transurban-map]
- **I-66:** official Fairfax County and Arlington County road-centerline ramp
  geometries, with VDOT maps used to validate movement semantics.[^fairfax-gis][^arlington-gis]
- **Dulles Toll Road:** official Fairfax County road-centerline ramp geometries,
  with MWAA maps used to validate movement semantics.[^fairfax-gis]
- **Dulles Greenway:** official Loudoun County ramp centerlines, with the
  operator topology used to validate access function and direction.[^loudoun-gis]

Only access-capable records are imported into `oracle.access_movement`.
Non-access oracle topology may appear only as a documented handoff when it is
needed to prove continuity.

## I-95 operational state

The modeled I-95/395 Express Lanes are never bidirectionally open. Their real
operational state is one of:

- `northbound_open`
- `southbound_open`
- `closed`

`unknown` is an evidence state, not a physical lane state.

The new oracle availability surface will read the latest synchronized status
observations already exposed through `current_i95_direction`. It must preserve
the underlying northbound and southbound status fields so that fully closed can
be distinguished from uncertainty.

| Northbound evidence | Southbound evidence | Operational result |
| --- | --- | --- |
| `NORTHBOUND_OPEN` | `CLOSED` | `northbound_open` |
| `CLOSED` | `SOUTHBOUND_OPEN` | `southbound_open` |
| `CLOSED` | `CLOSED` | `closed` |
| Anything else | Any | `unknown` |

The two observations must describe the same `interval_end_at`. Freshness is
measured from each row's `calculated_at`, which the adopted v2 contract treats
as the source observation time, against the database transaction's current
time. The initial maximum age is **20 minutes**, or two expected I-95
publication intervals. Either observation exceeding that age, or being
more than two minutes ahead of the transaction time, makes the evidence
`unknown`. A future timestamp inside that two-minute clock-skew tolerance is
treated as age zero. The result includes both source statuses,
`interval_end_at`, and `calculated_at` values so the agent can explain why
availability was accepted or withheld.

I-66, I-495, Dulles Toll Road, and Dulles Greenway direction restrictions are
static oracle facts in the first version. I-495's VDOT `link_status` is not a
usable open/closed signal, and I-66 pricing rows do not carry one.

## Route validation

### Static traversal

`oracle.validate_route` performs a bounded recursive traversal over
`oracle.directed_edge`.

The traversal must:

1. Start at an `entry` access movement.
2. End at an `exit` access movement.
3. Follow edges only in their stored direction.
4. Require a leg direction to match both endpoints. For a transfer, require
   `from_travel_direction` to match the source side and
   `to_travel_direction` to match the target side.
5. Track visited endpoint IDs and reject cycles.
6. Stop after a fixed maximum depth; twelve edges is sufficient for the
   initially supported network and prevents accidental query explosion.
7. Prefer the proof with the fewest transfers, then fewest edges, then stable
   edge IDs. This is deterministic selection, not a fastest-route claim.

The result is an ordered proof containing every leg and transfer. It never
returns only `true`.

Each transfer step includes `transfer_kind`. A `general_purpose_gap` is a
supported structural connection but must be disclosed in the proof and agent
response; it is not an Express Lane segment.

### Operational overlay

After finding a structural proof, validation applies current facility state:

- A proof without I-95 is currently valid when all static direction
  constraints pass.
- An I-95 leg is usable only when its direction matches the verified live
  operational direction.
- When the opposite I-95 direction is open, the structural proof is retained
  but the result is `structurally_valid_currently_unavailable` with reason
  `i95_opposite_direction_open`.
- When I-95 is fully closed, the same status is returned with reason
  `i95_fully_closed`.
- When I-95 evidence is unknown, the result is `availability_unknown`; it is
  not reported as a valid or definitively invalid route.

The database function returns at least:

```json
{
  "status": "valid",
  "structurally_valid": true,
  "currently_valid": true,
  "unavailable_reason": null,
  "origin_access_id": "...",
  "destination_access_id": "...",
  "steps": [],
  "availability": {
    "i95_state": "southbound_open",
    "observed_at": "..."
  }
}
```

Allowed statuses are:

- `valid`
- `structurally_valid_currently_unavailable`
- `availability_unknown`
- `invalid_entry_function`
- `invalid_exit_function`
- `direction_mismatch`
- `no_supported_route`
- `unknown_endpoint`
- `ambiguous_endpoint`

## Nearby access alternatives

`oracle.find_access_alternatives` takes:

- `unavailable_access_id`
- optional `route_counterpart_access_id`
- `same_facility_only`, default true
- `max_results`, default 3 and capped at 5
- `max_distance_m`, default 25,000 and capped at 50,000

Candidate generation must:

1. Resolve the requested access movement exactly.
2. Select only active Express Lane access movements.
3. Preserve `access_function` (`entry` remains entry; `exit` remains exit).
4. Select only movements compatible with the current open direction or the
   facility's static direction.
5. Exclude the requested movement.
6. Restrict candidates to the requested facility when `same_facility_only` is
   true. When false, search all supported Express Lane access movements and let
   route validation prove cross-facility usability when a route counterpart
   exists.
7. Apply `ST_DWithin` before exact distance calculation.
8. Rank by distance, then stable endpoint ID.
9. When a route counterpart is supplied, apply it according to the unavailable
   movement's function:
   - for an entry alternative, the counterpart must be an exit and
     `oracle.validate_route(candidate, counterpart)` must return `valid`;
   - for an exit alternative, the counterpart must be an entry and
     `oracle.validate_route(counterpart, candidate)` must return `valid`.
   A role-incompatible counterpart is a structured input error.

The returned `distance_m` is geodesic `ST_Distance` on geography. KNN may be
used to shortlist candidates, but final ordering and displayed distance must
use the exact distance expression. Because candidates are points, KNN ranking
is already well behaved; the explicit final calculation keeps the contract
clear.

If the I-95 facility state is `closed`, there are no I-95 Express Lane
alternatives. Unknown I-95 availability excludes an alternative only when the
candidate or its validated route depends on I-95. It does not suppress
otherwise valid candidates confined to fixed-direction facilities. The
function reports the evidence problem and must not guess about an I-95-dependent
candidate.

Without a route counterpart, alternatives are only **available access
movements**; the response must not claim that a complete trip is valid.

## Database interfaces

The first implementation should expose typed, read-only functions rather than
granting the agent arbitrary SQL:

```text
oracle.resolve_access_movement(
    query,
    facility_id default null,
    access_function default null,
    travel_direction default null
)
oracle.validate_route(origin_access_id, destination_access_id)
oracle.find_access_alternatives(
    unavailable_access_id,
    route_counterpart_access_id default null,
    same_facility_only default true,
    max_results default 3,
    max_distance_m default 25000
)
```

Functions should return typed rows or documented composite types. The
application wrapper may serialize them to JSON for the model. Inputs are
bounded, and no function accepts caller-provided SQL, filters, sort clauses, or
identifiers.

`oracle.resolve_access_movement` joins `oracle.access_movement` and never
returns handoffs. Any general endpoint resolver used by loaders or maintenance
is internal and is not granted to the agent role.

The agent-facing tool may wrap route validation and alternative lookup as
separate narrow operations. It must expose:

- canonical matched access IDs and labels;
- access function and direction;
- ordered facility and transfer proof;
- transfer classification, including any general-purpose gap;
- current I-95 state with observation time;
- distances in meters and miles for alternatives;
- structured failure reasons.

It must not expose or calculate prices.

## Security and permissions

- Place objects in an owned `oracle` schema.
- Use a non-login owner role for tables and functions.
- Give a loader role write access to canonical tables.
- Implement the approved read boundary as hardened `SECURITY DEFINER`
  functions owned by the non-login owner. Fully qualify every referenced
  object and pin `search_path` to trusted schemas only, including `pg_catalog`,
  `oracle`, and the known PostGIS extension schema; put `pg_temp` last.
- Give the agent runtime role `USAGE` on the `oracle` schema and `EXECUTE` only
  on approved read functions. Do not grant it table privileges.
- Revoke function execution from `PUBLIC`.
- Do not use dynamic SQL in the agent-callable functions. PostgreSQL warns that
  untrusted schemas in function lookup paths can enable Trojan-horse object
  substitution.[^postgres-function-security]
- Cap traversal depth, result count, radius, alias length, and returned JSON
  size.
- Log the function name, normalized inputs, result status, evidence timestamp,
  and duration; do not log credentials or database connection material.

## Data build and provenance

The v2 oracle is a reviewed build artifact, not a runtime scrape.

Recommended repository layout:

```text
v2/oracle/
  sources/          # source manifest and retained public source extracts
  data/             # normalized, reviewable canonical records
  scripts/          # deterministic builders and validators
v2/db/
  migrations/       # PostGIS, oracle schema, data, functions, roles
v2/tests/
  oracle_*.sql      # restore, migration, routing, and spatial contracts
```

Every normalized endpoint, leg, and transfer must retain source identity and
provenance. A build report should list:

- imported and rejected source records;
- exclusion reason for non-ramp oracle records;
- coordinate method counts;
- ambiguous or unmatched source records;
- duplicate labels and coordinates;
- same-label movements that remain intentionally distinct;
- unreachable access movements;
- transfers lacking a valid inbound or outbound leg.

Manual overrides live in a small, versioned file with evidence and rationale.
They must not be hidden in loader code.

## Integrity checks

Database constraints and loader validation must establish:

- every access subtype references an `access` endpoint;
- every handoff subtype references a `handoff` endpoint and carries one
  direction;
- every active leg references endpoints on the declared facility;
- every transfer crosses facilities;
- every leg and transfer is directed and non-self-referential;
- deactivated endpoints or facilities contribute no directed edges;
- every agent-visible access movement has a non-null SRID 4326 point;
- `entry`, `exit`, and `handoff` roles are never conflated;
- source identities and directed pair identities are unique;
- every transfer has a stable source identity and connector classification;
- every route proof starts with entry and ends with exit;
- no proof repeats an endpoint or transfer;
- I-95 never resolves to bidirectionally open;
- fully closed I-95 is distinct from unknown evidence;
- pricing tables are not referenced by structural-validity functions.

Cross-table semantic checks that cannot be expressed with ordinary foreign
keys should run in the deterministic loader and SQL contract tests rather than
in cross-row `CHECK` constraints.

## Acceptance tests

At minimum, tests must cover:

### Structural routing

- Greenway -> Dulles Toll Road -> I-495 -> I-95 produces an ordered proof with
  all three explicit transfers.
- The supported reverse route produces the reverse directed transfers.
- Eastbound Dulles Toll Road can follow distinct valid transfers to northbound
  and southbound I-495; wrong-way versions of each are rejected.
- Direction-specific handoff endpoints permit their matching legs and reject
  incompatible incoming or outgoing directions.
- The I-495/I-95 transfer is returned as a disclosed `general_purpose_gap`, not
  an uninterrupted Express Lane segment.
- A missing or wrong-way transfer returns `no_supported_route` or
  `direction_mismatch`.
- Fixed one-way I-66 and I-495 ramps cannot be used backward.
- An exit-only movement cannot start a route, and an entry-only movement cannot
  end one.
- Two same-label, same-function, same-direction source movements remain
  separate endpoints and retain their own coordinates and reachability.
- Deactivating an endpoint or facility independently removes its edges and any
  route that depends on them.
- A deliberately cyclic fixture terminates without repeating endpoints.

### I-95 availability

- Northbound open enables only northbound I-95 legs.
- Southbound open enables only southbound I-95 legs.
- A southbound structural route while northbound is open, and the reverse case,
  retain their proof but return `i95_opposite_direction_open`.
- Both closed retains the structural proof but returns `i95_fully_closed`.
- Both open, transitions, missing sources, interval mismatch, and stale data
  return `availability_unknown`.
- A `calculated_at` exactly inside and outside the 20-minute boundary verifies
  the freshness clock and cutoff.
- Future `calculated_at` values at the two-minute tolerance boundary are
  accepted as age zero; values beyond it return `availability_unknown`.

### Spatial alternatives

- Results preserve entry/exit function and compatible direction.
- Results include only Express Lane access movements.
- The unavailable movement is excluded.
- Distances are monotonic and deterministic.
- A route counterpart removes geographically close but unreachable candidates.
- Entry alternatives validate candidate entry to requested exit; exit
  alternatives validate requested entry to candidate exit.
- Role-incompatible route counterparts return a structured error.
- Same-facility scope is the default, while explicitly disabling it permits a
  reachable cross-facility candidate.
- The resolver uses travel direction to distinguish same-label movements and
  reports unresolved ambiguity when direction is omitted.
- The agent-callable resolver never returns a handoff, even when its alias
  matches exactly.
- Fully closed I-95 yields no Express Lane alternatives.
- Unknown I-95 availability blocks I-95-dependent candidates without
  suppressing valid candidates confined to fixed-direction facilities.
- Generalized v1 frontend pins are absent from canonical coordinate sources.

### Operational contracts

- Blank restore, additive migration, rollback, grants, and extension presence
  are tested.
- Each approved function executes successfully under the actual agent role.
- The agent role cannot read or mutate oracle tables or execute unapproved
  functions.
- Functions never return pricing fields.

## Implementation sequence

1. Confirm the deployed RDS PostgreSQL and available PostGIS versions.
2. Add a v2 migration for core PostGIS and the owned `oracle` schema.
3. Build the v2 source manifest, normalized access movements, direct legs, and
   explicit transfers.
4. Add integrity and representative route fixtures before loading production
   data.
5. Add the I-95 operational-state view that distinguishes closed from unknown.
6. Implement and test structural route validation.
7. Implement and test PostGIS alternative lookup.
8. Grant schema usage and approved function execution to the future agent
   runtime role, with no underlying table privileges.
9. Add the agent wrapper and eval cases after the database contract is stable.

## Rejected alternatives

### Use pricing rows as route edges

Rejected because pricing coverage and route reachability are different facts.
Unpriced gaps and unavailable observations would create false invalid routes.

### Store only ramp points

Rejected because proximity alone cannot prove that an entry reaches a chosen
exit or that facilities connect in the required direction.

### Import full road centerlines and use pgRouting

Rejected for the first version because TollChat does not need street routing,
cost optimization, or map-matched paths. It would add topology maintenance
without improving the oracle's defined answer.

### Precompute complete transitive closure immediately

Rejected initially because the graph is small and updates are rare. Recursive
traversal keeps direct evidence visible and avoids closure-refresh complexity.
A materialized reachability view may be added only after measurement shows a
need.

### Let the language model compose SQL

Rejected because route validity and availability must be deterministic,
bounded, testable, and least-privileged.

## Research references

[^postgres-recursive]:
    [PostgreSQL 18: recursive `WITH`, search order, and cycle detection](https://www.postgresql.org/docs/18/queries-with.html)
[^postgis-dwithin]: [PostGIS `ST_DWithin`](https://postgis.net/docs/en/ST_DWithin.html)
[^postgis-knn]: [PostGIS nearest-neighbor `<->` operator](https://postgis.net/docs/en/geometry_distance_knn.html)
[^pgrouting-graph]: [pgRouting sample graph model](https://docs.pgrouting.org/latest/en/sampledata.html)
[^aws-postgis]:
    [Amazon RDS: managing spatial data with PostGIS](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/Appendix.PostgreSQL.CommonDBATasks.PostGIS.html)
[^postgres-function-security]:
    [PostgreSQL 18: function security](https://www.postgresql.org/docs/18/perm-functions.html)
[^transurban-map]: [Transurban Express Lanes trip map](https://www.expresslanes.com/map-your-trip/)
[^fairfax-gis]:
    [Fairfax County public roadway-centerline service](https://www.fairfaxcounty.gov/gispubsf1/rest/services/DPSC/RapidDeploy/MapServer/0)
[^arlington-gis]:
    [Arlington County public street-network layer](https://arlgis.arlingtonva.us/arcgis/rest/services/Open_Data/od_Street_Network/FeatureServer/0)
[^loudoun-gis]:
    [Loudoun County public road-centerline layer](https://logis.loudoun.gov/gis/rest/services/COL/LandRecords/MapServer/3)
