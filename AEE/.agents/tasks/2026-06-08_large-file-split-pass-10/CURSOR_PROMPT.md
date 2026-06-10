# Cursor Prompt

Review the pass-10 daemon split for behavioral regressions.

Check:
- `daemon.py` imports and wiring for `HTTPServer` and `handle_chat_request`.
- `http_server.py` preserves the old HTTP routes and IPC forwarding behavior.
- `ipc_chat_handler.py` preserves cache probing, pipeline dispatch, source identity, source profile update, and safe JSON/state snapshot cleanup.

Do not edit runtime data, logs, caches, models, or secrets.
