---
name: holdout-release
description: Guide the connected repository side of TollChat private holdout preparation, aggregate import, and guarded production delivery. Use for holdout handoffs, activation, release readiness, and resuming these operations; private authoring and detailed evidence stay in the separate private workspace.
---

# Holdout and release guide

Do the mechanical work and explain the next human decision. Identify the current
stage from source, permitted exchange files, and actual GitHub state. Use
[the private workspace guide](../../../v2/eval/HOLDOUT_SETUP.md) for the human
journey and [the qualification contract](../../../v2/eval/GOLDEN_RELEASE.md) for
admission. This skill supplies no spending, PR, infrastructure, publication, or
deployment authorization; use the user's existing authorization for each action.

## Privacy and handoffs

The repository session may prepare public tooling/candidate inputs and read only
the outgoing `identities.json` and `summary.json`. Never inspect private Docker
volumes, auth, corpus, case hashes, reviews, reports, transcripts, or model traces.
Do not ask the human to paste private evidence here. Keep granular public-side
working output in ignored `v2/eval/private/`; publish only requested aggregate
findings under the repository's existing documentation rules.

The fixed exchange folder on the private workstation is
`~/Documents/private-holdout/exchange/`. The private guide imports exactly
`candidate/` and `policy.json`; it exports only `identities.json` and `summary.json`.
Keep candidate material outside the private authoring workspace until freeze.
Use the guide's bounded exports, not a private backup or an arbitrary file copy.

## Prepare the kit and private handoff

From a reviewed checkout's `v2/` directory:

```sh
uv run --locked python -m eval.holdout_container.build --output eval/private/holdout-packet --images all
```

Run the relevant synthetic checks. Explain the transfer directory and the one
host bootstrap command, `python3 holdout.py guide`. Help the human attach VS Code
to `tollchat-holdout-workspace` and start its **Start/Resume Holdout** task.
Prepare the host prerequisites from HOLDOUT_SETUP.md, including the native Linux
VS Code package and its `code` command on `PATH`; the isolated profile does not
support the Snap launcher.
Model selection and subscription login belong in that private session.

The private guide completes the draft, then leads every ten-case batch review,
explicit freeze, authorized preparation, and calibration review. Any corpus edit
invalidates all batch approvals. Do not infer approvals from completed
files or successful commands. When it requests a preparation candidate, discover
the intended successful development delivery and export it:

```sh
uv run --locked python -m scripts.holdout_candidate --development-run RUN_ID --output ~/Documents/private-holdout/exchange/candidate
```

The output contains the **original** `release.zip`, six-field `context.json`, and
`policy.json`. It is published atomically and refuses overwrite. Write it to the
fixed exchange only when the private guide requests it. Retain an earlier input
packet under ignored `eval/private/` before publishing its replacement; never
overwrite private exports. The human only switches sessions and announces that
the handoff is ready; do not ask them to assemble files or copy digests. A
pending policy is allowed for preparation. The preparation candidate does not
become the scored release candidate automatically.

## Activate policy and choose the scored candidate

- Validate `identities.json` as exactly the three aggregate holdout, evaluator,
  and calibration SHA-256 digests. Populate the reviewed policy and its approval
  record through the normal worktree/PR path. Retain the exact approved policy;
  the private guide imports it from exchange `policy.json`.
- Complete authorized source and infrastructure activation using
  [GOLDEN_RELEASE.md](../../../v2/eval/GOLDEN_RELEASE.md). Verify actual reviewer
  protections, golden IAM/read access, production bootstrap, and schema
  prerequisites; configuration does not prove activation. Keep required GitHub
  approvals as human clicks. After relevant pipeline/IAM changes and before
  release publication, run `gh workflow run v2-golden-read.yml --ref main` and
  confirm the [reader identity check](../../../.github/workflows/v2-golden-read.yml)
  succeeds. This checks OIDC role assumption; verify evidence-read permissions
  separately.
- Wait for successful development delivery of the final policy/source changes.
  Select and export that exact final candidate using `holdout_candidate`, then
  hand it to the private guide with the approved policy. Calibration may be
  reused when the frozen holdout/evaluator/review identities still match.
  Never silently replace a scored bundle when `main` advances.
- The private guide obtains explicit scoring authorization and final review,
  retaining all spending and failed/incomplete attempts. The repository receives
  only the validated aggregate `summary.json`.

## Import and deliver

Use `golden_gate`'s strict validators for the aggregate and the existing
`golden_release.resolve()` provenance resolver for the development identity.
`golden_release.prepare/approve` run inside their trusted GitHub workflow; do not
call them locally to manufacture admission. When import is authorized, dispatch
`v2-golden-evaluation.yml` on `main` with the exact development run and aggregate.
Follow the real run, summarize its review packet, and give the human the actual
`golden-review` approval link. Approval records valid failures too; it cannot
waive the qualification threshold.

Before authorized publication, follow
[the production preflight](../../../v2/manual-releases/README.md): exact candidate,
schema readiness, retained evidence, bootstrap, stable unused tag. Prepare the
concrete release for the user. Follow the published release's actual claim and
workflow; summarize the saved plan for the protected `production` review. After
candidate validation, present preparation evidence and the separate
`production-cutover` link. Mention any additional `production` approval GitHub
requests. Report deployment and recovery outcomes separately.

## Resume without repeating work

Rediscover run IDs, attempts, approvals, claims, artifact identities, and outcomes
from GitHub. Conversation notes are pointers, not evidence. Pending approval means
wait and explain that decision; do not dispatch another operation.

- Never rerun private scoring automatically. Unknown usage and incomplete runs
  return to the private guide. Only the existing explicit validity-replacement
  procedure can authorize a replacement; quality retries remain forbidden.
  Incomplete preparation may be repeated only after its evidence is presented
  and the human explicitly authorizes the paid work; reuse complete preparation.
  Review does not clear unknown usage, which remains a hard stop.
- Golden workflow reruns are rejected. Transport/publication recovery uses a new
  import of identical evidence after the earlier import completes and requires
  fresh protected approval. Changed gate code can invalidate a receipt; inspect
  whether the same report remains admissible before importing it again.
- Production reruns are rejected. A durable claim, interrupted delivery, expired
  plan, or changed state requires inspecting the existing evidence and the
  [protected recovery procedure](../../../v2/runbooks/blue-green-deployments.md),
  never an automatic new release. The preparation plan expires after 24 hours;
  required workflow artifacts last 90 days. Private evaluation has no age limit.
- A build/synthetic rehearsal request ends with the verified kit and handoff.
  Real private work and repository-side activation require the user's authority
  for those operations.
