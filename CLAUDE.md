Do all work in git worktrees so that multiple sessions do not collide.

When you find a bug, find and fix the root cause so that we are not stacking bandaids.

When Ryan corrects you, fix the mistake and add its rule to this table. Enforce it at the
highest level that works: structure first, then a check whose error names the fix, then a
test. Use prose only for judgment calls. Drop a rule once its mistake cannot happen.

| Rule | Enforced by |
| --- | --- |
| Work in a git worktree. | The pre-commit hook rejects commits from the main checkout once it has linked worktrees. |
| Fix root causes, not symptoms. | Nothing; judgment. |
| Set up each new worktree before committing. | `v2/scripts/setup.sh`; the pre-commit hook fails on a missing tool. |
| Run what CI runs. | `.github/scripts/verify.sh` is what CI calls; `test_ci_jobs_run_verify` fails on a `ci.yml` job that bypasses it. The pre-push hook runs its `quick` subset. |
| Changes reach `main` by a PR that passes CI. | Branch protection. |
| Keep shared-resource changes out of application releases. | `v2/scripts/infrastructure_plan.py` in `verify.sh` fails on planned-value changes; it cannot see IAM policy text. List hand-applied addresses in `v2/infra/administrator-applied.txt`. |
| Write a check, not Markdown: no new Markdown files. Point docs at the code that owns a value instead of copying it. When a judgment call needs nuance, ask Ryan instead of writing it down. | `v2/tests/test_documentation.py` fails on a new Markdown file (journal pages excepted) and on broken links, anchors, runbook target lists and skill step names. Whether new prose is a rule is judgment. |
| Do not write code comments. | Nothing; judgment. |
| Test infrastructure by planned values, not Terraform text. | The `development_plan` fixture. A ratchet test fails on new `assert_assignment` or `terraform_block` matches; plain `in` text matches are not counted. |
