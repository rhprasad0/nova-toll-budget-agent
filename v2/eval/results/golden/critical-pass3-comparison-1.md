# Critical pass³ — first comparison

Both runs use approved calibration 16, corpus 1.0.12, harness 1.2.2, and identical model/settings, actors, fixtures, and graders. They are source-checkout evidence, not production qualification.

| Metric | Reference prompt 2.3.0 | Candidate prompt 2.3.1 |
| --- | --- | --- |
| Critical pass³ | 9/17 (52.9%) | 12/17 (70.6%) |
| Critical pass@1 | 41/51 | 45/51 |
| Overall pass@1 | 58/72 | 63/72 |
| Overall pass³ | 14/24 | 16/24 |
| Invalid trials | 0 | 0 |
| Model cost | $0.39132020 | $0.40261721 |
| Latency median / p95 | 16.68s / 28.99s | 18.19s / 27.63s |

**Observed improvement: 9/17 → 12/17 critical pass³ (+17.6 percentage points). The 17/17 target is not met.** Three trials per case are regression evidence, not a precise underlying reliability estimate.

The earlier 12/17 baseline used a different contract; do not compare it directly with these scores. Original attempts and verdicts are unchanged.

## Remaining findings

- The source wording fix clears Greenway and I-66 schedule-derived observation failures.
- Annualized-daily table labeling remains inconsistent; the next prompt removes conflicting historical-scenario wording.
- One stale-price answer copied evaluation time into observation time.
- No-history answers sometimes omit the eligible-date denominator; one correct “not assumed to be $0” denial was mechanically rejected.
- The reference also exposed conditional salary choice phrasings absent from the first checker fix. Expanded money checks need new exact calibration approval.

## Retained evidence

- [Reference report](runs/ae4f4eb7f3114f5dffa18f29bd69c0694b558f905ec00e807de2a47b6e6bf6f0/report.md)
- [Candidate report](runs/21495881f52a4e5e0f2bd162f7996b1ffaeafa7eeb1e3cc48d77e3b37ea74712/report.md)

The registries and original baseline are unchanged. The next candidate is prompt 2.3.2; prompt 2.3.1 was an unreleased intermediate candidate, retained in its commit and evidence rather than added as a second release in the final agent manifest.
