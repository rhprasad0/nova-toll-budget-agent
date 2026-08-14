# Deterministic TollChat evaluation: single-leg base cases

Nine exact-price cases cover both directions of I-95, I-495, I-66 ITB, and
the Dulles Greenway, plus a Greenway-to-Toll-Road composite. Every request uses
exactly one pricing tool call, no route planner, and no junction tool. See
`eval-plan.md` and `test-cases.jsonl` for the contract and fixtures.
The reciprocal Greenway cases cross its mainline plaza and require the full
peak fare plus a separately attributed $2.00 Dulles Toll Road item in travel
order.
The composite case uses a prior-year date whose month and day sort after the
current date, covering chronological comparison and cross-facility routing.

## Self-check (no network)

```bash
uv run python eval/deterministic/single_leg_base_cases/deterministic_single_leg_base_cases.py --check
```

This exercises fixture loading and evaluator branches with synthetic calls and
responses. It does not invoke OpenAI, Bedrock, AWS, or RDS.

## Code-graded live run

```bash
env -u OPENAI_BASE_URL AWS_PROFILE=nova-toll uv run python eval/deterministic/single_leg_base_cases/deterministic_single_leg_base_cases.py
```

The live run invokes TollChat once per case using the OpenAI key from SSM and
read-only historical RDS for VDOT-backed roads. `dulles_route` reads committed
oracles. Results are written to `eval/results/<timestamp>.json`.

Run `--check` manually first. The code-based grader is repeatable, but live
TollChat execution is stochastic, so this suite and its matching three-turn
simulation require explicit authorization as observational evidence.
