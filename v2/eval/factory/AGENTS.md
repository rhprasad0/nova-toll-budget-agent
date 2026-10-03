# Evaluation factory agent

Author private inputs only in `/private/work/drafts/`; preserve revisions in the
private Git repository. Use the frozen schemas and contract in
`/opt/factory/v2/eval/factory/`. Start at suite/split version 4.0.0: 100 training,
50 holdout, 10 shadow. Read `/opt/factory/v2/eval/factory/README.md` for commands
and review formats; it stays available after initialization and restore.

## Agent-driven authoring and execution

1. Read the [authoring guide](AUTHORING.md) at
   `/opt/factory/v2/eval/factory/AUTHORING.md`, the frozen `contract.json`, and
   `examples/schemas.json` under
   `/opt/factory/v2/eval/factory/`. Inspect the historical teaching examples to
   understand shapes, not to seed fresh holdout cases. Plan coverage allocations
   and scenario groups for all three splits before writing cases, preserving
   the contract's counts and family allocations. Cover networks/directions,
   observed/fixed/modeled sources, weekend schedules, I-95 availability/restart
   decisions, clarifications, cancellations and workflow changes. Distribute
   facilities and dynamic/fixed pricing across splits.
2. Create `cases.jsonl`, `fixtures/*.json`, `examples.json`, and
   `prompt-points.json` in each draft split. Generate realistic cases, reconciled
   fixtures, a complete passing reference per case, and at least 20 labeled
   negative references across the suite. Include valid wording variants,
   omission-only failures, grounded consent violations and actor-invalid controls;
   assess Outcome, Grounding and Rules independently. References must show
   achievable receipts and actor behavior. Set every actor budget to five turns
   including the opening; derive minimum turns from necessary exchanges.
   Do not substitute lifecycle smoke data.
3. Run `factory validate --inputs /private/work/drafts`; repair drafts until it
   passes. Review novelty, paraphrases, behavioral pairs, and cross-split leakage
   yourself; keep a complete private case/reference assessment matrix outside the
   split input directories and summarize aggregate coverage and limitations for
   Ryan. Keep materially similar scenarios together; new endpoints or prices
   alone do not establish independence. Canonical current/outbound/return route
   pairs cannot cross splits, including reversed legs and role/direction variants.
4. Freeze the validated suite with `factory freeze`. Use new suite and changed
   split versions for repairs; never overwrite a freeze. Do not change the
   pinned evaluator or model settings to make generated cases pass.
5. Run calibration only with Ryan's explicitly authorized per-command budget
   and authorization record. Prepare the complete calibration evidence for his
   review; record his actual decisions before exporting training/shadow inputs.
6. Evaluate only an explicitly handed-off, trusted source snapshot and an
   authorized budget. Prepare the blinded audit before any reveal, collect the
   real reviewer's assessments, then record dispositions and export evidence.
   Retain Ryan's holdout-reuse and release decisions. Never impersonate him or
   treat an agent review as human or independent inspection.

Use the existing factory CLI as your tools. Preserve generated drafts and
private history across sessions. Ask for missing user decisions when needed;
continue authoring and validation without asking for permission for routine
draft edits. Budget authorization applies only to its stated command/scope.
Codex defaults to YOLO mode in this container: command approvals are disabled,
and container files/networking are available without Codex sandbox restrictions.
Continue authorized authoring and private Git work directly. This setting does
not authorize paid commands, human review decisions, or broader database access.

## Development data for authoring

Read `/opt/factory/v2/eval/factory/DATABASE.md` and the committed schema references
under `database/` before any database query. AWS CLI and PostgreSQL tools are
installed, along with an unprivileged Tailscale daemon and a PostgreSQL SOCKS
wrapper that work with rootless Docker. Ryan logs this container into Tailscale
and configures the independent `nova-toll-dev` SSO profile inside the container.
Keep their state/configuration/caches under `/private/agent-state/`.
Never read credentials, import host login caches, or request keys in chat.

Every read must verify account `903859731897`, the fixed private `nova-toll-db`
instance, site-1 route, and TLS CA, then use only `nova_toll_development` with
`pricing_reader_development`. Follow DATABASE.md's bounded, timed, read-only
transaction procedure. Inspect explicit route/pricing columns, not application
conversations or stored eval cases/results. Stop on missing login, privileges,
connectivity, or schema uncertainty; report the boundary without leaking tokens
or connection metadata. Do not substitute production or change IAM/database roles.

Use observed catalog/pricing data to ground realistic synthetic cases. Reconcile
fixture arithmetic, preserve relevant observation times/provenance, and label
generated fixtures truthfully. The schema references are documentation; never
execute them. Use the bundled point catalog if oracle tables are not readable.
Freeze all case evidence before calibration. References, actors, and application
trials use frozen fixtures and never fetch live database data.

Author realistic passenger-car/E-ZPass requests, full actor profiles, bounded
tool steps, reconciled synthetic fixtures, passing references, and useful
negative references. Keep actor facts separate from delivered consent. Verify
amounts, endpoints, time roles, provenance, terminal objectives, and split groups.
Shared scenario groups, equivalent pricing evidence, or paraphrased cases must
stay within one split. Automated duplicate checks cannot prove novelty: review
near duplicates and coverage before freezing. Exposed historical cases are
teaching material, never a fresh holdout. Do not author the real suite during a
tooling smoke test.

Never read the application repository or its agent memories while authoring a
holdout. No repository or Docker socket mount belongs in this container. Local
separation is procedural, not protection against malicious candidate code or a
host administrator. Relocate the kit and private volume to another host/account
when stronger separation is needed. Source snapshots contain executable code;
accept only reviewed, trusted handoffs. The worker inherits no provider/AWS
credentials; its provider key travels over stdin.

Ryan enters the evaluation API key himself with `factory set-api-key` at a hidden
terminal prompt. The factory loads `/private/agent-state/openai-api-key` only for
paid commands; `OPENAI_API_KEY` can explicitly override it. Never ask for the key
in chat, read/print it with tools, or export it globally into Codex's environment.
Keep credentials and authentication exclusively in `/private/agent-state/` or
runtime environment, never in work files, candidate snapshots, Git, or backup.
Use a separate factory login and memory; do not import the repo's Codex state.
Backups include only the private work directory. Maintain backup files privately.

Paid calibration or application commands require Ryan's explicit budget and
authorization evidence. Never infer paid authorization from installing tooling.
Calibrate every reference once and check one passing scripted exchange per case
once per frozen suite. Review full evidence and all material disagreements;
repairs require a new version and calibration. Synthetic mocks are smoke-only.

For every holdout attempt, review `audit.json` first. Record Outcome, Grounding,
Rules, and actor validity before opening application identity or judge verdicts.
Then reveal and disposition disagreements. Never edit original scores. Material
grading/actor defects block release-ready evidence. Assessments and dispositions
are immutable; repairs need fresh versioned evidence.

Record every manual feedback disclosure with payload digest, recipient, purpose,
and timestamp. Report exports do this automatically. Reuse requires Ryan's
approval for the next exact source snapshot and current ledger, even after
training/shadow revisions. No automatic attempt cap or numerical release gate.
Detailed transcripts, audit findings, and case differences stay private. Export
only training/shadow inputs and their calibration evidence, or aggregate report
fields through the factory commands. Release and renewal remain Ryan's decisions.
