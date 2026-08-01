# Security notes

This is the living security record for TollChat. It documents implemented
controls and operating expectations; it must never contain credentials,
database endpoints, IP addresses, account IDs, or KMS key IDs.

## Current posture

The data pipeline uses separate least-privilege Lambda roles, parameterized
database queries, RDS IAM authentication, and TLS certificate verification.
The public chat agent is not deployed yet. Its release gate is documented in
[`docs/public-agent-launch-gate.md`](docs/public-agent-launch-gate.md).

## Implemented hardening (2026-07-26)

- Raw toll feeds, Terraform state, and audit logs use separate KMS keys with
  rotation enabled and a 30-day deletion window.
- Raw and state buckets block public access, require TLS, enforce bucket-owner
  ownership, retain versions/data indefinitely, and abort incomplete multipart
  uploads after seven days.
- Raw feed writes require the designated KMS key. Only the two fetcher roles
  and the dedicated replay role may write under `raw/`.
- The `toll-raw-replay` role is separate from Lambda and Terraform roles. It
  requires MFA to assume and can only write KMS-encrypted raw objects.
- The loader validates the expected source bucket, supported key structure,
  declared and actual object size, and feed type before parsing or connecting
  to RDS.
- CSV, XML, and JSON parsers impose payload-derived row, field-length,
  identifier, and toll-value limits. XML uses `defusedxml` to reject entity
  expansion and related parser attacks.
- A multi-region CloudTrail trail records S3 object read/write events for raw
  data and Terraform state, with log-file validation in a dedicated audit
  bucket.
- CI actions are pinned to immutable SHAs with read-only repository
  permissions. Secret scanning runs in CI (`gitleaks.yml`, full history on
  every push/PR) and locally in `.githooks/pre-commit` (staged files, any
  committer) once `core.hooksPath` is set per the operating rule below; its
  single allowlist entry is the PostgreSQL `EXCLUDED` pseudo-table false
  positive. CI is the gate nothing can bypass -- the local hook is a
  fast-fail courtesy that only applies to clones that have opted in.
- The Lambda build verifies the downloaded RDS CA bundle SHA-256 before
  packaging it.

## Implemented hardening (2026-07-27)

- RDS is no longer publicly accessible. The only network paths to it are
  the loader Lambda's security group and a Tailscale subnet router
  (`infra/tailscale.tf`), replacing the prior static home-IP ingress rule.
  Confirmed live: a direct public connection attempt now times out.
- GitHub Actions authenticates to AWS via OIDC (`nova-toll-github-ci`,
  `infra/iam.tf`) rather than long-lived credentials, scoped to
  `rds-db:connect` as the read-only `pricing_reader` role and
  `rds:DescribeDBInstances` only. The trust policy's `sub` condition is
  scoped to this repo's actual subjects, not a trailing wildcard, and the
  CI job independently guards against fork PRs (a fork PR produces the same
  `pull_request` subject shape as a same-repo PR, so the trust condition
  alone can't distinguish them).
- The tailnet ACL (`policy.hujson`) is managed via GitOps
  (`.github/workflows/tailscale-acl.yml`, `tailscale/gitops-acl-action`)
  rather than hand-edited in the console: PRs run policy `tests` only, pushes
  to `main` apply. The `tests` assert the owner's access and the RDS route
  survive any future edit, and that `tag:ci` can never reach the general
  internet through the subnet router's exit-node capability.
- Terraform plan/apply now runs in CI (`.github/workflows/terraform.yml`),
  same pattern: PRs get a read-only `plan`, pushes to `main` `apply`
  automatically. Two dedicated OIDC roles, separate from
  `nova-toll-github-ci`: `nova-toll-terraform-plan` (trust scoped to the
  `pull_request` subject only; `ReadOnlyAccess` plus `kms:Decrypt` scoped to
  the Terraform-state and Cloudflare-token KMS keys) and
  `nova-toll-terraform-apply` (trust scoped to `ref:refs/heads/main` only;
  `AdministratorAccess`). The apply role is admin-equivalent because this
  repo's own Terraform manages IAM, including these two roles — a curated
  set of service-scoped policies would still need `IAMFullAccess` to manage
  `infra/iam.tf`, at which point it could attach `AdministratorAccess` to
  anything anyway. The real boundary is the trust policy's branch
  restriction, not the permission policy. The Cloudflare API token was moved
  off the shared default `alias/aws/ssm` key onto its own dedicated key
  (`infra/kms.tf`) specifically so the plan role's decrypt grant doesn't
  also cover the VDOT feed tokens or Tailscale authkey.

## Deployment verification

Historical verification after the 2026-07-26 deployment:

- `toll-fetcher`, `toll-express-fetcher`, and `toll-loader` were Active with
  successful updates.
- Raw and Terraform-state buckets reported KMS default encryption.
- CloudTrail logging was enabled.
- A reconciliation Terraform plan reported no changes.

The desired configuration now retires `toll-express-fetcher`. Before any
authorized apply, review the plan for only that Lambda's runtime, role,
schedule target, alarm, log group, and related policy removal; retained raw
S3 objects and RDS rows must not be destroyed.

## Operating rules

- Run `git config core.hooksPath .githooks` once per clone. Without it, git
  uses no hooks at all -- neither the lint/type/test checks nor the local
  gitleaks secret scan run before a commit, for any tool or person
  committing from that clone.
- Keep VDOT feed tokens in SSM Parameter Store. Do not place them in source,
  Terraform variables, shell history, or this document.
- Keep the OpenAI API key in SSM Parameter Store at
  `/nova-toll/openai_api_key`. The agent reads it with decryption through the
  ambient AWS identity; never export it, log it, or copy it into a local file.
- Keep the Cloudflare API token in SSM Parameter Store
  (`var.cloudflare_api_token_param_name`, `infra/ssm.tf`), same as the VDOT
  feed tokens, but on its own dedicated KMS key rather than the shared
  default -- see the hardening note above for why. Never in a file. Fetch it
  immediately before a Terraform operation and let it die with the shell:
  `export CLOUDFLARE_API_TOKEN=$(aws ssm get-parameter --name /nova-toll/cloudflare-api-token --with-decryption --query Parameter.Value --output text)`
  Requires the identity running it to have `ssm:GetParameter` and
  `kms:Decrypt` on that parameter's key -- an account/SSO-level grant for
  local use (`AWS_PROFILE=nova-toll`), or `nova-toll-terraform-plan`'s /
  `nova-toll-terraform-apply`'s scoped grant in CI.
- Set `AWS_PROFILE=nova-toll` before running Terraform locally.
  `infra/providers.tf` and the `infra/versions.tf` backend block no longer
  hardcode a profile, so both local runs and CI rely on ambient credentials
  (an exported env var locally, OIDC-assumed env-var credentials in CI)
  rather than a named profile lookup.
- If an AI coding agent is checking whether a value matches something,
  compare hashes or lengths, not the raw value. See `AGENTS.md`'s Secrets
  section -- it applies to any agent operating in this repo, not just
  Claude Code.
- Use `./scripts/build_zips.sh` before applying infrastructure changes. If AWS
  rotates the RDS CA, review the rotation notice and update the pinned digest
  in the script before rebuilding.
- Apply Terraform with the real deployment zip paths and handlers. The raw
  bucket policy intentionally rejects placeholder Lambda packages.
- Review the CloudTrail audit bucket and SNS alarms regularly. Retention is
  intentionally indefinite; monitor the storage alarms and associated cost.
- Use the replay role only for approved recovery work, with MFA. Never widen
  its S3 or KMS permissions for convenience.

## Remaining review items

- Before a public agent launch, implement every control in the public-agent
  launch gate, including WAF throttling, concurrency/spend limits, a kill
  switch, output validation, and a dedicated read-only runtime role.
