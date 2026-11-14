Do all work in git worktrees so that multiple sessions do not collide.

When you find a bug, find and fix the root cause so that we are not stacking bandaids.

When Ryan corrects you, fix the mistake and add its rule to this table. Enforce it at the
highest level that works: structure first, then a check whose error names the fix, then a
test. Use prose only for judgment calls. Drop a rule once its mistake cannot happen.

| Rule | Enforced by |
| --- | --- |
| Work in a git worktree. | Nothing; judgment. |
| Fix root causes, not symptoms. | Nothing; judgment. |
| Set up each new worktree before committing. | `v2/scripts/setup.sh`; the pre-commit hook fails on a missing tool. |
| Run what CI runs. | `.github/scripts/verify.sh` is what CI calls; the pre-push hook runs its `quick` subset. |
| Changes reach `main` by a PR that passes CI. | Branch protection. |
| Keep shared-resource changes out of application releases. | `v2/scripts/infrastructure_plan.py` in `verify.sh`; exceptions in `.github/administrator-applied-infrastructure`. |
