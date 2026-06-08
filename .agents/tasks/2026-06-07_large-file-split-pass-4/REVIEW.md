# REVIEW.md - large-file-split-pass-4

## Review Checklist

- [ ] `record_causal_observation()` is called in train-only mode after language training.
- [ ] `record_causal_observation()` is called near normal tick end before diary write.
- [ ] Observation dimensions match the old inline blocks.
- [ ] Observation payload shape matches the old inline blocks.
- [ ] Rolling retention still keeps the latest 200 observations.
- [ ] Daemon docs and `XIA_SYSTEMS.md` mention the new helper module.

## Review Notes

This pass intentionally does not review or alter existing source-identity,
observability, autonomous-action-memory, environment-vector, or output-causal
changes already present in the working tree.
