# GPT-5.6 Luna price-synthesis fixture review

**Gate 2 packet:** 1,000 canonical contexts and 5,000 frozen prompt variants.
The single-leg and multi-leg runs are complete; see [`RESULTS.md`](RESULTS.md)
for the concise evidence, limitations, and remaining review work.

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
`2a10b175d38bf8fffcb24896a67679018ea199fcad581dddd233e3880422cd39`

This revision adds a checksum-covered `blocked_duplicate` record to each of the
200 multi-leg fixtures and its CSV review row. No toll amount, source timestamp,
route fact, or ordinary prompt changed.

This is a review-only revision: it does not change the approved fixture data or
authorize upload or inference.

## Execution status

Gate 4's 1,000-response single-leg run and Gate 5's 2,400-response multi-leg
run completed without execution failures. Gate 4's fixed manual audit was
approved; Gate 5 currently has deterministic screening only. Generated response
dumps are intentionally untracked. The frozen fixtures, parity manifests,
packet hashes, graders, and tests remain here for audit and reproduction.
