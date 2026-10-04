# Evaluation factory

Log into Codex inside this portable VS Code container and ask it to author and
validate **50 training, 25 private holdout, and 10 public shadow cases**. With
your explicit budget, the agent can also freeze the suite and run calibration
and candidate evaluations through the existing factory commands. You retain
review, holdout-reuse, and release decisions. The suite starts at 4.0.0 and wraps
the pinned golden evaluator without changing the public runner or application
model/prompt. The kit contains teaching examples; the real suite still needs
authoring. Hill-climbing integration, shadow CI, and deployment remain separate
work. Experiment history stays in the
[journal](../EXPERIMENT_JOURNAL.md).
Read the [authoring guide](AUTHORING.md) before planning coverage, scenarios,
actor exchanges and independently labeled references.

## Build and open

From `v2/` in a worktree:

```bash
python -m eval.factory.kit build --output eval/private/factory-kit
docker build -t tollchat-eval-factory eval/private/factory-kit
```

In VS Code, choose **File → Open Folder**, open the generated
`v2/eval/private/factory-kit` directory in that worktree, then choose
**Dev Containers: Reopen in Container**. The source directory `v2/eval/factory`
does not contain the generated `runtime/` build context. Opening it directly
stops before the image build and prints the kit-generation command. If you see
`COPY runtime ... file does not exist`, generate the kit and open its directory.

The devcontainer replaces the default repository bind mount with the persistent
`tollchat-factory-private` volume at `/private`. There is no Docker socket mount.
The [workspace mount configuration](https://github.com/devcontainers/spec/blob/main/docs/specs/devcontainerjson-reference.md)
is explicit. The kit can be copied to another host/account; it needs no repository.
The image contains Python 3.13, Git, a pinned uv, checksum-verified Codex CLI
0.160.0 (the complete package, including `codex-code-mode-host`) and AWS CLI
2.36.32 for AMD64/ARM64, PostgreSQL client tools, the existing
dependency lock, verified evaluator sources, database/tool schemas, and three
historical teaching examples. Tailscale 1.102.4 runs without root or a TUN device;
the PostgreSQL SOCKS wrapper reaches the development route even with rootless
Docker. See
[development database authoring](DATABASE.md) for login, transport, and bounded
read-only queries.
Teaching examples and synthetic smoke data are never fresh holdout cases.

## Log in, enter the evaluation key, and start the agent

The image already places the virtual environment on `PATH`; no activation
command is needed. Python terminal auto-activation is disabled, including for
the default `/bin/sh` terminal.

In the container terminal, initialize once, then sign into your factory Codex
account and enter the separate evaluation API key:

```bash
factory init
codex login --device-auth
codex login status
factory set-api-key
codex
```

Enable device code login in your ChatGPT security settings (or ask your workspace
admin), open the printed link in your host browser, and enter the one-time code.
The browser does not need to run inside the container. See the official
[Codex authentication guide](https://developers.openai.com/codex/auth/).

If an older image reports `package contains a directory link`, use
`codex --no-daemon` for the current session. Regenerate the kit and rebuild
the container to pick up the separate Codex package directory.

Use the container's Codex VS Code extension instead if you prefer its interface;
ensure it runs in the container with `/private/work` as its workspace.

Codex defaults to **YOLO mode inside this container**. The image's
`/etc/codex/config.toml` sets `approval_policy = "never"` and
`sandbox_mode = "danger-full-access"`, so plain `codex` can use container files
and networking without command approval prompts. User settings and explicit CLI
flags can override these defaults; see the official
[configuration precedence](https://learn.chatgpt.com/docs/config-file/config-basic).
Paid evaluations still require your explicit budget and authorization record.

For optional Codex sandboxing, the image includes bubblewrap. The devcontainer uses
the bundled `.devcontainer/seccomp.json`, based on
[Docker's default profile at 2ceae35](https://github.com/moby/profiles/blob/2ceae35d351c156cb5a8efc0fdc4a08cf94569d8/seccomp/default.json).
It retains default syscall restrictions and adds only user-namespace creation
(`clone`/`unshare` with `CLONE_NEWUSER`) and the three mount operations bubblewrap
needs inside that namespace. The non-root user, dropped capabilities, and
`no-new-privileges` remain. Choosing `codex --sandbox workspace-write` requires
the host to permit unprivileged user namespaces.

Codex authentication persists under `/private/agent-state/codex/`, separate from
your application workspace and memories. The hidden key prompt writes an
owner-only file at `/private/agent-state/openai-api-key`. Paid factory commands
load it directly; it is not exported into Codex's environment or stored in
`/private/work`, Git, reports, kits, or backups. Runtime `OPENAI_API_KEY` explicitly
overrides the saved key. Run `factory set-api-key` again to replace it. Reopening
or rebuilding with the same private volume preserves login and the saved key.
After a backup restore into a fresh volume, log in and enter the key again.
ChatGPT login pays for Codex access according to your account; evaluation model
calls use the separate API key and authorized factory budgets.

For database-grounded authoring, log this container into Tailscale and configure
`nova-toll-dev` AWS SSO following [DATABASE.md](DATABASE.md). Verify the fixed
development reader before authoring. Tailscale state, AWS configuration, and
login caches persist only under `/private/agent-state/`; no host credential
directory or Tailscale socket is mounted. Database reads
are authoring inputs, and eval runs continue using frozen fixture replay.

Start Codex in `/private/work` and give it this prompt:

> Follow AGENTS.md and the frozen factory contract. Author a fresh 4.0.0 suite
> with 50 training, 25 private holdout, and 10 public shadow cases. First read
> /opt/factory/v2/eval/factory/AUTHORING.md, plan its coverage dimensions across
> all splits while retaining the contract's family allocations, then read
> /opt/factory/v2/eval/factory/DATABASE.md and its committed schema references.
> Use nova-toll-dev, account 903859731897, and pricing_reader_development to
> inspect only bounded development route/pricing data through the verified
> Tailscale SOCKS route using DATABASE.md's PostgreSQL wrapper. If login, reader
> access, or connectivity is missing, tell me
> which setup step is needed; do not change permissions or substitute another
> database. Use these observations to author realistic synthetic fixtures,
> recording relevant retrieval times and provenance without credentials or
> connection details. Plan coverage and scenario groups, generate reconciled
> fixtures and complete passing
> references plus valid wording variants, at least 20 independently labeled
> negative references and actor-invalid controls. Use five-turn actor budgets,
> including the opening, and derive minimum turns from necessary exchanges.
> Keep related scenarios and canonical route pairs in one split; distribute
> facilities/directions and dynamic/fixed pricing across splits. Then run factory
> validate and repair drafts. Review novelty and split leakage, summarize the
> aggregate coverage and limitations, retain a complete private case/reference
> assessment matrix outside the split inputs, and freeze the suite. Ask for an explicit budget
> before paid calibration or evaluation. Prepare review evidence for me and
> retain my holdout-reuse and release decisions. Do not read credentials or
> application repository memories. Keep all database reads in authoring; freeze
> their evidence before calibration and use fixture replay for every eval run.

When updating an already initialized factory, use this prompt in a new Codex
session after rebuilding the container. The private volume retains its existing
`AGENTS.md`; reconcile it with the new image's factory instructions, preserving
any local edits. Do not rerun `factory init` or reset private history.
This resumes that factory's history. For a fresh real run after exposed review
material, use the new-volume procedure below instead.

No paid budget is implied by this prompt. When ready, authorize a particular
calibration/evaluation command with a dollar ceiling and record; the agent uses
that evidence with `--budget-usd` and `--authorization`. Review the full calibration
report before approving it. Hand over a candidate snapshot explicitly, then
review the blinded audit before revealing its scores. The agent may prepare
review files, but must never invent your decisions or claim human inspection.

Author only in `/private/work/drafts/{training,holdout,shadow}/`, using
`cases.jsonl`, `fixtures/*.json`, `examples.json`, and `prompt-points.json`.
Shapes match the golden evaluator; see `examples/schemas.json` and
[factory agent instructions](AGENTS.md). Every case requires a passing reference;
the complete suite requires at least 20 labeled negative references. Validation
checks allocations, replay, arithmetic, known endpoints, timestamps, actor
boundaries, five-turn budgets (including the opening), duplicate openings,
equivalent fixture evidence, split groups and canonical route pairs across
current/outbound/return legs. Reversed legs and role/direction variants count as
reuse, including the I-495 180/181 boundary; within-split reuse is allowed.
I-95 counterparts use explicit catalog aliases; numeric stems alone do not
establish equivalence. I-495's 183/184 boundary also shares one identity.
Human review must also check semantic independence and reference labels.

Validate drafts without freezing them or calling models:

```bash
factory validate --inputs /private/work/drafts
```

| Split | Current | Annual | Mixed |
| --- | ---: | ---: | ---: |
| Training | 20 | 27 | 3 |
| Holdout | 10 | 14 | 1 |
| Shadow | 4 | 5 | 1 |

`contract.json` gives the coverage-family allocations. Case numbers are local to
each split; case IDs are unique across the suite. Scenario groups and behavioral
pairs stay in one split. Private Git commits preserve all freezes and reviews.
Frozen inputs cannot be edited: increment the suite and changed split versions;
unchanged splits retain their versions/digests. Training/shadow changes do not
reset holdout reuse history.

## Fresh real run after exposed review material

**Use a new private volume and a new authoring session.** Recreating or rebuilding
the container preserves its existing named volume, including drafts, history,
login state and memories. Docker volumes
[persist beyond a container's lifecycle](https://docs.docker.com/engine/storage/volumes/).
Keep the exposed packet and its assessment matrix as private, retired review
material in the old volume or ignored `v2/eval/private/`; do not use them to seed
the new suite or claim fresh holdout performance.

From `v2/` in the revised worktree, build a new portable kit directory and change
its existing mount setting to a unique volume name before opening it in VS Code:

```bash
python -m eval.factory.kit build --output eval/private/factory-kit-fresh
python - <<'PY'
import json
import uuid
from pathlib import Path

path = Path("eval/private/factory-kit-fresh/.devcontainer/devcontainer.json")
config = json.loads(path.read_text())
volume = "tollchat-factory-private-" + uuid.uuid4().hex
config["workspaceMount"] = f"source={volume},target=/private,type=volume"
path.write_text(json.dumps(config, indent=2) + "\n")
print("Fresh private volume:", volume)
PY
```

Use another output directory if that kit directory already exists. Open the
generated kit in VS Code and choose **Reopen in Container**; Docker creates the
new volume on first use. Run `factory init` once in the new `/private/work`, log
in independently, and follow the setup and authoring prompt above. Enter the
evaluation key only when needed for explicitly budgeted paid work.

Carry only the revised generic factory instructions and authoring guide into
the clean session. Do not restore an old backup, copy drafts/references/review
evidence, import old Codex history or memories, or mount the application repo.
The bundled historical examples remain teaching material. Start with a new
coverage plan and independent scenarios. Paid calibration and real generation
are separate from tooling smoke checks; this setup does not authorize model
calls or establish application performance.

## Freeze, calibrate, and review

```bash
factory freeze --inputs /private/work/drafts --suite 4.0.0
factory calibrate --suite 4.0.0 --budget-usd 25 \
  --authorization 'Ryan approved this calibration budget in <record>'
```

Only run the paid command after explicit budget authorization. Use the saved
evaluation key from `factory set-api-key`, or explicitly supply `OPENAI_API_KEY`
at runtime with a separate factory identity; do not put it in work files.
Credentials/authentication and Codex state belong outside `work`,
under `/private/agent-state/`. The container does not load deployed SSM secrets.
All calls use the existing reservation/usage accounting; unknown usage stops
further work. The budget is a per-command ceiling. Costs and interrupted attempts
remain in the ledger and private events.

Exactly one calibration evaluates **every authored reference** once across all
85 cases, then performs one scripted actor check per case. Review the full
private `suites/4.0.0/calibration/report.json`, including incomplete measurements
and label/actor disagreements. Submit a JSON review:

```json
{
  "evidence_sha256": "<calibration evidence digest>",
  "reviewer": "Ryan",
  "evidence": "<review record and findings>",
  "dispositions": [
    {"id": "<reference or actor-check ID>", "dimension": "outcome",
     "material": false, "disposition": "accepted_limitation",
     "evidence": "<reason>"}
  ]
}
```

Use `[]` when there are no disagreements. Every disagreement needs a disposition.
Dimensions are `outcome`, `grounding`, `rules`, or `actor_validity`; dispositions
are `accepted_limitation`, `grading_defect`, or `actor_defect`. Material defects
block approval; repairs require a new version and calibration. Reviews identify
the real reviewer, never claim human inspection that did not occur.

```bash
factory review-calibration --suite 4.0.0 --review /private/review.json
factory export-suite --suite 4.0.0 --output /private/public-suite.zip
```

The export allowlist contains training/shadow inputs and their calibration/actor
evidence plus the shared evaluator/calibration identity. It contains no holdout
inputs, examples, case names, review findings, or transcripts.

## Source handoff and holdout

On the application host, from `v2/`:

```bash
python -m eval.factory.kit snapshot --source /path/to/clean/checkout \
  --output eval/private/candidate.zip
```

The checkout must be clean and committed. Only the specified application Python
files, SOP, project file, and lock enter the handoff, with commit and file hashes;
no Git history or eval inputs. Transfer it with `docker cp` or another explicit
handoff. Accept only reviewed source; worker isolation is procedural and is not
a sandbox for malicious code. Dependencies must match the frozen lock; the worker
must retain the frozen Luna model, output/reasoning settings, and cache configuration.

```bash
factory import-source --snapshot /private/candidate.zip
factory evaluate --suite 4.0.0 --source <source-sha256> --role candidate \
  --budget-usd 25 --authorization '<explicit authorized budget record>'
```

Holdout trials run three times per case. Every headline retains **75 slots** and
25 cases; measured actor inconclusives count as unsuccessful slots. Missing,
duplicate, or incompletely measured slots cannot support a comparison. No retries
replace failures. The CLI prints the run ID; detailed reports remain private.

## Blinded audit and feedback

```bash
factory audit --run <run-id>
```

Read only `runs/<run-id>/audit.json` during initial review. It includes the first
successful and first scored failing trial in every coverage family, ordered by
`(case_id, trial)`, plus every actor-inconclusive trial, deduplicated. The view
contains case requirements, delivered conversation, actual tool evidence, and
actor controls, with no judge verdicts, selection reasons, or application identity.
The private volume also contains unblinded files; do not open them before recording
assessments. Local separation remains procedural.

Record a JSON assessment with `audit_sha256`, `reviewer`, `evidence`, and `items`.
Each item contains its `token`, boolean `outcome`, `grounding`, `rules`,
`actor_validity` (`valid`, `invalid`, `uncertain`), and supporting `evidence`.
Application scores are `null` when your actor assessment is invalid or uncertain.

```bash
factory assess --run <run-id> --review /private/assessments.json
```

This records immutable assessments, then creates `audit-reveal.json` with original
scores, source identity, and disagreements. Submit a disposition JSON with
`reveal_sha256`, `reviewer`, `evidence`, and `dispositions` in the calibration format;
use the revealed item token as `id`. Original scores are never revised.

```bash
factory disposition --run <run-id> --review /private/dispositions.json
factory export-report --run <run-id> --output /private/aggregate.json \
  --recipient Ryan --purpose 'Release evidence review'
factory disclose --run <run-id> --payload-sha256 <digest-of-manually-shared-payload> \
  --recipient Ryan --purpose 'Manual feedback'
```

Report exports record payload digest, recipient, purpose, and timestamp before
publishing bytes. Transcripts, case differences, and audit findings stay private.
The append-only hash-chained ledger retains its committed Git checkpoint and
tracks started/finished attempts, costs,
source/suite/calibration identity, and feedback. Incomplete or blocked evidence
can be exported, clearly marked as not release ready. There is no numerical gate.

After the first attempt against a holdout digest, **Ryan must approve each next
use**, bound to its exact source and current ledger:

```bash
factory approve-reuse --suite 4.0.0 --source <next-source-sha256> \
  --reviewer Ryan --evidence '<approval after reviewing the current ledger>'
```

Run the approved next evaluation immediately. Any intervening disclosure or
ledger event invalidates the approval. Even aborted attempts consume that use.
There is no automatic attempt cap; holdout renewal remains Ryan's decision.

## Optional incumbent

Import the incumbent through the same source handoff and evaluate with
`--role incumbent`. Evaluate it once per frozen comparison contract; audit it
using the same workflow. After approval, reuse that report for compatible later
candidates. Each new candidate still needs holdout reuse approval.

```bash
factory export-report --run <candidate-run> --incumbent <incumbent-run> \
  --output /private/comparison.json --recipient Ryan --purpose 'Release comparison'
```

Compatible reports share the exact holdout, suite, calibration and review,
evaluator, lock, installed dependency versions, Python/runtime architecture,
settings, and three-trial budget. Comparison
exports successful trials/75, cases passing all three/25, the zero/one/two/three
success histogram, aggregate improvements/regressions, paired case score deltas,
and deterministic scenario-group bootstrap 95% intervals. Measured inconclusives
remain unsuccessful; there are no excluded cases. Individual differences stay in
private `runs/<candidate>/comparison-<incumbent>.json`. Without an incumbent, the
same command produces a standalone report.
Release decisions remain manual.

## Backup and credential-free checks

```bash
factory backup --archive /private/factory-backup.tar.gz
factory restore --archive /private/factory-backup.tar.gz
```

Restore into a **fresh work directory/volume**, never over existing history. Keep
the matching kit/image with each backup. Changed evaluator/runtime identities
require a new version and calibration. Backups
contain private work/history only, excluding `/private/agent-state/`, runtime
credentials, authentication, and editor state. Transfer archives privately using
`docker cp`; they contain holdout content. Reauthenticate independently after a
restore. Never store credentials in private work or source snapshots.

From the generated kit on the host, run the complete smoke and restore in two
fresh volumes, with networking disabled:

```bash
docker run --rm --network none --cap-drop=ALL --security-opt=no-new-privileges \
  --security-opt=seccomp=.devcontainer/seccomp.json \
  tollchat-eval-factory codex sandbox -c 'sandbox_mode="workspace-write"' \
  timeout 20s python -m eval.factory.container_check
docker volume create tollchat-factory-smoke
docker run --rm --network none --mount type=volume,source=tollchat-factory-smoke,target=/private \
  --cap-drop=ALL --security-opt=no-new-privileges --security-opt=seccomp=.devcontainer/seccomp.json \
  tollchat-eval-factory python -m eval.factory.smoke --directory /private
docker create --name factory-backup-copy --mount type=volume,source=tollchat-factory-smoke,target=/private tollchat-eval-factory
docker cp factory-backup-copy:/private/backup.tar.gz ./backup.tar.gz
docker rm factory-backup-copy
docker volume create tollchat-factory-restore
docker create --name factory-restore --network none --mount type=volume,source=tollchat-factory-restore,target=/private \
  --cap-drop=ALL --security-opt=no-new-privileges --security-opt=seccomp=.devcontainer/seccomp.json \
  tollchat-eval-factory python -m eval.factory.smoke --directory /private --restore /private/backup.tar.gz
docker cp ./backup.tar.gz factory-restore:/private/backup.tar.gz
docker start -a factory-restore
docker rm factory-restore
```

The smoke uses synthetic cases/labels/reviews and mocked application trials;
it never creates release-ready evidence or spends money. Focused regressions run
from the repo with `pytest -q tests/test_eval_factory.py`.
