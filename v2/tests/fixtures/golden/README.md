# Test-only golden harness inputs

These 25 old scenarios, 55 references, 17 tool fixtures, and frozen point catalog
support existing offline regression and packaged-agent smoke checks. They are
**not an evaluation corpus, calibration set, or holdout**. They have no corpus
manifest, calibration reference, or human approval. Production code never falls
back to this directory. Tests opt in explicitly.

Inputs originate from commit `4654b4323edd28a49d696c6af00a8a09e31864c7`.
Original numbers, IDs and held-out flags survive only to exercise existing tests,
including exclusion of reserved examples from calibration. None is a candidate
for the future set. See the [recreation guide](../../../eval/GOLDEN_EVAL_SPEC.md).
