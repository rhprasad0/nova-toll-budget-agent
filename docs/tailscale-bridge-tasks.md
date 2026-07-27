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

- [ ] **Subnet router infra**: `aws_security_group.tailscale_router` (no
      ingress, default egress), `aws_instance.tailscale_router` (`t4g.nano`,
      AL2023 arm64, user-data installs+configures Tailscale with
      `--advertise-routes=172.31.0.0/16 --advertise-exit-node --ssh`), IAM
      role/instance profile scoped to `ssm:GetParameter` on a new
      `/nova-toll/tailscale-authkey` SSM SecureString param (seeded
      placeholder, same pattern as `i95_token`/`i66_token`).
- [ ] **Remove the home-IP hole**: delete
      `aws_vpc_security_group_ingress_rule.rds_from_home` and
      `variable "home_ip"`; add `rds_from_tailscale` ingress rule
      referencing the new SG instead.
- [ ] **Close public RDS exposure**: `infra/rds.tf` `publicly_accessible`
      `true` → `false`.
- [ ] **GitHub OIDC role for CI**: `aws_iam_openid_connect_provider` +
      `aws_iam_role.github_ci` trusting `token.actions.githubusercontent.com`
      scoped to this repo, with `rds-db:connect` as `pricing_reader` only.
- [ ] **Manual one-time Tailscale setup** (out of Terraform, tracked here so
      it isn't forgotten): create reusable authkey → SSM; approve the
      advertised `172.31.0.0/16` route in the admin console; write ACL
      granting laptop + `tag:ci` access to the route (not to each other, not
      to the exit node); create the CI OAuth client (`TS_OAUTH_CLIENT_ID`/
      `TS_OAUTH_SECRET`) and add as GitHub repo secrets.
- [ ] **New CI integration test**: `tests/test_ci_rds_connectivity.py` —
      calls `agent_tools._oracle_route.env_connect()` (IAM auth as
      `pricing_reader`, the real prod path), runs `SELECT 1`. Marked
      `pytest.mark.live`, only ever invoked explicitly.
- [ ] **CI workflow**: new `integration` job in `.github/workflows/ci.yml`
      (separate from `check`) — `tailscale/github-action` →
      `aws-actions/configure-aws-credentials` (role-to-assume) → `uv run
      pytest -m live tests/test_ci_rds_connectivity.py` with the `DB_*` env
      vars set.
- [ ] **Docs**: rewrite `docs/poller-spec.md`'s "Network posture (accepted
      tradeoff)" paragraph for the new posture; remove the resolved
      public-RDS bullet from `SECURITY.md`'s "Remaining review items"; fix
      the drifted `infra/network.tf:33-45` line reference in
      `docs/pre-launch-checklist.md`.
- [ ] **Verification**: `terraform plan`/`apply`; `tailscale up` from dev
      box + psql over the tailnet; toggle exit-node on a non-home network;
      trigger CI and confirm both jobs go green; confirm direct
      (non-tailnet) psql to the RDS public hostname now fails.
