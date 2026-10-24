# TollChat MCP server privacy notice

Benevolent Clankers LLC operates the TollChat MCP server at `https://mcp.tollchat.ai/mcp`. Send privacy questions or requests to contact@tollchat.ai.

## What the server receives

The server receives the tool arguments your assistant sends: the start and end places of a trip, as text. It does not create accounts and does not receive your name, email address, or conversation. Like any web service it sees the network address of the connecting computer (for Muse, Meta's cloud), which it does not log. Avoid sending exact home or work addresses; a landmark, neighborhood, or nearby intersection works.

## How it is used

To find ramps, the server sends each place text to Amazon Location Service. Amazon Location removes customer and account information from the query before passing it to its map data providers. The server compares the result with TollChat's ramp catalog and returns matching toll routes.

## What is kept

- The server does not store place text, lookup results, or locations.
- It keeps one daily counter of how many lookups were made, with no query content; each day's counter expires after two days.
- Server logs record which tool ran, its outcome, and how long it took, never the places or locations. They are kept for seven days.

## Your assistant

Your assistant's provider (for Muse, Meta) handles your conversation under its own terms and privacy policy. This notice covers only what reaches the TollChat MCP server.
