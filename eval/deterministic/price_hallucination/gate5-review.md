# Gate 5 — 2,400-response multi-leg review

**Completed Batch:** `batch_6a7cd888fae48190843f8792dffa0d1f` finished
**2,400/2,400 with zero execution failures**. Raw output SHA-256:
`4b2c8e3ac6a987cf4bcea7b4cdc939b989cf97597184c82c2165d8ae666ec111`.
Automated screening found no unsupported dollar values and automatically
cleared 1,799/2,400 required answers. The other 601 responses require manual
review: 61 have automated completeness exceptions, while 540 use fixtures with
equal-valued components that need semantic attribution review. The fixed
100-pass sample also remains pending; see `RESULTS.md`.

| Check | Result |
| --- | ---: |
| Reviewed canonical fixtures | 200 |
| Ordinary reviewed prompts | 1,000 |
| Blocked-duplicate recovery prompts | 200 |
| Total reviewed base requests | 1,200 |
| Repeat executions per base request | 2 |
| Total Batch requests | **2,400** |
| Unapproved production-payload differences | 0 |
| Shards | 1 |
| Pilot-linear cost projection | **$0.72** |
| Absolute conservative ceiling | **$22.89** |

The 2,400 responses are two complete repeat sweeps
(`r07` and `r08`) of 1,000 ordinary case/prompt pairs plus one blocked-duplicate
recovery prompt for each of the 200 canonical fixtures. The recovery prompts
replay the exact duplicate guard message after a matching successful tool call
to test whether Luna then invents a price. Repetition increases reliability
evidence, **not scenario coverage**; it does not justify a naive IID confidence
interval.

This frozen synthesis run does not execute the hook itself; the dedicated
duplicate-tool-guard evaluation covers suppression. Gate 5 isolates the next
risk: Luna's answer after receiving the production-formatted cancellation.
The audit must report the 2,000 ordinary and 400 recovery responses
separately as well as together.

The absolute ceiling intentionally treats every UTF-8 body byte as a billed
cache-write token and every response as consuming all 2,048 output tokens. The
pilot-linear projection is the useful budget estimate; the ceiling is the
break-glass bound.

## Batch shards

| File | Requests | Size |
| --- | ---: | ---: |
| `multi-leg-batch-04.jsonl` | 2,400 | 159.7 MB |

Each shard stays below OpenAI's 200 MB Batch input limit and contains complete
repeat sweeps; all 1 shard must complete before a
2,400-response result is reported.

## Integrity

```bash
sha256sum -c gate5-packet.sha256
sha256sum gate5-packet.sha256
```

The generated Batch JSONL is intentionally untracked, so the first command
requires regenerating or restoring `multi-leg-batch-04.jsonl` first. The
manifest records the submitted input identity; it is not a self-contained
result packet.

**Gate 5 packet SHA-256:** `f85fd3e36ac3a5c9e49a5e2878a43b05133427643245fc5713257311ffe10b55`

This hash covers the exact selected shard. Manual semantic review must finish
before the results become a public accuracy claim.
