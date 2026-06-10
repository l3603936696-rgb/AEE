# REVIEW_CODEX.md - expression-relief-v1

## Verdict

Pass for v1 offline validation.

## Findings

No blocking findings after the accuracy fix.

## Notes

- The design correctly keeps loneliness out of self-expression relief.
- `repetition_discount` is used in the correct direction: fresh is near `1.0`,
  repeated is lower.
- Pure connector strings are suppressed to a weak residual relief.
- v1 does not pollute old quenching efficiency.

## Next Gate

Before connecting this to construction learning, collect online traces for:

- expression text
- accuracy
- novelty
- structure_score
- applied deltas
- later drift in boredom/unresolved

Construction learning should consume that audit only after a separate review.
