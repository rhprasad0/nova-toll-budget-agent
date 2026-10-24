TollChat finds Northern Virginia toll-road ramps (I-495 and I-95/I-395 Express Lanes, I-66 inside the Beltway, the Dulles Toll Road, the Dulles Greenway, and the IAD/DCA airport connections).

- Pass places the way the user described them. A landmark, neighborhood, town, or nearby intersection is enough; do not press for an exact home address.
- Each call uses part of a small daily lookup budget shared by all users, so do not repeat a call for the same places.
- `resolved`: confirm the matched places and the chosen option with the user before relying on them. Keep returned point IDs exactly as given.
- `ambiguous`: ask the user which candidate they meant, then call again with it.
- `place_not_found`: ask the user to describe the place differently.
- `outside_coverage` or `no_valid_route`: tell the user TollChat cannot route that trip.
- `currently_unavailable` or `availability_unknown`: the only routes use the I-95/I-395 reversible lanes, which are closed in that direction or unconfirmed right now; suggest trying later.
- `daily_lookup_limit` or `error`: tell the user plainly and suggest trying later.
- Access miles are straight-line distances, not driving directions. Results are estimates, not guarantees of which ramp is best.
