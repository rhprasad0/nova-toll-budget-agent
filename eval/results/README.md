# Curated evaluation evidence

This directory contains technically valid, representative agent evaluations for
review. Scores are preserved as observed; failed, superseded, and ad hoc runs are
not curated.

| Report | Scenario | Type | Result |
| :-- | :-- | :-- | :-- |
| [`20260802T171949Z.json`](20260802T171949Z.json) | Same four closures with fixed actor premises and scoped judges | Deterministic trace grading plus goal-success and helpfulness judges | 0.9167 overall; 12/12 judgments passed; 0 execution errors |
| [`20260804T214058Z.json`](20260804T214058Z.json) | Eight reciprocal single-leg cases with explicit facility attribution for both Greenway mainline charges | Deterministic trace and hardened response grading | 1.0000 overall; 16/16 judgments passed; 0 execution errors |
| [`20260803T215248Z.json`](20260803T215248Z.json) | Matching multi-turn single-leg conversations with neutral fee-attribution and arithmetic follow-ups | Deterministic trace grading plus goal-success and helpfulness judges | 0.9167 overall; 24/24 judgments passed; 0 execution errors |
| [`20260804T153800Z.json`](20260804T153800Z.json) | I-95/395 one-way destination, origin, and supported-control access checks | Deterministic trace and response grading | 1.0000 overall; 3/3 cases passed; 0 execution errors |
| [`20260804T153830Z.json`](20260804T153830Z.json) | I-95/395 one-way destination, origin, and supported-control access checks | Deterministic trace and response grading | 1.0000 overall; 3/3 cases passed; 0 execution errors |
| [`20260804T153901Z.json`](20260804T153901Z.json) | I-95/395 one-way destination, origin, and supported-control access checks | Deterministic trace and response grading | 1.0000 overall; 3/3 cases passed; 0 execution errors |
| [`20260804T192029Z.json`](20260804T192029Z.json) | Ambiguous McLean location resolved before pricing | Simulated user, goal-success and helpfulness judges | 0.9165 overall; 2/2 judgments passed; 0 execution errors |
| [`20260804T192403Z.json`](20260804T192403Z.json) | Four historical I-95 closure conversations | Deterministic trace grading plus goal-success and helpfulness judges | 0.9167 overall; 12/12 judgments passed; 0 execution errors |
| [`20260804T211001Z.json`](20260804T211001Z.json) | Reciprocal I-66 / Dulles Toll Road trips split at the shared untolled junction | Code-graded live planner trajectory and response wording | 1.0000 overall; 2/2 cases passed; plaza billing preserved |
| [`20260804T211034Z.json`](20260804T211034Z.json) | Fixed directional access plus Glebe-to-Wiehle cross-corridor recovery | Deterministic trace and response grading | 1.0000 overall; 5/5 cases passed; 0 execution errors |
| [`20260804T211601Z.json`](20260804T211601Z.json) | Westpark-to-Scott and Glebe-to-Wiehle multi-turn alternative selection | Simulated-user trace grading plus goal-success and helpfulness judges | 0.9443 overall; 6/6 judgments passed; 0 execution errors |
| [`20260804T214919Z.json`](20260804T214919Z.json) | Missing origin, destination, or both before an I-495 quote | Scripted user with deterministic trace grading | 1.0000 overall; 6/6 verdicts passed; 0 execution errors |
| [`20260805T114633Z.json`](20260805T114633Z.json) | Ambiguous McLean clarification plus lowercased direct I-95 labels | Code-graded live trajectory | 1.0000 overall; 2/2 verdicts passed; direct I-95 access checked before pricing |
| [`20260805T114738Z.json`](20260805T114738Z.json) | Four historical I-95 closure requests after the mandatory access check | Code-graded live trajectory and response | 1.0000 overall; 8/8 verdicts passed; no unavailable route quoted a fare |
| [`20260805T124340Z.json`](20260805T124340Z.json) | New York date/time interpretation across EDT, explicit Pacific conversion, and EST | Deterministic live trace and response grading | 1.0000 overall; 6/6 verdicts passed; 0 execution errors |
| [`20260805T124420Z.json`](20260805T124420Z.json) | Relative future-date request (“tomorrow afternoon”) | Simulated user with goal-success and helpfulness judges | 0.8335 overall; 2/2 judgments passed; no pricing tool calls |
| [`20260805T134209Z.json`](20260805T134209Z.json) | IAD and DCA as directional endpoints, including normal Dulles Toll Road billing after IAD access and non-airport Access Highway refusal | Code-graded live planner trajectory and response | 1.0000 overall; 6/6 cases passed; airport access remained untolled but Toll Road billing remained intact |
| [`20260805T134505Z.json`](20260805T134505Z.json) | Simulated IAD toll pricing, DCA arrival, and attempted Dulles Airport Access Highway misuse | Simulated-user trace grading plus goal-success and helpfulness judges | 0.9443 overall; 9/9 judgments passed; no free non-airport bypass |

The repaired closure run found exactly one supported `i95_access_options`
execution followed by one `i95_route` execution per case, kept every actor on
its assigned route and time, and used response-only LLM assertions. See
`../deterministic/i95_historical_closures/` for the cases, assertions, and
runner. Telemetry-grounded analysis of the removed failed baseline remains in
`../eval-report.md`.

The single-leg deterministic run matched all eight captured tool results and
answers. Its Greenway cases returned `$5.80 + $2.00 = $7.80` eastbound and
`$2.00 + $5.80 = $7.80` westbound, with the `$2.00` item attributed to the
Dulles Toll Road. The simulated run preserved those tool results and totals
through both Greenway conversations without giving the actor the expected
facility or amount; every trace, goal-success, and helpfulness judgment passed.

The three one-way-access runs each required `i95_access_options` before direct
I-95 pricing, correctly explained both the southbound Quantico exit and the
northbound Joplin entry restrictions without quoting a fare, and checked access
before the supported control route's one `i95_route` call. This satisfies the
three-perfect-run promotion criterion for the deterministic suite.

The non-I-95 deterministic run rejected every wrong-direction endpoint before
pricing, including Compass Creek, Westpark-to-Scott, and the reported
Glebe-to-Wiehle request. Both simulated drivers selected Fairfax Drive and
completed full cross-corridor replans without changing the other endpoint. The
reciprocal junction run started or ended each Dulles leg at node `66`; the
junction stayed out of billing while mainline and ramp charges remained intact.

The missing-parameter run asked the exact question for all and only the absent
endpoints, then made one matching `i495_route` call per case after the scripted
user supplied the missing values. No LLM actor or judge participated.

The New York-time run resolved EDT, explicit Pacific, and EST requests to the
expected instants and preserved the tool-returned timestamps in US format. The
relative-future run refused “tomorrow afternoon” without calling a planner,
access, junction, or pricing tool; its helpfulness judge's partial score reflects
an unrelated request for alternative future-quote sources, not a failed refusal.

The airport runs resolved IAD and DCA as named endpoints rather than nearby
interchanges. IAD used the untolled Dulles Airport Access Highway only at the
airport boundary; a following Dulles Toll Road leg still itemized its `$4.00`
mainline and `$2.00` exit charges. The misuse conversation declined a non-IAD
bypass and warned that it can result in a ticket.
