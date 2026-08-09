# TollChat kill switch

The service-wide switch sets reserved concurrency on `tollchat-chat-proxy` to
zero. AWS then throttles every private and public proxy invocation without
stopping the toll fetcher, loader, or RDS. Terraform intentionally ignores concurrency drift for this function so a normal apply cannot undo the switch.

## Authorized private drill

Run only from the repository worktree on an approved Tailscale client. The
admin must give **explicit approval** immediately before execution.
Reserve a 15-minute private-preview outage, stop other Terraform operations,
and keep a second terminal ready for the emergency restore command below.

Before starting:

1. Open `https://preview.tollchat.ai/` in the browser and leave the page loaded.
   Reloading after engagement cannot work because the proxy also serves the
   private page.
2. Build the exact four deployment packages and run the read-only preflight:

   ```bash
   ./scripts/build_zips.sh
   uv run --frozen python scripts/drill_kill_switch.py
   ```

3. Confirm the preflight prints `"status": "ready"` and baseline concurrency
   `5`. Do not continue after any failure or unexpected Terraform drift. The
   runner permits only AWS's two behavior-preserving API policy ARN
   normalization updates; every other planned change aborts the drill.

After the admin says go, run:

```bash
report="$(mktemp)"
trap 'rm -f "$report"' EXIT
uv run --frozen python scripts/drill_kill_switch.py \
  --execute --approved-by Admin --pause-for-screenshot >"$report" &&
  uv run --frozen python -m json.tool "$report" >/dev/null &&
  mv "$report" "eval/results/$(date -u +%Y%m%dT%H%M%SZ)-kill-switch-drill.json"
```

The runner records start and restore timestamps, captures the live concurrency
baseline, and restores that exact value in `finally`. While engaged it proves
both private API routes are blocked, no AgentCore invocation is produced, a
controlled fetcher run loads both feeds into RDS, every pipeline alarm stays
healthy. The runner rejects Lambda handler failures and correlates loader
successes to uniquely suffixed objects from that exact fetcher invocation, so
scheduled polls cannot satisfy the drill. The saved Terraform plan must be a
no-op or contain only those two
exact policy normalizations, and the following apply must leave concurrency at zero. The
Cloudflare token is read from SSM Parameter Store directly into the Terraform
subprocess environment; it is never written to a file or report.

At the screenshot pause, keep the already-loaded branded preview beside the
sanitized terminal summary. Trigger **New chat** if the unavailability notice
is not already visible. Capture both the notice and these terminal lines:

```text
TOLLCHAT KILL-SWITCH — ENGAGED
Config endpoint          BLOCKED
Chat endpoint            BLOCKED
AgentCore invocations    0
Toll ingestion           HEALTHY
RDS                      HEALTHY
Terraform apply          SWITCH PRESERVED
Automatic restore        ARMED
```

Do not include AWS account/caller identifiers, browser developer tools,
cookies, prompts, answers, request/session/trace identifiers, or database
endpoints. Press Enter immediately after the screenshot. The runner restores
concurrency and then runs the canonical private smoke; recovery does not pass
unless the browser path, AgentCore tool call, historical `$12.15` RDS result,
and disclaimer all pass.

Only a successful final JSON file belongs in `eval/results/`. Update
`eval/results/README.md` with its measured disable/recovery times, then run
`gitleaks git --pre-commit --redact .` before committing. Delete
failed or superseded reports; external outages never waive a fresh passing
rerun.

### Last successful private drill

The authorized 2026-08-09 drill confirmed the switch in **2.3 seconds** and
restored concurrency `5` plus the canonical private smoke in **21.4 seconds**.
Both private API routes were blocked with zero AgentCore invocations while
ingestion and RDS stayed healthy, and Terraform preserved the switch. See the
[metadata-only report](../../eval/results/20260809T193920Z-kill-switch-drill.json).

### Emergency restore

Interrupting the runner normally still executes restoration. If the terminal,
host, or network disappears, run this from the second approved client and
verify the result is the captured baseline (`5` for this drill):

```bash
AWS_PROFILE=nova-toll aws --region us-east-1 lambda put-function-concurrency \
  --function-name tollchat-chat-proxy --reserved-concurrent-executions 5
AWS_PROFILE=nova-toll aws --region us-east-1 lambda get-function-concurrency \
  --function-name tollchat-chat-proxy
```

Escalate immediately if restoration exceeds 60 seconds or cannot be confirmed
after three attempts. Block public chat at WAF, preserve the Terraform lock,
and do not retry the drill until AWS access and the private smoke test are
healthy.

## Incident use

For suspected service-wide harm, set concurrency to zero with the first
emergency command but substitute `0`, verify both private API routes fail, and
record the incident start time. Restore the last approved baseline only after
admin approval, then run the canonical private smoke. Never place credentials
or response content in an incident record.

## Public switch

Public chat is declaratively enabled. Its immediate switch is the
`tollchat-public-chat` CloudFront WAF
default action: change `Allow` to the existing `unavailable` custom `Block`
response with status `503`, verify public `/api/config` returns 503 while the
static site and private preview remain available, then restore `Allow` only
after admin approval. To remove the public path declaratively, apply
`enable_public_chat=false`; CloudFront removes `/api/*` while the private path
remains governed by proxy concurrency.
