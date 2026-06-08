# Spec

Split `src/action_system/executor.py` below the 400-line project limit without changing action execution behavior.

Scope:
- Move prompt/context construction into a helper module.
- Move somatic feedback and failure analysis into a helper module.
- Move failure resolution and capability-gap helpers into a helper module.
- Keep `execute_xia_choice` wired to the extracted helpers.

Out of scope:
- No runtime voice/log data edits.
- No action behavior redesign.
