# Spec

Split `src/action_system/tools.py` below the 400-line project limit without changing tool parsing behavior.

Scope:
- Move natural-language tool extraction helpers to a new module.
- Keep `extract_tool_calls` and `run_with_tools` public behavior intact.
- Update system documentation.

Out of scope:
- No tool registry redesign.
- No runtime data, logs, cache, voice, model, or secret edits.
