# Angry Math Nerd Plan

## Test Strategy

- Missing definition: loading `.codex/agents/angry_math_nerd.toml` fails before implementation.
- Valid definition: standard-library TOML parsing yields the expected name, Sol model, medium effort, and read-only sandbox.
- Contract: instructions name #164 and #165, all three verdicts, evidence-backed recomputation, unpriced-gap handling, source dependence, serial correlation, and the independent-review limitation.

## Implementation

- Add one custom-agent TOML following the existing reviewer pattern.
- Keep the reviewer read-only and narrowly scoped to accuracy evidence and methodology claims.
- Validate with the focused contract test, strict Codex configuration, and the repository's normal static checks relevant to the changed files.

## Acceptance Examples

- Input `$5.80 + $2.00 = $7.80` with complete provenance: `Grudgingly placated`.
- Input `$5.80 + $2.00 = $7.70`: `Not placated` with the corrected equation.
- Input treating an unpriced junction as `$0`: `Not placated`.
- Input without paired data or methodology: `Cannot audit`.
