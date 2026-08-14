# Duplicate tool guard evaluation

Three code-graded cases verify that exact repeated tool attempts are suppressed while SOP-directed changed calls and downstream pricing continue. Run the credential-free evaluator check with:

```bash
uv run python eval/deterministic/duplicate_tool_guard/deterministic_duplicate_tool_guard.py --check
```

Omit `--check` only for an explicitly authorized manual run: live execution uses OpenAI and historical RDS pricing.
