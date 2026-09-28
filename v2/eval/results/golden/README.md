# Golden release metadata

This directory retains versioned policies and historical approval/registry records.
The active [private production gate](../../GOLDEN_RELEASE.md) uses `policy-4.0.0.json`,
which remains pending until private authoring, calibration, and human approval.
Protected GitHub approval attests the result; no signing key or held-out cases
belong here. Historical signed policies and receipts remain unchanged.
The historical initial archive is summarized in the journal; focused synthetic
fixtures cover offline report compatibility. The retired `golden_baseline` CLI
is no longer part of the release path. A production reference is not required.

The [experiment journal](../../EXPERIMENT_JOURNAL.md) records prior results and
decisions. Keep development output in ignored `eval/private/` or the existing
private workflow artifact store. The external evaluator retains held-out details;
only aggregate JSON reports cross into the release workflow. Publish only
journal summaries, never new per-run review packets in this directory.

Earlier retired artifacts remain recoverable from commit
[`19fb7fa`](https://github.com/rhprasad0/nova-toll-budget-agent/tree/19fb7faed8fee2c286bf71d6e2f92f27fe33e352/v2/eval).
The remaining demonstration and calibration archives removed in the 2026-09-26
cleanup remain recoverable from
[`e2b7d4b`](https://github.com/rhprasad0/nova-toll-budget-agent/tree/e2b7d4b5514ce3f0228d2556ab197f0c1c38ec1a/v2/eval).
Policies and recorded approvals retain their original identities. The new policy
does not reset spending, approve a private corpus, or retroactively change
historical scores.
