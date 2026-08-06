# TollChat rollback

1. Set the proxy Lambda concurrency to `0` using the kill-switch runbook.
2. Select the last reviewed AgentCore zip from the versioned artifact record or rebuild the corresponding Git commit.
3. Run `terraform plan` with all four real package paths and verify only the runtime artifact/version and expected dependent endpoint change.
4. Apply after owner approval, exercise `/api/config`, one known toll query, the disclaimer check, and the no-leak checks through Tailscale.
5. Restore proxy concurrency to `5` and record the deployed Git commit and artifact digest.

Do not roll back the database, raw feed objects, or Terraform state as part of an agent rollback.
