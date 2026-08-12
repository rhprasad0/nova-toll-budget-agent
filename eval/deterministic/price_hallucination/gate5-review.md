# Gate 5 — 12,000-response multi-leg review

**Nothing in this packet has been uploaded and no additional model call has
been made.**

| Check | Result |
| --- | ---: |
| Reviewed canonical fixtures | 200 |
| Ordinary reviewed prompts | 1,000 |
| Blocked-duplicate recovery prompts | 200 |
| Total reviewed base requests | 1,200 |
| Repeat executions per base request | 10 |
| Total Batch requests | **12,000** |
| Unapproved production-payload differences | 0 |
| Shards | 5 |
| Pilot-linear cost projection | **$3.62** |
| Absolute conservative ceiling | **$114.43** |

The 12,000 responses are ten repeat executions of 1,000
ordinary case/prompt pairs plus one blocked-duplicate recovery prompt for each
of the 200 canonical fixtures. The recovery prompts replay the exact duplicate
guard message after a matching successful tool call to test whether Luna then
invents a price. Repetition increases reliability evidence, **not scenario
coverage**; it does not justify a naive IID confidence interval.

This frozen synthesis run does not execute the hook itself; the dedicated
duplicate-tool-guard evaluation covers suppression. Gate 5 isolates the next
risk: Luna's answer after receiving the production-formatted cancellation.
The audit must report the 10,000 ordinary and 2,000 recovery responses
separately as well as together.

The absolute ceiling intentionally treats every UTF-8 body byte as a billed
cache-write token and every response as consuming all 2,048 output tokens. The
pilot-linear projection is the useful budget estimate; the ceiling is the
break-glass bound.

## Batch shards

| File | Requests | Size |
| --- | ---: | ---: |
| `multi-leg-batch-01.jsonl` | 2,400 | 159.7 MB |
| `multi-leg-batch-02.jsonl` | 2,400 | 159.7 MB |
| `multi-leg-batch-03.jsonl` | 2,400 | 159.7 MB |
| `multi-leg-batch-04.jsonl` | 2,400 | 159.7 MB |
| `multi-leg-batch-05.jsonl` | 2,400 | 159.7 MB |

Each shard stays below OpenAI's 200 MB Batch input limit and contains complete
repeat sweeps; all 5 shards must complete before a
12,000-response result is reported.

## Integrity

```bash
sha256sum -c gate5-packet.sha256
sha256sum gate5-packet.sha256
```

**Gate 5 packet SHA-256:** `bed693a4767fbf70d8ca4c5363ccd110e8b3c342b1c805635206b33729070164`

Approval authorizes submission of these exact 5 shards only. Collection and
audit must finish before another stratum is rendered or submitted.
