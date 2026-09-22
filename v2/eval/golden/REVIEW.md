# Review the 200-case golden corpus

**Status: proposed labels; exact human review pending.** Start with a family below, then follow each reference link to its full transcript and actual tool evidence. The [contract and research](../GOLDEN_EVAL_SPEC.md) explain the grading boundaries.

There are 326 labeled references (274 development, 52 reserved), including 104 negative application examples and 2 actor-invalid probes. Every case has a passing reference. Original IDs 1–24 are development.

| Family | Total | Reserved |
| --- | ---: | ---: |
| [current_state](review/current_state.md) | 24 | 5 |
| [current_evidence](review/current_evidence.md) | 24 | 5 |
| [current_unsupported](review/current_unsupported.md) | 8 | 2 |
| [current_i95](review/current_i95.md) | 20 | 4 |
| [annual_inputs](review/annual_inputs.md) | 36 | 6 |
| [annual_routes](review/annual_routes.md) | 28 | 6 |
| [annual_evidence](review/annual_evidence.md) | 28 | 6 |
| [annual_finance](review/annual_finance.md) | 28 | 4 |
| [mixed](review/mixed.md) | 4 | 2 |

Overlapping behavioral counts: stateful **67**, fact correction **17**, cancellation **11**, workflow switch **4**, over refusal control **29**, partial evidence or failure **38**, adversarial direct **4**, adversarial tool **4**.

## Behavioral pairs

Paired cases stay within one split group. Contrastive pairs require a change in behavior; invariance pairs retain the same behavior despite irrelevant variation.

| Pair | Type | Cases |
| --- | --- | --- |
| annual-alternative-consent | contrastive | [130: Honor the second returned morning entry](review/annual_routes.md#case-130-annual-alternative-other-choice), [131: Discovery does not authorize a replacement](review/annual_routes.md#case-131-annual-alternative-declined) |
| annual-clock-notation | invariance | [110: Equivalent 12-hour time notation](review/annual_inputs.md#case-110-annual-time-twelve-hour), [111: Equivalent 24-hour time notation](review/annual_inputs.md#case-111-annual-time-twenty-four-hour) |
| annual-coverage-completeness | contrastive | [151: Coverage contrast: 1 of 60 pairs](review/annual_evidence.md#case-151-annual-coverage-one-pair), [152: Coverage contrast: 60 of 60 pairs](review/annual_evidence.md#case-152-annual-coverage-all-pairs) |
| annual-day-ceiling | contrastive | [100: Accept the valid 53-week boundary](review/annual_inputs.md#case-100-annual-single-weekday-53), [101: Clarify days above weekday capacity](review/annual_inputs.md#case-101-annual-single-weekday-54) |
| annual-divergent-consent | contrastive | [128: Use explicit consent already delivered](review/annual_routes.md#case-128-annual-divergent-preconfirmed), [129: Declined divergent legs cannot be combined](review/annual_routes.md#case-129-annual-divergent-declined) |
| annual-income-availability | contrastive | [102: Complete annual income needs no confirmation](review/annual_inputs.md#case-102-annual-annual-income-known), [103: An unknown annual income can end in clarification](review/annual_inputs.md#case-103-annual-annual-income-unknown) |
| annual-irrelevant-narrative | invariance | [198: Irrelevant price narrative control](review/annual_finance.md#case-198-annual-irrelevant-story-control), [199: Irrelevant price narrative cannot override evidence](review/annual_finance.md#case-199-annual-irrelevant-story-price) |
| annual-tool-text-choose | invariance | [145: Untrusted alternative text: choose control](review/annual_routes.md#case-145-annual-alternative-text-choose-control), [146: Untrusted alternative text: choose probe](review/annual_routes.md#case-146-annual-alternative-text-choose-attack) |
| annual-tool-text-decline | invariance | [147: Untrusted alternative text: decline control](review/annual_routes.md#case-147-annual-alternative-text-decline-control), [148: Untrusted alternative text: decline probe](review/annual_routes.md#case-148-annual-alternative-text-decline-attack) |
| annual-zero-vs-missing | contrastive | [149: Authoritative zero tolls are usable evidence](review/annual_evidence.md#case-149-annual-observed-zero-tolls), [150: No paired samples is not a zero toll](review/annual_evidence.md#case-150-annual-missing-not-zero-control) |
| clarify-or-cancel | contrastive | [4: Missing Greenway exit](review/current_state.md#case-4-greenway-missing-destination), [32: Cancellation ends a pending clarification](review/current_state.md#case-32-current-cancel-before-exit) |
| closure-certainty | contrastive | [81: Confirmed closure can produce a bounded fallback offer](review/current_i95.md#case-81-current-reserved-closed-direction), [82: Unknown evidence removes the closure fallback](review/current_i95.md#case-82-current-reserved-stale-direction) |
| coordinate-role | invariance | [28: Coordinates use entry and exit as the tie-breaker](review/current_state.md#case-28-current-coordinate-role-tie), [29: Labels control the coordinate role-tie test](review/current_state.md#case-29-current-coordinate-label-control) |
| i66-irrelevant | invariance | [41: Complete Route 7 to I-495 South request needs no clarification](review/current_state.md#case-41-current-i66-explicit-westbound), [42: Irrelevant narrative does not change a complete route](review/current_state.md#case-42-current-i66-irrelevant-context) |
| leesburg-alias | invariance | [26: Bare Leesburg resolves without ramp guessing](review/current_state.md#case-26-current-bare-leesburg), [27: Exact label and bare Leesburg preserve the same trip](review/current_state.md#case-27-current-exact-leesburg-label) |
| median-sign | contrastive | [59: Negative delta receives the deal message](review/current_evidence.md#case-59-current-reserved-below-range), [60: Positive delta receives the alert message](review/current_evidence.md#case-60-current-reserved-above-range) |
| missing-versus-scheduled-zero | contrastive | [6: Missing price during toll hours](review/current_evidence.md#case-6-i66-missing-price), [8: I-66 outside toll hours](review/current_evidence.md#case-8-i66-free-period) |
| movement-direction | contrastive | [46: Rising movement is recent evidence, not a forecast](review/current_evidence.md#case-46-current-movement-rising), [47: Falling movement must reverse the sign and label](review/current_evidence.md#case-47-current-movement-falling) |
| profile-default | invariance | [1: Greenway current toll](review/current_state.md#case-1-greenway-current), [25: Explicit supported profile needs no re-confirmation](review/current_state.md#case-25-current-explicit-supported-profile) |
| restart-consent | contrastive | [70: Restart requires an explicit new-trip acceptance](review/current_i95.md#case-70-current-restart-accept), [71: A declined restart ends without replacement pricing](review/current_i95.md#case-71-current-restart-decline) |


## Case index

| # | Case | Family | Split |
| ---: | --- | --- | --- |
| 1 | [Greenway current toll](review/current_state.md#case-1-greenway-current) | current_state | development |
| 2 | [Correct the Greenway origin](review/current_state.md#case-2-greenway-origin-correction) | current_state | development |
| 3 | [Unsupported vehicle profile](review/current_unsupported.md#case-3-unsupported-profile) | current_unsupported | development |
| 4 | [Missing Greenway exit](review/current_state.md#case-4-greenway-missing-destination) | current_state | development |
| 5 | [No evidence of a price increase](review/current_evidence.md#case-5-i66-no-comparison) | current_evidence | development |
| 6 | [Missing price during toll hours](review/current_evidence.md#case-6-i66-missing-price) | current_evidence | development |
| 7 | [Observed I-66 toll](review/current_evidence.md#case-7-i66-observed-price) | current_evidence | development |
| 8 | [I-66 outside toll hours](review/current_evidence.md#case-8-i66-free-period) | current_evidence | development |
| 9 | [Stale I-66 evidence](review/current_evidence.md#case-9-i66-stale-price) | current_evidence | development |
| 10 | [Current-price tool failure](review/current_evidence.md#case-10-current-tool-error) | current_evidence | development |
| 11 | [Unsupported origin](review/current_unsupported.md#case-11-unsupported-origin) | current_unsupported | development |
| 12 | [Fixed-rate annual commute](review/annual_finance.md#case-12-annual-fixed) | annual_finance | development |
| 13 | [Clarify the Tysons exit](review/annual_routes.md#case-13-annual-tysons-clarification) | annual_routes | development |
| 14 | [Collect the missing schedule](review/annual_inputs.md#case-14-annual-missing-schedule) | annual_inputs | development |
| 15 | [Clarify a salary range](review/annual_inputs.md#case-15-annual-salary-range) | annual_inputs | development |
| 16 | [Clarify hourly income](review/annual_inputs.md#case-16-annual-hourly-income) | annual_inputs | development |
| 17 | [Adjust annual commute days](review/annual_inputs.md#case-17-annual-confirm-days) | annual_inputs | development |
| 18 | [Correct invalid time and days](review/annual_inputs.md#case-18-annual-invalid-schedule) | annual_inputs | development |
| 19 | [Unsupported annual return route](review/annual_evidence.md#case-19-annual-no-return-route) | annual_evidence | development |
| 20 | [Corridor choice and partial history](review/annual_evidence.md#case-20-annual-partial-history) | annual_evidence | development |
| 21 | [Independent morning and evening ramps](review/annual_routes.md#case-21-annual-independent-ramps) | annual_routes | development |
| 22 | [Retain a selected annual alternative](review/annual_routes.md#case-22-annual-select-alternative) | annual_routes | development |
| 23 | [Confirm different commute areas](review/annual_routes.md#case-23-annual-confirm-divergent) | annual_routes | development |
| 24 | [No complete paired history](review/annual_evidence.md#case-24-annual-no-paired-days) | annual_evidence | development |
| 25 | [Explicit supported profile needs no re-confirmation](review/current_state.md#case-25-current-explicit-supported-profile) | current_state | development |
| 26 | [Bare Leesburg resolves without ramp guessing](review/current_state.md#case-26-current-bare-leesburg) | current_state | development |
| 27 | [Exact label and bare Leesburg preserve the same trip](review/current_state.md#case-27-current-exact-leesburg-label) | current_state | development |
| 28 | [Coordinates use entry and exit as the tie-breaker](review/current_state.md#case-28-current-coordinate-role-tie) | current_state | development |
| 29 | [Labels control the coordinate role-tie test](review/current_state.md#case-29-current-coordinate-label-control) | current_state | development |
| 30 | [Bare Washington requires its specific corridor clarification](review/current_state.md#case-30-current-washington-corridor) | current_state | development |
| 31 | [Collect both current endpoints together](review/current_state.md#case-31-current-both-endpoints-missing) | current_state | development |
| 32 | [Cancellation ends a pending clarification](review/current_state.md#case-32-current-cancel-before-exit) | current_state | development |
| 33 | [Replace the exit without replacing the origin](review/current_state.md#case-33-current-destination-correction) | current_state | development |
| 34 | [A full reversal changes both roles and direction](review/current_state.md#case-34-current-reverse-after-answer) | current_state | development |
| 35 | [A later HOV correction invalidates the supported quote](review/current_state.md#case-35-current-profile-correction) | current_state | development |
| 36 | [A clarification can correct a previously supplied fact](review/current_state.md#case-36-current-correction-during-clarification) | current_state | development |
| 37 | [Future request changes to current only after acceptance](review/current_state.md#case-37-current-time-switch-consent) | current_state | development |
| 38 | [A friend’s quote is not current evidence](review/current_state.md#case-38-current-quoted-friend-not-evidence) | current_state | development |
| 39 | [Direct instruction bypass remains outside scope](review/current_state.md#case-39-current-direct-prompt-extraction) | current_state | development |
| 40 | [One qualified-Washington correction is automatic](review/current_state.md#case-40-current-washington-corrective-retry) | current_state | development |
| 41 | [Complete Route 7 to I-495 South request needs no clarification](review/current_state.md#case-41-current-i66-explicit-westbound) | current_state | reserved |
| 42 | [Irrelevant narrative does not change a complete route](review/current_state.md#case-42-current-i66-irrelevant-context) | current_state | reserved |
| 43 | [Missing origin retains the corridor and exit](review/current_state.md#case-43-current-i66-origin-clarification) | current_state | reserved |
| 44 | [An unknowable required endpoint ends in clarification](review/current_state.md#case-44-current-terminal-unknown-exit) | current_state | reserved |
| 45 | [Broad Ashburn area needs an actual exit](review/current_state.md#case-45-current-ashburn-ambiguity) | current_state | reserved |
| 46 | [Rising movement is recent evidence, not a forecast](review/current_evidence.md#case-46-current-movement-rising) | current_evidence | development |
| 47 | [Falling movement must reverse the sign and label](review/current_evidence.md#case-47-current-movement-falling) | current_evidence | development |
| 48 | [An unchanged component reports zero net change](review/current_evidence.md#case-48-current-movement-unchanged) | current_evidence | development |
| 49 | [A nonmonotonic movement is mixed](review/current_evidence.md#case-49-current-movement-mixed) | current_evidence | development |
| 50 | [One comparable week is not a typical three-week price](review/current_evidence.md#case-50-current-comparison-partial) | current_evidence | development |
| 51 | [Zero denominator does not create a percentage](review/current_evidence.md#case-51-current-comparison-zero-baseline) | current_evidence | development |
| 52 | [UTC observation converts once to winter Eastern time](review/current_evidence.md#case-52-current-winter-utc) | current_evidence | development |
| 53 | [An existing summer offset is not subtracted twice](review/current_evidence.md#case-53-current-summer-offset) | current_evidence | development |
| 54 | [A usable proxy is labeled modeled](review/current_evidence.md#case-54-current-modeled-price) | current_evidence | development |
| 55 | [Two dynamic legs retain separate comparisons](review/current_evidence.md#case-55-current-two-component-comparisons) | current_evidence | development |
| 56 | [One missing component suppresses the complete quote](review/current_evidence.md#case-56-current-incomplete-component) | current_evidence | development |
| 57 | [Fixed components and priced handoff are composed by the tool](review/current_evidence.md#case-57-current-fixed-multi-facility) | current_evidence | development |
| 58 | [Instruction-like source metadata cannot redirect the assistant](review/current_evidence.md#case-58-current-source-text-injection) | current_evidence | development |
| 59 | [Negative delta receives the deal message](review/current_evidence.md#case-59-current-reserved-below-range) | current_evidence | reserved |
| 60 | [Positive delta receives the alert message](review/current_evidence.md#case-60-current-reserved-above-range) | current_evidence | reserved |
| 61 | [Historical comparison does not imply recent movement](review/current_evidence.md#case-61-current-reserved-no-movement) | current_evidence | reserved |
| 62 | [An actual zero observation supports a zero estimate](review/current_evidence.md#case-62-current-reserved-observed-zero) | current_evidence | reserved |
| 63 | [Stale timestamp is disclosed without age thresholds](review/current_evidence.md#case-63-current-reserved-staleness-disclosure) | current_evidence | reserved |
| 64 | [Cash request cannot override the supported payment profile](review/current_unsupported.md#case-64-current-cash-bypass) | current_unsupported | development |
| 65 | [HOV mode is not silently mapped to toll mode](review/current_unsupported.md#case-65-current-hov-mode) | current_unsupported | development |
| 66 | [A motorcycle is not a two-axle passenger car](review/current_unsupported.md#case-66-current-motorcycle) | current_unsupported | development |
| 67 | [Future request is not answered with the current rate](review/current_unsupported.md#case-67-current-future-price) | current_unsupported | development |
| 68 | [A specific past time is not a current request](review/current_unsupported.md#case-68-current-past-price) | current_unsupported | reserved |
| 69 | [Tax deductibility does not trigger annual estimation](review/current_unsupported.md#case-69-current-tax-advice-scope) | current_unsupported | reserved |
| 70 | [Restart requires an explicit new-trip acceptance](review/current_i95.md#case-70-current-restart-accept) | current_i95 | development |
| 71 | [A declined restart ends without replacement pricing](review/current_i95.md#case-71-current-restart-decline) | current_i95 | development |
| 72 | [Accepted prefix fallback preserves the destination](review/current_i95.md#case-72-current-prefix-accept) | current_i95 | development |
| 73 | [Declined prefix fallback preserves the refusal](review/current_i95.md#case-73-current-prefix-decline) | current_i95 | development |
| 74 | [Accepted suffix fallback preserves the origin](review/current_i95.md#case-74-current-suffix-accept) | current_i95 | development |
| 75 | [Declined suffix fallback cannot become automatic pricing](review/current_i95.md#case-75-current-suffix-decline) | current_i95 | development |
| 76 | [Opposite-direction opening supports only the specified fallback](review/current_i95.md#case-76-current-opposite-direction) | current_i95 | development |
| 77 | [Stale direction data does not establish closure](review/current_i95.md#case-77-current-unknown-stale-direction) | current_i95 | development |
| 78 | [No direction source does not establish closure](review/current_i95.md#case-78-current-unknown-missing-direction) | current_i95 | development |
| 79 | [A pure I-95 closure has no I-495 fallback](review/current_i95.md#case-79-current-closed-without-gap) | current_i95 | development |
| 80 | [A southbound prefix is outside the fallback combinations](review/current_i95.md#case-80-current-unsupported-gap-boundary) | current_i95 | development |
| 81 | [Confirmed closure can produce a bounded fallback offer](review/current_i95.md#case-81-current-reserved-closed-direction) | current_i95 | reserved |
| 82 | [Unknown evidence removes the closure fallback](review/current_i95.md#case-82-current-reserved-stale-direction) | current_i95 | reserved |
| 83 | [Future-dated feed evidence is inconclusive](review/current_i95.md#case-83-current-reserved-future-direction) | current_i95 | reserved |
| 84 | [Conflicting direction intervals cannot be merged](review/current_i95.md#case-84-current-reserved-interval-direction) | current_i95 | reserved |
| 85 | [A proof follow-up receives the exact bounded response](review/current_i95.md#case-85-current-closure-proof) | current_i95 | development |
| 86 | [Latest withdrawal beats an earlier yes in the same reply](review/current_i95.md#case-86-current-fallback-withdrawal) | current_i95 | development |
| 87 | [Wrong-role discovery waits for the user’s replacement choice](review/current_i95.md#case-87-current-wrong-role-selection) | current_i95 | development |
| 88 | [Alternative alias instructions cannot authorize a replacement](review/current_i95.md#case-88-current-tool-alias-injection) | current_i95 | development |
| 89 | [An open southbound prefix remains a complete supported route](review/current_i95.md#case-89-current-open-southbound-prefix) | current_i95 | development |
| 90 | [Price first, then assess the job commute](review/mixed.md#case-90-current-then-annual) | mixed | development |
| 91 | [Annual estimate followed by a one-way current quote](review/mixed.md#case-91-annual-then-current) | mixed | development |
| 92 | [User changes request after unavailable annual distance](review/mixed.md#case-92-annual-unavailable-then-current) | mixed | reserved |
| 93 | [User requests historical annual estimate after missing current observation](review/mixed.md#case-93-current-unavailable-then-annual) | mixed | reserved |
| 94 | [Collect only the missing origin](review/annual_inputs.md#case-94-annual-missing-origin-only) | annual_inputs | reserved |
| 95 | [Collect only the missing destination](review/annual_inputs.md#case-95-annual-missing-destination-only) | annual_inputs | reserved |
| 96 | [Acquire gross rather than infer income](review/annual_inputs.md#case-96-annual-missing-income-only) | annual_inputs | development |
| 97 | [Preserve a supplied return time](review/annual_inputs.md#case-97-annual-missing-outbound-only) | annual_inputs | development |
| 98 | [Preserve a supplied outbound time](review/annual_inputs.md#case-98-annual-missing-return-only) | annual_inputs | development |
| 99 | [Weekday clarification must retain explicit annual days](review/annual_inputs.md#case-99-annual-weekdays-with-explicit-days) | annual_inputs | development |
| 100 | [Accept the valid 53-week boundary](review/annual_inputs.md#case-100-annual-single-weekday-53) | annual_inputs | reserved |
| 101 | [Clarify days above weekday capacity](review/annual_inputs.md#case-101-annual-single-weekday-54) | annual_inputs | reserved |
| 102 | [Complete annual income needs no confirmation](review/annual_inputs.md#case-102-annual-annual-income-known) | annual_inputs | development |
| 103 | [An unknown annual income can end in clarification](review/annual_inputs.md#case-103-annual-annual-income-unknown) | annual_inputs | development |
| 104 | [Correct zero income before any call](review/annual_inputs.md#case-104-annual-zero-income-correction) | annual_inputs | development |
| 105 | [Reject a nonpositive gross input without choosing one](review/annual_inputs.md#case-105-annual-negative-income-unresolved) | annual_inputs | reserved |
| 106 | [Distinguish take-home pay from gross input](review/annual_inputs.md#case-106-annual-net-income-needs-gross) | annual_inputs | development |
| 107 | [Ask for user-supplied annual US dollars](review/annual_inputs.md#case-107-annual-non-usd-income) | annual_inputs | development |
| 108 | [User chooses the single gross amount including bonus](review/annual_inputs.md#case-108-annual-separate-bonus-income) | annual_inputs | development |
| 109 | [Accept an annual estimate supplied alongside hourly pay](review/annual_inputs.md#case-109-annual-user-supplied-annualization) | annual_inputs | development |
| 110 | [Equivalent 12-hour time notation](review/annual_inputs.md#case-110-annual-time-twelve-hour) | annual_inputs | development |
| 111 | [Equivalent 24-hour time notation](review/annual_inputs.md#case-111-annual-time-twenty-four-hour) | annual_inputs | development |
| 112 | [Interpret midnight and noon without swapping them](review/annual_inputs.md#case-112-annual-midnight-noon) | annual_inputs | development |
| 113 | [Deduplicate weekdays without dropping distinct days](review/annual_inputs.md#case-113-annual-duplicate-weekdays) | annual_inputs | development |
| 114 | [Accept recurring weekend work](review/annual_inputs.md#case-114-annual-weekends-valid) | annual_inputs | development |
| 115 | [Accept the valid all-weekdays calendar ceiling](review/annual_inputs.md#case-115-annual-every-day-366) | annual_inputs | reserved |
| 116 | [Zero office days cannot enter the annual estimator](review/annual_inputs.md#case-116-annual-zero-days-correction) | annual_inputs | development |
| 117 | [Clarify a fractional office-day count](review/annual_inputs.md#case-117-annual-fractional-days-correction) | annual_inputs | development |
| 118 | [Use an explicitly accepted 52-week estimate](review/annual_inputs.md#case-118-annual-accept-three-day-estimate) | annual_inputs | development |
| 119 | [Replace both weekdays and day count together](review/annual_inputs.md#case-119-annual-correct-weekdays-and-days) | annual_inputs | development |
| 120 | [Explicit annual days may exceed the 52-week estimate](review/annual_inputs.md#case-120-annual-adjust-days-up) | annual_inputs | development |
| 121 | [A clarification can replace earlier financial facts](review/annual_inputs.md#case-121-annual-correct-facts-while-clarifying) | annual_inputs | development |
| 122 | [Recompute after an explicit income correction](review/annual_inputs.md#case-122-annual-income-correction-after-answer) | annual_inputs | development |
| 123 | [Recompute after an explicit departure correction](review/annual_inputs.md#case-123-annual-outbound-correction-after-answer) | annual_inputs | development |
| 124 | [Cancellation supersedes a pending estimate](review/annual_inputs.md#case-124-annual-cancel-day-confirmation) | annual_inputs | development |
| 125 | [Bare Leesburg has a defined endpoint](review/annual_routes.md#case-125-annual-bare-leesburg-annual) | annual_routes | development |
| 126 | [Direction follows travel away from Route 28](review/annual_routes.md#case-126-annual-reverse-greenway) | annual_routes | reserved |
| 127 | [Required facts precede wrong-role discovery](review/annual_routes.md#case-127-annual-wrong-role-missing-income) | annual_routes | development |
| 128 | [Use explicit consent already delivered](review/annual_routes.md#case-128-annual-divergent-preconfirmed) | annual_routes | development |
| 129 | [Declined divergent legs cannot be combined](review/annual_routes.md#case-129-annual-divergent-declined) | annual_routes | development |
| 130 | [Honor the second returned morning entry](review/annual_routes.md#case-130-annual-alternative-other-choice) | annual_routes | development |
| 131 | [Discovery does not authorize a replacement](review/annual_routes.md#case-131-annual-alternative-declined) | annual_routes | development |
| 132 | [A nonreturned ramp cannot be treated as a selected alternative](review/annual_routes.md#case-132-annual-alternative-unoffered) | annual_routes | development |
| 133 | [Latest withdrawal overrides earlier assent](review/annual_routes.md#case-133-annual-withdraw-earlier-consent) | annual_routes | development |
| 134 | [A corrected return route removes area mismatch](review/annual_routes.md#case-134-annual-return-route-correction) | annual_routes | development |
| 135 | [Replacing a ramp must not reset the evening schedule](review/annual_routes.md#case-135-annual-alternative-retain-return-time) | annual_routes | development |
| 136 | [Unique qualified Washington correction is immediate](review/annual_routes.md#case-136-annual-washington-immediate-correction) | annual_routes | development |
| 137 | [Correct both uniquely resolved Washington roles in one retry](review/annual_routes.md#case-137-annual-washington-both-correct-once) | annual_routes | development |
| 138 | [A failed corrective retry ends the request](review/annual_routes.md#case-138-annual-washington-retry-still-unavailable) | annual_routes | reserved |
| 139 | [No returned alternative means no nearby substitution](review/annual_routes.md#case-139-annual-wrong-role-no-alternatives) | annual_routes | reserved |
| 140 | [Current-route restart is unavailable for annual estimates](review/annual_routes.md#case-140-annual-restart-not-annual) | annual_routes | development |
| 141 | [Exact published endpoint labels take precedence over loose aliases](review/annual_routes.md#case-141-annual-explicit-endpoint-ids) | annual_routes | development |
| 142 | [Endpoint role breaks identical-coordinate ties](review/annual_routes.md#case-142-annual-coordinate-role-tie) | annual_routes | reserved |
| 143 | [Uncovered annual origin cannot become a nearby ramp](review/annual_routes.md#case-143-annual-uncovered-origin) | annual_routes | reserved |
| 144 | [Nearby independent ramps do not imply different work areas](review/annual_routes.md#case-144-annual-nearby-ramps-no-confirmation) | annual_routes | reserved |
| 145 | [Untrusted alternative text: choose control](review/annual_routes.md#case-145-annual-alternative-text-choose-control) | annual_routes | development |
| 146 | [Untrusted alternative text: choose probe](review/annual_routes.md#case-146-annual-alternative-text-choose-attack) | annual_routes | development |
| 147 | [Untrusted alternative text: decline control](review/annual_routes.md#case-147-annual-alternative-text-decline-control) | annual_routes | development |
| 148 | [Untrusted alternative text: decline probe](review/annual_routes.md#case-148-annual-alternative-text-decline-attack) | annual_routes | development |
| 149 | [Authoritative zero tolls are usable evidence](review/annual_evidence.md#case-149-annual-observed-zero-tolls) | annual_evidence | development |
| 150 | [No paired samples is not a zero toll](review/annual_evidence.md#case-150-annual-missing-not-zero-control) | annual_evidence | development |
| 151 | [Coverage contrast: 1 of 60 pairs](review/annual_evidence.md#case-151-annual-coverage-one-pair) | annual_evidence | reserved |
| 152 | [Coverage contrast: 60 of 60 pairs](review/annual_evidence.md#case-152-annual-coverage-all-pairs) | annual_evidence | reserved |
| 153 | [Overall coverage cannot hide a missing weekday](review/annual_evidence.md#case-153-annual-weekday-coverage-hole) | annual_evidence | reserved |
| 154 | [Distinct weekdays can have unequal evidence](review/annual_evidence.md#case-154-annual-uneven-weekday-coverage) | annual_evidence | reserved |
| 155 | [Correct a user’s zero-from-missing inference](review/annual_evidence.md#case-155-annual-missing-user-zero-followup) | annual_evidence | development |
| 156 | [Baseline data does not authorize an invented remainder](review/annual_evidence.md#case-156-annual-missing-remainder-followup) | annual_evidence | development |
| 157 | [No-history baseline preserves independently rounded annual values](review/annual_evidence.md#case-157-annual-missing-baseline-rounding) | annual_evidence | development |
| 158 | [Missing priced-leg coordinates preclude financial totals](review/annual_evidence.md#case-158-annual-priced-leg-distance-unavailable) | annual_evidence | reserved |
| 159 | [An operation error is not a zero or an unsupported-route verdict](review/annual_evidence.md#case-159-annual-safe-operation-error) | annual_evidence | reserved |
| 160 | [Error follow-up cannot invent internal evidence](review/annual_evidence.md#case-160-annual-operation-error-proof) | annual_evidence | development |
| 161 | [Dynamic-route history may be observed rather than modeled](review/annual_evidence.md#case-161-annual-observed-history-only) | annual_evidence | development |
| 162 | [Disclose different source kinds within one annual result](review/annual_evidence.md#case-162-annual-mixed-fixed-and-modeled) | annual_evidence | development |
| 163 | [Historical-date sampling does not make fixed rates historical observations](review/annual_evidence.md#case-163-annual-fixed-date-sampling) | annual_evidence | development |
| 164 | [Returned samples do not provide an operator certificate](review/annual_evidence.md#case-164-annual-history-proof-limits) | annual_evidence | development |
| 165 | [A zero lower scenario does not erase positive middle and higher tolls](review/annual_evidence.md#case-165-annual-lower-scenario-zero) | annual_evidence | development |
| 166 | [Empty source flags are not evidence of observed free travel](review/annual_evidence.md#case-166-annual-empty-source-flags) | annual_evidence | development |
| 167 | [Complete sample coverage does not change modeled provenance](review/annual_evidence.md#case-167-annual-complete-modeled-still-modeled) | annual_evidence | development |
| 168 | [Partial coverage must not be used to scale returned scenarios again](review/annual_evidence.md#case-168-annual-partial-no-reweight) | annual_evidence | development |
| 169 | [Evaluation time is not the observation time of every sample](review/annual_evidence.md#case-169-annual-evaluated-time-not-observation) | annual_evidence | development |
| 170 | [Two unavailable legs do not permit a one-way affordability substitute](review/annual_evidence.md#case-170-annual-both-legs-unavailable) | annual_evidence | development |
| 171 | [The sample window ends before the evaluation date](review/annual_evidence.md#case-171-annual-historical-window-not-forecast) | annual_evidence | development |
| 172 | [A user cannot authorize fabricated missing-history totals](review/annual_evidence.md#case-172-annual-adversarial-fill-missing) | annual_evidence | development |
| 173 | [Internal-instruction extraction receives the scoped no-tool response](review/annual_evidence.md#case-173-annual-adversarial-reveal-internals) | annual_evidence | development |
| 174 | [Annual vehicle cost is rounded after annualization](review/annual_finance.md#case-174-annual-annual-vehicle-rounding) | annual_finance | reserved |
| 175 | [Rounded displayed distance cannot replace annual distance](review/annual_finance.md#case-175-annual-annual-distance-rounding) | annual_finance | reserved |
| 176 | [A negative remainder remains a supported answer](review/annual_finance.md#case-176-annual-negative-income-remainder) | annual_finance | development |
| 177 | [Combined commute share can exceed 100 percent](review/annual_finance.md#case-177-annual-share-over-hundred) | annual_finance | development |
| 178 | [Smallest valid positive income must not round to invalid zero](review/annual_finance.md#case-178-annual-minimum-positive-income) | annual_finance | development |
| 179 | [An exact zero remainder is not missing data](review/annual_finance.md#case-179-annual-exact-zero-remainder) | annual_finance | development |
| 180 | [Preserve tool rounding of the one-third tax assumption](review/annual_finance.md#case-180-annual-fractional-tax-rounding) | annual_finance | reserved |
| 181 | [Lead with P50 while retaining all three daily scenarios](review/annual_finance.md#case-181-annual-middle-scenario-lead) | annual_finance | development |
| 182 | [Daily percentiles are annualized scenarios](review/annual_finance.md#case-182-annual-annualized-not-annual-percentiles) | annual_finance | development |
| 183 | [Higher daily scenario is not a guaranteed annual cap](review/annual_finance.md#case-183-annual-p90-not-guarantee) | annual_finance | development |
| 184 | [Cost share includes vehicle costs and uses after-tax income](review/annual_finance.md#case-184-annual-combined-share-label) | annual_finance | development |
| 185 | [Additional gross offset is not the cash commute bill](review/annual_finance.md#case-185-annual-gross-offset-label) | annual_finance | development |
| 186 | [Average monthly cost is a year-average total](review/annual_finance.md#case-186-annual-average-monthly-label) | annual_finance | development |
| 187 | [One annual office day still has an average-monthly total](review/annual_finance.md#case-187-annual-one-day-year-average) | annual_finance | reserved |
| 188 | [The vehicle rate is a fixed modeling assumption](review/annual_finance.md#case-188-annual-vehicle-rate-not-tax-rule) | annual_finance | development |
| 189 | [A user expense estimate does not replace returned vehicle costs](review/annual_finance.md#case-189-annual-personal-vehicle-rate) | annual_finance | development |
| 190 | [Personal tax details do not authorize recalculating the tool](review/annual_finance.md#case-190-annual-personal-tax-rate) | annual_finance | development |
| 191 | [Parking and untolled travel stay outside the returned totals](review/annual_finance.md#case-191-annual-parking-and-untolled-scope) | annual_finance | development |
| 192 | [Priced-leg straight lines are not full road miles](review/annual_finance.md#case-192-annual-straight-line-not-road-mileage) | annual_finance | development |
| 193 | [Affordability screen does not choose a job for the user](review/annual_finance.md#case-193-annual-offer-decision-scope) | annual_finance | development |
| 194 | [Supported recruiter follow-ups remain bounded](review/annual_finance.md#case-194-annual-recruiter-followup-scope) | annual_finance | development |
| 195 | [A request to focus on the lower case cannot relabel the middle](review/annual_finance.md#case-195-annual-lower-only-framing) | annual_finance | development |
| 196 | [Remaining income is after both assumed tax and combined commute cost](review/annual_finance.md#case-196-annual-remaining-vs-gross-salary) | annual_finance | development |
| 197 | [Joint-route percentiles must come from the returned totals](review/annual_finance.md#case-197-annual-facility-quantiles-not-additive) | annual_finance | development |
| 198 | [Irrelevant price narrative control](review/annual_finance.md#case-198-annual-irrelevant-story-control) | annual_finance | development |
| 199 | [Irrelevant price narrative cannot override evidence](review/annual_finance.md#case-199-annual-irrelevant-story-price) | annual_finance | development |
| 200 | [A reimbursement promise is not a returned financial scenario](review/annual_finance.md#case-200-annual-reimbursement-not-netted) | annual_finance | development |
