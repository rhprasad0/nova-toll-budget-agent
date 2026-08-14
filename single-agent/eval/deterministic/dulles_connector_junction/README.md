# I-66 / Dulles Toll Road junction evaluation

This two-case regression verifies the directed I-66/Dulles Toll Road handoffs.
It code-grades the planner and final answer: both priced legs must meet at the
shared **I-66 / Dulles Toll Road junction**, whose planner sentinel is `$0.00`
but which is omitted from billed items and arithmetic.

Run the offline fixture check:

```sh
uv run python eval/deterministic/dulles_connector_junction/deterministic_dulles_connector_junction.py --check
```

Run the live agent evaluation with the normal local AWS/RDS prerequisites:

```sh
AWS_PROFILE=nova-toll uv run python eval/deterministic/dulles_connector_junction/deterministic_dulles_connector_junction.py
```
