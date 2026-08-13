# Price-hallucination evaluation: evidence so far

## The narrow claim

Across **3,400 frozen, tool-disabled GPT-5.6 Luna responses**, the deterministic
screen found **no dollar amount absent from the supplied tool evidence**. That
is encouraging evidence about price synthesis from known inputs. It is not
proof that the live agent always chooses the right route, calls the right tool,
or receives correct source data.

## Test battery

The test used production-formatted prompts and frozen tool results so the model
could synthesize an answer but could not fetch new data.

| Cohort | Design | Responses |
| --- | --- | ---: |
| Single leg | 200 reviewed route contexts × 5 prompt variants | 1,000 |
| Ordinary multi-leg | 200 reviewed contexts × 5 variants × 2 repeats | 2,000 |
| Blocked duplicate | 200 contexts × 1 production-formatted duplicate-call cancellation × 2 repeats | 400 |

The grader reconciled every expected response ID, required successful provider
completion, parsed money with exact decimal arithmetic, and allowed only source
component prices, valid component subtotals, and the expected total. It also
checked claimed timestamps and whether required components, totals, and partial-
price disclosures were present. In total it screened **19,320 monetary
mentions**.

The 1,000 single-leg responses included five facility families. The multi-leg
responses covered Dulles Toll Road/Greenway combinations, I-495/Dulles,
I-66/Dulles, and known-partial I-95/I-495 trips.

## Results

| Cohort | Provider complete | No unsupported dollars | Automatically verified complete | Other grounding failures |
| --- | ---: | ---: | ---: | ---: |
| Single leg | 1,000/1,000 | 1,000/1,000 | 885/1,000 | 115 attribution deferrals; 1 unsupported timestamp |
| Ordinary multi-leg | 2,000/2,000 | 2,000/2,000 | 1,517/2,000 | 0 unsupported timestamps |
| Blocked duplicate | 400/400 | 400/400 | 282/400 | 0 unsupported timestamps |

The grader defers **115 single-leg responses** from automatic clearance because
their fixtures contain equal-valued components; repeated dollar tokens cannot
prove that every component was attributed correctly. The unsupported timestamp
is in a different response, leaving 884/1,000 fully grounded by the screen.

The grader also sends **601 multi-leg responses** to manual review rather than
calling them complete. Of those, 61 fail one or more automated completeness
checks: 37 omit at least one component, 49 omit the expected total, and 18 omit
a required partial-price disclosure. Counts overlap. Another 540 responses
come from 45 fixtures with equal-valued components; repeated dollar tokens
cannot prove that the model attributed every equal-priced toll correctly, so
none count as automatically complete. These two review groups do not overlap.

The automatic-clearance rates (75.85% ordinary and 70.50% blocked duplicate)
therefore mix detected omissions with conservative semantic-review deferrals.
They must not be presented as measured failure rates.

Gate 4's original automated exception and fixed 100-pass sample were manually
reviewed and approved. The corrected duplicate-value check now leaves 115
additional Gate 4 responses awaiting semantic review. **Gate 5 has only
automated screening so far**: its 601 review-required responses and fixed
100-pass sample still need semantic review to confirm that amounts were attached
to the correct facilities, legs, and roles.

## What this does not establish

- The archived adversarial-pressure stratum was not executed and is excluded
  from every denominator above.
- Repeated prompts increase execution evidence, not independent scenario
  coverage; these results do not support a naive confidence interval.
- Frozen synthesis does not test route selection, tool invocation, duplicate-
  call suppression itself, live source accuracy or freshness, production
  traffic, or abuse resistance.
- The deterministic screen can detect unknown values and missing required
  values, but semantic attribution still needs human review.

## Retained evidence and current audit gap

The committed fixture packet contains all 1,000 reviewed contexts and source
evidence. `review-packet.sha256`, the Gate 3 and Gate 5 packet manifests, parity
reports, graders, and tests preserve the inputs and evaluation method without
committing bulky model-output dumps. `audit-packet.json` and its checksum retain
aggregate counts, per-response verdict hashes for every review-required output,
and the fixed sample identities. They do **not** let an independent reviewer
verify response text from a fresh clone; the raw provider outputs must still be
supplied separately and matched to the hashes below.

The completed provider outputs are identified by:

- Single leg: `batch_6a7bac52ad608190b65511c6b687751e`, SHA-256
  `b7eec9b494418510042c21e8f438ff102fdad86a5c080440ea0722e93edf2cc4`
- Multi-leg: `batch_6a7cd888fae48190843f8792dffa0d1f`, SHA-256
  `4b2c8e3ac6a987cf4bcea7b4cdc939b989cf97597184c82c2165d8ae666ec111`

With those raw JSONL files available, rerun the deterministic summaries from
the repository root:

```bash
uv run python eval/deterministic/price_hallucination/grade.py \
  eval/deterministic/price_hallucination/test-cases.jsonl SINGLE_OUTPUT.jsonl \
  --summary
uv run python eval/deterministic/price_hallucination/grade.py \
  eval/deterministic/price_hallucination/test-cases.jsonl MULTI_OUTPUT.jsonl \
  --stratum multi-leg --summary
```

The next useful step is manual Gate 5 review, followed by an independent
quantitative and methodology audit before turning this evidence into a public
accuracy claim.
