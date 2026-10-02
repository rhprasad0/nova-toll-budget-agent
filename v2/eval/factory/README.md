# Evaluation factory

This portable VS Code container authors and freezes **100 training, 50 private
holdout, and 10 public shadow cases**. It starts at 4.0.0 and wraps the pinned
golden evaluator without changing the public runner or application model/prompt.
Real case authoring, paid execution, hill-climbing integration, shadow CI, and
deployment are separate work. Experiment history stays in the
[journal](../EXPERIMENT_JOURNAL.md).

## Build and open

From `v2/` in a worktree:

```bash
python -m eval.factory.kit build --output eval/private/factory-kit
docker build -t tollchat-eval-factory eval/private/factory-kit
```

Open the **generated kit directory** in VS Code and choose **Reopen in Container**.
The devcontainer replaces the default repository bind mount with the persistent
`tollchat-factory-private` volume at `/private`. There is no Docker socket mount.
The [workspace mount configuration](https://github.com/devcontainers/spec/blob/main/docs/specs/devcontainerjson-reference.md)
is explicit. The kit can be copied to another host/account; it needs no repository.
The image contains Python 3.13, Git, a pinned uv, the existing dependency lock,
verified evaluator sources, schemas, and three historical teaching examples.
Teaching examples and synthetic smoke data are never fresh holdout cases.

In the container:

```bash
factory() { python -m eval.factory.factory "$@"; }
factory init
```

Author only in `/private/work/drafts/{training,holdout,shadow}/`, using
`cases.jsonl`, `fixtures/*.json`, `examples.json`, and `prompt-points.json`.
Shapes match the golden evaluator; see `examples/schemas.json` and
[factory agent instructions](AGENTS.md). Every case requires a passing reference;
the complete suite requires at least 20 labeled negative references. Validation
checks allocations, replay, arithmetic, known endpoints, timestamps, actor
boundaries, duplicate openings, equivalent fixture evidence, and split groups.
Human review must also check paraphrases and case novelty.

| Split | Current | Annual | Mixed |
| --- | ---: | ---: | ---: |
| Training | 40 | 55 | 5 |
| Holdout | 20 | 28 | 2 |
| Shadow | 4 | 5 | 1 |

`contract.json` gives the coverage-family allocations. Case numbers are local to
each split; case IDs are unique across the suite. Scenario groups and behavioral
pairs stay in one split. Private Git commits preserve all freezes and reviews.
Frozen inputs cannot be edited: increment the suite and changed split versions;
unchanged splits retain their versions/digests. Training/shadow changes do not
reset holdout reuse history.

## Freeze, calibrate, and review

```bash
factory freeze --inputs /private/work/drafts --suite 4.0.0
factory calibrate --suite 4.0.0 --budget-usd 25 \
  --authorization 'Ryan approved this calibration budget in <record>'
```

Only run the paid command after explicit budget authorization. Supply
`OPENAI_API_KEY` at runtime with a separate factory identity; do not put it in
work files. Credentials/authentication and Codex state belong outside `work`,
under `/private/agent-state/`. The container does not load deployed SSM secrets.
All calls use the existing reservation/usage accounting; unknown usage stops
further work. The budget is a per-command ceiling. Costs and interrupted attempts
remain in the ledger and private events.

Exactly one calibration evaluates **every authored reference** once across all
160 cases, then performs one scripted actor check per case. Review the full
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

Holdout trials run three times per case. Every headline retains **150 slots** and
50 cases; measured actor inconclusives count as unsuccessful slots. Missing,
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
exports successful trials/150, cases passing all three/50, the zero/one/two/three
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
docker volume create tollchat-factory-smoke
docker run --rm --network none --mount type=volume,source=tollchat-factory-smoke,target=/private \
  tollchat-eval-factory python -m eval.factory.smoke --directory /private
docker create --name factory-backup-copy --mount type=volume,source=tollchat-factory-smoke,target=/private tollchat-eval-factory
docker cp factory-backup-copy:/private/backup.tar.gz ./backup.tar.gz
docker rm factory-backup-copy
docker volume create tollchat-factory-restore
docker create --name factory-restore --network none --mount type=volume,source=tollchat-factory-restore,target=/private \
  tollchat-eval-factory python -m eval.factory.smoke --directory /private --restore /private/backup.tar.gz
docker cp ./backup.tar.gz factory-restore:/private/backup.tar.gz
docker start -a factory-restore
docker rm factory-restore
```

The smoke uses synthetic cases/labels/reviews and mocked application trials;
it never creates release-ready evidence or spends money. Focused regressions run
from the repo with `pytest -q tests/test_eval_factory.py`.
