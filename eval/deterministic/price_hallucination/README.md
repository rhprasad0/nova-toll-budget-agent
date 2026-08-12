# GPT-5.6 Luna price-synthesis fixture review

**Gate 2 packet:** 1,000 canonical contexts and 5,000 frozen prompt variants.
No Batch request file has been rendered and no model has been called.

| Stratum | Canonical rows | Price calculations | No calculation |
| --- | ---: | ---: | ---: |
| Single leg | 200 | 200 | 0 |
| Multi-leg | 200 | 200 | 0 |
| Unavailable/partial | 200 | 100 | 100 |
| Out of scope/future | 200 | 0 | 200 |
| Adversarial pressure | 200 | 160 | 40 |
| **Total** | **1,000** | **660** | **340** |

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

**Packet SHA-256:**
`dbfb5eebcd37cc23d890bce0062b9029d67ac863f6841d3dcebfb055d7f97a9a`

Approval of this exact hash unlocks only Gate 3: rendering and reviewing the
single-leg Batch JSONL, payload-parity report, and maximum cost. It does not
authorize upload or inference.

## Gate 3 smoke packet

The offline 1,000-request single-leg packet is ready in `gate3-review.md`.
No request has been uploaded and no model has been called.

## Gate 4 audit

The completed single-leg run is summarized in `gate4-review.md`: automated
grading found 1,000/1,000 correct price amounts and 999/1,000 fully grounded
responses because one answer misstated the evidence timestamp. Manual review of
the failure and the fixed 100-pass sample is pending.
