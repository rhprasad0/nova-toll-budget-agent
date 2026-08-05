# Adversarial regression evaluation

This suite covers GitHub issue #67 with eight fixed, hand-authored single-turn
attacks. A fresh real TollChat agent runs each case, while deterministic code
grades ordered tool calls, captured results, fare grounding, attack sentinels,
and protected prompt/config disclosure. It does not use an LLM judge.

Run the network-free fixture and evaluator check:

```bash
uv run python eval/deterministic/adversarial_regression/deterministic_adversarial_regression.py --check
```

Run the live suite from a Tailscale-connected environment with the repository's
normal AWS/RDS prerequisites:

```bash
env -u OPENAI_BASE_URL AWS_PROFILE=nova-toll uv run python eval/deterministic/adversarial_regression/deterministic_adversarial_regression.py
```

The live command makes eight OpenAI agent invocations plus model-controlled tool
loops against historical RDS. Credentials are loaded from SSM Parameter Store;
never put them in a local file. Reports are written as
`eval/results/adversarial-<timestamp>.json`.

## Regression versus red teaming

This is a **repeatable regression track**: prompts and pass/fail rules are fixed,
versioned, and suitable for nightly automation. It catches known failures but
does not measure the full attack surface.

**Exploratory red teaming** generates or adapts attacks, may use multi-turn
manipulation or qualitative review, and requires separate scope and run
authorization. New confirmed failures should be reduced to a stable fixture
here; exploratory scanning itself is not part of this suite.

Ordinary CI runs only `--check`. `nightly-evals.yml` runs the paid live suite in
its own job and uploads its prefixed report separately from simulated-user
artifacts.
