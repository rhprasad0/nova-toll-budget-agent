# NY-time handling + US date/time format eval — task checklist

Status: in progress

Adds evaluation coverage (following the `eval/deterministic/fuzzy_location_matching`
pattern) for two agent behaviors that currently have no eval:

1. Correctly interpreting a user-given date/time as an America/New_York
   instant when calling the pricing tools' `at_time` parameter — including a
   date/time already stated in a non-Eastern zone, and a date on the winter
   (EST) side of the DST boundary.
2. Reporting any date/time back to the user in US Standard format
   (`M/D/YYYY h:MM AM/PM ET`), not the tool's raw ISO-8601 string.

Track 1 (deterministic, CI-gating) uses fixed absolute dates/times, so every
expected `at_time` is assertable. Track 2 (simulated-user, nightly,
observational) covers relative/fuzzy phrasing ("tomorrow at 5pm") that Track
1 can't assert against, since the agent has no injected "current date."

Behavior (2) required a SOP change — `agent-sops/nova-toll-pricing-assistant.sop.md`
previously only said to copy `observed_at` through verbatim.

## Tasks

- [x] Update the SOP (Step 4) to require US-format date/time output;
      validate with `scripts/validate-sop.sh`.
- [x] Write `eval/deterministic/ny_time_us_format/eval-plan.md`.
- [x] Write `eval/deterministic/ny_time_us_format/test-cases.jsonl` (3 cases,
      real oracle pair + data range verified against RDS first).
- [x] Write `eval/deterministic/ny_time_us_format/deterministic_ny_time_us_format.py`
      with a `TimeInterpretationEvaluator` (checks the tool-call `at_time`
      argument resolves to the correct aware instant) and a
      `USFormatEvaluator` (checks the final response's timestamp is
      US-formatted, not raw ISO-8601). Include a `--check` self-test.
- [x] Write `eval/deterministic/ny_time_us_format/README.md`.
- [ ] Wire the deterministic suite into `.github/workflows/ci.yml`'s
      `integration` job (same pattern as the fuzzy-location step).
- [ ] Write `eval/simulated/simulated_user_ny_time_us_format.py` (relative
      date phrasing, `HelpfulnessEvaluator` + `GoalSuccessRateEvaluator`,
      observational per the Track 2 convention). Include `--check`.
- [ ] Wire it into `.github/workflows/nightly-evals.yml` alongside the
      existing simulated-user job.
- [ ] Update `eval/README.md` with commands for both new suites.
- [ ] Run `--check` self-tests, `ruff`, `pyright`; live-run the deterministic
      suite if RDS/Bedrock access allows.
