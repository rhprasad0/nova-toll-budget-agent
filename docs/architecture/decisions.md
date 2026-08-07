# AgentCore deployment decisions

**Status:** implemented in Terraform; deployment remains owner-gated.

- **Private preview:** `preview.tollchat.ai` resolves to an internal ALB. Its security group accepts HTTPS only from the existing Tailscale subnet router. The ALB redirects `/` to the public static site in preview mode and forwards only `/api/*` to the proxy.
- **Invocation path:** a VPC-attached Lambda validates the browser contract and signs AgentCore data-plane calls with its dedicated IAM role. The runtime resource policy also requires the private AgentCore VPC endpoint (`aws:SourceVpce`). ALB-to-endpoint-IP targeting was rejected because interface endpoint addresses are not a stable application protocol or target contract.
- **Public launch:** anonymous access may later use the existing CloudFront distribution, an opt-in VPC origin, and WAF. `enable_public_chat` defaults to `false`.
- **Credentials:** `/nova-toll/openai_api_key` remains a SecureString in SSM Parameter Store. It is read at runtime by the dedicated AgentCore role and is never copied into Terraform state or an AgentCore credential provider.
- **Sessions:** state exists only in the AgentCore microVM. Sessions allow five turns, idle after 15 minutes, and expire after 60 minutes. AgentCore Memory is not enabled.
- **Availability:** two private subnets support the ALB and runtime. One NAT gateway is intentional for the private preview; add one per AZ before an availability SLO requires it.
- **Private-preview traces:** retain every invocation for 30 days using split AgentCore telemetry. Native spans redact message/system content; correlated application records contain sanitized prompts, responses, model messages, tools, and full Guardrail assessments. System-prompt text is excluded and represented only by its version.
- **Guardrail boundary:** because TollChat invokes OpenAI rather than a Bedrock model, it uses the standalone `ApplyGuardrail` API instead of Converse `guardrailConfig` or selective `guardContent` blocks. INPUT uses HIGH prompt-attack filtering; INPUT and OUTPUT use MEDIUM hate, violence, sexual, insults, and misconduct filtering. Both blocked paths return only “I can only help with Northern Virginia toll road estimates.” Production pins a tested numbered version, retains prior numbered versions, and never sends a guardrail `trace` option; `outputScope=FULL` assessments stay inside the governed trace path.
- **Guardrail version baseline:** version 2 is the retention baseline. Version 1 was removed during the one-time lifecycle migration because its prior Terraform state did not yet include `skip_destroy`.
- **IaC:** Terraform owns AWS resources. The one provider gap—AgentCore resource policies—is reconciled by `terraform_data` using the documented control-plane CLI command.
- **Frontend:** the existing dependency-free map page contains a progressively disclosed, accessible chat. It stays hidden unless `/api/config` succeeds.

## Public-launch decisions still required

- Owner approval of the legal drafts and runbooks.
- A real **OpenAI project budget/limit**. AWS Budgets cannot cap charges billed directly by OpenAI; presenting an AWS-only budget as an OpenAI kill switch would be security theater.
- Verified telemetry retention/redaction, WAF tests, IAM simulation, alarm delivery, rollback, and end-to-end evaluation evidence.
