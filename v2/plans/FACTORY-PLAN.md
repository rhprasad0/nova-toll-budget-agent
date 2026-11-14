# TollChat Factory Plan

Status: **plan, nothing built**. This is the build order for the design in
[FACTORY-SPEC.md](FACTORY-SPEC.md). Like the spec, it grants no AWS, Terraform,
database, or CI authority; each step that touches those says who does it.

Each stage ends with a check. Do not start a stage until the one before it
passes. Steps marked **Ryan** need a human at a keyboard or a decision; the
rest can be done by a coding agent in a worktree.

## Decisions

Ryan settled the spec's proposals on 2026-11-14; they are listed in the spec's
Decisions section. Still open:

- **Does a full work order fit the subscription?** One author round used
  under 1% of the weekly limit (Stage 2). Log the utilization header per work
  order from Stage 6 and decide on daily volume after the first five.
- **Does replaying production traces into Phoenix fit the public privacy
  notice?** Check before building the production mode (Stage 8).
- **Training evals on factory PRs** (see Not in this plan).

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

**Reaching Phoenix.** The thin client has no screen and Phoenix listens only on
its loopback. Browse it from the workstation through an SSH tunnel over
Tailscale: `ssh -L 6006:127.0.0.1:6006 <user>@<thin client>`, then open
`http://localhost:6006`. Phoenix links in issue comments work only while that
tunnel is open.

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

1. Copy the needed pieces of `factory-scoreboard/sandbox/` into `factory/`:
   the dispatcher (`host/`), the worker image (`agent/`), the proxy, the
   collector config, the Compose file, and the systemd unit. Leave out the
   oracle, the host graders, Grafana, and Tetragon.
2. Apply the spec's differences that need no AWS: bearer-token injection, the
   `factory` label trigger, and the TollChat toolchains in the worker image.
   The worker's clone runs the setup block under "Verify the build" in
   `v2/README.md` (`uv sync`, both `npm ci` runs, `install_check_tools.sh`,
   and `git config core.hooksPath .githooks`), so the pre-commit hook catches
   lint and type errors before a commit rather than in CI. The hook installs
   nothing and fails without that setup. Set `core.hooksPath` only in the
   sandbox clone, never in the dispatcher's host clone.
3. Add the throwaway PostGIS container and the Playwright browser to the
   sandbox, and write `factory/verify.sh`. Its first step is the full
   `python3 v2/scripts/check_repository.py`, since the hook only checks what
   is staged and the worker can skip it. Spike 6 found three gaps to close
   here:
   - The database tests need Docker, which the sandbox lacks.
     `v2/scripts/run_db_tests.sh` uses `docker exec` on the Postgres container;
     `test_adopt_production_baseline.py` starts and stops its own database per
     test; `test_development_migrations.py` and it skip, rather than fail,
     without Docker; and the MCP server's `e2e.sh` starts PostGIS and DynamoDB
     Local and copies files in with `docker cp`. Give them a path that needs
     only the network (two PostGIS services, as CI has, plus DynamoDB Local),
     and make `verify.sh` fail if any of them skips.
   - The golden artifact smoke needs ARM. Leave it to CI and say so in
     `verify.sh`.
   - Eight tests in `test_production_plan_workflow.py` and
     `test_production_migration_workflow.py` failed in the spike but pass in
     CI, as root and as a normal user. The cause is unknown: either the image
     lacks something the GitHub runner has, or the clone differed (made from a
     bundle, with no `origin` remote and no tags).
   Build the image with `postgresql-client` (for `psql`), Node 22.22.1, and
   Terraform 1.15.8. Allow the hosts the setup downloads from on the proxy, as
   the spec's Egress proxy section lists; the spike's copy allowed only
   Anthropic and crates.io. Re-test spike 5's trace workaround in the
   long-lived container, deleting `~/.claude.json` as well (see the spec's
   Tracing section).
4. Keep the copied tests passing, add one for the new trigger, and add a CI
   job that runs the `factory/` tests. Today's `ci.yml` jobs all run under
   `v2/`, so nothing would run them otherwise. **Ryan** then makes that job a
   required check, since the dispatcher waits only on required checks.
5. Before opening the PR, check how development delivery and the release
   manifest treat a new top-level directory. PR CI has missed delivery
   rejections before.
6. Ship as a normal PR. Nothing runs yet.

**Done when:** `factory/verify.sh` passes on an unmodified `main` inside the
sandbox, with none of the database tests skipped; the PR is merged, its
`factory/` job passed, and the development delivery that follows the merge is
green.

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
object under `factory-traces/`, with Phoenix and the collector both using
credentials from `serve`, and stopping Phoenix makes the preflight fail.

## Stage 6: First work order

1. **Ryan:** create the `factory` label. Sign `gh` in on the thin client with a
   fine-grained token limited to this repository. It needs to write contents,
   pull requests, and issues, and to read check results and failed job logs.
   Confirm the exact permission names when creating it, and grant nothing
   more. In particular, **no Workflows permission**.
2. Finish the dispatcher: the three stations (author, reviewer, verify), the
   guard (secrets scan and protected paths), push and PR, the CI watch, the
   shared budget of three fix rounds, and the outcome comment. Have the proxy
   log the `anthropic-ratelimit-unified-7d-utilization` response header per
   work order, as spike 6 did.
3. Test the guard before trusting it. Each of these work orders must end with
   no branch pushed:
   - its diff touches a protected path;
   - it contains a planted fake secret;
   - it deletes a line from the experiment journal;
   - it adds a `CLAUDE.md` or `AGENTS.md` in any directory;
   - its verify step fails, including when the worker has edited
     `factory/verify.sh` to make it pass.

   One that only appends to the journal must pass. Then test the outer
   checks: an issue written by another account is refused, and direct pushes
   with the factory token that edit a workflow file, change `main`, or move a
   release tag are all rejected by GitHub.
4. **Ryan:** label one small, real issue.
5. Enable the systemd unit so the poller survives a reboot. It runs the
   dispatcher from a checkout of `main` that only Ryan updates.

**Done when:** that issue becomes a PR that is ready for review, with one trace
in Phoenix and the outcome comment on the issue.

## Stage 7: Scoring plumbing

No experiments yet; this stage only makes sure the data exists.

1. Write the outcome annotations onto the `work_order` span.
2. Add the sweep that records how each factory PR closed.
3. Measure the Phoenix database's size and raise the 30-day retention if there
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

- The spec's deferred items: factory experiments, a lane for PR review
  feedback, a separate test author, a rubric grader, and the other lanes.
- Workstation Claude Code telemetry. Ryan dropped it.
- Running training evals on factory PRs. Required CI does not include them
  today, so the first version does not verify agent behaviour. Decide after
  the first five work orders whether the dispatcher should run them.
- Hardening the thin client itself: disk encryption, Secure Boot, or a
  TPM-held key. The TPM would first need converting from 1.2 to 2.0.
