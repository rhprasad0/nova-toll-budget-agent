# Curated evaluation evidence

This directory contains technically valid, representative agent evaluations for
review. Scores are preserved as observed; failed, superseded, and ad hoc runs are
not curated.

| Report | Scenario | Type | Result |
| :-- | :-- | :-- | :-- |
| [`20260812T191012Z.json`](20260812T191012Z.json) | Exact duplicate suppression on Dumfries/Pentagon I-95-to-I-495 routes plus changed-origin recovery from Joplin to Dumfries | Live deterministic tool-attempt and result grading | 1.0000; 3/3 cases passed; one duplicate planner attempt was cancelled after its matching success, all downstream tools completed, and the changed planner signature remained allowed |
| [`20260812T190511Z.json`](20260812T190511Z.json) | Three simulated I-95 one-way alternative selections, including cross-corridor replanning from Joplin to Dumfries | Live simulated user with duplicate-aware deterministic trace grading | 1.0000; 3/3 cases passed; changed inputs were allowed, every recovery tool completed, no duplicate attempt occurred, and no execution errors were recorded |
| [`20260809T214710Z-private-load-baseline.json`](20260809T214710Z-private-load-baseline.json) | Five concurrent private users making 15 canonical requests while both toll feeds ingest | Metadata-only deployed load and ingestion baseline | Passed; all requests and feed loads succeeded with zero errors or throttles, 15.47-second client p99, 15.19-second proxy p99, six active sessions, 5.43% peak RDS CPU, and 83.16 MiB minimum free memory |
| [`20260809T204906Z-actionable-alarms.json`](20260809T204906Z-actionable-alarms.json) | Proxy failure/latency, AgentCore session, toll-data freshness, and RDS capacity alarms | Metadata-only deployed observability verification | Passed; 10 alarms route to the confirmed alert topic, canonical smoke passed, CloudWatch recorded successful alarm-action execution, and the owner confirmed notification receipt |
| [`20260809T203937Z-agentcore-failure-drill.json`](20260809T203937Z-agentcore-failure-drill.json) | Request-scoped deployed AgentCore runtime exception through the private browser path | Metadata-only deployed failure and recovery drill | Passed on runtime 22; the browser received the exact safe error, governed failure telemetry correlated without contradictory records, and the same session recovered with the canonical $12.15 request while deployment identity stayed fixed |
| [`20260809T193920Z-kill-switch-drill.json`](20260809T193920Z-kill-switch-drill.json) | Authorized private TollChat service-wide kill-switch drill | Metadata-only deployed operational drill | Passed; proxy concurrency reached 0 in 2.3 seconds, both private API routes were blocked with zero AgentCore invocations, ingestion and RDS stayed healthy through Terraform apply, and concurrency 5 plus the canonical smoke recovered in 21.4 seconds |
| [`20260809T184848Z-agentcore-canonical-smoke.json`](20260809T184848Z-agentcore-canonical-smoke.json) | Versioned historical I-66 eastbound toll through the private browser path | Metadata-only deployed AgentCore canonical toll-query smoke | Passed on runtime 19; one exact `i66_route` call returned $12.15 and the browser received the required disclaimer |
| [`20260809T154455Z-agentcore-session-ownership.json`](20260809T154455Z-agentcore-session-ownership.json) | Anonymous browser credential ownership, expiry, rejection, reset, and runtime isolation | Metadata-only automated and live session-ownership verification | Passed 21/21 proxy, 34/34 Python, and 6/6 focused browser tests; live runtime 19 kept browser sessions disjoint and rotated only the reset owner |
| [`20260808T140554Z.json`](20260808T140554Z.json) and [Batch verdicts](batch-judges-batch_6a7737dfbd388190a78681ff30118b13-verdicts.json) | Four historical I-95 closures followed by one official-proof request; reimbursement excluded as out of scope | Live simulated user with deterministic trace/source grading and report-only OpenAI Batch judges | 1.0000; 8/8 deterministic verdicts, 4/4 goal success, helpfulness: 3 `Somewhat helpful` and 1 `Very helpful`; 0 execution errors |
| [`20260807T213709Z-guardrail-boundary.json`](20260807T213709Z-guardrail-boundary.json) | Prompt-attack and harmful-content block/pass behavior at both Guardrail boundaries | Metadata-only live `ApplyGuardrail` evaluation bound to the TollChat Guardrail identity, `us-east-1`, and immutable version 2 | Passed 6/6; prompt attack, harmful input, and harmful output blocked with the expected categories; benign input and clean toll input/output allowed |
| [`20260807T214229Z-agentcore-session-isolation.json`](20260807T214229Z-agentcore-session-isolation.json) | Two interleaved private-preview sessions through turn exhaustion and reset | Metadata-only live AgentCore session-isolation verification | Passed on AgentCore runtime version 13; disjoint runtime streams, isolated turn budgets, reset isolation, and runtime rotation verified |
| [`20260807T162433Z-agentcore-tracing.json`](20260807T162433Z-agentcore-tracing.json) | Private-preview route request plus synthetic-credential block | Metadata-only live AgentCore trace verification | Passed; 4 governed stages, 37 correlated native spans, and 2 redacted blocked-request records; native credential scan passed and no prompt, response, session, account, endpoint, or key data was curated |
| [`20260802T171949Z.json`](20260802T171949Z.json) | Same four closures with fixed actor premises and scoped judges | Deterministic trace grading plus goal-success and helpfulness judges | 0.9167 overall; 12/12 judgments passed; 0 execution errors |
| [`20260804T214058Z.json`](20260804T214058Z.json) | Eight reciprocal single-leg cases with explicit facility attribution for both Greenway mainline charges | Deterministic trace and hardened response grading | 1.0000 overall; 16/16 judgments passed; 0 execution errors |
| [`20260803T215248Z.json`](20260803T215248Z.json) | Matching multi-turn single-leg conversations with neutral fee-attribution and arithmetic follow-ups | Deterministic trace grading plus goal-success and helpfulness judges | 0.9167 overall; 24/24 judgments passed; 0 execution errors |
| [`20260804T153800Z.json`](20260804T153800Z.json) | I-95/395 one-way destination, origin, and supported-control access checks | Deterministic trace and response grading | 1.0000 overall; 3/3 cases passed; 0 execution errors |
| [`20260804T153830Z.json`](20260804T153830Z.json) | I-95/395 one-way destination, origin, and supported-control access checks | Deterministic trace and response grading | 1.0000 overall; 3/3 cases passed; 0 execution errors |
| [`20260804T153901Z.json`](20260804T153901Z.json) | I-95/395 one-way destination, origin, and supported-control access checks | Deterministic trace and response grading | 1.0000 overall; 3/3 cases passed; 0 execution errors |
| [`20260804T192029Z.json`](20260804T192029Z.json) | Ambiguous McLean location resolved before pricing | Simulated user, goal-success and helpfulness judges | 0.9165 overall; 2/2 judgments passed; 0 execution errors |
| [`20260812T193949Z.json`](20260812T193949Z.json) | Issue #175 multi-match location clarification and direct-resolution controls | Code-graded live trajectories | 1.0000; 14/14 cases passed, every multi-match alias clarified before tools, and explicit/exact controls proceeded with canonical inputs |
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

The calibrated proof-only run retained those two tool executions and exactly two
agent turns in all four conversations. No actor requested reimbursement. Every
agent used the grounded no-source disclosure and generic VDOT/511 referral; all
goal judges passed and every helpfulness judge rated the response at least
`Somewhat helpful`.

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

The duplicate-aware one-way simulation preserved the other endpoint while each
driver selected the assigned alternative. Both direct cases executed one
rejected access check, one changed successful access check, and one pricing
call. The cross-corridor case executed the rejected planner call, changed
planner call, junction call, and I-495 call. All tool spans had distinct IDs and
no guard cancellation was needed in this observed run.

The dedicated duplicate-hook run reproduced the original Dumfries stutter with
two distinct planner call IDs and identical arguments. The first execution
succeeded, the hook cancelled the second, and the junction and I-495 calls then
completed. Pentagon completed without a stutter. The two-turn recovery first
received the expected Joplin mismatch, then allowed the changed Dumfries planner
call and completed both downstream calls.

The non-I-95 deterministic run rejected every wrong-direction endpoint before
pricing, including Compass Creek, Westpark-to-Scott, and the reported
Glebe-to-Wiehle request. Both simulated drivers selected Fairfax Drive and
completed full cross-corridor replans without changing the other endpoint. The
reciprocal junction run started or ended each Dulles leg at node `66`; the
junction stayed out of billing while mainline and ramp charges remained intact.

The missing-parameter run asked the exact question for all and only the absent
endpoints, then made one matching `i495_route` call per case after the scripted
user supplied the missing values. No LLM actor or judge participated.

The issue #175 deterministic run asked before tools for all seven current
multi-match aliases, including same-corridor Ballston, Vienna, and Herndon.
Bare Washington clarified as either endpoint even when the other endpoint
suggested a corridor; explicit I-66/I-395 requests proceeded directly, and
exact `Washington D.C.` was not reinterpreted as the bare alias. McLean retained
Westpark Drive and 7/15/2026 3:30 PM ET through clarification, while its explicit
I-495 control used the same canonical inputs without an extra question.

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
