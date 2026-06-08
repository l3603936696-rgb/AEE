# REVIEW.md - large-file-split-pass-5

## Review Checklist

- [ ] `update_response_cache()` is called after pending output-causal recording.
- [ ] Drive-vector, text, and tick extraction match the old inline block.
- [ ] Store/skip weighting matches the old inline block.
- [ ] Cache update failure logging matches the old inline block.
- [ ] Daemon docs and `XIA_SYSTEMS.md` mention the new helper module.

## Review Notes

This pass intentionally does not review or alter existing source-identity,
observability, or earlier split-pass changes already present in the working
tree.
