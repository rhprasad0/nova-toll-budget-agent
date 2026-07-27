# Tailscale bridge for RDS: CI, dev laptop, exit node

Status: implemented — core path verified end-to-end in CI 2026-07-27
(`https://github.com/rhprasad0/nova-toll-budget-agent/actions/runs/30294746855`).
Optional follow-ups remain (see bottom).

Replaces the `home_ip/32` public ingress rule on RDS with a Tailscale
subnet-router EC2 instance in the default VPC. That one box gives
GitHub Actions CI, the dev laptop, and public-wifi exit-node coverage a
network path to RDS, without RDS being publicly addressable at all. See
plan discussion for full rationale (home-IP rule is manually maintained
and a real public exposure; the subnet router removes both problems with
one mechanism).

## Tasks

- [x] **Subnet router infra**: `aws_security_group.tailscale_router` (no
      ingress, default egress), `aws_instance.tailscale_router` (`t4g.nano`,
      AL2023 arm64, user-data installs+configures Tailscale with
      `--advertise-routes=<vpc-cidr> --advertise-exit-node --ssh`), IAM
      role/instance profile scoped to `ssm:GetParameter` on a new
      `/nova-toll/tailscale-authkey` SSM SecureString param (seeded
      placeholder, same pattern as `i95_token`/`i66_token`). Landed in the
      new `infra/tailscale.tf`.
- [x] **Remove the home-IP hole**: deleted
      `aws_vpc_security_group_ingress_rule.rds_from_home` and
      `variable "home_ip"`; added `rds_from_tailscale` ingress rule
      referencing the new SG instead. Also fixed the dangling `home_ip`
      reference in `scripts/build_zips.sh`'s usage message.
- [x] **Close public RDS exposure**: `infra/rds.tf` `publicly_accessible`
      `true` → `false`.
- [x] **GitHub OIDC role for CI**: `aws_iam_openid_connect_provider` +
      `aws_iam_role.github_ci` trusting `token.actions.githubusercontent.com`,
      with `rds-db:connect` as `pricing_reader` and `rds:DescribeDBInstances`
      (so CI can resolve the endpoint at runtime instead of it being
      hardcoded into the public workflow file). Trust condition scoped to
      `ref:refs/heads/*`/`pull_request` subjects rather than a trailing
      `:*` (an automated review flagged the wildcard); the `integration`
      job also skips fork PRs via an `if:` check, since fork PRs produce
      the same `pull_request` subject a same-repo PR does — the trust
      condition alone can't tell them apart.
- [x] **Tailscale authkey → SSM**: real reusable key set via
      `aws ssm put-parameter --overwrite`. Note: the key value ended up in
      this chat's transcript despite trying to avoid it (running it via `!`
      pipes the command and output back into the session, it doesn't stay
      local) — Ryan chose to accept that rather than rotate.
- [x] **`terraform apply`**: RDS flipped to `publicly_accessible = false`,
      OIDC provider + `github_ci` role created, tailscale SG/IAM/instance
      created. Hit one snag: `data.aws_subnets.default.ids[0]` landed on
      `us-east-1e`, which doesn't support `t4g` instance types in this
      account — pinned the router to `us-east-1c` explicitly and re-applied
      just the instance. Everything else from the first apply succeeded
      clean.
- [x] **Manual Tailscale admin-console steps**: subnet route approved;
      CI-join OAuth client (Auth Keys scope, `tag:ci`) created, added as
      `TS_OAUTH_CLIENT_ID`/`TS_OAUTH_SECRET` GitHub secrets; ACL-pipeline
      OAuth/trust credential created, added as `TS_ACL_OAUTH_CLIENT_ID`/
      `TS_ACL_OAUTH_SECRET`. Exit-node approval not separately confirmed —
      see follow-ups.
- [x] **ACL managed via GitOps instead of the admin console**: switched
      from the originally-planned `tailscale_acl` Terraform resource after
      finding it does a blind overwrite with no ETag/If-Match concurrency
      check (open upstream bug) — risky given we'd been hand-editing this
      tailnet in the console all session. Used `tailscale/gitops-acl-action`
      instead: `policy.hujson` at repo root,
      `.github/workflows/tailscale-acl.yml` runs `tests`-only on PRs and
      applies on push to `main`. Scopes `tag:ci` to just the RDS route,
      keeps the owner's full access, adds `autoApprovers` for the router's
      route + exit-node (so future re-creates skip the manual console
      click), and drops an unrelated `tag:server`/`tag:k8s-operator` grant
      from another project per go-ahead to consolidate. Two real syntax
      fixes needed before it applied clean: `grants`' `dst` can't carry a
      CIDR+port combo (port has to move to `ip`, e.g. `"ip": ["tcp:5432"]`);
      `tests`' `accept`/`deny` can't target a CIDR at all, only a concrete
      IP or hostname (aliased RDS's resolved private IP via `hosts`).
- [x] **New CI integration test**: `tests/test_ci_rds_connectivity.py` —
      resolves the RDS endpoint via `describe_db_instances` (not hardcoded,
      per SECURITY.md), then calls `_oracle_route.env_connect()` (IAM auth
      as `pricing_reader`, the real prod path), runs `SELECT 1`. Marked
      `pytest.mark.live`, only ever invoked explicitly; passes lint/type
      checks and fails correctly (on missing DB access, not on import) when
      run locally without nova-toll credentials.
- [x] **CI workflow**: new `integration` job in `.github/workflows/ci.yml`
      (separate from `check`, so a Tailscale/AWS hiccup never blocks
      lint/typecheck/unit tests) — `tailscale/github-action` →
      `aws-actions/configure-aws-credentials` (role-to-assume) → `uv run
      pytest -m live tests/test_ci_rds_connectivity.py`. Third-party actions
      pinned to commit SHA per this repo's existing convention (verified
      against the actual current release tags, not guessed).
- [x] **Docs**: rewrote `docs/poller-spec.md`'s network-posture paragraph
      (marked "written, not yet applied" rather than claiming the new
      posture is already live — it isn't); kept SECURITY.md's public-RDS
      item, reworded to state it's still open pending apply, rather than
      deleting it as resolved; fixed the drifted `infra/network.tf:33-45`
      line reference in `docs/pre-launch-checklist.md` (now `39-65`).
- [x] **Post-implementation review fixes** (advisor + automated security
      scan caught these before anything was applied): verified
      `pricing_reader` actually exists and works live (`SELECT 1` via IAM
      token) rather than trusting a docstring; fixed `set -x` echoing the
      decrypted Tailscale authkey into cloud-init's log in the instance
      user-data; attached `AmazonSSMManagedInstanceCore` to the router's
      instance role so it's recoverable if the authkey placeholder is still
      unset on first boot; confirmed via AWS docs that a private RDS
      endpoint's DNS resolves straight to the private IP from anywhere (no
      split-DNS/VPC-resolver step needed for the tailnet route to work).
- [x] **`terraform apply` + CI verification**: applied for real; confirmed
      `check` and `integration` both green on a real push
      (`tailscale/github-action` joins the tailnet → OIDC role assumed →
      `env_connect()` connects as `pricing_reader` over the bridge →
      `SELECT 1`); confirmed a direct (non-tailnet) connection attempt to
      the RDS hostname now times out. Three real bugs found and fixed along
      the way, not just config typos:
      1. `data.aws_ssm_parameter` AMI lookup path was wrong (AWS's actual
         public parameter is under `ami-amazon-linux-latest`, not the path
         first guessed) — fixed by testing the parameter directly with the
         `nova-toll` profile rather than trusting the assumed path.
      2. The OIDC trust policy's `sub` condition assumed a plain
         `repo:owner/repo:...` subject; GitHub actually issues
         `repo:owner@<ownerID>/repo@<repoID>:...` (immutable IDs) for this
         account. Diagnosed by adding a temporary workflow step to decode
         and print the real token's claims, not by guessing — removed once
         fixed. Kept the ID-qualified form since it's also rename/transfer
         proof, rather than looking for a way to disable it.
      3. `infra/build/` (holding the RDS CA bundle) is gitignored, so a
         fresh CI checkout never had it — added a step fetching just that
         file with the same URL + pinned SHA256 `scripts/build_zips.sh` uses.
- [x] **Retag the router for `autoApprovers`**: added
      `--advertise-tags=tag:nova-toll-router` to `infra/tailscale.tf`'s
      user-data (`terraform apply` — only changed the stored `user_data`
      hash, no instance replacement since `user_data_replace_on_change`
      defaults false) so future re-creates auto-approve without a console
      click. Retagged the already-running instance to match, over SSM:
      `tailscale set --advertise-tags=...` doesn't exist (that flag is
      `up`-only) — used `tailscale up` with the same route/exit-node/ssh
      flags plus the tag and `--reset`, which re-applies cleanly on an
      already-authed device without needing a fresh authkey. Confirmed via
      `tailscale status --json`: tagged, online, route/exit-node intact;
      confirmed RDS is still reachable on 5432 post-retag.
- [ ] **Follow-up (optional, not blocking)**: exit-node approval/use was
      never separately confirmed — verify from a non-home network before
      relying on it.
