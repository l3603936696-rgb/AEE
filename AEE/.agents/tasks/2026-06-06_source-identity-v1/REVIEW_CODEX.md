# REVIEW_CODEX.md - source-identity-v1

## Verdict

Pass for v1 offline validation.

## Findings

No blocking findings.

## Notes

- bcyq direct chat no longer shares the generic `external` profile bucket.
- Pasted text can be routed to `pasted_text:unknown`, preserving bcyq as the
  deliverer without treating the content as bcyq's own speech.
- Sibling remains isolated as `sibling:<peer>`.
- The old `external` bucket remains usable as legacy/fallback data.

## Next Gate

Design `processing_depth-v1` only after this identity substrate is accepted.
That design should use source trust to allocate understanding effort, not to
make statements automatically true.
