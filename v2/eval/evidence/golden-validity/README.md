# Golden actor validity evidence

These are scripted development diagnostics, not application evaluations.
Each run checks three fresh actors for each of the 20 development cases.
All four held-out cases remain excluded. Manifests pin the source commit;
journals preserve model usage, actor replies, and the scripted conversation.

| Run | Original check result | Cost | Change being tested |
| --- | --- | --- | --- |
| [Actors 1](actors-1/review.html) | 56/60 | $0.02998186 | Initial validity guards and prompt corrections |
| [Actors 2](actors-2/review.html) | 47/60 | $0.02788004 | Formatting prompt bound to the undelivered reply; regressed |
| [Actors 3](actors-3/review.html) | 59/60 | $0.01879760 | Required direct structured output |
| [Actors 4](actors-4/review.html) | 55/60 | $0.01654240 | Nullable message derives stop; extra terminal replies remained |
| [Actors 5](actors-5/review.html) | 57/60 | $0.01733860 | Terminal-answer instructions; three diagnostic false failures |
| [Actors 6](actors-6/review.html) | 59/60 | $0.01784300 | Completed the profile-required Baltimore refusal exchange |

The earlier diagnostic incorrectly expected silence after an invitation to
choose another origin, despite the unsupported-origin profile requiring a
Baltimore clarification. Its historical results above are not rewritten.

In actors 6, all required clarifications were delivered. In
`greenway-missing-destination-1`, the actor added its vehicle/E-ZPass profile after
the completed answer. That redundant reply remains a failed scripted check.
Ryan explicitly accepted this limitation on September 21, 2026; the 59/60 result
is unchanged. This is residual simulator variability, not an application failure.
Semantic profile fidelity and premature stops still require human transcript
review on fresh application runs; the runtime guards cannot establish them alone.

Actor prompt/schema code was unchanged by the subsequent judge-only experiments.
See the [validity review](../../GOLDEN_VALIDITY_REVIEW.md),
[complete cost and digest index](index.json), and retained calibration attempts
9 onward under `../golden-360/`.
