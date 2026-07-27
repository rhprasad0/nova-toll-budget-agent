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

## Deployment verification

After the 2026-07-26 deployment:

- `toll-fetcher`, `toll-express-fetcher`, and `toll-loader` were Active with
  successful updates.
- Raw and Terraform-state buckets reported KMS default encryption.
- CloudTrail logging was enabled.
- A reconciliation Terraform plan reported no changes.

## Operating rules

- Run `git config core.hooksPath .githooks` once per clone. Without it, git
  uses no hooks at all -- neither the lint/type/test checks nor the local
  gitleaks secret scan run before a commit, for any tool or person
  committing from that clone.
- Keep VDOT feed tokens in SSM Parameter Store. Do not place them in source,
  Terraform variables, shell history, or this document.
- Keep the Cloudflare API token in SSM Parameter Store
  (`var.cloudflare_api_token_param_name`, `infra/ssm.tf`), same as the VDOT
  feed tokens. Never in a file. Fetch it immediately before a Terraform
  operation and let it die with the shell:
  `export CLOUDFLARE_API_TOKEN=$(aws ssm get-parameter --name /nova-toll/cloudflare-api-token --with-decryption --query Parameter.Value --output text --profile nova-toll)`
  Requires the `nova-toll` profile identity to have `ssm:GetParameter` on
  that parameter path -- an account/SSO-level grant, not something this
  repo's Terraform manages.
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

- RDS is still publicly reachable from the approved home-IP rule as of
  2026-07-27. Terraform to close this (Tailscale subnet router,
  `publicly_accessible = false`) is written but not applied — pending a
  manual one-time Tailscale setup step and a plan review. See
  `docs/tailscale-bridge-tasks.md`.
- Before a public agent launch, implement every control in the public-agent
  launch gate, including WAF throttling, concurrency/spend limits, a kill
  switch, output validation, and a dedicated read-only runtime role.
