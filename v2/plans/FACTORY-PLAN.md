# TollChat Factory Plan

Status: **in progress**. Stages 1 and 2 are done, and Stage 3's sandbox is
merged (#766, #767). This is the build order for the design in
[FACTORY-SPEC.md](FACTORY-SPEC.md). Like the spec, it grants no AWS, Terraform,
database, or CI authority; each step that touches those says who does it.

Each stage ends with a check. Do not start a stage until the one before it
passes. Steps marked **Ryan** need a human at a keyboard or a decision; the
rest can be done by a coding agent in a worktree.

## Decisions

Ryan settled the spec's proposals on 2026-11-14 and four more questions on
2026-11-15; they are listed in the spec's Decisions section. Still open:

- **Does replaying production traces into Phoenix fit the public privacy
  notice?** Check before building the production mode (Stage 8).

## Stage 1: Reformat the thin client

**Status on 2026-11-14: done. Steps 1 to 5 are complete; step 6 is deferred.**

The machine is an HP EliteDesk 800 G2 mini: a four-core Core i5-6500T from
2015, 16 GB of memory, and a 224 GB SSD with 86 GB free on the root volume and
120 GB unallocated. It runs Ubuntu Server 26.04.1 LTS. Memory and disk are enough. Stage 2 found
the processor fast enough so far: a verify round took 13.9 minutes, measured
outside the sandbox.

**It is a home lab box, by Ryan's decision.** It has no disk encryption, Secure
Boot is off, and its TPM is version 1.2, which the signing helper cannot use.
The factory's secrets on it (the certificate's private key and the GitHub
token) are therefore plain files. The controls that matter are the ones in
GitHub and AWS: what the token and the role are allowed to do.

1. [x] Install Ubuntu Server LTS, wiping the disk. No desktop.
2. [x] One user, `ryan`, runs everything. The workstation's SSH key is
   authorized. Automatic security updates are on and the system is up to date.
3. [x] Docker Engine and the Compose plugin from Docker's repository; `ryan`
   is in the `docker` group.
4. [x] **Ryan:** install Tailscale, join the tailnet as `factory`, and disable
   key expiry for the device.
5. [x] Install `gh`, `gitleaks` (8.30.1, the version CI uses), `uv`, and
   Claude Code.
6. Deferred: **Ryan:** set the BIOS to power back on after an outage. Until
   then, a power cut stops the factory until someone presses the power button.

**Do not copy onto it:** the evaluation holdout, `~/.aws` from the workstation,
or any production profile.

**Reaching Phoenix and the dashboard.** The thin client has no screen, and
Phoenix and the dashboard listen only on its loopback. Browse them from the
workstation through an SSH tunnel over Tailscale:
`ssh -L 6006:127.0.0.1:6006 -L 6007:127.0.0.1:6007 <user>@<thin client>`, then
open `http://localhost:6006` (Phoenix) or `http://localhost:6007` (dashboard).
Phoenix links in issue comments work only while that tunnel is open.

**Done when:** from the workstation, `ssh <user>@<thin client>` works over Tailscale,
and `docker run hello-world` succeeds without `sudo`.

## Stage 2: Run the spikes that need no AWS

**Status on 2026-11-14: done.** Spikes 1, 4, and 5 passed (5 with a
workaround); spike 6 is partly settled. Results, workarounds, and the spec
changes they forced are in the spec's Spike results section. A verify round
took 13.9 minutes outside the sandbox shape, and one Opus author round used
under 1% of the weekly subscription limit. Stage 3 must show verify passing
inside the sandbox.

Run these on the thin client with a copy of `factory-scoreboard/sandbox/`, so
they also prove the machine. Mint a subscription token with
`claude setup-token` and export it for the session only. Check where that
command stores anything on a headless machine before relying on it.

| Spike | Question | Pass |
| --- | --- | --- |
| 1. Token injection | Can the proxy replace a placeholder with the subscription token as a bearer header? | A sandboxed `claude -p "hello"` answers while the container holds only the placeholder. |
| 5. `TRACEPARENT` with `--resume` | Do resumed turns join the same trace? | Two rounds in one container show one trace ID in the existing Grafana stack. |
| 4. Span rendering | Does Phoenix show `claude_code.*` spans usefully? | Point the collector at a throwaway Phoenix with its default local database and read one trace. If it is unreadable, add Arize's collector bridge. |
| 6. Subscription headroom and speed | How much of the plan does one run use, and is the machine fast enough? | Record the tokens for one realistic issue against a scratch repository, and time one build and test round of this repo in the worker image against the 30-minute limit. |

**If spike 1 fails, stop.** The spec's credential design depends on it, and the
spec needs a revision before anything else is built.

**Done when:** all four have a result, and the matching items in the spec's
Spike results section are closed with it. These are setup checks, not
experiments, so they do not go in the experiment journal.

## Stage 3: Bring the factory code into the repo

**Status on 2026-11-15: done once step 4's PR merges, except one deferred check.** Steps 1 to 3, 5 and 6 are merged
(#766, #767), and the development delivery after the merge was green.
`.github/scripts/verify.sh` passed inside the sandbox on `main` (145b860f) on
2026-11-15, with the full database profile and no database test skipped, in
900 s; pytest's counts (2183 passed, 4 skipped) matched CI's.
Step 4 is built on the `stage3/decisions` branch: `factory/host/inbox.py`
(poller, runner, restart), `factory/host/dashboard.py`, and the units in
`factory/systemd/`, with the runner refusing to start until Stage 6. The spike 5
re-test ran on 2026-11-15 (see the spec's Spike results, 5): every round
nests with its prompt on stdin as stream-json and, for resumed rounds, the
cached-settings deletion. `factory` became a required check on 2026-11-15. Deferred: a
green development delivery, because the manual delivery of 145b860f failed
during the 2026-11-15 AWS us-east-1 outage (`apply` stage, `gate_rejected`).
Check the next delivery after AWS recovers; Stage 4 does not wait on it.

1. Copy the needed pieces of `factory-scoreboard/sandbox/` into `factory/`:
   the dispatcher (`host/`), the worker image (`agent/`), the proxy, the
   collector config, and the Compose file. Leave out the oracle, the host
   graders, Grafana, Tetragon, and the systemd units, which step 4 replaces.
2. Apply the spec's differences that need no AWS: bearer-token injection, the
   `factory` label trigger, and the TollChat toolchains in the worker image.
   The worker's clone runs the setup block under "Verify the build" in
   `v2/README.md` (`uv sync`, both `npm ci` runs, and
   `git config core.hooksPath .githooks`; the checkers are baked into the
   image), so the pre-commit hook catches
   lint and type errors before a commit rather than in CI. The hook installs
   nothing and fails without that setup. Set `core.hooksPath` only in the
   sandbox clone, never in the dispatcher's host clone.
3. Add the two throwaway PostGIS containers and the Playwright browser to the
   sandbox. Verify is `.github/scripts/verify.sh`, the script the required CI
   jobs already run; the dispatcher copies it from its checkout of `main`.
   Spike 6 found three gaps, now settled:
   - The database tests need Docker. `v2/scripts/run_db_tests.sh` uses
     `docker exec` on the Postgres container, and
     `test_adopt_production_baseline.py` starts and stops its own database per
     test. Mount the Docker socket and add the Docker CLI to the image, as the
     spec's Sandbox section records. Confirm in the first verify round that
     the two test files that skip without Docker now run.
   - The golden artifact smoke needs ARM. It stays CI-only; `verify.sh` does
     not run it.
   - The eight failing tests in `test_production_plan_workflow.py` and
     `test_production_migration_workflow.py` needed `xxd`, which the image
     lacked. The image needs `jq`, `xxd`, `zip` and `unzip`; the test suite
     now stops at startup and names any that are missing.
   Build the image with `postgresql-client` (for `psql`), Node 22.22.1, and
   Terraform 1.15.8. Allow the hosts the setup downloads from on the proxy, as
   the spec's Egress proxy section lists; the spike's copy allowed only
   Anthropic and crates.io. Re-test spike 5's trace workaround in the
   long-lived container (done 2026-11-15; see the spec's Tracing section).
4. Split the dispatcher into poller and runner around the inbox and add the
   dashboard, as the spec's Inbox and Dashboard sections describe. Three
   systemd units replace `factory-scoreboard`'s one-shot poll pass with its
   45-minute timeout: a timer that runs the poller every 60 seconds and
   finishes in seconds, a long-running runner service, and the dashboard
   service. The stations, push, and outcome steps are Stage 6 work, so stub
   them here. Test the inbox with GitHub's responses faked (it is a
   credentialed service):
   - the overlapping re-read records nothing twice;
   - a cold start rebuilds the queue from labeled open issues;
   - two `labeled` events run oldest first;
   - an `unlabeled` event drops a queued one but not a newer re-label, and
     marks a running work order cancelled only if it is newer than the event
     that started it;
   - a stale event whose label is gone is dropped silently;
   - a second runner exits on the lock;
   - on restart, an orphaned `running` event returns to `pending`, and a
     work order that died with no branch on GitHub is queued again once,
     while one with a branch ends `crashed`.

   Test the dashboard against a seeded inbox: it renders every section,
   escapes an issue title containing HTML, and refuses `POST`.
5. Keep the copied tests passing, add one for the new trigger, and add a CI
   job that runs the `factory/` tests. Today's `ci.yml` jobs all run under
   `v2/`, so nothing would run them otherwise. **Ryan** then makes that job a
   required check, since the dispatcher waits only on required checks.
6. Before opening the PR, check how development delivery and the release
   manifest treat a new top-level directory. PR CI has missed delivery
   rejections before.
7. Ship as a normal PR. Nothing runs yet.

**Done when:** `.github/scripts/verify.sh` passes on an unmodified `main` inside the
sandbox, with none of the database tests skipped; the PR is merged, its
`factory/` job passed, and the next development delivery (nightly or manual
since #769) is green.

## Stage 4: AWS access

1. **Ryan:** on the workstation, create the CA and issue the thin client's
   certificate. Copy only the certificate and its private key to the thin
   client, owned by `ryan`, mode `600`. The CA key never leaves the
   workstation.
2. Terraform in `infra/`, through a normal PR: the Roles Anywhere trust anchor
   and profile, and the factory role with its trust policy and the four
   permissions the spec lists. The same PR notes in `SECURITY.md` the two
   factory credentials kept outside SSM: the certificate's private key and
   the GitHub token.
3. **Ryan:** apply it by hand after the merge. CI only formats and validates
   `infra/`; no workflow applies it. No apply while the circuit breaker is
   tripped.
4. **Ryan:** store the subscription token in SSM as a SecureString.
5. **Ryan (administrator):** on the development RDS instance, create the
   `phoenix` database and the `phoenix_factory` role with `rds_iam`.
6. If the tailnet's access rules do not already let the thin client reach the
   RDS endpoint, change them through the existing Tailscale ACL workflow.
7. Install `aws_signing_helper` on the thin client.

Then run the two remaining spikes:

| Spike | Pass |
| --- | --- |
| 2. Container credentials | A throwaway container running the AWS CLI gets the factory role from the helper's `serve` endpoint; the same request from the sandbox network fails. |
| 3. Tailscale from a container | A container on the thin client opens a connection to the RDS endpoint. |

**Done when:** on the thin client, `aws sts get-caller-identity` returns the factory
role, reading the token parameter works, and reading any other parameter is
denied.

## Stage 5: Trace stack

1. One Compose file for the proxy, the collector, and Phoenix, with Phoenix on
   RDS through IAM authentication and published on `127.0.0.1` only. Use the
   spec's Phoenix settings (version pin, authentication and assistant off)
   and the collector's token-count `transform`.
2. Add the collector's S3 exporter to `factory-traces/`.
3. Add the admission preflight: Phoenix health, proxy, and Tailscale.

**Done when:** a sandboxed `claude -p "hello"` appears in Phoenix and as an
object under `factory-traces/`; a first and a resumed round, run the way the
spec's Tracing section says, nest under one `TRACEPARENT`; with Phoenix and the collector both using
credentials from `serve`, and stopping Phoenix makes the preflight fail.

## Stage 6: First work order

1. **Ryan:** create the `factory` label. Sign `gh` in on the thin client with a
   fine-grained token limited to this repository. It needs to write contents,
   pull requests, and issues, and to read check results and failed job logs.
   Confirm the exact permission names when creating it, and grant nothing
   more. In particular, **no Workflows permission**.
2. Finish the runner: the three stations (author, reviewer, verify), the
   guard (secrets scan and protected paths), push and PR, the CI watch, the
   shared budget of three fix rounds, the cancel checks, the outcome comment
   and label removal, and the sweep of `closed` events. Run every round with
   its prompt on stdin as stream-json and record its `session.id` on the round
   span (see the spec's Tracing section).
3. Test the guard before trusting it. Each of these work orders must end with
   no branch pushed:
   - its diff touches a protected path;
   - it contains a planted fake secret;
   - it deletes a line from the experiment journal;
   - it adds a `CLAUDE.md` or `AGENTS.md` in any directory;
   - its verify step fails, including when the worker has edited
     `.github/scripts/verify.sh` to make it pass.

   One that only appends to the journal must pass. Then test the outer
   checks: an issue written by another account is refused, and direct pushes
   with the factory token that edit a workflow file, change `main`, or move a
   release tag are all rejected by GitHub.

   Then test the inbox against real GitHub: two issues labeled a minute apart
   run one after the other; removing the label mid-round stops the container
   and pushes nothing more, and the label stays off; removing and re-adding
   it mid-run cancels the run and then starts a new one; killing the runner
   after its first push and restarting it pushes nothing more and ends
   `crashed`; and stopping the
   dashboard changes nothing. Note how long a label takes to appear in the
   issue events feed.
4. **Ryan:** label one small, real issue.
5. Enable the three systemd units (poller timer, runner, dashboard) from
   `factory/systemd/` as user units, and run `loginctl enable-linger ryan`
   (off on 2026-11-15), or they stop at logout and never start at boot. They
   run from a checkout of `main` that only Ryan updates.

**Done when:** that issue becomes a PR that is ready for review, with one trace
in Phoenix and the outcome comment on the issue, and the dashboard showed it
move through its stations while it ran.

## Stage 7: Scoring plumbing

No experiments yet; this stage only makes sure the data exists.

1. Write the outcome annotations onto the `work_order` span, and the sweep's
   `merged` and `human_commits` (the sweep itself is built in Stage 6).
2. Measure the Phoenix database's size and raise the 30-day retention if there
   is room.

**Done when:** merge rate, first-pass CI rate, and list-price cost per merged
PR can be read from Phoenix for the first five work orders.

## Stage 8: Agent trace replay

Run replays **from the workstation**, through the SSH tunnel from Stage 1. The
workstation already has the profiles that read `agentcore-traces/`; the factory
role does not, and should not gain them. This keeps the production profile off
the thin client.

1. Write the replay script for development traces.
2. Check the production mode against the public privacy notice, then add it
   behind its explicit flag.

**Done when:** one hour of development agent traces is browsable in the
`tollchat-agent-dev` project.

## Not in this plan

- The spec's deferred items: factory experiments, lanes for PR review
  feedback and clarification replies, dashboard controls, the article's
  timers and outbox, parallel work orders, AWS alarm events in the inbox, a
  separate test author, a rubric
  grader, and the other lanes.
- Workstation Claude Code telemetry. Ryan dropped it.
- Running training evals on factory PRs. Ryan decided against it on
  2026-11-15. Required CI does not include them, so the factory does not
  verify agent behaviour.
- Hardening the thin client itself: disk encryption, Secure Boot, or a
  TPM-held key. The TPM would first need converting from 1.2 to 2.0.
