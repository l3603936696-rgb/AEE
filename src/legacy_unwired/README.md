# Legacy Unwired Modules

This folder keeps modules that are preserved for possible future reuse but are
not currently imported by the runtime pipeline.

## Contents

| File | Previous location | Status |
| --- | --- | --- |
| `narrative_context.py` | `src/language_system/narrative_context.py` | Superseded by the current `narrative_fragments.try_narrative_expression()` path |
| `stereotype_tree_stage3_helpers.py` | `src/language_system/stereotype_tree_stage3_helpers.py` | Helper-style duplicate of logic currently implemented in `stereotype_tree_stage3.py` |

Before reusing one of these modules, check the current pipeline call path and
add tests around the restored integration point.
