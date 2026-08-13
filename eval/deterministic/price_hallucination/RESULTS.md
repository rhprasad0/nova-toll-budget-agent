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

| Cohort | Provider complete | No unsupported dollars | Required answer complete | Other grounding failures |
| --- | ---: | ---: | ---: | ---: |
| Single leg | 1,000/1,000 | 1,000/1,000 | 1,000/1,000 | 1 unsupported timestamp |
| Ordinary multi-leg | 2,000/2,000 | 2,000/2,000 | 1,967/2,000 | 0 unsupported timestamps |
| Blocked duplicate | 400/400 | 400/400 | 373/400 | 0 unsupported timestamps |

The **60 unique multi-leg completeness exceptions** overlap across three
checks: 37 omitted at least one component, 49 omitted the expected total, and
17 omitted a required partial-price disclosure. These are failures to provide
the requested answer, even though they are not invented-price failures. The
blocked-duplicate cohort was less complete than its ordinary counterpart
(93.25% versus 98.35%), which is a real weakness rather than rounding glitter.

Gate 4's one automated exception and fixed 100-pass sample were manually
reviewed and approved. **Gate 5 has only automated screening so far**: its 60
exceptions and fixed 100-pass sample still need semantic review to confirm that
amounts were attached to the correct facilities, legs, and roles.

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

## Audit trail

The committed fixture packet contains all 1,000 reviewed contexts and source
evidence. `review-packet.sha256`, the Gate 3 and Gate 5 packet manifests, parity
reports, graders, and tests preserve the input and evaluation method without
committing bulky model-output dumps.

The completed provider outputs are identified by:

- Single leg: `batch_6a7bac52ad608190b65511c6b687751e`, SHA-256
  `b7eec9b494418510042c21e8f438ff102fdad86a5c080440ea0722e93edf2cc4`
- Multi-leg: `batch_6a7cd888fae48190843f8792dffa0d1f`, SHA-256
  `4b2c8e3ac6a987cf4bcea7b4cdc939b989cf97597184c82c2165d8ae666ec111`

The next useful step is manual Gate 5 review, followed by an independent
quantitative and methodology audit before turning this evidence into a public
accuracy claim.
