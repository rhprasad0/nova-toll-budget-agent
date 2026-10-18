# Development release bring-up (#331, #307) [historical, completed]

The one-time development-account bring-up is complete: the 4via6 route and
router handoff (slices 2A/2B), the `dev.tollchat.ai` custom domain and DNS
cutover (slice 3), and the #307 development trace archive bootstrap. Ordinary
development releases now run through automatic protected delivery; see the
[runbook](../RUNBOOK.md) and the
[blue-green procedure](blue-green-deployments.md).

**Do not run the historical procedures.** They remain in
[Git history before this cleanup](https://github.com/rhprasad0/nova-toll-budget-agent/blob/ed784c8e/v2/runbooks/development-release.md).
The "Keep trace archives" section below is current.

## Keep trace archives

Since October 2026, `agentcore-traces/` has no expiration rule in either
environment: the archive keeps impact-study and public traces indefinitely, as
`privacy.txt` states. CloudWatch retention is unchanged. The lifecycle is a
shared resource that release delivery rejects (`phase_boundary`), and the
production delivery role cannot write it, so an administrator applies it once
per environment. Each environment briefly keeps traces while its served notice
still says seven days, until its next release; that lag is accepted. With no
expiry the unpartitioned trace table grows, so full scans will eventually hit
the 1 GiB Athena cutoff; filter by time or add partitions then.

1. Before applying, confirm with `aws s3api get-bucket-lifecycle-configuration`
   that the bucket has exactly the `expire-raw-waf-logs`,
   `expire-athena-results`, and `expire-agentcore-traces` rules. List
   `agentcore-traces/` keys and dates only (never payloads) and stop if any
   object is more than about seven days old: removing the rule unschedules
   overdue expirations, so such objects would be kept forever.
2. Prepare a private saved Terraform plan from the reviewed source, with the
   currently deployed packages and that environment's backend and account
   (development `903859731897`, production `920534282028`). Target only
   `aws_s3_bucket_lifecycle_configuration.agent_measurement`. Require exactly
   one in-place update that removes `expire-agentcore-traces`, with the other
   two rules and every dependency-expanded address unchanged. Apply that exact
   file. Then sync state: the bucket's computed `lifecycle_rule` still records
   the previous rules, which release gates reject as `incomplete_or_drift`.
   Save a `-refresh-only` plan targeting the bucket and its lifecycle
   configuration, require exactly one drift entry
   (`aws_s3_bucket.agent_measurement`, `lifecycle_rule` only) and no resource
   changes, and apply that exact file. A second refresh-only plan with the same
   targets must show no drift. The PR's `trusted-development-plan` check passes
   either way, so it is not evidence that the sync ran.
3. Development: apply from the reviewed PR head **before merge**. The trusted PR
   plan then sees main's old rule as the trace-enable transition that
   `infra/delivery_plan_validator.py` accepts, and post-merge delivery sees a
   no-op. After the apply, re-run the PR's `trusted-development-plan` check and
   merge only when it is green; otherwise apply main's rule back the same way.
   Merging first instead fails delivery with `phase_boundary` and fails every
   trusted PR plan, reverts included, until the apply. Merge no other PR between
   the apply and this merge. If the PR is abandoned, apply main's rule back the
   same way.
4. Production: after merge, confirm no production recovery is pending (its
   recover phase would then fail with `phase_boundary`), apply, and start the
   next protected production release right away so tollchat.ai serves the
   updated notice. That release otherwise fails with `phase_boundary`.
5. Verify the bucket lists two rules and that the served `privacy.txt` says
   traces are kept indefinitely. About eight days later, list keys and dates
   only and confirm that objects older than seven days remain.
