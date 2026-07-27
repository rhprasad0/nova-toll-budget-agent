# Terraform plan/apply in CI

Status: in progress · started 2026-07-27

Closes the Tier 3 item in `docs/pre-launch-checklist.md`: deploys are
currently fully manual (`scripts/build_zips.sh` + hand-run `terraform
apply`). CI will run `terraform plan` on PRs touching infra and `terraform
apply` automatically on push to `main`, mirroring the existing
`tailscale-acl.yml` pattern. Full design rationale (trust-policy-as-boundary
for the apply role, why the Cloudflare token needs its own KMS key, the
`ignore_changes=[value]` migration hazard) lives in the approved plan this
checklist was generated from — see git history / conversation for the
original writeup if a "why" here needs more depth than the task note gives.

## Tasks

- [x] **Migrate the Cloudflare token to a dedicated KMS key.** Add
      `aws_kms_key.cloudflare_token` (+ alias) to `infra/kms.tf`, following
      the existing `raw`/`tfstate`/`audit` per-resource key pattern. Add
      `key_id = aws_kms_key.cloudflare_token.arn` to
      `aws_ssm_parameter.cloudflare_api_token` in `infra/ssm.tf`. Apply this
      change in isolation, then **immediately** re-run the out-of-band
      `aws ssm put-parameter --name /nova-toll/cloudflare-api-token
      --overwrite ...` command to restore the real token — the existing
      `lifecycle { ignore_changes = [value] }` pattern means Terraform's
      cached state value is the placeholder, and this update would otherwise
      silently push it back over the real value. Confirm with a follow-up
      `terraform plan` (no diff) and `aws ssm get-parameter
      --with-decryption` (real value, not the placeholder). Done: applied
      targeted, real token captured before the update and restored
      immediately after (verified byte-for-byte match); a full `terraform
      plan` with the real deployment zips afterward reports no changes.
- [x] **Add the two Terraform CI OIDC roles** to `infra/iam.tf`:
      `nova-toll-terraform-plan` (trust scoped to the `pull_request` subject
      only; `ReadOnlyAccess` + inline `kms:Decrypt` on the `tfstate` and
      `cloudflare_token` keys) and `nova-toll-terraform-apply` (trust scoped
      to `ref:refs/heads/main` only; `AdministratorAccess` — this repo's own
      Terraform manages IAM, so the real boundary is the trust policy, not
      the permission policy). Reuse the ID-qualified `sub` pattern already
      in `github_ci_assume`.
- [x] **Drop the hardcoded `profile = "nova-toll"`** from
      `infra/providers.tf` and the `backend "s3"` block in
      `infra/versions.tf`. Local runs rely on `AWS_PROFILE=nova-toll` in the
      shell instead; CI relies on the OIDC-assumed env-var credentials. Done:
      `terraform init -reconfigure` with only `AWS_PROFILE` set (no
      `--profile` flags) reconfigured the backend and a full plan showed no
      unexpected drift.
- [x] **Bootstrap**: apply the two new IAM roles locally (existing
      `nova-toll` profile flow, now via `AWS_PROFILE` per the item above).
      The workflow can't create its own credentials on the first run. Done:
      applied for real, 5 resources added (2 roles, 2 attachments, 1 inline
      policy), 0 changed/destroyed elsewhere.
- [x] **Add `.github/workflows/terraform.yml`**: `fmt-validate` job
      (credential-free, runs for everyone including forks), `plan` job (PR,
      fork-guarded like `ci.yml`'s `integration` job, assumes
      `nova-toll-terraform-plan`, `terraform plan -lock=false`), `apply` job
      (push to `main`, assumes `nova-toll-terraform-apply`, `terraform apply
      -auto-approve`, `concurrency` group so overlapping merges can't race
      the state lock). Both `plan` and `apply` run `./scripts/build_zips.sh`
      and pass the same six `-var` flags it prints, and fetch
      `CLOUDFLARE_API_TOKEN` from SSM with the assumed role. Trigger paths:
      `infra/**`, `scripts/build_zips.sh`, `scripts/loader-requirements.txt`,
      `lambdas/**`. Third-party actions pinned to a commit SHA per this
      repo's convention.
- [x] **Update docs**: `SECURITY.md` (new hardening bullet for the CI
      plan/apply automation + `AWS_PROFILE` guidance), `docs/poller-spec.md`
      (drop the hardcoded-profile line), `docs/pre-launch-checklist.md`
      (check off the Tier 3 item).
- [ ] **Follow-up (not blocking): scope trust policy to `job_workflow_ref`.**
      Automated security review flagged that `nova-toll-terraform-plan`'s
      trust condition (`sub == repo:...:pull_request`) matches any
      `pull_request`-triggered workflow in this repo, not specifically
      `terraform.yml`'s `plan` job — same shape as the existing
      `nova-toll-github-ci` precedent, but this role's permissions
      (`ReadOnlyAccess` + Cloudflare token decrypt) are broader. Low risk
      today (solo repo, only same-repo non-fork PRs can trigger it, and the
      author already has local admin access), but worth tightening before a
      second collaborator exists. Before adding a `job_workflow_ref`
      condition, verify the actual claim shape by decoding a real token from
      a live run — this repo already got burned once assuming an unverified
      OIDC claim format for `sub` (see `567059c`).
- [ ] **Verify end-to-end**: open a PR with a trivial `infra/*.tf` comment
      change, confirm `plan` runs and reports a clean diff; merge, confirm
      `apply` runs and completes; re-run `ci.yml`'s `integration` job
      afterward to confirm the live Tailscale/RDS bridge wasn't disturbed;
      confirm the fork guard actually skips `plan` for a fork PR (or a dry
      read of the `if:` condition, if no fork is available to test with).
