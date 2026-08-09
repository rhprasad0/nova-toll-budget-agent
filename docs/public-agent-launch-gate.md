# Public agent launch gate

**Status:** blocked; this repository does not deploy a public agent.
**Owner:** Ryan Prasad · **Last updated:** 2026-08-09

The private-preview implementation now exists on branch
`feat/agentcore-private-preview`, but no item below is complete until an
authorized deployment produces reviewable evidence. Public routing remains
disabled by Terraform default.

This is the authoritative checklist for exposing TollChat to internet traffic.
Every unchecked item blocks launch.

## Runtime and spend

- [ ] Deploy the AgentCore runtime with a private path to RDS. The current
      infrastructure permits only the loader and Tailscale subnet router.
- [ ] Put the API behind AWS WAF: limit each IP address to 20 requests per five
      minutes and reject oversized request bodies.
- [ ] Cap turns and tokens per session, reserve at most five concurrent
      executions, alarm at $10/day of Bedrock spend, and provide an audited
      kill switch that disables public invocation.
- [ ] Give the runtime a dedicated role that can invoke only the approved model
      and connect only as `pricing_reader`; do not grant S3, secret, database
      write, or administrative access.

## User and data safety

- [ ] Validate the public response shape and expose no tool-selection,
      stack-trace, database, or infrastructure details.
- [ ] Log redacted request metadata, tool outcomes, and denials. Never log
      credentials, IAM tokens, connection strings, or raw prompts containing
      personal data.
- [ ] Publish terms and a privacy policy describing collected data and its
      retention period.
- [ ] Keep a visible “estimates only—verify with the toll operator” disclaimer
      and identify the chat as an AI assistant.

## Operations

- [x] Drill the service-wide private kill switch. The 2026-08-09 drill blocked
      both private API routes in 2.3 seconds with zero AgentCore invocations,
      kept ingestion and RDS healthy through Terraform apply, and restored
      concurrency `5` plus the canonical smoke in 21.4 seconds. Escalate if
      recovery exceeds 60 seconds or cannot be confirmed after three attempts.
- [ ] With public chat temporarily enabled under owner approval, prove the WAF
      switch returns 503, then apply `enable_public_chat=false` and prove
      CloudFront removes `/api/*` without changing private proxy governance.
- [ ] Make the SNS subscription address and `scripts/smoke.sh` instruction
      agree, confirm the subscription, and test delivery.
- [ ] Record when each route oracle was retrieved and define a manual
      re-verification cadence.
- [ ] Retain a known-good deployment artifact for rollback.

Launch review must pass WAF throttling, IAM policy simulation, response-shape,
cost-alarm, kill-switch, alarm-delivery, and end-to-end agent tests.
