# Spec

Split `src/daemon/daemon.py` below the 400-line project limit without changing daemon behavior.

Scope:
- Move HTTP API server code into its own daemon module.
- Move IPC chat request handling into its own daemon module.
- Keep IPC dispatch, startup, and shutdown wiring intact.
- Update daemon/system documentation.

Out of scope:
- No daemon startup.
- No runtime data, logs, cache, model artifact, or secret edits.
