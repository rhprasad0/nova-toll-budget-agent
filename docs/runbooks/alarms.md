# Launch alarm response

Every launch alarm notifies the existing `nova-toll-alerts` SNS topic. Treat an
alert as a rollout pause until its cause is understood; alarms are warnings, not
automatic scaling or public-traffic controls.

| Alarm | Trigger | First response |
| :-- | :-- | :-- |
| `tollchat-chat-proxy-errors` | Any timeout or uncaught proxy error in 5 minutes | Inspect the proxy log and correlated AgentCore traces; disable public chat if requests are failing. |
| `tollchat-chat-proxy-failures` | Any caught dependency or stream failure in 5 minutes | Confirm the browser received only the safe error, then inspect AgentCore and RDS health. |
| `tollchat-chat-proxy-latency` | p99 duration reaches 45 seconds | Compare active sessions and RDS alarms; pause rollout before the 50-second timeout is exhausted. |
| `tollchat-agentcore-active-sessions` | At least 10 sessions for 2 of 3 minutes | Compare proxy invocations and WAF metrics; disable public chat for unexplained demand. |
| `toll-freshness-i95` / `toll-freshness-i66` | No successful load for 30 minutes | Run `scripts/smoke.sh --fire`, inspect fetcher/loader logs and the failure queue, and keep serving the last-known-good snapshot. |
| `toll-rds-cpu` | CPU above 70% for 5 minutes | Inspect query activity and correlated proxy/loader traffic; pause rollout instead of resizing from one spike. |
| `toll-rds-free-memory` | Freeable memory below 64 MiB for 3 of 5 minutes | Check connections and query pressure; disable public chat if memory continues falling. |
| `toll-rds-connections` | At least 60 connections for 3 of 5 minutes | Check for leaked or idle sessions and stop traffic growth before PostgreSQL's 79-connection maximum. |
| `toll-rds-cpu-credits` | Fewer than 72 credits for 15 minutes | Pause rollout and investigate sustained CPU; resize only when load evidence supports it. |

Once the gate's OpenAI project budget alert is configured and its delivery is
confirmed, treat it as a **soft provider-spend warning**, not a hard cutoff. On
receipt, review provider usage and disable the public WAF route if spend is
unexpected; never claim that an AWS Budget controls OpenAI billing.

## Private load baseline and rollout limits

The 2026-08-09 private ceiling test ran five browser sessions for three requests
each while both feeds fetched and loaded. One validated alarm-recovery canary was
still active, so the observed AgentCore peak of six comprises that canary plus
the five load workers.

| Signal | Observed ceiling baseline | Rollout pause threshold |
| :-- | --: | --: |
| Client p99 latency | 15.47 seconds | 45 seconds |
| Proxy p99 duration | 15.19 seconds | 45 seconds |
| AgentCore active sessions | 6 | 10 |
| RDS CPU | 5.43% | 70% |
| RDS freeable memory | 83.16 MiB minimum | 64 MiB minimum |
| RDS connections | 0 sampled | 60 |
| RDS CPU credits | 288 minimum | 72 minimum |
| RDS read/write latency | 0.75 / 0.18 ms maximum | Baseline comparison only |
| RDS disk queue depth | 0.011 maximum | Baseline comparison only |
| Proxy, AgentCore, fetcher, and loader failures | 0 | Any failure |

Keep proxy reserved concurrency at **5** for the initial rollout. Pause expansion
on any alarm or threshold breach, and do not raise concurrency until a new
private test at the proposed ceiling passes the same gates. The baseline does
not justify an RDS resize; reassess through issue #95 only if later evidence
shows sustained pressure.

Run the repeatable check from an approved Tailscale client and curate its output
only when it exits successfully:

```bash
PREVIEW_URL=https://preview.tollchat.ai/ \
  uv run --frozen python scripts/load_test_private.py
```

## Delivery verification

Run `scripts/smoke.sh` to require a confirmed email subscription, publish a
metadata-only test, and verify all alarm states. For launch evidence, temporarily
set one non-breaching alarm to `ALARM`, confirm CloudWatch alarm history reports
successful SNS execution, and have the owner confirm receipt. Let CloudWatch
return the alarm to its metric-evaluated state. Record no recipient, account,
subscription, message, or provider identifiers in curated evidence.
