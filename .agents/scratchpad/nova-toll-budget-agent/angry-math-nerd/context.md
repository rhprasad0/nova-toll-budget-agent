# Angry Math Nerd Context

## Summary

Add a project-scoped Codex reviewer for the quantitative and public-claim work in GitHub issues #164 and #165. The agent is a read-only adversarial pre-reviewer, not the independent statistical reviewer required by #164.

## Existing Documentation

- `README.md` directs reviewers to verify pricing claims against constrained tools, deterministic evaluations, and source documentation.
- `.codex/agents/adversarial_reviewer.toml` and `security_reviewer.toml` establish the local custom-agent format and read-only reviewer conventions.
- Issue #164 defines the accuracy estimand, paired-observation, decimal-safe metric, coverage, serial-correlation, and reproducibility requirements.
- Issue #165 requires public methodology claims to match the pricing implementation and disclose source relationships, freshness, averages, composite trips, and unpriced gaps.

## Integration

Codex automatically discovers project agents from `.codex/agents/*.toml`. The new agent has no runtime, AWS, dependency, or TollChat application integration.

## Requirements

- Use `gpt-5.6-sol` with medium reasoning and a read-only sandbox.
- Focus on #164 accuracy evidence and #165 methodology claims.
- Recompute monetary and statistical claims from cited evidence.
- Report only evidence-backed findings with a fixed placation verdict.
- Keep the skeptical-manager parody professional and explicitly avoid substituting for independent statistical review.
