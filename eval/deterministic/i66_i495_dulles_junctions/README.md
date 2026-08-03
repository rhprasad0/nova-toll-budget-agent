# I-66/I-495 and Dulles/I-495 junction evaluations

Sixteen Issue #19 cases cover eight directed junction movements and one natural
paraphrase each. PR #53 superseded the issue's two Route 267 detour expectations:
all four I-66/I-495 movements now use the direct interchange.

The deterministic runner calls the real TollChat agent, planner, route tools,
and committed oracles. It replaces only the RDS connection with fixed synthetic
I-66 and I-495 price rows, so model tool selection and response claims are live
while pricing data remains repeatable. Dulles rates come from committed oracles.

## Offline checks

```bash
uv run python eval/deterministic/i66_i495_dulles_junctions/deterministic_i66_i495_dulles_junctions.py --check
uv run python eval/simulated/simulated_user_i66_i495_dulles_junctions.py --check
```

These checks exercise all fixtures and grader branches without OpenAI, Bedrock,
AWS, or RDS.

## Code-graded live regression

```bash
env -u OPENAI_BASE_URL TOLLCHAT_MODEL_BACKEND=openai AWS_PROFILE=nova-toll \
  uv run python eval/deterministic/i66_i495_dulles_junctions/deterministic_i66_i495_dulles_junctions.py
```

This makes 16 fresh OpenAI agent runs. Tool loops make the exact Responses API
request count model-controlled; roughly 64 requests are expected. It makes no
RDS or Bedrock calls.

## Three-turn simulated users

```bash
env -u OPENAI_BASE_URL TOLLCHAT_MODEL_BACKEND=openai AWS_PROFILE=nova-toll \
  uv run python eval/simulated/simulated_user_i66_i495_dulles_junctions.py
```

This runs 16 actors capped at three TollChat turns, plus goal-success and
helpfulness judges. TollChat uses OpenAI; actors and judges use Bedrock. Set
`NOVA_TOLL_EVAL_MODEL_ID` to override the committed Bedrock model. Do not retry
a live suite without renewed authorization.
