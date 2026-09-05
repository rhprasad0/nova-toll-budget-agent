---
name: eval-graph
description: "Run a reusable Codex eval loop around an agent: $eval-graph, pin a case, fixture run, improve a suite, pass^k gate, or sealed held-out comparison."
---

# Eval graph

Use for a concrete miss, measured candidate improvement, or a frozen release
gate. Do not use for feature implementation, ordinary code review, speculative
case generation, or installing this skill. Installation never starts trials.
The graph is the harness around the agent, not another agent.

Parent: **gpt-6-astra, medium**. Every spawned leaf: **gpt-5.6-luna, medium**.
Reuse [project-graph](../project-graph/SKILL.md)'s registration, worktrees,
five-line `.graph/STATE.md`, and one-writer discipline. Do not start its
explorer/pre-checker/builder/checker sequence or add another orchestrator.
The eval-specific intervention and metric rules below govern this graph.

## Invariants

1. The proposer cannot edit the metric.
2. The critic cannot patch.
3. The runner cannot see the rubric.
4. Held-out is not in the prompt and fixer/case_miner must not read it.
5. Scripts beat prose when they disagree.
6. A flake is a finding, not noise to average away.
7. Promotion is identity-pinned (model, prompt hash, tool contract, dataset hash, commit/artifact digest).
8. Humans own the definition of correct, the holdout, and merge.

## Files and ownership

The eval root is **`v2/eval/`**, not `evals/`. Preserve `run_evaluation.py`,
existing JSONL corpora, batch evaluation, and results. Do not duplicate them in
`cases/`; adapt an existing case at the trusted boundary only when needed.

| Path | Owner / use |
| --- | --- |
| `.codex/agents/{case_miner,eval_runner,eval_reviewer,eval_fixer}.toml` | Four leaf contracts; no eval_gate agent |
| `.codex/hooks/graph-write-guard.py` | Existing native-ID/worktree registry |
| `.graph/STATE.md` | Parent: Intent, Worktree, Current node, Next legal edge, Blocked by |
| `v2/eval/cases/<id>.json` | Miner proposes one new case; human accepts and freezes it |
| `v2/eval/grade.sh`, `compare.sh`, `graph_checks.py`, `schemas/scorecard.schema.json` | Frozen deterministic metric; humans approve changes |
| `v2/eval/held_out/` | Human-controlled sealed inputs; only placeholder tracked |
| `v2/eval/artifacts/<run>/` | Ignored public artifacts, manifests, scorecards and sanitized reports |
| `v2/eval/ledger.jsonl` | Parent appends sanitized decisions after writers stop |

## Preconditions and registration

1. Create/reuse an isolated project-root `.worktrees/<run-or-leaf>` checkout.
   Assign one writer at a time. Freeze candidate, metric, dataset and approved
   input files before any trial. Do not let a leaf change its own contract.
2. When the project hook exists, follow AGENTS.md's `/hooks` trust/activation
   procedure for SubagentStart and PreToolUse. Start new children after activation.
   The four eval roles must be registered in the existing config and guarded-role
   set. Missing support blocks the run; do not bypass it or create a new registry.
3. Require a sealed runtime exposing only the leaf's approved view. Worktrees,
   workspace-write and the hook alone do **not** isolate reads. Exclude rubric,
   expected checks, full cases, grading source, old eval files containing checks,
   private data, sibling views, and Git object access to those files from runners.
   Keep Git metadata needed for top-level confirmation behind the trusted boundary.
   Miner/fixer views exclude held-out inputs and sealed reports. If these
   restrictions cannot be enforced, stop with `infra_dependency`; do not build a
   sandbox system or claim instruction-only isolation is sealed.
4. Humans run held-out trials through a trusted external executor. It executes
   the exact candidate with the frozen metric and returns sealed before/after
   manifests and scorecards only. Never put held-out inputs in leaf prompts or
   send held-out failures to the miner/fixer as corrective examples. Missing
   held-out evidence blocks promotion. This skill does not supply that executor.
5. Parent updates STATE before each spawn/handoff/result. Spawn fresh context,
   wait for the child's native SubagentStart `agent_id`, then run:

   ```text
   python3 <active-checkout>/.codex/hooks/graph-write-guard.py register <agent-id> <role> <absolute-worktree>
   ```

   Acknowledge: `Registered native agent_id <id> as <role> to <absolute-worktree>.
   You may now confirm the worktree and use tools within your assigned view.`
   Never use a task name as ID or acknowledge a failed registration. If the hook
   is absent, require native identity from the host, record assignment in STATE,
   and acknowledge the assignment explicitly; do not invent an ID or a registry.

### Exact spawn text

Use tool arguments `agent_type=<role>`, `model="gpt-5.6-luna"`,
`reasoning_effort="medium"`, `fork_turns="none"`. If the host uses configured
roles without overrides, the role TOML must supply the same model and effort.
Replace placeholders; never inherit the parent conversation.

**First spawn, mode=pin:**

> Spawn `case_miner` with `model="gpt-5.6-luna"`, `model_reasoning_effort="medium"`, and `fork_turns="none"` for mode=pin in `<absolute-worktree>`. Your only write target is `<absolute-worktree>/v2/eval/cases/<case-id>.json`. Use the supplied sanitized concrete miss and human-defined behavior to propose one case; do not invent product behavior or read held-out data. Before using any tool, report your native SubagentStart `agent_id` and wait. The parent registers it using `python3 <active-checkout>/.codex/hooks/graph-write-guard.py register <agent-id> case_miner <absolute-worktree>` when that hook exists, then explicitly acknowledges registration. Missing native identity or failed registration blocks tools. After acknowledgement, confirm the worktree with `cd <absolute-worktree> && git rev-parse --show-toplevel`; prefix every Bash command with that directory. Do not spawn children, commit, push, or open a PR. Return sanitized JSON identifying the case artifact, evidence, and `failure_class`.

For subsequent spawns, use this exact shared paragraph followed by one role
paragraph and the named sanitized inputs:

> You are `<role>`, gpt-5.6-luna at medium effort, spawned with fork_turns="none", in `<absolute-worktree>`. Before tools, report your native SubagentStart agent_id and wait for the parent's registration acknowledgement. The parent registers using `python3 <active-checkout>/.codex/hooks/graph-write-guard.py register <agent-id> <role> <absolute-worktree>` if the hook exists. Missing identity or failed registration blocks tools. After acknowledgement run `cd <absolute-worktree> && git rev-parse --show-toplevel` and confirm that exact path; prefix all Bash with `cd <absolute-worktree> &&`. Follow your role TOML and the approved sealed view. You are not alone; preserve existing edits. Do not spawn children, commit, push, or open a PR. Return the sanitized JSON report required by the skill.

> eval_runner: Execute `<public-input-packet>` for `<mode>` using `<approved-entrypoint-and-fixtures>`. Write only the declared raw artifacts under `<artifact-directory>`. For gate execute exactly `<case/trial-list>`, each with independent agent and tool state. Do not read full cases, expected checks, rubric, grader, or held-out. Do not grade. Missing real-entrypoint fixture support is infra_dependency.

> eval_reviewer: Falsify `<frozen-public-evidence>` against `<human-contract>` and `<scorecards>`. Read only; no patches or file writes. Wait for completed scorecards before final findings. Return findings and reasons, plus up to five public human-sample references when identity or grader changed. Scripts own pass/fail; do not recompute pass^k by vibes.

> eval_fixer: Make one bounded change to `<allowlisted-candidate-file>` for `<public-compare/reviewer-reason>`. Do not read held-out or sealed reports. Refuse edits to eval/cases/held_out/schema/script paths, graders, copied metrics, or permissions. Do not grade or approve yourself. Return changed paths and reason; stop if more than one bounded change is needed.

## Legal edges and stops

```text
cases → runner → grade → critic → compare → keep|drop
                                    ↓ improve only, once
                                  fixer → fresh runner → grade → fresh critic → compare → keep|drop
```

Grade is a deterministic process, not a leaf. Scripts are the metric;
eval_reviewer only falsifies and prepares a human sample. Only the parent
schedules edges. Reviewer and grade may overlap on immutable raw evidence;
reviewer waits for scorecards before finalizing. No other concurrent writers.
Parent persists read-only reviewer JSON unchanged after grading ends. Never
write checklist/verdict analogues on a leaf's behalf or approve your own repair.

- **pin:** sanitized concrete prod miss → case_miner → frozen proposed case →
  runner expecting failure → grade.sh → critic → compare if a baseline exists →
  human accepts the case. Without baseline, record reproduction only. Stop if the
  case passes, evidence is missing, or failure is infra/dependency. Only a
  deterministic agent-quality failure reproduces the miss; human acceptance
  freezes the new case. No fixer or automatic case acceptance.
- **improve:** freeze suite, candidate and baseline → runner per public case in
  assigned worktree → grade → fresh critic → compare with sealed evidence. On
  any held-out pass→fail stop and drop immediately. Permit at most one fixer
  invocation for a bounded public reason; then rerun the entire same suite and
  obtain fresh held-out evidence before comparing again. Keep only an improved
  candidate with no regressions, unresolved critic findings or evidence gaps;
  unchanged is drop. No further fixer passes in that invocation.
- **gate:** human freezes release suite and N independent trials, default N=3.
  Run declared public trials → grade → fresh critic → compare including sealed
  evidence → identity check against the human-approved candidate manifest.
  Gate never starts a fixer. Every release case must pass every trial; both
  agent-quality and infra/dependency failures fail the gate. Critic cannot
  override a script failure. Stop for human merge; never merge automatically.
- **pass@k** (capability): at least one success in k independent attempts. Record
  every attempt; never use it as release permission. **pass^k** (gate): all k
  attempts pass for every release case. Mixed outcomes are a flake finding,
  not a retry budget or noise to average away.

### Stall handling

Trigger on repeated failed approach without new evidence, no artifact across
two follow-ups, sandbox escape, missing identity, or a done claim with no report.
Contain an escape immediately. Request evidence and give **one concrete
correction**. If unresolved, interrupt the leaf, confirm its commands and pending
writes stopped, preserve artifacts, update STATE, and respawn the **same Luna
role** with fresh context/UUID/registration. For a fixer, replacement continues
the same one-change allowance; it does not earn another pass. If the required
boundary or identity remains unavailable, record blocked and stop. Astra may
diagnose read-only but never completes the leaf's job and blesses it.

## Data and script contract

Python 3.10+ and Bash are required. No network/model in grade or compare.
Commands use the trusted frozen metric checkout, outside the runner view:

```text
v2/eval/grade.sh <artifact-dir> <case.json>
v2/eval/compare.sh <before> <after> [held-out-dir]
```

Public case JSON: `case_id`, `prompt` (nonempty string), `setup` (object, may be
empty), `expected`, `rubric` (rubric ID array). Missing or invalid runner inputs
are infra_dependency. `expected` is a nonempty object with only these checks:

| Key | Value / deterministic meaning |
| --- | --- |
| `exit_code` | Integer equality with `exit_code.json` |
| `stdout_contains` / `stdout_not_contains` | Nonempty arrays of nonempty literal substrings |
| `file_exists` | Nonempty array of relative file paths below artifact `files/`; no escapes |
| `regex` | Nonempty array of Python regex search patterns against stdout |
| `json_path` | Nonempty array of `{ "path": ["key", 0], "equals": <JSON> }`; typed key/index traversal of output.json, empty path checks the whole value |

The supervisor passes runner only `case_id`, `prompt`, `setup` and approved
entrypoint instructions. Runner writes `stdout.txt`, integer `exit_code.json`,
optional `output.json`, `trace.json`, and `files/`. All data must be sanitized
before storage; if redaction would change the behavior under test, stop and ask
the human for a safe fixture. Do not silently redact the graded output.

The trusted supervisor seals `run.json` after execution, outside leaf write
access: `identity`, `case_digest` (SHA-256 of exact full case bytes),
`failure_class` (`none` or `infra_dependency`), `tokens`, `latency_ms` (nonnegative
integers or null). Never let runner self-assert trusted identity or classify a
dependency error as a successful run. An unexpected exit/check failure without
an infrastructure finding is agent_quality; preserve both evidence classes if
both occurred, with infra_dependency blocking promotion.

Identity fields: `model`, `prompt_hash`, `tool_contract_hash`, `dataset_hash`,
`commit`, `artifact_digest`, `grader_digest`; scorecards also require unique
`trial_id`. Hashes are lowercase SHA-256. Commit is the full Git object ID.
Hash exact prompt bytes, canonical JSON tool contract (sorted keys, compact
separators, UTF-8), and sorted `[relative-path, file-sha256]` JSON arrays for
dataset/candidate files. Candidate digest covers all executable candidate code,
prompt and tool configuration, including dirty files; exclude eval artifacts.
Grader digest covers ordered filename/NUL/bytes/NUL for `grade.sh`, `compare.sh`,
`graph_checks.py`, `schemas/scorecard.schema.json`. `graph_checks.grader_digest()`
computes it. Human approves dataset membership and candidate manifest before
runs. Existing JSONL cases retain their original corpus identity.

Grade writes `scorecard.json` matching the schema. Exit 0 means every check
passed. Malformed checks, missing raw evidence, invalid identity or dependency
failure produce infra_dependency and exit 1. Failed output JSON/path checks are
agent_quality. Null identity fields are permitted only to represent invalid
runs; compare always rejects missing identity. No exception text or raw output
is copied into scorecards.

Before/after directories each contain `manifest.json`:

```json
{
  "mode": "gate",
  "identity": {"model": "...", "prompt_hash": "...", "tool_contract_hash": "...", "dataset_hash": "...", "commit": "...", "artifact_digest": "...", "grader_digest": "..."},
  "cases": ["case-1"],
  "trials": ["1", "2", "3"],
  "trial_count": 3,
  "scorecards": ["case-1/1/scorecard.json", "case-1/2/scorecard.json", "case-1/3/scorecard.json"]
}
```

Declare all case×trial pairs, no duplicates or extras. Gate defaults trial_count
to 3. Baseline/candidate must have the same mode, case/trial set, dataset and
grader. Changed model/prompt/tool/code identities are allowed across improvement
runs, never within one run. A human-approved changed metric needs a newly graded
baseline; do not compare scores across graders. For the first gate, a human may
designate the candidate evidence as both inputs: all-pass and identity checks
still apply, without claiming improvement.

Held-out evidence directory contains `before/` and `after/` in this same format.
Its dataset hash may differ from public, but must match across the held-out
pair; all other identity fields must match the corresponding public candidate.
Use opaque case IDs and only scorecards, never prompts or traces. Humans own
the sealed evidence provenance; a digest does not prove who produced it.

Compare prints `improved`, `regressed`, or `unchanged`; any pass→fail outranks
gains. It returns 1 for regressions, incomplete/invalid evidence, identity gaps,
infra failures, or failed gates. A gate can print unchanged and still exit 1
when both sides fail. Diagnostics go to stderr. Improve/gate require held-out
evidence. Keep/drop also requires the critic report and human review; a script
exit 0 alone is not merge permission.

Reports: JSON with `role`, `status`, `identity`, `artifact_paths`,
`failure_class`, `reason`; reviewer adds `findings` and `human_sample`. Use
opaque IDs, relative evidence references, and sanitized reasons; no secrets or
PII. Missing measurements stay null. Append ledger JSON only after writers
stop: mode, decision, identities, scorecard/report digests, failure_class and
sanitized reason. Preserve every trial, flake and rejected candidate. Humans
own the definition of correct, held-out evidence, case acceptance and merge.

## Offline verification

Run `python3 v2/eval/test_graph_checks.py` and
`python3 .codex/hooks/test_graph_write_guard.py`. These use synthetic temporary
artifacts, not product-agent trials. Validate the skill frontmatter and TOMLs.
