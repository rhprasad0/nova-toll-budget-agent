# Private holdout workspace

**Work with Codex in a private VS Code workspace.** Codex leads authoring, review,
calibration, and evaluation; you make the review and spending decisions. The
connected repository session handles public tooling, policy activation, aggregate
import, and production delivery. GitHub's protected approvals remain your clicks.

The kit contains public tools and synthetic examples. Building and rehearsing it
does not author a real holdout, spend on models, activate policy, or qualify a
release. Those are later authorized steps.

## 1. Open the private workspace

Use an **x86 Linux workstation with Python 3.10+, Docker, Microsoft's native Linux
VS Code 1.138+ package with Dev
Containers, and working ARM64 binfmt/QEMU support**. Prepare these before
restricting network access. Native Codex handles the conversation; the separate
ARM64 Python 3.13 evaluator loads the delivered application unchanged.
The launcher installs the tested Dev Containers extension version, 0.469.0.
Use the native package's `code` command on `PATH`; repository Codex can prepare it
during host setup. The Snap launcher is unsupported for this isolated profile.

Ask the repository Codex session to use the `holdout-release` skill to build and
rehearse the reviewed transfer kit. Copy the complete packet to the private
workstation, preserving `transfer.json`, its checksums, and image archives. Do not
copy the repository, development cases, host Codex profile, connectors, or memory.

From the transferred directory, the host bootstrap is:

```sh
python3 holdout.py guide
```

In VS Code, select **Dev Containers: Attach to Running Container…**, choose
**tollchat-holdout-workspace**, and open the workspace's **Start/Resume Holdout**
task from `/workspace`. Keep the host launcher open. Choose the private Codex
model on first launch, then copy its subscription sign-in URL into your ordinary
host browser; automatic external HTTP links are disabled in the private editor.
Use the terminal conversation, Explorer, and the review
links Codex supplies in VS Code's integrated browser through its remote proxy.
This is the normal workflow; the command reference below is for diagnosis.

Private Codex subscription login and evaluator API access are separate. When
authorizing evaluation, enter `key` at the host launcher's prompt and supply the
API key privately there. It stays in launcher memory and is passed only to the
evaluator as `OPENAI_API_KEY`. Use an account/project whose traces the repository
session cannot access.
Do not put credentials in the exchange folder, packet, or conversation. Codex
usage is separate from the evaluator's $5 execution/$25 cumulative accounting.

The private workspace has no repository mount or Docker socket. Its bounded guide
can ask the host to perform fixed holdout actions; it cannot execute host shell
commands. Network access uses the reviewed role-specific proxy rules. The host
operator, desktop editor, native URI handlers, and reviewed code remain trusted.

## 2. Review every case batch and freeze

Tell private Codex to start or resume the holdout. It shows the current stage,
what it can do next, and the decision it needs from you. It authors independent
cases using only the public contract and teaching examples. Candidate bundles
and evaluation results remain unavailable during authoring.

Codex completes the full draft before asking you to approve ten-case batches.
Review **every case batch** in the local pages: scenario allocation, independence,
route plausibility, fixture arithmetic, references, actor behavior, and labels.
Use Explorer for the complete files. Any corpus edit invalidates all batch
approvals; finish corrections before reviewing every batch again. When all 100
cases are approved, explicitly approve **freeze**. The guide stops writable
authoring, validates and hashes the corpus, and continues with a read-only corpus.
Reconnect VS Code after that workspace restart and run **Start/Resume Holdout**.
Keep the frozen manifest unchanged; a correction requires a new reviewed identity.

## 3. Prepare and approve calibration

The guide now requests a candidate from the repository session. The fixed exchange
folder is **`~/Documents/private-holdout/exchange/`** on the private workstation:

| Handoff | Contents |
| --- | --- |
| Repository → `candidate/` | Exactly `release.zip`, `context.json`, `policy.json` |
| Repository → `policy.json` | The exact approved policy after the policy review |
| Private → `identities.json` | Only the holdout, evaluator, calibration SHA-256 digests |
| Private → `summary.json` | Only the validated release aggregate |

Ask the repository Codex session to prepare the packet in `exchange/candidate/`.
Tell private Codex it is ready; `import_candidate` takes
a private snapshot of those exact files. The evaluator checks the original ZIP,
manifest, inventory, and application package. It does not rebuild the candidate.
A pending policy is allowed for preparation.

Codex checks the persistent spending history and asks for explicit **preparation
authorization**. Carry forward earlier calibration/evaluation spending and unknown
usage; zero is valid only for an unused authorization. Preparation calibrates
judges against the references and rehearses each actor three times. It does not
measure candidate quality.

Review the flagged disagreements, invalid actors, and incomplete measurements;
all evidence remains available privately. Explicitly approve **calibration** only
after resolving the review. Codex records the decision against the exact evidence
and exports `identities.json`. Successful execution alone is not review approval.

## 4. Complete the policy roundtrip and score

Tell the repository session that `identities.json` is ready in the exchange.
Ask it to complete the reviewed policy/source changes and authorized activation. It verifies
actual IAM, protected environments, golden-reader access, bootstrap, and schema
prerequisites. The kit rehearsal alone establishes none of these.

**Choose the scored candidate after the final changes have completed development
delivery.** The repository session exports that candidate's exact original bundle
and six-field delivery identity. The preparation candidate may have an earlier
commit; calibration remains reusable when the frozen holdout, evaluator, evidence,
and review identities match. Keep the reviewed kit fixed during this roundtrip.

Repository Codex retains the earlier packet, writes the final one to
`exchange/candidate/`, and writes the approved policy to `exchange/policy.json`.
Tell private Codex to import them; `import_policy` reads that one policy file.
Importing verifies the artifact and policy structure and saves private snapshots.
After your explicit **scoring authorization**, the guide checks active identities,
calibration review, spending history, and approval time before starting paid calls.
Do not replace the candidate merely because `main` later advances.

After scoring, review the flagged failures, disagreements, invalid/incomplete
measurements, provenance, and accounting. Open any complete private evidence you
need. Explicit **final review approval** lets Codex render and export `summary.json`.
It retains failures and raw grades. Qualification requires **240/300 successful
trials with all 300 measured and valid**, known usage, and the spending limits;
approval cannot waive a failed gate. Emulated latency describes this benchmark,
not production latency.

Tell the repository session that `summary.json` is ready in the exchange. It
imports it and guides the real `golden-review`, preparation, and cutover approvals.
See [the production qualification contract](GOLDEN_RELEASE.md). Private reports,
reviews, backups, manifests, cases, and transcripts stay on the private workstation.

## Resume and interruptions

Reopen **Start/Resume Holdout** and ask Codex to continue. The guide uses existing
manifests, ledger, run directories, and reviews to discover progress; conversation
notes do not authorize work. If an evaluator is still running, reconnect to its
status. Never start another paid run or render a completion marker while it runs.

For interrupted or incomplete preparation, Codex presents the existing evidence
before asking explicitly to run paid preparation again. Complete, usable
preparation is reused. All runs and costs stay in the same history.

Unknown usage blocks further spending. Reviewing a run does not reconcile usage;
the guide has no accounting reconciliation action. One original scored execution
is allowed per artifact/holdout. After an infrastructure or actor-validity failure,
Ryan may explicitly authorize the existing one-replacement procedure after
reviewing the original evidence. Quality-only retries are forbidden. Keep the
same history and all attempts; deleting files does not reset authorization.

Policy has no maximum private evaluation age. The connected release still needs
its retained workflow artifacts (90 days), and a saved Terraform preparation plan
expires after 24 hours. Codex inspects existing GitHub runs and claims before any
recovery; it does not automatically retry imports, evaluations, or releases.

## Lower-level reference

From a reviewed repository checkout's `v2/` directory, these commands build the
public packet and export a verified preparation/final candidate respectively:

```sh
uv run --locked python -m eval.holdout_container.build --output eval/private/holdout-packet --images all
uv run --locked python -m scripts.holdout_candidate --development-run RUN_ID --output eval/private/candidate
```

The exporter refuses overwrite; its optional `--policy PATH` selects the reviewed
policy bytes. Output must be under ignored `v2/eval/private/` or at the fixed
exchange `candidate/`. Keep the packet's original ZIP unchanged.

On the private host, `holdout.py load`, `check`, `network-check`, and `preflight`
verify transfer/image identities, synthetic teaching inputs, permitted connectivity,
and ARM64 imports. An `exec format error` means host emulation needs repair.
`holdout.py --help` retains direct author/validate/evaluate and export commands for
diagnosis. Direct commands retain the same authorization and privacy requirements.
`export-private` creates a private backup; never send that backup to the repository.
