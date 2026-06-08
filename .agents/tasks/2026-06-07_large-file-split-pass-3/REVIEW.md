# REVIEW.md - large-file-split-pass-3

## Review Checklist

- [ ] `close_pending_output_causal()` is called before the pipeline run.
- [ ] `record_pending_output_causal()` is called after a result is available.
- [ ] Tracked dimensions match the old inline block.
- [ ] Closed observation payload shape matches the old inline block.
- [ ] New pending snapshot payload shape matches the old inline block.
- [ ] Daemon docs and `XIA_SYSTEMS.md` mention the new helper module.

## Review Notes

This pass intentionally does not review or alter existing source-identity,
observability, autonomous-action-memory, or environment-vector changes already
present in the working tree.
