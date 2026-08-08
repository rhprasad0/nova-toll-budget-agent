# I-95/I-495 junction regression

Seven live, code-graded cases protect all four movement-aware I-95 boundaries, both boundary-equal endpoints, the historical both-directions-closed behavior, and the **Known toll total** contract. Run the offline grader check with:

```bash
uv run python eval/deterministic/i95_i495_junctions/deterministic_i95_i495_junctions.py --check
```

Omit `--check` only with the repository's configured OpenAI and AWS/RDS credentials.
