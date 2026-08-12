# GPT-5.6 Luna price-synthesis fixture review

**Gate 2 packet:** 1,000 canonical contexts and 5,000 frozen prompt variants.
The approved single-leg pilot has since completed; the multi-leg Gate 5 packet
is rendered but has not been uploaded.

| Stratum | Canonical rows | Price calculations | No calculation |
| --- | ---: | ---: | ---: |
| Single leg | 200 | 200 | 0 |
| Multi-leg | 200 | 200 | 0 |
| Unavailable/partial | 200 | 100 | 100 |
| Out of scope/future | 200 | 0 | 200 |
| Adversarial pressure | 200 | 160 | 40 |
| **Total** | **1,000** | **660** | **340** |

The adversarial-pressure rows remain in this approved historical fixture packet
but are **excluded from Batch execution and all accuracy denominators**. The
public claim covers good-faith supported pricing requests, not user-abuse
resistance; the exclusion was recorded before adversarial outputs were run.

## Manual review

1. Verify the packet from this directory:

   ```bash
   sha256sum -c review-packet.sha256
   sha256sum review-packet.sha256
   ```

2. Open `fixture-review.md`. Its dashboard aggregates all 1,000 fixtures into
   category counts, price ranges, structural patterns, and 25 representative
   high-risk rows.
3. Recompute the displayed representative calculations and follow their raw
   evidence links. The deterministic validator performs the same exact decimal
   and typed-provenance checks across all 660 calculations.
4. Use `fixture-review.csv` only when a category needs full-row drill-down;
   `test-cases.jsonl` retains every prompt and raw source result.
5. Confirm connectors stay excluded, and every I-95/I-495 gap remains
   `unpriced_gap` rather than a `$0.00` operand.
6. Review the aggregated abstention categories and representative reasons.

There are 58 source-returned zero-price dynamic components in the single- and
multi-leg strata: 56 I-66 WB and two I-495 SB. They are typed tool results,
not connector or unpriced-gap sentinels. Connector `$0.00` planning sentinels
appear only as excluded `source_value` fields and never enter arithmetic.

**Approved Gate 2 packet SHA-256 (historical):**
`dbfb5eebcd37cc23d890bce0062b9029d67ac863f6841d3dcebfb055d7f97a9a`

**Current Gate 5 review revision SHA-256:**
`1255b82220206328d74f1852959c834e84946f25343dc4282c7129d9a61e36d2`

This revision adds a checksum-covered `blocked_duplicate` record to each of the
200 multi-leg fixtures and its CSV review row. No toll amount, source timestamp,
route fact, or ordinary prompt changed.

This is a review-only revision: it does not change the approved fixture data or
authorize upload or inference.

## Gate 3 smoke packet

The offline 1,000-request single-leg packet is ready in `gate3-review.md`.
No request has been uploaded and no model has been called.

## Gate 4 audit

The completed single-leg run is summarized in `gate4-review.md`: automated
grading found 1,000/1,000 correct price amounts and 999/1,000 fully grounded
responses because one answer misstated the evidence timestamp. The failure and
fixed 100-pass sample were manually reviewed and approved.

Gate 4 was approved on 2026-08-12. The next review artifact is
`gate5-review.md`: 12,000 multi-leg responses split across five size-bounded
Batch files. Its 1,200 base requests comprise 1,000 ordinary prompts and 200
exact duplicate-guard recovery transcripts. Nothing has been uploaded.
