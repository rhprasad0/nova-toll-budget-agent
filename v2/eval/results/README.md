# Evaluation results

Publish experiment summaries in the [experiment journal](../EXPERIMENT_JOURNAL.md).
It records the historical [live checks](../EXPERIMENT_JOURNAL.md#august-22-live-integration-checks),
[golden demonstration and calibrations](../EXPERIMENT_JOURNAL.md#legacy-golden-demonstration-and-calibrations),
and [proxy validation](../EXPERIMENT_JOURNAL.md#i-95i-495-identity-proxy-validation).
These have different scopes; their pass rates are not comparable.

- [Golden release metadata](golden/README.md) retains versioned policies and
  exact historical approvals.
- [I-95/I-495 proxy guidance](i95-missing-od-pricing.md) describes the current
  mapping, modeled-label requirements and queries.
- [Evaluation guide](../README.md) describes current commands. Keep granular
  output in ignored `eval/private/` or the existing private workflow store.
