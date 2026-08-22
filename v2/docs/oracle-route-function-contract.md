# Oracle Route Function Contract

- **Status:** Adopted in oracle `1.5.0`; current schema `1.10.1`
- **Audience:** TollChat v2 agent tool and its callers
- **Operation:** `oracle.validate_toll_route(text, text)`

## Purpose

This function answers whether one supported toll access movement can reach
another **right now**. It follows the curated directed oracle graph, applies
live I-95/395 direction state where required, and explains any supported
general-purpose connection at the I-495/I-95 boundary.

For a known ramp that cannot serve the submitted trip, it may return up to two
same-facility replacement ramps. It does not resolve user language to point
IDs, calculate a toll, provide navigation, or prove that an unsupported
real-world route is impossible.

## Agent tool boundary

The agent-facing tool accepts exactly two stable point IDs:

| Input | Required meaning |
| --- | --- |
| `origin_point_id` | An oracle `entry` or airport point |
| `destination_point_id` | An oracle `exit` or airport point, or a direct curated IAD airport-access entry connector |

The tool wrapper must pass both values as bound parameters. It must not expose
arbitrary SQL, accept labels in place of IDs, infer connections from proximity,
or silently substitute another point. Point-name resolution belongs before this
operation.

```sql
SELECT *
FROM oracle.validate_toll_route($1, $2);
```

The function returns exactly one row with this shape:

| Field | Type | Contract |
| --- | --- | --- |
| `status` | `text` | One status from the table below |
| `reason` | `jsonb` or null | Structured explanation for every non-`valid` status |
| `point_ids` | `text[]` | Selected route points in travel order |
| `connection_ids` | `text[]` | Selected connections in travel order |
| `connection_types` | `text[]` | Type aligned with each connection ID |
| `general_purpose_gaps` | `jsonb` | Ordered TP1 fallback explanations |
| `i95_evidence` | `jsonb` or null | Live evidence used by the result |

`connection_ids` and `connection_types` always have the same length.
`point_ids` has one more item than those arrays for a returned structural path.

## Status contract

| Status | Meaning | Path returned? |
| --- | --- | --- |
| `invalid_origin` | Origin is missing, has the wrong role, or cannot form the requested directed route | No |
| `invalid_destination` | Destination is missing, has the wrong role, or cannot form the requested directed route | No |
| `valid` | At least one currently usable path exists | Yes |
| `currently_unavailable` | Every structural proof requires a known unavailable I-95 direction | Yes |
| `unknown_availability` | No usable proof exists without unknown I-95 evidence | Yes |
| `no_supported_route` | Bounded traversal conclusively found no graph path | No |
| `traversal_limit_exceeded` | The 12-connection limit prevented a conclusion | No |

Origin validation takes precedence over destination validation. For valid
inputs, the function prefers statuses in this order:

1. `valid`
2. `traversal_limit_exceeded`
3. `unknown_availability`
4. `currently_unavailable`
5. `no_supported_route`

Within the same status, the function selects the fewest-connection proof and
then breaks ties by ordered connection IDs. It never relies on recursive-query
emission order.

For statuses without a path, all three path arrays and
`general_purpose_gaps` are empty, and `i95_evidence` is null. Availability
statuses retain the structural proof that could not currently be used.

## Reason contract

`reason` is SQL null when `status` is `valid`. Every other status returns one
JSON object with exactly these top-level fields:

```json
{
  "code": "i95_opposite_direction_open",
  "details": {
    "required_i95_directions": ["NB"],
    "availability": "southbound"
  }
}
```

`code` is a stable machine-readable value. `details` is always a JSON object;
callers must use the code and details to produce user-facing prose rather than
displaying either as a prewritten message.

| Status | Reason code | Details |
| --- | --- | --- |
| `invalid_origin` | `origin_required` | Empty object |
| `invalid_origin` | `origin_not_found` | Submitted `point_id` |
| `invalid_origin` | `origin_not_entry` | `point_id`, actual `point_type`, allowed point types, and `alternatives` |
| `invalid_origin` | `origin_ramp_incompatible` | `point_id`, actual `point_type`, and `alternatives` |
| `invalid_origin` | `i95_northbound_requires_i495_restart` | Submitted `point_id`, `entry` point type, `suggested_restart_point_id` (`i495:192NO`), and direction-compatible `suggested_destination_point_id` |
| `invalid_destination` | `destination_required` | Empty object |
| `invalid_destination` | `destination_not_found` | Submitted `point_id` |
| `invalid_destination` | `destination_not_exit` | `point_id`, actual `point_type`, allowed point types, and `alternatives` |
| `invalid_destination` | `destination_ramp_incompatible` | `point_id`, actual `point_type`, and `alternatives` |
| `currently_unavailable` | `i95_opposite_direction_open` | Required directions and observed availability |
| `currently_unavailable` | `i95_fully_closed` | Required directions and `closed` availability |
| `unknown_availability` | `i95_missing_source` | Required directions and `unknown` availability |
| `unknown_availability` | `i95_invalid_source` | Required directions and `unknown` availability |
| `unknown_availability` | `i95_interval_mismatch` | Required directions and `unknown` availability |
| `unknown_availability` | `i95_future_evidence` | Required directions and `unknown` availability |
| `unknown_availability` | `i95_stale_evidence` | Required directions and `unknown` availability |
| `unknown_availability` | `i95_indeterminate_state` | Required directions and `unknown` availability |
| `no_supported_route` | `no_supported_route` | Origin and destination point IDs |
| `traversal_limit_exceeded` | `traversal_limit_exceeded` | Point IDs and `maximum_connections` (`12`) |

Required I-95 directions are returned in structural-path order. The reason
classification follows the same evidence precedence as availability: missing
fields, invalid corridor identities, mismatched intervals, future evidence,
stale evidence, and finally an indeterminate link state.

## Invalid-ramp alternatives

The `i95_northbound_requires_i495_restart` result is intentionally separate:
it contains no `alternatives`. It applies when a northbound I-95 entry at or
south of the I-495/I-95 junction cannot continue to a northbound I-495 exit
through the supported toll graph, and gives the caller the exact TP1NB point
for a separately accepted current-price call.
The result is independent of live I-95 direction state and contains no route
path or I-95 evidence.

`origin_not_entry`, `destination_not_exit`, `origin_ramp_incompatible`, and
`destination_ramp_incompatible` include an `alternatives` JSON array. Each
item has exactly these public fields:

| Field | Meaning |
| --- | --- |
| `point_id` | Stable replacement point ID |
| `network_id` | Facility identifier; always matches the submitted ramp |
| `source_node_id` | Source ramp identifier |
| `point_type` | `entry` for an origin replacement or `exit` for a destination replacement |
| `direction` | Supported movement direction |
| `label` | Display label |
| `aliases` | Ordered public aliases |
| `location` | GeoJSON Point or null when coordinates are unavailable |

The array contains at most two ramps. Each candidate forms a structural path
to or from the unchanged opposite endpoint within the same 12-connection
bound. Ranking uses reviewed corridor-local order, retained preferences, and a
stable point-ID tie-break. Selection deliberately ignores live I-95
availability; a follow-up call with the driver's chosen point applies normal
availability rules. Missing and unknown point IDs do not receive suggestions.
For role-correct same-corridor ramps, corridor order identifies which movement
conflicts with the requested direction. When both conflict, origin recovery
takes precedence.

An alternative **changes the priced endpoint**. It is not a general-purpose
lane route, turn-by-turn navigation advice, or proof that the driver can access
the suggested ramp from the originally requested place. The submitted trip
remains invalid: TollChat must present the choices, wait for the driver to
select one, and call again with that exact point ID. It must never silently
substitute or validate a suggestion.

## General-purpose gap contract

`general_purpose_gaps` is always a JSON array. Each item corresponds to a
selected `general_purpose_gap` connection and contains:

| Field | Value |
| --- | --- |
| `connection_id` | Matching item from `connection_ids` |
| `boundary_point_id` | `i495:192NO` for TP1NB or `i495:192SD` for TP1SB |
| `role` | `prefix` before the I-495 toll leg or `suffix` after it |
| `i95_direction` | `NB` or `SB`; the Express direction that avoids fallback |
| `fallback_required` | `true`, `false`, or null |

Interpret `fallback_required` as follows:

| Value | Agent meaning |
| --- | --- |
| `true` | The needed I-95 direction is known unavailable; explain the GP prefix or suffix and name TP1 |
| `false` | The needed I-95 direction is open; do not tell the user that GP travel is required |
| null | I-95 state is unknown; the top-level status is `unknown_availability` unless another usable path wins |

A gap does not make the entire route free. It says only that the identified
prefix or suffix uses general-purpose lanes when required. Pricing later must
price the retained toll portion and must not charge for the GP segment.

## I-95 evidence

`i95_evidence` is returned when the selected path requires an I-95 direction or
contains a general-purpose gap. It is null for paths unrelated to I-95.

The `availability` field is one of:

| Value | Source interpretation |
| --- | --- |
| `northbound` | Northbound open and southbound closed |
| `southbound` | Northbound closed and southbound open |
| `closed` | Both directions closed |
| `unknown` | Missing, stale, future-dated, mismatched, contradictory, or transitional evidence |

When source rows exist, the evidence also includes both corridor names, link
statuses, interval ends, and calculation timestamps. When the pricing view
reports missing source data, including an empty feed, the evidence is
`{"availability":"unknown","reason":"missing_source"}`.

Both directional observations must describe the same interval and be no more
than 20 minutes old relative to PostgreSQL `statement_timestamp()`. The agent
must not reinterpret stale or contradictory evidence as a direction. It may
describe `closed` as closed; for `unknown`, it should say only that current
availability could not be confirmed.

## Required agent behavior

- Treat `valid` as supported by this oracle, not as turn-by-turn navigation.
- When `fallback_required` is true for a suffix, explain that the Express
  portion ends at TP1SB before the I-495/I-95 interchange and that the driver
  would need general-purpose lanes for the rest of the trip.
- When `fallback_required` is true for a prefix, explain that the driver would
  need general-purpose lanes until TP1NB, where the tolled I-495 portion begins.
- When it is false, do not claim that the fallback is mandatory.
- When it is null, follow the top-level `unknown_availability` status and say
  that the required I-95 direction could not be confirmed.
- Treat `currently_unavailable` as a current directional restriction, not a
  permanently invalid route.
- Treat `unknown_availability` as inconclusive; do not guess a direction.
- Treat `no_supported_route` as outside the curated graph, not proof that no
  physical route exists.
- Treat `traversal_limit_exceeded` as an internal inconclusive result, never as
  `no_supported_route`.
- For an invalid-ramp alternative, explain that choosing it changes the priced
  origin or destination, present only the returned choices, and wait for the
  driver to choose.
- Never describe a ramp alternative as general-purpose-lane routing,
  navigation advice, or proof of access from the requested place.
- Never substitute an alternative before a follow-up call with the selected
  point ID.
- Never invent a toll from this response. Pricing is a separate operation.
- Preserve point and connection order when handing the result to later tools.
- Surface a database/tool error as an operation failure; never fabricate one of
  the documented statuses.

## Examples

### Dulles Airport to Backlick while I-95 is closed

Call:

```sql
SELECT *
FROM oracle.validate_toll_route('airport_iad', 'i95:205SD');
```

Illustrative response excerpt (timestamp and corridor-name evidence fields are
omitted only for readability):

```json
{
  "status": "currently_unavailable",
  "reason": {
    "code": "i95_fully_closed",
    "details": {
      "required_i95_directions": ["SB"],
      "availability": "closed"
    }
  },
  "point_ids": ["airport_iad", "i495:182SO", "i95:205SD"],
  "connection_ids": [
    "iad_to_i495_south",
    "source:i95_shared:Southbound:182SO:205SD"
  ],
  "connection_types": ["airport_access", "general_purpose_gap"],
  "general_purpose_gaps": [
    {
      "connection_id": "source:i95_shared:Southbound:182SO:205SD",
      "boundary_point_id": "i495:192SD",
      "role": "suffix",
      "i95_direction": "SB",
      "fallback_required": true
    }
  ],
  "i95_evidence": {
    "availability": "closed",
    "northbound_link_status": "CLOSED",
    "southbound_link_status": "CLOSED"
  }
}
```

The agent should explain that this trip is currently unavailable as a complete
Express route: the I-495 Express portion ends at TP1SB before the I-495/I-95
interchange, and the driver would need general-purpose lanes for the remainder
to Backlick. The function does not return or authorize a price.

### I-95 origin using a TP1NB prefix

When northbound I-95 Express is unavailable, an I-95-origin to I-495 trip is
`currently_unavailable` with:

```json
{
  "boundary_point_id": "i495:192NO",
  "role": "prefix",
  "i95_direction": "NB",
  "fallback_required": true
}
```

The agent should explain that the driver uses general-purpose lanes to TP1NB
and begins the tolled I-495 trip there.

## Airports

- Dulles International Airport is an explicit external endpoint. Its
  `airport_access` connections may use the untolled Airport Access Highway;
  this does not make an ordinary Dulles Toll Road trip free.
- A direct IAD route may terminate at its curated I-66, DTR, or I-495 entry
  connector. These terminal `airport_access` routes are valid and untolled;
  other entry points remain invalid destinations.
- Reagan National Airport departures may enter I-395 northbound at `224NO` or
  southbound at `2233SO` near Pentagon/Eads, subject to the corresponding live
  direction. Reagan remains an arrival destination only through northbound
  exit `223ND`; there is no southbound arrival connection.
- An airport can be the origin or destination but never an intermediate point.

## Security and versioning

`tollchat_agent` receives only schema usage and execution on the exact function
signature. It has no direct read or write access to oracle or pricing tables.
The function is `STABLE SECURITY DEFINER`, owned by `oracle_owner`, uses a fixed
trusted search path, and performs no dynamic SQL.

This response shape is part of the independently versioned `oracle` schema
contract. Renaming a field, changing status meaning or precedence, changing
freshness rules, or changing null/empty behavior requires an oracle SemVer
change and corresponding PostgreSQL contract tests.

The database implementation and graph invariants remain specified in the
[routing oracle specification](oracle-spec.md).

## Internal pricing-route validation

The Python pricing wrapper binds the submitted endpoints directly to:

```sql
SELECT *
FROM oracle.validate_pricing_route($1, $2);
```

The function resolves the canonical route once and returns the seven route
fields above plus ordered `facility_legs` derived from committed connection
metadata. Existing endpoint and live-availability statuses retain their
meanings; only `valid` results contain facility legs.

`pricing_caller` may execute the internal validator and the bounded
`oracle.get_i66_pricing_comparisons(integer, integer)` and
`oracle.get_i95_i495_pricing_comparisons(integer)` operations. It cannot
execute agent-facing `oracle.validate_toll_route(text, text)`, the private
resolver, or select the underlying oracle or pricing relations directly.
`tollchat_agent` cannot execute this internal pricing validator.
