# Private holdout workstation

Use an **x86 Linux host with Python 3.10+, Docker, and working ARM64
binfmt/QEMU support**. Run the packet from a directory outside the repository.
The containers isolate the author from repository files and host Codex state;
the host operator remains trusted and can access Docker volumes. Keep private
cases and credentials out of repository sessions. Prepare Docker and emulation
before restricting its network.
The author runs natively; the evaluator runs ARM64 Python 3.13 to load the delivered
application unchanged. Emulated latency is useful for this benchmark, not a
production latency prediction.

This guide prepares the workflow. Subscription authoring, paid calibration,
evaluation, policy approval, and deployment each require the operator's existing
authorization.
No real holdout or production qualification is included in the public packet.

## 1. Build and transfer

On the repository machine, from a reviewed checkout's `v2/` directory:

```sh
uv run --locked python -m eval.holdout_container.build \
  --output eval/private/holdout-packet --images all
```

The output contains `authoring-kit.zip`, three image archives, `holdout.py`, this
guide, and `transfer.json` with checksums and immutable image IDs. Keep the whole
directory together. Its build needs network access; loading it does not. Rebuild
after any change to exported sources. Preserve the original export for the run.

Copy the complete directory to the private host, outside the repository. **Keep
the candidate bundle away from the author until the 100 cases have been reviewed
and frozen.** Do not copy the repository, development runs, host Codex profile,
connectors, or memory.

From the transferred directory:

```sh
python3 holdout.py load
python3 holdout.py check
python3 holdout.py preflight
python3 holdout.py network-check
```

`load` verifies checksums and image IDs; every later command checks IDs again.
`check` validates only synthetic teaching files and the disabled Codex integrations.
`network-check` checks both proxy policies with unauthenticated TLS connections
and verifies repository, package, cross-policy, and direct outbound access are
denied. It makes no inference calls and mounts no login credentials.
`preflight` must confirm ARM64 Python 3.13 and evaluator imports. An `exec format
error` means the host's ARM64 emulation is missing; fix that before proceeding.

The launcher gives online containers only an internal Docker network and a Squid
proxy. Author/login sessions can reach only `auth.openai.com:443` and
`chatgpt.com:443`; evaluator sessions can reach only `api.openai.com:443`.
Use a host firewall consistent with these restrictions. The containers have no
Docker socket, host profile, or repository
mount. This is reviewed-code isolation; the host operator remains trusted.

## 2. Author, review, and freeze privately

Codex is installed in the author image. Authoring uses your ChatGPT subscription;
the launcher never passes an API key to the author and has no API fallback.
Enable device-code login in your ChatGPT security settings (or through your
workspace administrator), then run on the host:

```sh
python3 holdout.py login
```

Open the printed sign-in link in your browser and enter its one-time code. Use
an account/workspace whose authoring content is inaccessible to the repository
agent. See the [Codex authentication guide](https://developers.openai.com/codex/auth).
Choose a model available through your subscription, then start:

```sh
python3 holdout.py author --model YOUR_AUTHOR_MODEL
python3 holdout.py validate
```

The author reads `/opt/kit/START_HERE.md`, `/opt/kit/public/`, and teaching examples.
It writes new cases to `/private/corpus` and notes to `/private/review`. Dependencies
are already installed; package downloads are blocked. Each invocation has fresh
Codex configuration/history; files persist in `tollchat-holdout-corpus`.
Only the login credentials persist in the separate `tollchat-holdout-auth` volume.
This volume is never mounted into evaluation, validation, or export commands.
One author/login/logout session can use it at a time. Expired sign-in requires
`python3 holdout.py login` again. To remove saved credentials without deleting
cases or results, run `python3 holdout.py logout`. Private backups exclude login
credentials; sign in again when moving to a new host.
Give a follow-up prompt as the optional final argument to `author` when needed.

Ryan reviews the scenario allocation, independence, route plausibility, fixture
arithmetic, references, actor behavior, and labels using the authoring checklist.
To inspect files on the private host, export a new private backup directory:

```sh
python3 holdout.py export-private private-review-001
```

The backup has `authoring/` and `evaluation/`. Keep it on the private machine.
After review:

```sh
python3 holdout.py validate --final
python3 holdout.py export-private private-frozen-001
python3 -c 'import json; print(json.load(open("private-frozen-001/authoring/corpus/manifest.json"))["holdout_sha256"])'
```

Final validation creates `/private/corpus/manifest.json`; the last command prints
only its aggregate `holdout_sha256`. The manifest stays private. Its `review_status: pending` is a
fixed validator marker; human approval belongs in separate notes and the release
policy. Do not edit the frozen manifest. Correcting frozen inputs requires a new
reviewed corpus identity, retaining the original privately.

## 3. Introduce the candidate and prepare the evaluator

Only after freeze, transfer a separate input directory containing **exactly**:

| File | Source |
| --- | --- |
| `release.zip` | Immutable successful development release artifact |
| `context.json` | Exact candidate, artifact ID/digest, delivery run/attempt/deployment |
| `policy.json` | Reviewed policy 4 file; pending identities are allowed during preparation |

The packet's candidate handoff must identify all six fields in `context.json`.
The evaluator checks the ZIP digest, release manifest, inventory, and application
package before spending. It does not rebuild or patch the delivered application.
Use an absolute path for this directory below; it mounts read-only at `/input`.

Record the evaluator identity and initialize the persistent spending ledger once:

```sh
python3 holdout.py evaluate -- identity
python3 holdout.py evaluate -- init-history --history /output/history.json \
  --prior-cost-usd 0 --prior-unknown-usage false
```

Use zero only for a genuinely unused evaluation authorization. Carry earlier
evaluation/calibration spending and unknown usage when applicable. The ledger
refuses overwrites and locks concurrent runs. Keep its volume and every recorded
run; deleting them does not reset the spending authorization. Authoring Codex
usage is separate from the evaluator's model-call ledger.

Once private model spending is authorized, set `OPENAI_API_KEY` privately on the
operator host using the private evaluation account/project. Only evaluator
`prepare` and `run` receive it; the key is never saved in the packet. Preparation
includes paid calibration and actor checks. Then run:

```sh
python3 holdout.py evaluate --inputs /ABSOLUTE/PATH/candidate -- prepare \
  --corpus /private/corpus --bundle /input/release.zip \
  --context /input/context.json --policy /input/policy.json \
  --output /output/prep-001 --history /output/history.json
python3 holdout.py export-report --run prep-001 preparation-report.json
```

Preparation calibrates judges against every supplied reference and rehearses
actors three times per case. It does not measure candidate quality. Review
disagreements and all incomplete/invalid measurements privately; `complete: true`
alone is not semantic approval. The $5 execution and $25 cumulative ceilings
include preparation and failed calls. Unknown usage blocks further paid calls.

Create `calibration-review.json` on the private host after Ryan's review:

```json
{
  "status": "approved",
  "evidence_sha256": "COPY_FROM_PREPARATION_REPORT",
  "reviewer": "Ryan",
  "evidence": "Describe the private review, disagreements, and decision."
}
```

```sh
python3 holdout.py import-review calibration-review.json
python3 holdout.py evaluate -- render --output /output/prep-001 \
  --history /output/history.json --review /output/reviews/calibration-review.json
```

The command prints the approved `calibration_sha256`. Return **only the three
aggregate identity digests** (holdout, evaluator, calibration) for policy review.
Follow `GOLDEN_RELEASE.md` in the connected repository to approve policy 4, ship
the workflow, apply the separate foundation IAM change, and verify protected
`golden-review`. Transfer the exact approved policy back as `candidate/policy.json`
before evaluating the candidate.

## 4. Evaluate and review the frozen candidate

After the policy approval and paid-run authorization:

```sh
python3 holdout.py evaluate --inputs /ABSOLUTE/PATH/candidate -- run \
  --corpus /private/corpus --bundle /input/release.zip \
  --context /input/context.json --policy /input/policy.json \
  --output /output/run-001 --history /output/history.json \
  --calibration /output/prep-001 \
  --calibration-review /output/reviews/calibration-review.json
python3 holdout.py export-report --run run-001 candidate-report.json
python3 holdout.py export-private private-review-002
```

Review the complete private evidence under `evaluation/run-001/`, including
`events.jsonl`, against the frozen corpus and references. Review provenance,
grading, actor validity, spending, and completeness. Preserve failures and raw
grades; do not change cases or select a better quality retry.

Create `candidate-review.json` with the same four review fields above, using
`candidate-report.json`'s evidence digest and the actual private review decision.
Then:

```sh
python3 holdout.py import-review candidate-review.json
python3 holdout.py evaluate -- render --output /output/run-001 \
  --history /output/history.json --review /output/reviews/candidate-review.json
python3 holdout.py export-summary --run run-001 summary.json
```

Only `summary.json` returns to the connected release operator. It contains
aggregate counts, timing, cost, uncertainty, and opaque identities. Private
reports, reviews, backups, manifests, cases, and transcripts stay private.
The protected workflow archives valid results and qualifies only **240/300 or
better with all 300 trials valid and measured**, within the spending limits.
The qualification policy has no maximum evaluation age; evidence remains bound
to the exact artifact, active policy, and approval. Release verification requires
workflow artifacts retained for 90 days; see [GOLDEN_RELEASE.md](GOLDEN_RELEASE.md).
Approval cannot waive failures.

There is one original execution per artifact/holdout. For an infrastructure or
actor-validity interruption, Ryan may explicitly authorize one replacement by
reviewing the original evidence and adding `replacement_reason: infrastructure`
or `actor_validity` to a separate review JSON. Import that file and add
`--replacement-review /output/reviews/NAME.json` to `run`, with a new output
directory. Quality-only retries are rejected. Keep the same ledger; both attempts
remain in the aggregate. After interruption, `render` conservatively uses the
original start time when no completion marker exists.

## Updating the packet

Build a new complete packet from the reviewed source into a new ignored output
directory. Keep the original packet, and copy the new directory alongside it
outside the repository. Do not mix launchers, archives, or manifests from
different packets. From the new directory, rerun `load`, `check`, `preflight`,
and `network-check`, then `login` when needed. The existing named corpus, results,
and auth volumes persist; never delete them to install a packet update.
Loading a packet changes the local image tags, so reload an older packet before
using its launcher. Frozen corpus inputs and their existing kit identity remain
binding; an update is not permission to rewrite a frozen manifest.
