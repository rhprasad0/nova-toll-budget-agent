# Single-AZ endpoints and router NAT

Both environments retain their existing private subnets and single-AZ RDS.
The three interface endpoints use only `us-east-1c`. Private HTTPS egress uses
the existing Tailscale EC2 primary ENI, then its public IPv4 and internet gateway.
Internet requests do not traverse another Tailscale node. S3/DynamoDB gateway
endpoints, warm Lambda, Tailscale routes and production exit-node use remain.

This deliberately accepts one router as a failure point. Both private CIDRs
(`172.31.224.0/24`, `172.31.225.0/24`) may forward TCP/443. Separate nftables rules
preserve Tailscale's chains and block other forwarding on the physical interface.
The router's existing public IPv4 remains billable; managed NAT and its separate
Elastic IP are removed. Cross-AZ traffic from subnet `1a` can still incur charges.

## Review and prerequisites

Merge the reviewed PR after required CI and human review. Use that exact checkout
and its locked providers; never use these steps to deploy an unreviewed checkout.
Run `bash v2/scripts/test_router_nat.sh`, Terraform validation for both roots, and
`uv run --project v2 pytest v2/tests/test_router_nat.py v2/tests/test_infrastructure_contract.py`.
The Docker test uses real Linux packet forwarding and Tailscale-equivalent rules;
it simulates lost kernel state and executes the persisted service, not a VM reboot.

Deploy development completely before production. The fixed identities are:

| Environment | Profile | Account | Foundation state key |
|---|---|---|---|
| Development | `nova-toll-dev` | `903859731897` | `nova-toll/development/terraform.tfstate` |
| Production | `nova-toll-prod` | `920534282028` | `nova-toll/terraform.tfstate` |

Each bucket is `nova-toll-tfstate-<account>`, region `us-east-1`, KMS alias
`alias/nova-toll-tfstate`, with encryption and S3 locking enabled. Verify STS
identity before each operation. Confirm the unique running
`nova-toll-tailscale-router` is in the public default subnet in `us-east-1c`, has
a public IPv4 and an IGW route, and is SSM Online. Record its instance and primary
ENI IDs. Check current forwarding rules and private routes. Do not retrieve the
Tailscale auth key; existing-node setup never re-enrolls the router.

Build `v2/scripts/build_fetcher_zip.sh` and preserve the deployed fetcher digest.
Supply the existing budget recipient through `TF_VAR_budget_notification_email`
in process memory. Development must also retain its existing
`TF_VAR_development_final_snapshot_identifier` from private state, preventing an
unrelated RDS update. Keep the existing route-advertisement input (`true` for the
reviewed, enrolled nodes). Do not print state, plan JSON, budget values or secrets.

## Configure, plan and apply

1. Prepare a private mode-0700 temporary directory on tmpfs for plan artifacts
   and logs, with `umask 077` and shell tracing disabled. Keep Terraform plugins
   on executable disk. Copy the reviewed foundation root, including
   `router-nat.tf`, the lockfile and fetcher artifact. Initialize the matching
   fixed backend with `-lockfile=readonly`; never use `-upgrade`.
2. Configure the verified existing router via SSM `AWS-RunShellScript`. Export
   the shared local from the initialized reviewed root using
   `terraform console <<< 'jsonencode(local.router_nat_setup)' | jq -r fromjson`
   into a private temporary script. Generate parameters with
   `jq -n --rawfile script <private-script> '{commands:[$script],executionTimeout:["180"]}'`
   and pass the private parameters file to `aws ssm send-command`. Specify the verified
   single instance ID and profile. Wait for completion and require `Success`.
   The shared script installs nftables if needed, validates its own table,
   enables persistent forwarding and the `tollchat-nat` service, and loads it.
   Repeat setup is safe. Check service status, table rules, and Tailscale access.
3. Generate one saved full foundation plan with `environment`,
   `tailscale_advertise_routes=true`, and `fetcher_package_path=build/fetcher.zip`,
   preserving the runtime inputs above. Stream `terraform show -json <plan>` to
   `python3 v2/scripts/validate_router_nat_plan.py --environment <environment>`.
   Expected first-apply counts: **2 creates, 5 updates, 2 deletes**. Review the
   private plan independently and record its SHA-256 and reviewed source commit.
   Existing computed drift is visible for review; unrelated planned mutations,
   replacements, failed checks and unknown target identities are rejected.
4. Stop on unrelated changes. Resolve them separately with explicit review;
   do not widen this validator, hide them with targeting, or use `-refresh=false`.
   Recheck identity and the reviewed plan digest, then apply **that saved plan**.
   No fresh implicit plan, application release, or database migration is part of
   this operation. Terraform changes source/destination checks without restarting
   the router; boot-script changes are intentionally ignored on existing nodes.
5. Verify HTTPS from private workloads, chat/AgentCore operation, all three
   endpoints, Tailscale database connectivity and route isolation. In production
   also check exit-node access. Verify no managed NAT/EIP remains, each interface
   endpoint has only subnet `1c`, the default route targets the recorded router
   ENI, and gateway endpoint routes remain. Require a zero-change full foundation
   follow-up plan before advancing. Record only sanitized results and counts.
6. Remove private plan/log/parameter files and unset runtime inputs. Confirm
   actual cost reduction in subsequent billing data rather than claiming an
   estimate as observed savings.

## Recovery

SSM remains reachable through the router's own public connection. On failure,
inspect `systemctl status tollchat-nat`, `journalctl -u tollchat-nat`, and
`nft list table ip tollchat_nat`; correct and reapply the reviewed setup script.
Do not flush the complete firewall or re-enroll Tailscale. If restoring managed
NAT is necessary, review a separate saved recovery plan; the released Elastic
IP is not guaranteed to be recoverable. Preserve database data and network
isolation even when accepting downtime.
