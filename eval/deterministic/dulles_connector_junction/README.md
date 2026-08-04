# Dulles Connector Road junction evaluation

This two-case regression verifies the directed I-66/Dulles Toll Road handoffs.
It code-grades the planner and final answer: the connector must be **Dulles
Connector Road**, have a `$0.00` planner price, and never mention an airport.

Run the offline fixture check:

```sh
uv run python eval/deterministic/dulles_connector_junction/deterministic_dulles_connector_junction.py --check
```

Run the live agent evaluation with the normal local AWS/RDS prerequisites:

```sh
AWS_PROFILE=nova-toll uv run python eval/deterministic/dulles_connector_junction/deterministic_dulles_connector_junction.py
```
