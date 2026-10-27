# TollChat MCP server privacy notice

Benevolent Clankers LLC operates the TollChat MCP server at `https://mcp.tollchat.ai/mcp`. Send privacy questions or requests to contact@tollchat.ai.

## What the server receives

The server receives the tool arguments your assistant sends: the latitude and longitude of a trip's start and end; for an annual estimate, a route's ramp IDs and a commute schedule (departure and return times, weekdays, and days per year); and for a salary estimate, a job title, the job's location, and optionally an experience range. Since 2026-10-26 the toll tools no longer receive place names or addresses. It does not create accounts and does not receive your name, email address, or conversation. Like any web service it sees the network address of the connecting computer (for Muse, Meta's cloud), which it does not log. The coordinates of a landmark, neighborhood, or nearby intersection work; your assistant does not need to send your exact home or work location.

## How it is used

The server compares the coordinates with TollChat's ramp catalog and returns matching toll routes, and prices a commute schedule against recent recorded and published tolls. It does not send the coordinates, routes, or schedules, or anything derived from them, to any third party. Before 2026-10-26 it sent place text to Amazon Location Service to find coordinates; that step has been removed.

Since 2026-10-27, for a salary estimate, the server sends the job title, job location, and experience range, and nothing else, to OpenWeb Ninja, which looks up Glassdoor's salary estimates and handles the request under its own terms and privacy policy. It sends no coordinates, schedules, or network addresses with them.

## What is kept

- The server does not store coordinates, routes, schedules, or results, apart from the logs below.
- Server logs record which tool ran, its outcome, and how long it took, never coordinates, routes, or schedules. For a salary estimate they also record the job title, location, and experience range, and OpenWeb Ninja's reply status, response time, and request ID; they never record its API key. Logs are kept for seven days; Amazon Web Services can take up to three more days to delete them.
- Amazon Web Services monitoring keeps per-minute counts of requests and errors, with no request content or network addresses, for up to 15 months.
- A daily counter caps salary lookups. It holds only a count per UTC day, with no query content, and each day's count expires after two days. (The place-lookup counter used before 2026-10-26 was deleted.)

## Your assistant

Your assistant's provider (for Muse, Meta) handles your conversation under its own terms and privacy policy. This notice covers only what reaches the TollChat MCP server.
