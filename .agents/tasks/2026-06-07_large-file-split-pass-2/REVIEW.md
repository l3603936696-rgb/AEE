# REVIEW.md - large-file-split-pass-2

## Review Checklist

- [ ] `decay_environment_vector()` is called before `run_pipeline()`.
- [ ] `inject_source_residue()` is called only when `_src_id != "none"`.
- [ ] The default environment vector shape is unchanged.
- [ ] The old decay/prune/tension formulas are preserved.
- [ ] The old source-residue injection and tension reset are preserved.
- [ ] Daemon docs and `XIA_SYSTEMS.md` mention the new helper module.

## Review Notes

This pass intentionally does not review or alter existing source-identity,
observability, or autonomous-action-memory changes already present in the
working tree.
