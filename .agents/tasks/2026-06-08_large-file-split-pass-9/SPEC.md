# Spec

Split the remaining large daemon tick orchestration blocks without changing runtime behavior.

Scope:
- Keep `src/daemon/tick_engine.py` under the 400-line project limit.
- Move self-contained daemon tick concerns into helper modules.
- Keep helper modules wired into the tick engine.
- Update daemon/system documentation.

Out of scope:
- No daemon startup.
- No live runtime data, logs, cache, model artifact, or secret edits.
