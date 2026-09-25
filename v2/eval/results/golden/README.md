# Golden release metadata

This directory retains versioned policies and historical approval/registry records.
The active [private production gate](../../GOLDEN_RELEASE.md) uses `policy-3.0.0.json`,
which remains pending until independent evaluator activation. Its public key will
be supplied here after review; no private key or held-out cases belong here.
The historical initial archive remains for offline compatibility tests. It cannot
qualify production, and a production reference is no longer required.

The [experiment journal](../../EXPERIMENT_JOURNAL.md) records prior results and
decisions. Keep development output in ignored `eval/private/` or the existing
private workflow artifact store. The external evaluator retains held-out details;
only aggregate signed summaries cross into the release workflow. Publish only
journal summaries, never new per-run review packets in this directory.

Historical artifacts remain recoverable from commit
`19fb7faed8fee2c286bf71d6e2f92f27fe33e352`. Policies and recorded approvals retain
their original identities. The new policy does not reset spending, approve a
private corpus, or retroactively change historical scores.
