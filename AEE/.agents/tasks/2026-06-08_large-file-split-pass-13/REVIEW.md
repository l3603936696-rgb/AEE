# Review

Risk focus:
- `try_narrative_expression` now imports `_build_context` from `narrative_context.py`.
- Template registration and sampling stayed in `narrative_fragments.py`.
- Context lookup tables moved with the context builder.

Residual risk:
- No live narrative generation over a real entity snapshot was run.
