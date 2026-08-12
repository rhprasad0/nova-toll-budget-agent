# Gate 5 — 10,000-response multi-leg review

**Nothing in this packet has been uploaded and no additional model call has
been made.**

| Check | Result |
| --- | ---: |
| Reviewed canonical fixtures | 200 |
| Reviewed base requests | 1,000 |
| Repeat executions per base request | 10 |
| Total Batch requests | **10,000** |
| Unapproved production-payload differences | 0 |
| Shards | 5 |
| Pilot-linear cost projection | **$3.01** |
| Absolute conservative ceiling | **$95.23** |

The 10,000 responses are ten repeat executions of each of the 1,000
reviewed case/prompt pairs. This increases repeat-reliability evidence, **not
scenario coverage**. Results remain descriptive; repetitions are clustered by
fixture and do not justify a naive IID confidence interval.

The absolute ceiling intentionally treats every UTF-8 body byte as a billed
cache-write token and every response as consuming all 2,048 output tokens. The
pilot-linear projection is the useful budget estimate; the ceiling is the
break-glass bound.

## Batch shards

| File | Requests | Size |
| --- | ---: | ---: |
| `multi-leg-batch-01.jsonl` | 2,000 | 132.9 MB |
| `multi-leg-batch-02.jsonl` | 2,000 | 132.9 MB |
| `multi-leg-batch-03.jsonl` | 2,000 | 132.9 MB |
| `multi-leg-batch-04.jsonl` | 2,000 | 132.9 MB |
| `multi-leg-batch-05.jsonl` | 2,000 | 132.9 MB |

Each shard stays below OpenAI's 200 MB Batch input limit and contains complete
repeat sweeps; all five shards must complete before a 10,000-response result is
reported.

## Integrity

```bash
sha256sum -c gate5-packet.sha256
sha256sum gate5-packet.sha256
```

**Gate 5 packet SHA-256:** `983a77ead86bd090fabbc1e296810fb05b55f072388680d836d9086662db1501`

Approval authorizes submission of these exact five shards only. Collection and
audit must finish before another stratum is rendered or submitted.
