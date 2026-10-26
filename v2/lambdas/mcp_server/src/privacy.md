# TollChat MCP server privacy notice

Benevolent Clankers LLC operates the TollChat MCP server at `https://mcp.tollchat.ai/mcp`. Send privacy questions or requests to contact@tollchat.ai.

## What the server receives

The server receives the tool arguments your assistant sends: the latitude and longitude of a trip's start and end. Since 2026-10-26 it no longer receives place names or addresses. It does not create accounts and does not receive your name, email address, or conversation. Like any web service it sees the network address of the connecting computer (for Muse, Meta's cloud), which it does not log. The coordinates of a landmark, neighborhood, or nearby intersection work; your assistant does not need to send your exact home or work location.

## How it is used

The server compares the coordinates with TollChat's ramp catalog and returns matching toll routes. It does not send the coordinates, or anything derived from them, to any third party. Before 2026-10-26 it sent place text to Amazon Location Service to find coordinates; that step has been removed.

## What is kept

- The server does not store coordinates, routes, or results.
- Server logs record which tool ran, its outcome, and how long it took, never coordinates or routes. They are kept for seven days.
- Amazon Web Services monitoring keeps per-minute counts of requests and errors, with no request content or network addresses, for up to 15 months.
- The daily lookup counter used before 2026-10-26 is no longer updated. It held only a count, with no query content, and its entries expire on their own.

## Your assistant

Your assistant's provider (for Muse, Meta) handles your conversation under its own terms and privacy policy. This notice covers only what reaches the TollChat MCP server.
