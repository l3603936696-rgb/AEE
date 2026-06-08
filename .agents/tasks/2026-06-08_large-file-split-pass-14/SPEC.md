# Spec

Split `src/language_training.py` below the 400-line project limit without changing training behavior.

Scope:
- Move anchor expression matching into a helper module.
- Keep `run_language_training_tick` wired to `match_anchor_expression`.
- Update system documentation.

Out of scope:
- No language training algorithm redesign.
- No runtime data, logs, caches, models, or secrets.
