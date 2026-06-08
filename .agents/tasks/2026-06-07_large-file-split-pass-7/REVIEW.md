# REVIEW.md - large-file-split-pass-7

## Review Checklist

- [ ] Covariance tracker update still writes tracker data and attention weights.
- [ ] Reading intake still uses `max_candidates=3` and `min_similarity=0.35`.
- [ ] Reading taste recording still happens only after positive injection.
- [ ] Sentence extraction still uses the pipeline decision action type.
- [ ] StatePatternMemory still uses result drive vector and result tick.
- [ ] Daemon docs and `XIA_SYSTEMS.md` mention the new helper modules.

## Review Notes

This pass intentionally groups several low-coupling helper extractions to speed
up the large-file split while keeping each helper focused.
