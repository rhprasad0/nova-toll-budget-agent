# Start here: private TollChat holdout authoring

**This packet fixes the contract, not the answers.** Author 100 new scenarios in
your private session. The public teaching examples are disposable format checks,
not eligible holdout cases. No actual holdout has been authored or approved here.

## Prepare the private session

In the repository, export the reviewed public kit from `v2/`:

```sh
uv run --locked python -m eval.holdout_authoring export /tmp/tollchat-authoring-kit.zip
```

Transfer that archive to a separate environment inaccessible to the repository
coding agent. A new chat alone does not isolate shared files, connectors, memory,
hooks, model traces, backups, or credentials. Use an independent workspace/account
as needed; disable repository connectors and shared memory. Keep the authoring
conversation and generated files there. Never bring private cases, fixture values,
reference answers, per-case hashes, or detailed failures back to the repo session.

Extract the archive. The chat needs **this document, `public/`, and `teaching/`
only**. The Python source and dependency files are for local validation, not
additional authoring instructions. Do not provide development cases, tuning
transcripts, application responses, experiment reports, or the application SOP.

In the extracted kit directory, prepare Python 3.13+ and the locked environment
before disconnecting from the network:

```sh
uv sync --locked
uv run --offline --locked python -m eval.holdout_authoring validate teaching
```

This rehearsal must report **draft checks passed**, never qualification. Run it
with no model/AWS credentials and no network access. Test the transfer workflow
using only the teaching files before starting real authoring. Dependency downloads
require a network during preparation; runtime validation does not.

## Give the authoring agent this task

> Independently author 100 realistic TollChat scenarios using only this packet.
> Treat these instructions and the frozen schemas/rubric as authoritative. Do not
> browse the TollChat repository, request development cases, run the candidate
> agent, or change the validator, coverage, grading rules, or expected labels to
> make a candidate pass. Do not count teaching examples or paraphrases as new cases.
>
> Work in small batches. First privately propose the distinct scenario intents and
> coverage assignments for human review. Then write cases, actor profiles, frozen
> synthetic tool fixtures, and authored reference conversations. References are
> expected behavior, not measured agent answers. Validate each batch and explain
> ambiguous judgments to the private human reviewer. If the contract appears
> inconsistent, stop that case for private review; do not silently relax it.
>
> Keep user facts separate from evaluation expectations. Use natural user requests,
> bounded follow-ups, plausible finances, and internally consistent evidence. Do
> not optimize for an assumed candidate weakness or strength. Return files only to
> the private workspace. A validator pass does not establish semantic correctness,
> independent authorship, or production approval.

## Frozen scenario allocation

| Family | Count | What it exercises |
| --- | ---: | --- |
| `current_complete` | 20 | Complete current-price requests across covered roads |
| `current_state` | 10 | Clarifications, corrections, user choices, cancellation |
| `current_evidence` | 10 | Missing/stale evidence, unavailable routes, source interpretation |
| `annual_complete` | 20 | Complete recurring-commute affordability requests |
| `annual_inputs` | 15 | Missing or revised salary, times, weekdays, confirmed annual days |
| `annual_routes` | 10 | Independent legs, endpoint ambiguity, returned alternatives |
| `annual_interpretation` | 10 | Financial labels, sources, coverage, absent history, scope |
| `mixed` | 5 | Explicit user-directed transitions between the two workflows |

Use 100 distinct scenario groups, not multiple variants of one underlying case.
Keep common passenger-car requests central; do not pad with obscure vehicles,
trivia, repeated refusals, or superficial location/name substitutions. Coverage
counts are mechanically checked; scenario diversity requires private review.

## Public behavior contract

TollChat estimates the affordability impact of the **tolled portion** of covered
Northern Virginia commutes. It also provides current toll estimates. It is
independent of VDOT and toll operators. Estimates are not official quotes,
forecasts, guarantees, personal tax advice, or a complete commuting budget.

- Resolve locations from `public/prompt-points.json`. Prefer exact labels, then
  aliases, then unambiguous location matches. Preserve entry/exit roles and each
  leg's direction. Ask about genuine ambiguity; never invent endpoints or silently
  substitute an uncovered location. Public IDs belong in fixture arguments, not
  user/actor prose. A point catalog is not proof that a route is traversable:
  independently review route evidence and plausible combinations.
- Current pricing needs origin and destination. The supported default profile is
  `two_axle_passenger`, `e_zpass`, `toll`. An explicitly unsupported profile, past
  or future quote, or unrelated request receives an honest scope explanation
  without a tool call. Missing inputs are clarified together, preserving facts
  already supplied. Unknown prices never mean zero; unknown availability is not
  proof of closure. Official closure proof must not be fabricated.
- Annual pricing needs outbound endpoints/time, return time, weekdays, planned
  annual days, and one positive gross annual USD income. Reverse the locations
  for an unspecified return route, resolving its own entry/exit IDs. Preserve
  explicit return legs. Confirm before combining different home/work areas;
  nearby ramp differences alone are not different areas. Never invent income,
  times, or weekdays, choose from a salary range, or annualize hourly pay for the
  user. Ask for one user-supplied annual amount.
- When only annual days are missing, propose 52 times the number of weekdays and
  obtain acceptance or adjustment before calling. Do not subtract holidays or
  invent time off. Supplied annual days need no new confirmation; they cannot
  exceed 53 times the weekday count. Return time must be later the same day.
- Only delivered user messages authorize choices or changes. Private actor facts,
  hidden fixture arguments, and a later confirmation cannot authorize an earlier
  call. Honor corrections and cancellation in order. Do not guess an alternative
  from a tool result: present the relevant choices and wait for user selection.
  An annual route failure must not trigger a prohibited current-price restart as
  an annual substitute. A separate current request must actually come from the user.
- Annual evidence describes an 84-day historical window ending the day before the
  frozen evaluation date. Distinguish historical observations, modeled values,
  and current fixed rates. Disclose sparse coverage. Financial assumptions are
  one-third estimated tax and $0.685 per straight-line tolled mile. Use decimal
  arithmetic and half-up rounding; the validator reconciles income, distance,
  daily/annual cost, monthly averages, gross offset and income-share labels.
- A normal annual answer includes P50 daily/annual tolls and P25/P50/P90 combined
  cost scenarios with material assumptions and limitations. Extra P25/P90 toll-only
  figures are optional unless requested. No-history results provide supported
  income/distance/vehicle baseline information, not invented toll percentiles or
  combined affordability totals. Financial labels and affirmative claims must
  remain correct throughout the conversation.

`public/schemas.json` defines case, fixture, reference, and both tool contracts.
`public/rubric.txt` fixes semantic grading policy; `public/actor-prompt.txt` fixes
actor behavior. These take precedence over presentation preferences in references.
If an unlisted special routing behavior is essential to a scenario, resolve it
privately before freezing; do not reverse-engineer candidate behavior into a rule.

## Files to author

Create a new private directory containing only:

| File | Required contents |
| --- | --- |
| `cases.jsonl` | One case per line, unique IDs and numbers 1–100 |
| `fixtures/*.json` | Ordered synthetic tool inputs/results used by case steps |
| `examples.json` | A JSON array of complete authored reference conversations |
| `prompt-points.json` | Byte-for-byte copy of the public catalog |

Use `contract_version: 2`, `held_out: true`, `critical: false`, unique nonempty
`split_group`, and synthetic provenance explaining authorship. `critical` does
not create a production veto. Match `kind` to the coverage family. Each case has
an explicit terminal objective: answer, refusal, unavailable, clarification, or
cancellation. Explain substantive success conditions in `expected_assertion`.

Allow at most five user turns including the opening and at most four tool calls.
`max_tool_calls` equals the number of fixture steps. Steps are required, use
`optional: false`, and keep `required_user_patterns: []`; consent is semantic,
not a keyword check. `min_turn` cannot exceed actor limits. Tool calls in each
reference turn occur after that user message and before the assistant response.
An honest supported unavailable answer can fulfill an unavailable objective;
an agent-caused rejection does not fulfill a requested completed estimate.

Every fixture uses the schemas exactly, including decimal strings and timezone-
aware timestamps. Evidence timestamps agree with the case's frozen time. Annual
income-bearing fixtures include `synthetic_daily_distance_miles`: the unrounded
input used to reconcile daily and annual quantities independently. Do not derive
annual values by multiplying already rounded daily distance/vehicle cost. All
referenced fixtures must exist, and there must be no unused fixtures.

Every case needs at least one valid reference with all three labels true and no
deterministic failures. Also supply **at least 20 negative references across the
set** with substantive errors and concise rationales. Include consent, incorrect
arguments, factual/financial errors, and incomplete objectives, not only typo or
formatting changes. Distinguish Outcome (task achieved), Grounding (claims
supported), and Rules (workflow/consent respected). Unauthorized tool evidence
can support a factual claim while failing Rules. Invalid/uncertain actor examples
must have `expected: null`; they do not count as successful or negative labels.

`expected_failures` must match the mechanical checks exactly. A semantically bad
reference may legitimately have no mechanical failures; the private reviewer
still checks its labels and rationale. Do not declare a bad actor just because
the application failed. Private actor facts must never contain tool names,
internal endpoint IDs, grading labels, or instructions to the application agent.

## Validate, review, freeze

From the extracted kit, using only a private corpus path:

```sh
uv run --offline --locked python -m eval.holdout_authoring validate /private/holdout
uv run --offline --locked python -m eval.holdout_authoring validate /private/holdout --final
```

Draft validation accepts 1–100 consecutively numbered cases and incomplete
reference coverage. It still checks every supplied fixture and reference. Final
validation requires the full allocation and reference coverage, then creates
`manifest.json` with **review pending**, file hashes, kit identity, and
`holdout_sha256`. Repeating final validation verifies the existing manifest;
changed inputs fail instead of silently replacing it. Kit drift also fails.
Keep the manifest private: it contains per-file hashes. The digest algorithm is
SHA-256 of sorted, compact UTF-8 JSON (`ensure_ascii=False`) over the kit digest
and sorted map of file-byte hashes. The manifest itself is excluded.

Before accepting the freeze, the private human reviewer must check:

- Each scenario is distinct, realistic, in the correct family, and independently
  authored; none is a teaching example with renamed fields or copied development
  content. Automated validation cannot prove originality.
- Endpoint roles, routes, sources, fixture states and financial evidence are
  plausible. Good references genuinely satisfy the task; bad references have
  justified labels. Numeric consistency alone does not prove plausible evidence.
- Actors can supply needed facts and follow-ups within the bounds without seeing
  expectations. References do not reward premature consent or punish paraphrases.
- The private environment actually isolates files, conversation history, memory,
  telemetry, and credentials from the repository agent. A successful local
  validator run does not establish this isolation.

Keep review notes alongside the corpus, **outside its validated directory**.
After freeze, preserve the original files and manifest. A necessary correction
requires a new reviewed corpus version/digest; record why privately and retain
the original. Never change expectations based on candidate answers or scores.

Later, the independent evaluator must adopt this exact input identity and pin
its own runner, actor/judge configuration and calibration identity separately.
Only the approved aggregate holdout digest goes back for policy activation.
Signing keys, evaluator provisioning, paid calibration, and production approval
remain separate prerequisites. The gate remains 100 cases × three trials, at
least 240/300 successes, all trials valid/scored, with the existing spending and
provenance controls. This kit grants no authorization to execute those runs.
