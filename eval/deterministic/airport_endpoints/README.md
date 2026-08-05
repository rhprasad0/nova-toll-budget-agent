# Airport endpoint evaluation

Code-graded live coverage for IAD and DCA as planner endpoints. The cases
verify the untolled access connector, directional endpoint handoffs, and that
IAD does not erase a subsequent Dulles Toll Road charge.

Run a no-network fixture check with:

```sh
uv run python eval/deterministic/airport_endpoints/deterministic_airport_endpoints.py --check
```

Run the live evaluation with the normal local TollChat prerequisites:

```sh
uv run python eval/deterministic/airport_endpoints/deterministic_airport_endpoints.py
```
