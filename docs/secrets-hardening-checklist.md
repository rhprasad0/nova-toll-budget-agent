# Secrets Hardening for a Multi-Agent Repo

Status: in progress · Owner: Ryan Prasad · Last updated: 2026-07-27

This repo's production infra already handles secrets well — SSM `SecureString`
for feed tokens, RDS IAM auth with no static DB password, Secrets-Manager-managed
master password, KMS everywhere. The gaps are all at the local-dev/agent-facing
layer: an orphaned `.env` with live-looking, unread credentials, and a secret
scanner (`.gitleaks.toml`) that silently defined zero detection rules. Both were
found and verified during a 2026-07-27 review prompted by the question "how
should secrets work in a repo multiple coding agents operate in."

This closes [`pre-launch-checklist.md`](pre-launch-checklist.md)'s Tier 3 item
on `core.hooksPath` being opt-in (item 4 below), under the sharper motivation of
multi-agent coverage rather than just human onboarding — not duplicated there.

- [ ] **`.gitleaks.toml` defines zero rules.** No `[[rules]]` or `[extend]`
      table — gitleaks treats a supplied config as the entire ruleset unless
      told to extend the default. Verified empirically: a planted secret is
      caught with no config present, not caught with this repo's config. Add
      `[extend]` / `useDefault = true`, plus a custom rule for bcrypt-shaped
      tokens (`$2[aby]$NN$...`), which — separately verified — slip past the
      *default* ruleset too, even when a control secret in the same file is
      caught. Confirmed safe to flip: full history (68 commits) and the
      working tree both come back clean under the real ruleset, so this
      won't turn CI red with a backlog to triage.
- [ ] **`.gitignore` only covers the literal filename `.env`.** `.env.local`,
      `.envrc`, `*.tfvars` (root and `infra/`), and `.aws/` are all uncovered
      near-misses. Add them.
- [ ] **The only local secrets gate is Claude-Code-specific.** `.claude/hooks/gitleaks-guard.sh`
      fires on a `PreToolUse` hook matching Claude's own `Bash` tool calls —
      it does nothing for a terminal commit, a Codex session, or any future
      agent. `.githooks/pre-commit` (what `core.hooksPath` actually points
      git at) only runs lint/type/test. Move the gitleaks check there so it
      applies regardless of what's committing. `core.hooksPath` itself is
      local, uncommitted `.git/config` state — document `git config
      core.hooksPath .githooks` as a required setup step, and say plainly
      that CI (`gitleaks.yml`) remains the only gate nothing can bypass.
- [ ] **`.env` holds two live-looking API keys nothing reads.** Grepped the
      full repo and the sibling `hermes-agent` tool: zero references to
      `I95_API_KEY`/`I66_API_KEY`/`dotenv` anywhere in source. Strip both
      lines, replace with a comment pointing at the SSM parameters
      (`/nova-toll/i95-token`, `/nova-toll/i66-token`) that are the actual
      source of truth for the running system. Also migrate
      `CLOUDFLARE_API_TOKEN` — currently policy-documented in `SECURITY.md`
      as "password manager, supply as env var," never actually in a file —
      to the same SSM pattern (`aws_ssm_parameter` in `infra/ssm.tf`,
      mirroring `i95_token`/`i66_token` exactly).
- [ ] **No `.claude/settings.json` deny rules for secret-shaped files.** Add
      `Read`/`Edit` deny for `./.env`, `./.env.*`, `*.pem`, `*.key`,
      `~/.ssh/**`. Defense-in-depth only — known Claude Code enforcement
      gaps exist (anthropics/claude-code#24846, #6699), it doesn't cover
      subprocess/script reads, and the user-level settings already carry
      `skipDangerousModePermissionPrompt: true`. The item above (no live
      secret left to read) is what actually matters; this is what's left
      over for whatever else touches the filesystem.
- [ ] **No agent-facing secrets guidance anywhere.** Neither `AGENTS.md` nor
      `SECURITY.md`'s operating rules say anything about how an agent should
      handle a secret it encounters. Add short guidance, motivated by an
      actual incident from this review: two investigation subagents hit
      redaction bugs and briefly printed live key values into their own tool
      transcripts while "just checking" `.env`'s contents. Guidance: compare
      hashes/lengths, not raw values; never paste secret values into
      commits/PRs/chat; SSM is the source of truth, not a local file. One
      line on `.mcp.json` too — clean today (empty `env` block), should stay
      that way (GitGuardian found 24k+ secrets in public MCP configs in
      2026).
