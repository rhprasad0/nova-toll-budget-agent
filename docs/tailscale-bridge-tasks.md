# Tailscale bridge for RDS: CI, dev laptop, exit node

Status: in progress

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
      `aws_iam_role.github_ci` trusting `token.actions.githubusercontent.com`
      scoped to `repo:rhprasad0/nova-toll-budget-agent:*`, with
      `rds-db:connect` as `pricing_reader` and `rds:DescribeDBInstances`
      (so CI can resolve the endpoint at runtime instead of it being
      hardcoded into the public workflow file).
- [ ] **Manual one-time Tailscale setup** (out of Terraform, tracked here so
      it isn't forgotten): create reusable authkey → SSM; approve the
      advertised VPC-CIDR route in the admin console; write ACL granting
      laptop + `tag:ci` access to the route (not to each other, not to the
      exit node); create the CI OAuth client (`TS_OAUTH_CLIENT_ID`/
      `TS_OAUTH_SECRET`) and add as GitHub repo secrets. **Blocks the two
      items below** — nothing works until this is done.
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
- [x] **Docs**: rewrote `docs/poller-spec.md`'s network-posture paragraph;
      removed the resolved public-RDS bullet from `SECURITY.md`'s
      "Remaining review items"; fixed the drifted
      `infra/network.tf:33-45` line reference in
      `docs/pre-launch-checklist.md` (now `39-65`).
- [ ] **Verification**: `terraform plan`/`apply`; `tailscale up` from dev
      box + psql over the tailnet; toggle exit-node on a non-home network;
      trigger CI and confirm both jobs go green; confirm direct
      (non-tailnet) psql to the RDS public hostname now fails. **Not done
      yet** — deliberately held: `apply` flips a live RDS instance's public
      accessibility and stands up billable EC2/IAM/OIDC resources, and the
      subnet router won't actually function until the manual Tailscale step
      above is done first (its user-data auth key is still the
      `REPLACE_OUT_OF_BAND` placeholder). Say the word when you want me to
      run `terraform plan` for a look before applying.
