# REVIEW.md - large-file-split-pass-8

## Review Checklist

- [ ] `_src_id` returned by `update_source_tick()` is used by `tick_engine.py`.
- [ ] Source profile update still uses recognized words, social intent, last delta, and source identity.
- [ ] Semantic residue injection still happens after source profile update.
- [ ] Reply-drive injection still happens only for a real source id.
- [ ] Familiarity suppression still uses decay over 20 ticks and gain `0.4 * 0.001`.
- [ ] Daemon docs and `XIA_SYSTEMS.md` mention the new helper module.

## Review Notes

This pass groups the source/profile-related post-pipeline work into one helper
because the blocks already shared `_src_id` and source identity state.
