# Secrets Hardening for a Multi-Agent Repo

Status: all items landed on `worktree-secrets-hardening`, pending merge · two follow-ups open · Owner: Ryan Prasad · Last updated: 2026-07-27

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

- [x] **`.gitleaks.toml` defines zero rules.** No `[[rules]]` or `[extend]`
      table — gitleaks treats a supplied config as the entire ruleset unless
      told to extend the default. Verified empirically: a planted secret is
      caught with no config present, not caught with this repo's config.
      Fixed with `[extend]` / `useDefault = true`. Confirmed safe: full
      history (68 commits) and the working tree both come back clean under
      the real ruleset, no backlog to triage.
      A second, previously-invisible bug surfaced once real rules actually
      ran: the existing `[allowlist]` regex (`s3_key = EXCLUDED`) checks
      against gitleaks' *captured secret value* (the RHS, e.g.
      `EXCLUDED.s3_key`), not the full matched line — so it never actually
      matched anything; it only looked like it worked because the ruleset
      was empty. Fixed to `EXCLUDED\.\w+`, which also generalizes it to any
      `EXCLUDED.<column>` reference instead of just `s3_key`.
      A custom rule for bcrypt-shaped tokens (`$2[aby]$NN$...` — separately
      verified to slip past the *default* ruleset even when a control
      secret in the same file is caught) was attempted and dropped: on the
      installed gitleaks version (8.30.1), a local `[[rules]]` entry
      silently fails to merge when `[extend].useDefault` is also set —
      confirmed via isolated repro, matches a known class of upstream
      extend-merge bugs (gitleaks/gitleaks#1844, #1742, #1523). Shipping a
      rule that looks configured but doesn't fire would repeat the exact
      failure this item exists to fix. The real mitigation for this
      credential shape is the item below (don't leave it in a plaintext
      file at all), not a scanner rule.
- [x] **`.gitignore` only covers the literal filename `.env`.** `.env.local`,
      `.envrc`, `*.tfvars` (root and `infra/`), and `.aws/` were all
      uncovered near-misses. Added and verified each with `git check-ignore -v`.
- [x] **The only local secrets gate is Claude-Code-specific.** `.claude/hooks/gitleaks-guard.sh`
      fires on a `PreToolUse` hook matching Claude's own `Bash` tool calls —
      it did nothing for a terminal commit, a Codex session, or any future
      agent. Added the same `gitleaks protect --staged --redact` check to
      `.githooks/pre-commit`, so it applies regardless of what's
      committing. Verified in an isolated scratch repo (not this one): a
      staged secret is blocked, a clean commit goes through. Documented
      `git config core.hooksPath .githooks` as a required per-clone setup
      step in `SECURITY.md`, and stated plainly there that CI
      (`gitleaks.yml`) remains the only gate nothing can bypass —
      `core.hooksPath` is local, uncommitted `.git/config` state.
- [x] **`.env` holds two live-looking API keys nothing reads.** Grepped the
      full repo and the sibling `hermes-agent` tool: zero references to
      `I95_API_KEY`/`I66_API_KEY`/`dotenv` anywhere in source. Removed both
      lines directly (via `sed` matching on key name only, never reading or
      printing the values into any tool transcript) and replaced with a
      comment pointing at the SSM parameters (`/nova-toll/i95-token`,
      `/nova-toll/i66-token`) that are the actual source of truth. Re-ran
      the consumer grep after — still zero hits.
      Also migrated `CLOUDFLARE_API_TOKEN` — previously policy-documented
      in `SECURITY.md` as "password manager, supply as env var," never
      actually in a file — to the same SSM pattern: added
      `aws_ssm_parameter.cloudflare_api_token` to `infra/ssm.tf` and
      `cloudflare_api_token_param_name` to `infra/variables.tf`, mirroring
      `i95_token`/`i66_token` exactly. `terraform plan -target=` confirms a
      clean single-resource add. `SECURITY.md`'s operating rule now points
      at SSM with the fetch-before-apply command instead of "password
      manager, env var."
- [x] **No `.claude/settings.json` deny rules for secret-shaped files.** Added
      `Read`/`Edit` deny for `./.env`, `./.env.*`, `*.pem`, `*.key`,
      `~/.ssh/**`, `~/.aws/**` (JSON syntax validated). **Enforcement not
      verified** — known Claude Code deny-rule bugs exist
      (anthropics/claude-code#24846, #6699), and testing this properly
      needs a fresh session rooted at the updated settings file, which
      isn't something this session could cleanly self-check (the active
      settings for this running session are the main worktree's, not this
      branch's copy, until merged). **Action for you**: after merging, open
      a new Claude Code session in this repo and try to have it read
      `.env` — confirm it's actually refused rather than assuming the
      config works. Regardless of outcome, it doesn't cover
      subprocess/script reads, and the user-level settings already carry
      `skipDangerousModePermissionPrompt: true`. The item above this one
      (no live secret left to read) is what actually matters; this is what's
      left over for whatever else touches the filesystem.
- [x] **No agent-facing secrets guidance anywhere.** Neither `AGENTS.md` nor
      `SECURITY.md`'s operating rules said anything about how an agent
      should handle a secret it encounters. Added a Secrets section to
      `AGENTS.md` (applies to any agent that reads it, not just Claude
      Code), motivated by the actual incident from this review: two
      investigation subagents hit redaction bugs and briefly printed live
      key values into their own tool transcripts while "just checking"
      `.env`'s contents. Guidance: compare hashes/lengths, not raw values;
      never paste secret values into commits/PRs/chat; SSM is the source of
      truth, not a local file; keep `.mcp.json`'s `env` block free of
      literal secrets (confirmed still empty today). `SECURITY.md`'s
      operating rules cross-reference it.

## Follow-up (not this pass)

- [ ] Confirm `.claude/settings.json` deny rules actually block a `.env`
      read in a fresh session — see the caveat above.
- [ ] Once comfortable, merge this branch and delete the worktree.
