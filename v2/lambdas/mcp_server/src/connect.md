# TollChat MCP server

TollChat finds the toll-road ramps for a Northern Virginia trip and estimates what a regular commute on them costs in tolls per year. It covers the I-495 and I-95/I-395 Express Lanes, I-66 inside the Beltway, the Dulles Toll Road, the Dulles Greenway, and the IAD/DCA airport connections.

- **Endpoint:** `https://mcp.tollchat.ai/mcp`
- **Transport:** MCP Streamable HTTP, stateless. Every `POST` gets one `application/json` response; there are no sessions and no `GET` event stream.
- **Authentication:** none. Call from server-side code: requests carrying a browser `Origin` header get `403`.
- **Protocol versions:** `2025-11-25` and earlier (with the `initialize` handshake) and `2026-07-28` (no handshake; each request carries its version).
- **Privacy:** https://mcp.tollchat.ai/privacy
- **Version:** 0.4.0 (`serverInfo.version`)

## Changes

- **0.4.0, 2026-10-27:** `find_toll_ramps` returns one path per trip: the best route, plus other ramps onto the same roads in the same direction, never a second way around (Springfield to DC gets I-395, without the I-495 and I-66 alternative). The ranking now counts toll miles at half alongside access miles (`score.toll_miles`), so long detours rank last. Routes are chosen as the estimate prices them, without today's reversible-lane state, so the answer no longer changes with the time of day: an option that uses the I-95/I-395 reversible lanes is listed even while they run the other way, and its `reversible_lanes.usable_now` says whether it can be driven right now. The `currently_unavailable` and `availability_unknown` statuses and the top-level `reversible_lanes` field are gone, and a `route_id` no longer changes when the lanes do. `estimate_annual_tolls` scores return trips the same way.
- **0.3.1, 2026-10-27:** for routes with an I-95/I-495 leg, `estimate_annual_tolls` now estimates from whichever recent days have prices, so gaps in that feed rarely cause refusals. It refuses only when a commute weekday has fewer than two priced days or under a quarter of all days are priced. Other routes keep the half-of-each-weekday rule.
- **0.3.0, 2026-10-26:** new tool `estimate_annual_tolls`, a ballpark annual toll range for one `find_toll_ramps` option. `find_toll_ramps` is unchanged.
- **0.2.0, 2026-10-26:** `find_toll_ramps` takes each end as latitude and longitude. Place text inputs were removed on 2026-10-26, together with the server's place lookups (Amazon Location) and their daily limit; a call that still sends place text gets a tool error. Results gain `calculated_at`, `route_id`, `segments`, `score`, and `reversible_lanes`, and the text content is now a short summary. The `match`, `ambiguous`, `place_not_found`, and `daily_lookup_limit` results are gone, and `same_location` is new. Facility codes, the ordering rule, and the other statuses are unchanged.

## Connect with the 2025 handshake

Send these requests in order. The `initialized` notification gets an empty `202 Accepted`.

```http
POST /mcp HTTP/1.1
Host: mcp.tollchat.ai
Content-Type: application/json
Accept: application/json, text/event-stream

{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"my-assistant","version":"1.0"}}}
```

```http
POST /mcp HTTP/1.1
Host: mcp.tollchat.ai
Content-Type: application/json
Accept: application/json, text/event-stream
MCP-Protocol-Version: 2025-11-25

{"jsonrpc":"2.0","method":"notifications/initialized"}
```

```http
POST /mcp HTTP/1.1
Host: mcp.tollchat.ai
Content-Type: application/json
Accept: application/json, text/event-stream
MCP-Protocol-Version: 2025-11-25

{"jsonrpc":"2.0","id":2,"method":"tools/list"}
```

```http
POST /mcp HTTP/1.1
Host: mcp.tollchat.ai
Content-Type: application/json
Accept: application/json, text/event-stream
MCP-Protocol-Version: 2025-11-25

{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"find_toll_ramps","arguments":{"origin":{"latitude":38.96165,"longitude":-77.36346},"destination":{"latitude":38.9173,"longitude":-77.22093}}}}
```

Then estimate the yearly tolls for the first option it returns:

```http
POST /mcp HTTP/1.1
Host: mcp.tollchat.ai
Content-Type: application/json
Accept: application/json, text/event-stream
MCP-Protocol-Version: 2025-11-25

{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"estimate_annual_tolls","arguments":{"entry_point_id":"dtr:12:entry:EB","exit_point_id":"dtr:1819:exit:EB"}}}
```

## Call with protocol 2026-07-28

No handshake. Each request must carry the `MCP-Protocol-Version`, `Mcp-Method`, and `Mcp-Name` headers, and name its protocol version, client, and capabilities in `_meta`.

```http
POST /mcp HTTP/1.1
Host: mcp.tollchat.ai
Content-Type: application/json
Accept: application/json, text/event-stream
MCP-Protocol-Version: 2026-07-28
Mcp-Method: tools/call
Mcp-Name: find_toll_ramps

{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"find_toll_ramps","arguments":{"origin":{"latitude":38.96165,"longitude":-77.36346},"destination":{"latitude":38.9173,"longitude":-77.22093}},"_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28","io.modelcontextprotocol/clientInfo":{"name":"my-assistant","version":"1.0"},"io.modelcontextprotocol/clientCapabilities":{}}}}
```

## Tool: `find_toll_ramps`

**Classification: Read.** It reads TollChat's ramp catalog and the live reversible-lane direction. It changes nothing, calls no other service, and counts against no daily limit (only the request throttle under Limits applies), so repeating a call is safe.

**Input**

| Field | Type | Meaning |
| --- | --- | --- |
| `origin` | object: `latitude`, `longitude` | Where the trip starts. |
| `destination` | object: `latitude`, `longitude` | Where the trip ends. |
| `latitude` | number, −90 to 90 | WGS-84 decimal degrees north (about 38.9 here). |
| `longitude` | number, −180 to 180 | WGS-84 decimal degrees east (about −77.3 here). |

- **Named fields only.** Arrays such as `[lon, lat]`, place text, numeric strings, `null`, and missing or extra fields get a tool error (`isError: true`) that names the end and field to fix.
- **Precision:** coordinates are read as 64-bit doubles and echoed as read: nothing is rounded or rejected for extra digits, though digits beyond double precision are lost and an integer such as `-77` comes back as `-77.0`. Five decimal places (about 1 m) is plenty. A landmark or nearby intersection is precise enough; an exact home location is not needed.
- **JSON parsing** happens before the tool runs: if a field repeats, the last value wins, and JSON the server cannot parse (such as a number too large for a double) gets an HTTP or JSON-RPC error instead of a tool error.
- **Swapped pairs:** if an end is outside coverage but would be covered with its latitude and longitude swapped, the call fails with "… did you swap latitude and longitude?".
- **Coverage:** an origin is covered when a toll entry is within 8 straight-line miles; a destination, when a toll exit is.

**Worked example:** Reston Town Center to Tysons Corner Center, as in the requests above.

```json
{"origin":{"latitude":38.96165,"longitude":-77.36346},"destination":{"latitude":38.9173,"longitude":-77.22093}}
```

The result has `status: "resolved"` and two options, both on the Dulles Toll Road. The first:

```json
{
  "route_id": "dtr:12:entry:EB>dtr:1819:exit:EB",
  "entry": {"point_id": "dtr:12:entry:EB", "network": "dtr", "role": "entry", "direction": "EB", "label": "Exit 12 - SR 602 (Reston Pkwy)"},
  "exit": {"point_id": "dtr:1819:exit:EB", "network": "dtr", "role": "exit", "direction": "EB", "label": "Exit 18/19 - I-495 / SR 123 (Capital Beltway)"},
  "facilities": ["dtr"],
  "segments": [
    {"facility": "dtr", "entry_point_id": "dtr:12:entry:EB", "exit_point_id": "dtr:1819:exit:EB", "straight_line_miles": 7.9,
     "pricing_keys": [{"source_route_key": "EB:12:1819", "charge_index": 1}, {"source_route_key": "EB:12:1819", "charge_index": 2}]}
  ],
  "total_straight_line_miles": 7.9,
  "access_miles": {"origin": 0.8, "destination": 1.1},
  "score": {"access_miles": 1.9, "toll_miles": 3.9, "facility_penalty_miles": 0.0, "total": 5.8}
}
```

**Output.** `structuredContent` is the result. The text content is a one-line summary for people, not a copy of the JSON.

- `status`: one of the values in the table below. A `status: error` result also echoes `origin` and `destination`.
- `calculated_at`: when the result was computed, RFC 3339 in UTC, for example `2026-10-26T18:17:00.123456Z`.
- `origin`, `destination`: the coordinates as received, with `coverage` (`covered` or `outside_coverage`).
- `options`: the best route first, then up to 2 other ramp choices on the same roads; `[]` unless `status` is `resolved`. Every option has passed TollChat's pricing route validation.

Each option has:

- `route_id`: the entry, each toll segment's ends, and the exit, joined by `>`, such as `dtr:12:entry:EB>dtr:1819:exit:EB` or `dtr:12:entry:EB>dtr:1819:exit:EB>i495:182SO>i495:185SD`. The same ID always means the same priced route.
- `entry`, `exit`: `point_id`, `network`, `role` (`entry`, `exit`, or `airport`), `direction` (`NB`, `SB`, `EB`, or `WB`; omitted for airport points), and `label`.
- `facilities`: the toll facilities used, in travel order.
- `segments`: one per stretch of toll road, in travel order, with `facility`, `entry_point_id`, `exit_point_id`, `straight_line_miles`, and `pricing_keys`. Untolled connections, such as airport access roads or the free stretch from I-66 to the Dulles Toll Road's Exit 18/19, have no segment, and their intermediate points are not in `route_id`; so an entry's or exit's `network` can differ from the first or last facility. A transfer between the Greenway and the Dulles Toll Road adds a 0.0-mile `dtr` segment, from one road's Route 28 point to the other's, for the $2 DTR connection charge.
- `total_straight_line_miles`: the segments' sum.
- `access_miles`: straight-line miles from the origin to the entry and from the exit to the destination. These are not toll miles.
- `score`: `access_miles` (both access legs), `toll_miles` (half of `total_straight_line_miles`), `facility_penalty_miles` (2 per toll facility after the first), and `total`, their sum, which orders the options.
- `reversible_lanes`: `{"direction": …, "usable_now": …}`, only when the option depends on the I-95/I-395 reversible lanes. `direction` is where they run now; `usable_now` is `true` when that suits this option, `false` when they are closed or run the other way, and `null` when the direction is unknown. The option is listed either way, because a commute uses the lanes at commute time, not now.

Miles are rounded to 0.1, so parts can differ from a total by 0.1.

**Miles and prices.** `straight_line_miles` is the straight-line distance between a segment's ends; the road is longer. TollChat has no road-mile data (a future source would be the operators' published segment lengths), and its own annual estimate uses the same straight-line basis. This tool returns no prices; `estimate_annual_tolls` turns an option into an annual toll range. A segment's point IDs and `pricing_keys` (opaque keys into the operators' toll tables, one per toll charged on that stretch) are the join keys for a later pricing tool, and the option shape will not change for it. The Dulles Toll Road charges two tolls on some stretches, so such a segment has two keys. A facility appears in consecutive segments when its operator prices the trip in parts, for example the I-495 and I-95/I-395 Express Lanes.

**One path, ordering, and the 3-option cap.** Routes are ranked by `score.total`: the straight-line access miles plus half the toll miles (the express lanes run about twice as fast as the roads to the ramps), with each extra toll facility counting as 2 more miles. The best route sets the path: only routes over the same roads in the same direction are listed, so a trip to DC gets I-395 or I-66, whichever ranks first, never both. Ordering uses the unrounded score, so options showing the same rounded total can still differ; exact ties are ordered by entry, then exit point ID. Approach variants of one interchange appear once, and at most 3 options are returned. The ranking ignores price, so on the rare trip where two paths are close, the cheaper one can be left out.

**Point IDs.** Use them exactly as returned; never build or edit one.

| `network` | ID grammar | Example |
| --- | --- | --- |
| `dtr`, `greenway`, `i66` | `<network>:<interchange>:<entry or exit>:<EB or WB>` | `dtr:12:entry:EB` |
| `i495`, `i95` | `<network>:<ramp><N or S><O or D>` | `i495:185SD` |
| `airport_iad`, `airport_dca` | the network itself | `airport_iad` |

- `<interchange>` is the operator feed's interchange code, such as `12`, `1819` (Exit 18/19), or `2A`.
- `<ramp>` is the operator's numeric ramp code. Treat it as opaque: extra digits distinguish nearby ramps, and an exit code ending in an extra `9` (such as `1859ND` beside `185ND`) is the same exit reached from another approach, as its label says.
- `N` or `S` is northbound or southbound; `O` is an on-ramp (an entry) and `D` an off-ramp (an exit).

**Facilities and networks**

| `network` | Facility code | Facility |
| --- | --- | --- |
| `greenway` | `greenway` | Dulles Greenway |
| `dtr` | `dtr` | Dulles Toll Road |
| `i66` | `i66` | I-66 Express Lanes inside the Beltway |
| `i495`, `i95` | `i95_i495` | I-495 Express Lanes and I-95/I-395 Express Lanes |
| `airport_iad`, `airport_dca` | none | Airport connection to a toll road |

**Labels** are display text from the operators' feeds, naming the interchange rather than the toll road: an I-495 ramp at the I-66 interchange is labeled "Interstate 66" though its facility is `i95_i495`. Never use a label as a key.

**Airports.** An airport point is used only when that end is within 1.5 miles of it; otherwise the airport is reached like any other place, by an access leg to a nearby entry or exit. Dulles (`airport_iad`) connects to the Dulles Toll Road, I-66, and I-495, so Dulles trips usually start or end there. Reagan National (`airport_dca`) connects only to the I-95/I-395 reversible lanes: its departures need the lanes running in the trip's direction, and its arrivals need them northbound. A DCA route that uses them carries `reversible_lanes`; one that ranks better through an ordinary entry or exit, often on I-66, is listed instead.

**Reversible lanes.** The I-95/I-395 Express Lanes change direction during the day, typically northbound on weekday mornings and southbound in the afternoon and evening. Routes are chosen as if the lanes ran the trip's way. An option's `reversible_lanes.direction` is `northbound`, `southbound`, `closed`, or `unknown`, read from the operator's feed now; data more than 20 minutes old, missing, or contradictory is `unknown`. TollChat cannot say when the direction will next change. For a trip now, an option with `usable_now: false` cannot be driven until the lanes turn; for a commute estimate, it does not matter.

| `status` | Meaning | What to do |
| --- | --- | --- |
| `resolved` | Validated options are listed. | Confirm the chosen option with the user. |
| `same_location` | Both ends are covered and within 0.1 mile of each other, so there is no trip. | Ask for distinct start and end points. It is not a zero-toll trip. |
| `outside_coverage` | An end is not covered (see each end's `coverage`). | Tell the user TollChat does not cover it. |
| `no_valid_route` | Both ends are covered, but no supported toll route connects them. | Tell the user. It is not a zero-toll trip. |
| `error` (with `isError: true`) | Something failed on TollChat's side. | Retry as below; if it keeps failing, tell the user. |

Invalid arguments get a tool error (`isError: true`, no structured content) whose text says what to fix.

## Tool: `estimate_annual_tolls`

**Classification: Read.** It reads TollChat's ramp catalog and recent toll prices. It changes nothing, calls no other service, and counts against no daily limit, so repeating a call is safe.

It estimates what a regular commute on one `find_toll_ramps` option costs in tolls per year. It is a ballpark from recent prices, not a quote: present it as a range.

**Input**

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `entry_point_id` | string | required | The chosen option's `entry.point_id`. |
| `exit_point_id` | string | required | The same option's `exit.point_id`. |
| `depart_at` | `HH:MM` | `08:30` | When the trip from the origin starts, 24-hour America/New_York time. |
| `return_at` | `HH:MM` | `17:30` | When the return trip starts, later the same day (overnight schedules are not supported). |
| `weekdays` | list of day names | `monday` to `friday` | Commute days of the week, as lowercase English names. |
| `annual_commute_days` | integer | 50 × weekdays | Commute days per year: 250 for five weekdays, 150 for three. At most 53 × weekdays. |

Each invalid field gets a tool error naming it, and unknown fields are rejected. `null` for an optional field means its default. The entry and exit must form a toll route, as every `find_toll_ramps` option does.

**Return trip.** Pass only the outbound option. TollChat picks the way back itself, from entries near the outbound exit to exits near the outbound entry (the nearest per road, plus any within 3 miles). It prefers routes through the same roads in reverse, judged by the road networks they pass through whether tolled or not, then the best score, as in `find_toll_ramps`. Its ramps can differ from the outbound ones (out from Franconia-Springfield, back to Backlick Road, say), which barely changes the price.

**How it is estimated**

- Both trips are validated without today's reversible-lane state, because past days are priced; `find_toll_ramps` chooses routes the same way, so `outbound.route_id` matches the option's.
- The I-95/I-395 reversible lanes are priced only on days they ran the trip's way at that time. A trip against their usual direction (southbound at 08:30, say) has no priced days and gets `too_few_recent_prices`.
- For each of the last 84 completed days that falls on a commute weekday, TollChat prices the outbound trip at `depart_at` and the return trip at `return_at`. I-66 and I-95/I-495 use the operators' recorded prices at that time (the 6- or 10-minute interval containing it). The Dulles Toll Road and Greenway use their current published rates, applied to past dates.
- A day counts only if every toll on both trips has a price. I-66's toll-free times and holidays count as $0.
- `daily_round_trip_usd` is the 25th, 50th, and 90th percentile (`low`, `typical`, `high`) of those days' round-trip totals; `annual_toll_usd` multiplies each by `annual_commute_days`.
- **Routes with an I-95/I-495 leg:** that leg needs feed data every day, so gaps in the feed drop days at random. That thins the sample without biasing it, so the estimate uses whichever days are priced, and `basis` says how many. It refuses, with `too_few_recent_prices`, only when a commute weekday has fewer than two priced days or fewer than a quarter of all eligible days are priced.
- **Other routes** need at least half of each commute weekday's days priced. I-66 prices its toll-free weekends and holidays at $0 even when data is missing, so its gaps drop only tolled days. Without this rule, missing data would read as low or zero tolls.
- Some I-95 trips use modeled prices for origin-destination pairs the operator does not publish; `basis.uses_modeled_prices` says so.

**Worked example:** the first Reston Town Center → Tysons option above, with the defaults, as in the request above. The Dulles Toll Road charges $2 at the Exit 12 ramp and $4 at the main plaza each way, so $12 a day. An excerpt of the result, without the `entry`, `exit`, `window`, and `coverage_by_weekday` fields:

```json
{
  "status": "estimated",
  "schedule": {"depart_at": "08:30", "return_at": "17:30", "timezone": "America/New_York", "weekdays": ["monday", "tuesday", "wednesday", "thursday", "friday"], "annual_commute_days": 250},
  "outbound": {"route_id": "dtr:12:entry:EB>dtr:1819:exit:EB", "facilities": ["dtr"]},
  "return": {"route_id": "dtr:1819:entry:WB>dtr:12:exit:WB", "facilities": ["dtr"]},
  "annual_toll_usd": {"low": 3000.0, "typical": 3000.0, "high": 3000.0},
  "daily_round_trip_usd": {"low": 12.0, "typical": 12.0, "high": 12.0},
  "by_facility": [{"facility": "dtr", "annual_toll_usd": {"low": 3000.0, "typical": 3000.0, "high": 3000.0}, "priced_days": 60}],
  "basis": {"method": "recent_complete_same_date_round_trips", "eligible_days": 60, "priced_days": 60, "coverage_percent": 100.0, "sample_status": "complete", "uses_modeled_prices": false, "uses_published_fixed_rates": true}
}
```

**Output.** `structuredContent` is the result. The text content is a one-line summary.

- `status`: one of the values in the table below. `calculated_at`: when the result was computed, in UTC.
- `schedule`: the times (America/New_York), weekdays, and annual days used, with defaults filled in.
- `outbound`, `return`: `route_id`, `entry`, `exit`, and `facilities`, as in a `find_toll_ramps` option.
- `annual_toll_usd`, `daily_round_trip_usd`: `low`, `typical`, and `high`, in US dollars, only when `status` is `estimated`.
- `by_facility`: each toll road's `annual_toll_usd` range and `priced_days`. The roads' ranges do not add up to the total, because percentiles are taken over whole days.
- `basis` (absent for `no_return_route`): `method`; `window` (`start_date` and `end_date` of the 84 days); `eligible_days` (commute weekdays in the window); `priced_days`; `coverage_percent`; `coverage_by_weekday` (`weekday`, `eligible_days`, `priced_days`); `sample_status` (`complete` when every eligible day is priced, otherwise `partial`); `uses_modeled_prices`; and `uses_published_fixed_rates`.
- `message`: for statuses without an estimate.

| `status` | Meaning | What to do |
| --- | --- | --- |
| `estimated` | Enough recent days were priced. | Quote `annual_toll_usd.typical` as a ballpark with the low–high range, and mention partial coverage. |
| `too_few_recent_prices` | Too few recent days had prices for every toll on both trips at these times (see the rules above): the data is missing, or the I-95/I-395 reversible lanes rarely ran the needed way then. | Tell the user TollChat cannot estimate this schedule; try other times or another option. Never treat it as zero tolls. |
| `no_return_route` | No toll route back was found near the outbound ramps. | Tell the user TollChat could not price a round trip; try another option. |
| `error` (with `isError: true`) | Something failed on TollChat's side. | Retry as below; if it keeps failing, tell the user. |

## Limits

- No daily limit: the server makes no paid lookups.
- About 2 requests per second across all clients, with bursts up to 5; excess requests get HTTP `429`.
- Request bodies up to 64 KiB.
- An estimate reads 84 days of prices and can take several seconds. One that takes more than 20 seconds stops with `status: error`.

## Retries

- Retry a transport failure (no response, reset, or timeout), HTTP `429` or `5xx`, or `status: error` at most twice, waiting about 1 then 2 seconds plus random jitter.
- Calls are read-only and count against no limit, so a retry after a lost response double-counts nothing.
- Log each attempt's UTC time to the millisecond; TollChat can match it against its per-minute request counts.
- A call that never got an answer is unknown: never report it as "no route" or "zero tolls".
- Pace bulk tests below 2 requests per second, or the throttle answers `429`.

## Using TollChat well

- Geocode the user's places yourself; a landmark, neighborhood, or nearby intersection is precise enough. Do not press for an exact home location.
- Confirm the chosen option with the user before relying on it.
- For a yearly cost, pass the chosen option's entry and exit to `estimate_annual_tolls` and quote its range as a ballpark.
- Use returned point IDs exactly; never invent or edit them.
- Miles are straight-line, `find_toll_ramps` returns no prices, and every result is an estimate.
- Save this connector so it can be reused instead of rebuilt each conversation.
