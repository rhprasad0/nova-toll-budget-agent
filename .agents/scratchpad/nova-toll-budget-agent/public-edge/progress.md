# Public edge progress

- [x] Requirements and design decisions captured
- [x] Isolated worktree created
- [x] Failing proxy and runtime tests written
- [x] Failing infrastructure tests written
- [x] Proxy and runtime implementation complete
- [x] Terraform public edge and WAF complete
- [x] Launch text reconciled
- [x] Focused validation passes
- [x] Full validation and security scan pass
- [x] Diff reviewed and simplified
- [x] Changes committed locally

## TDD log

- RED: runtime test collection fails because `InvocationLimits` and its caps do
  not exist; infrastructure assertions fail because no conditional public edge
  exists. The proxy test also confirmed the fresh worktree needs its ignored
  `npm ci` dependencies before behavior can execute.
- GREEN: 377 non-live Python tests and eight Node tests pass; Pyright, Ruff,
  Terraform validation, Gitleaks, and dedicated-role IAM simulations pass.
- RED: adversarial browser tests showed public POSTs omitted Lambda OAC's body
  hash and the public client could not consume the proxy's NDJSON stream.
- GREEN: public chat/reset hash their exact request payloads, chat parses tool
  and terminal NDJSON events, and focused Playwright coverage passes.
- REVIEW: the adversarial follow-up found both P1 fixes complete with no
  remaining actionable findings.
