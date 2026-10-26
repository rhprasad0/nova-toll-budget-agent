TollChat finds Northern Virginia toll-road ramps (I-495 and I-95/I-395 Express Lanes, I-66 inside the Beltway, the Dulles Toll Road, the Dulles Greenway, and the IAD/DCA airport connections).

- Pass each end as `{"latitude": …, "longitude": …}` in WGS-84 decimal degrees; geocode the user's places first. A landmark, neighborhood, or nearby intersection is precise enough; do not press for an exact home location.
- Calls are read-only and count against no limit, so a retry is safe; still, do not repeat a call for the same coordinates without a reason.
- `resolved`: confirm the chosen option with the user before relying on it. Keep returned point IDs exactly as given; labels are display text only.
- `same_location`: the two ends are the same place; ask for distinct start and end points.
- `outside_coverage` or `no_valid_route`: tell the user TollChat cannot route that trip. Neither means zero tolls.
- `currently_unavailable` or `availability_unknown`: the only routes use the I-95/I-395 reversible lanes, which are closed, open the other way, or unconfirmed right now; suggest trying later.
- `error` or no response: retry at most twice with backoff. A call that never got an answer is unknown, never "no route" or "zero tolls".
- A tool error that names a field means the arguments need fixing, for example swapped latitude and longitude.
- Miles are straight-line, not driving distance, and no prices are returned. Results are estimates, not guarantees of which ramp is best.
