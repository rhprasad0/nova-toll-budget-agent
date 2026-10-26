# TollChat MCP server

TollChat finds the toll-road ramps for a Northern Virginia trip: the I-495 and I-95/I-395 Express Lanes, I-66 inside the Beltway, the Dulles Toll Road, the Dulles Greenway, and the IAD/DCA airport connections.

- **Endpoint:** `https://mcp.tollchat.ai/mcp`
- **Transport:** MCP Streamable HTTP, stateless. Every `POST` gets one `application/json` response; there are no sessions and no `GET` event stream.
- **Authentication:** none. Call from server-side code: requests carrying a browser `Origin` header get `403`.
- **Protocol versions:** `2025-11-25` and earlier (with the `initialize` handshake) and `2026-07-28` (no handshake; each request carries its version).
- **Privacy:** https://mcp.tollchat.ai/privacy
- **Version:** 0.2.0 (`serverInfo.version`)

## Changes

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

The result has `status: "resolved"` and three options. The first:

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
  "score": {"access_miles": 1.9, "facility_penalty_miles": 0.0, "total": 1.9}
}
```

**Output.** `structuredContent` is the result. The text content is a one-line summary for people, not a copy of the JSON.

- `status`: one of the values in the table below. A `status: error` result also echoes `origin` and `destination`.
- `calculated_at`: when the result was computed, RFC 3339 in UTC, for example `2026-10-26T18:17:00.123456Z`.
- `origin`, `destination`: the coordinates as received, with `coverage` (`covered` or `outside_coverage`).
- `options`: up to 3 routes, best first; `[]` unless `status` is `resolved`. Every option has passed TollChat's pricing route validation.
- `reversible_lanes`: `{"direction": …}`, only for `currently_unavailable` and `availability_unknown`.

Each option has:

- `route_id`: the entry, each toll segment's ends, and the exit, joined by `>`, such as `dtr:12:entry:EB>dtr:1819:exit:EB` or `dtr:12:entry:EB>dtr:1819:exit:EB>i495:182SO>i495:185SD`. The same ID always means the same priced route. One entry/exit pair can be routed differently when the reversible lanes change direction, and it then gets a different ID.
- `entry`, `exit`: `point_id`, `network`, `role` (`entry`, `exit`, or `airport`), `direction` (`NB`, `SB`, `EB`, or `WB`; omitted for airport points), and `label`.
- `facilities`: the toll facilities used, in travel order.
- `segments`: one per stretch of toll road, in travel order, with `facility`, `entry_point_id`, `exit_point_id`, `straight_line_miles`, and `pricing_keys`. Untolled connections, such as airport access roads or the free stretch from I-66 to the Dulles Toll Road's Exit 18/19, have no segment, and their intermediate points are not in `route_id`; so an entry's or exit's `network` can differ from the first or last facility. A transfer between the Greenway and the Dulles Toll Road adds a 0.0-mile `dtr` segment, from one road's Route 28 point to the other's, for the $2 DTR connection charge.
- `total_straight_line_miles`: the segments' sum.
- `access_miles`: straight-line miles from the origin to the entry and from the exit to the destination. These are not toll miles.
- `score`: `access_miles` (both access legs), `facility_penalty_miles` (2 per toll facility after the first), and `total`, which orders the options.
- `reversible_lanes`: `{"direction": …}`, only when the option depends on the I-95/I-395 reversible lanes. It is usable only while they run that way.

Miles are rounded to 0.1, so parts can differ from a total by 0.1.

**Miles and prices.** `straight_line_miles` is the straight-line distance between a segment's ends; the road is longer. TollChat has no road-mile data (a future source would be the operators' published segment lengths), and its own annual estimate uses the same straight-line basis. Prices are not returned yet. A segment's point IDs and `pricing_keys` (opaque keys into the operators' toll tables, one per toll charged on that stretch) are the join keys for a later pricing tool, and the option shape will not change for it. The Dulles Toll Road charges two tolls on some stretches, so such a segment has two keys. A facility appears in consecutive segments when its operator prices the trip in parts, for example the I-495 and I-95/I-395 Express Lanes.

**Ordering and the 3-option cap.** Options are ranked by `score.total`: the shortest total access distance, with each extra toll facility counting as 2 more miles. Ordering uses the unrounded score, so options showing the same rounded total can still differ; exact ties are ordered by entry, then exit point ID. Approach variants of one interchange appear once. The ranking ignores price and toll distance, so a long detour with short access legs can rank well (compare `total_straight_line_miles`). At most 3 options are returned, so the cheapest-toll route can be left out.

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

**Airports.** An airport point is used only when that end is within 1.5 miles of it; otherwise the airport is reached like any other place, by an access leg to a nearby entry or exit. Dulles (`airport_iad`) connects to the Dulles Toll Road, I-66, and I-495, so Dulles trips can start or end there, alongside nearby ordinary entries and exits. Reagan National (`airport_dca`) connects only to the I-95/I-395 reversible lanes: its departures need the lanes running in the trip's direction, and its arrivals need them northbound. When they are not, a DCA trip starts or ends at an ordinary entry or exit, often on I-66.

**Reversible lanes.** The I-95/I-395 Express Lanes change direction during the day. `direction` is `northbound`, `southbound`, `closed`, or `unknown`, read from the operator's feed; data more than 20 minutes old, missing, or contradictory is `unknown`. TollChat has no lane schedule, so it cannot say when the direction will next change. Call again near the time of travel.

| `status` | Meaning | What to do |
| --- | --- | --- |
| `resolved` | Validated options are listed. | Confirm the chosen option with the user. |
| `same_location` | Both ends are covered and within 0.1 mile of each other, so there is no trip. | Ask for distinct start and end points. It is not a zero-toll trip. |
| `outside_coverage` | An end is not covered (see each end's `coverage`). | Tell the user TollChat does not cover it. |
| `no_valid_route` | Both ends are covered, but no supported toll route connects them. | Tell the user. It is not a zero-toll trip. |
| `currently_unavailable` | The only routes use the I-95/I-395 reversible lanes, which are closed or open the other way right now. | Tell the user and suggest trying later. |
| `availability_unknown` | The only routes use the reversible lanes, and their current direction is unknown. | Tell the user TollChat cannot confirm the lanes are open; suggest trying later. |
| `error` (with `isError: true`) | Something failed on TollChat's side. | Retry as below; if it keeps failing, tell the user. |

Invalid arguments get a tool error (`isError: true`, no structured content) whose text says what to fix.

## Limits

- No daily limit: the server makes no paid lookups.
- About 2 requests per second across all clients, with bursts up to 5; excess requests get HTTP `429`.
- Request bodies up to 64 KiB.

## Retries

- Retry a transport failure (no response, reset, or timeout), HTTP `429` or `5xx`, or `status: error` at most twice, waiting about 1 then 2 seconds plus random jitter.
- Calls are read-only and count against no limit, so a retry after a lost response double-counts nothing.
- Log each attempt's UTC time to the millisecond; TollChat can match it against its per-minute request counts.
- A call that never got an answer is unknown: never report it as "no route" or "zero tolls".
- Pace bulk tests below 2 requests per second, or the throttle answers `429`.

## Using TollChat well

- Geocode the user's places yourself; a landmark, neighborhood, or nearby intersection is precise enough. Do not press for an exact home location.
- Confirm the chosen option with the user before relying on it.
- Use returned point IDs exactly; never invent or edit them.
- Miles are straight-line, no prices are returned, and results are estimates.
- Save this connector so it can be reused instead of rebuilt each conversation.
