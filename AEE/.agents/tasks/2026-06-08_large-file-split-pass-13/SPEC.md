# Spec

Split `src/language_system/narrative_fragments.py` below the 400-line project limit without changing narrative expression behavior.

Scope:
- Move narrative context construction and lookup tables into a helper module.
- Keep `try_narrative_expression` wired to the extracted context builder.
- Update system documentation.

Out of scope:
- No template scoring redesign.
- No runtime data, logs, caches, models, or secrets.
