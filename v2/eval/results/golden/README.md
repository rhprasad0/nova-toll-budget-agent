# Golden release metadata

This directory retains the versioned gate policies, approval records, and
registry required by [the release gate](../../GOLDEN_RELEASE.md). The production
reference is unset. The initial archive is required by the existing initializer
and offline compatibility tests; it is historical, not production qualification.

The [experiment journal](../../EXPERIMENT_JOURNAL.md) records prior results and
decisions. Repeated run reports and per-experiment documents have been removed.
Do not add new local runs here. Keep output in ignored `eval/private/` or the
existing private workflow artifact store and publish only a journal summary.

Historical artifacts remain recoverable from commit
`19fb7faed8fee2c286bf71d6e2f92f27fe33e352`. Policies and recorded approvals retain
their original identities; removing redundant documentation does not approve a
new corpus, reset spending, or change a release threshold.
