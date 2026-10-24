# TollChat MCP server

TollChat finds the toll-road ramps for a Northern Virginia trip: the I-495 and I-95/I-395 Express Lanes, I-66 inside the Beltway, the Dulles Toll Road, the Dulles Greenway, and the IAD/DCA airport connections.

- **Endpoint:** `https://mcp.tollchat.ai/mcp`
- **Transport:** MCP Streamable HTTP, stateless. Every `POST` gets one `application/json` response; there are no sessions and no `GET` event stream.
- **Authentication:** none. Call from server-side code: requests carrying a browser `Origin` header get `403`.
- **Protocol versions:** `2025-11-25` and earlier (with the `initialize` handshake) and `2026-07-28` (no handshake; each request carries its version).
- **Privacy:** https://mcp.tollchat.ai/privacy

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

{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"find_toll_ramps","arguments":{"origin":"Reston Town Center","destination":"Tysons Corner Center"}}}
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

{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"find_toll_ramps","arguments":{"origin":"Reston Town Center","destination":"Tysons Corner Center"},"_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28","io.modelcontextprotocol/clientInfo":{"name":"my-assistant","version":"1.0"},"io.modelcontextprotocol/clientCapabilities":{}}}}
```

## Tool: `find_toll_ramps`

**Classification: Read.** It looks places up and reads TollChat's ramp catalog; it changes nothing.

**Input**

| Field | Type | Meaning |
| --- | --- | --- |
| `origin` | string, 1–200 characters | Where the trip starts, as the user described it: a landmark, neighborhood, town, or nearby intersection. |
| `destination` | string, 1–200 characters | Where the trip ends, described the same way. |

No other fields are accepted.

**Output** (`structuredContent`, also sent as JSON text)

- `status`: one of the values below.
- `origin`, `destination`: how each place matched. `match` is `resolved` (with `name` and `address`), `ambiguous` (with up to 3 `candidates`), `place_not_found`, or `outside_coverage`.
- `options`: up to 3 routes, present when `status` is `resolved`. Best first: the shortest total access distance, where each extra toll road counts as 2 extra miles. Each has `entry` and `exit` (`point_id`, `label`, `direction`), the `facilities` used in order (`greenway`, `dtr` for the Dulles Toll Road, `i66`, `i95_i495` for the I-495 and I-95/I-395 Express Lanes), and straight-line `access_miles` from the origin to the entry and from the exit to the destination. Every option has passed TollChat's pricing route validation.

| `status` | Meaning | What to do |
| --- | --- | --- |
| `resolved` | Validated options are listed. | Confirm the places and the chosen option with the user. |
| `ambiguous` | A place matched several distant locations. | Ask which candidate the user meant, then call again with it. |
| `place_not_found` | A place could not be found. | Ask the user to describe it differently. |
| `outside_coverage` | A place is too far from any supported toll road. | Tell the user TollChat does not cover it. |
| `no_valid_route` | No supported toll route connects the two places. | Tell the user; suggest nearby places if they want. |
| `currently_unavailable` | The only routes use I-95/I-395 reversible lanes, which are open in the other direction right now. | Tell the user and suggest trying later. |
| `availability_unknown` | The only routes use I-95/I-395 reversible lanes, and their current direction is unknown. | Tell the user TollChat cannot confirm the lanes are open; suggest trying later. |
| `daily_lookup_limit` | The shared daily lookup limit is used up. | Tell the user to try again after midnight UTC. |
| `error` (with `isError: true`) | Something failed on TollChat's side. | Tell the user and try again later. |

Invalid arguments (wrong types, extra or missing fields, empty or overlong places) get a tool error (`isError: true`) saying what to fix; they use no lookups.

## Limits

- 1,000 place lookups per UTC day, shared by everyone. Each `find_toll_ramps` call uses 2.
- About 2 requests per second across all clients; excess requests get HTTP `429`.
- Request bodies up to 64 KiB.

## Using TollChat well

- Pass places the way the user described them; do not press for an exact home address.
- Confirm the matched places and the chosen option with the user before relying on them.
- Use returned point IDs exactly; never invent or edit them.
- Access miles are straight-line distances, and results are estimates.
- Save this connector so it can be reused instead of rebuilt each conversation.
