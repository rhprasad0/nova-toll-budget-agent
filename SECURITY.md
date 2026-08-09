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
  data, Terraform state, and deployment artifacts, with log-file validation in
  a dedicated audit bucket.
- CI actions are pinned to immutable SHAs with read-only repository
  permissions. Secret scanning runs in CI (`gitleaks.yml`, full history on
  every push/PR) and locally in `.githooks/pre-commit` (staged files, any
  committer) once `core.hooksPath` is set per the operating rule below; its
  single allowlist entry is the PostgreSQL `EXCLUDED` pseudo-table false
  positive. CI is the gate nothing can bypass -- the local hook is a
  fast-fail courtesy that only applies to clones that have opted in.
- The Lambda build verifies the downloaded RDS CA bundle SHA-256 before
  packaging it.
- Successful trusted-main deployments retain all four reviewed package ZIPs
  and their SHA-256 manifest in the private, versioned AgentCore artifact
  bucket. Release prefixes include the Git commit and manifest digest; the
  workflow uploads and downloads-verifies the complete set before apply, then
  advances `reviewed/latest` only after apply succeeds. Reviewed versions never
  expire, CloudTrail supplies an independently validated publication record,
  and rollback requires an explicitly approved prior release ID. It rejects
  missing or mismatched packages instead of rebuilding them.

## Implemented hardening (2026-07-27)

- RDS is no longer publicly accessible. The only network paths to it are
  the loader Lambda's security group and a Tailscale subnet router
  (`infra/tailscale.tf`), replacing the prior static home-IP ingress rule.
  Confirmed live: a direct public connection attempt now times out.
- GitHub Actions authenticates to AWS via OIDC (`nova-toll-github-ci`,
  `infra/iam.tf`) rather than long-lived credentials, scoped to
  `ssm:GetParameter` for the OpenAI key, `rds-db:connect` as the read-only
  `pricing_reader` role, and `rds:DescribeDBInstances`. Its workflow gate
  and OIDC `sub` trust condition both allow only the exact `main` push, so
  unreviewed branch and pull-request code cannot obtain these credentials.
- The tailnet ACL (`policy.hujson`) is managed via GitOps
  (`.github/workflows/tailscale-acl.yml`, `tailscale/gitops-acl-action`)
  rather than hand-edited in the console: PRs run policy `tests` only, pushes
  to `main` apply. The `tests` assert the owner's access and the RDS route
  survive any future edit, and that `tag:ci` can never reach the general
  internet through the subnet router's exit-node capability.
- Terraform CI (`.github/workflows/terraform.yml`) keeps pull-request
  feedback credential-free (`fmt`, `init -backend=false`, and `validate`).
  Only pushes to `main` run credentialed `apply` through the dedicated
  `nova-toll-terraform-apply` role, whose trust is scoped to
  `ref:refs/heads/main`. The apply role is admin-equivalent because this
  repo's own Terraform manages IAM — a curated set of service-scoped policies
  would still need `IAMFullAccess` to manage `infra/iam.tf`, at which point it
  could attach `AdministratorAccess` to anything anyway. The real boundary is
  the trust policy's branch restriction, not the permission policy. The
  Cloudflare API token remains on its own dedicated KMS key (`infra/kms.tf`),
  isolated from the VDOT feed tokens and Tailscale authkey.

## Implemented hardening (2026-08-01)

- Nightly simulated-user evaluations use a dedicated GitHub OIDC role trusted
  only for `main`. Its permissions are limited to the read-only pricing path,
  the two required SSM parameters, and the tagged Claude Haiku application
  inference profile plus its underlying regional models. The workflow cannot
  invoke arbitrary Bedrock models.
- Bedrock evaluation costs are attributed through an application inference
  profile tagged `project=nova-toll-budget-agent` and
  `purpose=nightly-eval`; the payer account must activate the `purpose`
  cost-allocation tag before it appears in Cost Explorer or CUR.

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
- Both OpenAI and Bedrock Mantle use stateful Responses, so provider-side
  retention must be reviewed before public launch. Local tool auditing uses
  the response `metrics.traces`, not Strands' empty stateful message history.
- Keep the Cloudflare API token in SSM Parameter Store at
  `/nova-toll/cloudflare-api-token`, on its dedicated KMS key. Terraform does
  not manage this parameter or its value; provision and overwrite it
  out-of-band through the AWS console. Never put it in a file. Fetch it
  immediately before a Terraform operation and let it die with the shell:
  `export CLOUDFLARE_API_TOKEN=$(aws ssm get-parameter --name /nova-toll/cloudflare-api-token --with-decryption --query Parameter.Value --output text)`
  Requires the identity running it to have `ssm:GetParameter` and
  `kms:Decrypt` on that parameter's key -- an account/SSO-level grant for
  local use (`AWS_PROFILE=nova-toll`) or
  `nova-toll-terraform-apply`'s scoped grant in CI.
- `infra/ssm.tf` retains a non-destructive `removed` block only to hand off
  the existing parameter from Terraform state. After a trusted-main apply has
  completed that handoff, create a new least-privilege Cloudflare token,
  overwrite the existing SSM parameter, validate a trusted Terraform plan,
  then revoke the old token. Treat every retained Terraform-state version as
  potentially exposed; do not inspect secret-bearing state just to audit it.
  Review and restrict S3 state-bucket readers and its KMS decrypt principals
  to the least privilege needed.
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
- Agent deployment keeps the OpenAI key in SSM Parameter Store and restricts
  the runtime to read that one parameter, connect to RDS only as
  `pricing_reader`, and apply the designated Bedrock Guardrail. Private preview
  traffic enters through the existing Tailscale subnet router and an internal
  private API Gateway custom domain; API and domain policies require the
  execute-api VPC endpoint, while direct runtime invocation requires the
  separate AgentCore VPC endpoint.
- Public chat routing is present but disabled by default. Enabling it before
  every launch-gate item has evidence is an operating-policy violation.
