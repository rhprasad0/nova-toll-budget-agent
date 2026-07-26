# Public agent launch gate

This repository does not yet deploy a public agent. Before TollChat accepts
internet traffic, the deployment must meet every control below.

- Put the API behind AWS WAF and enforce a rate-based rule of **20 requests per
  IP address per five minutes**. Reject oversized request bodies at the edge.
- Keep the service anonymous, but set execution reserved concurrency to **5**,
  create a **$10/day** Bedrock cost alarm, and provide an audited manual kill
  switch that disables public invocation.
- Run the agent with a dedicated role: invoke only the approved Bedrock model
  and connect to RDS only as `pricing_reader`. It must not receive S3, Secrets
  Manager, administration, or write permissions.
- Log request metadata, tool outcomes, and denials with redaction. Never log
  credentials, IAM tokens, raw prompts containing personal data, or database
  connection strings.
- Treat model output as untrusted. The public API must return a constrained,
  validated response shape and must expose no tool-selection, stack-trace, or
  infrastructure detail.

The launch review must verify these controls with a WAF-throttling test, an IAM
policy simulation, a cost-alarm test, and kill-switch exercise.
