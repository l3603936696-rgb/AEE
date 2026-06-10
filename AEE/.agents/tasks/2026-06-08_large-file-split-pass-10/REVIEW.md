# Review

Risk focus:
- `HTTPServer` was moved as a whole; request forwarding behavior should remain the same.
- `_handle_chat` now delegates to `handle_chat_request` with the same request, LLM callable, response cache, and logger.
- JSON-safe cleanup and public state snapshot filtering moved with the chat handler.

Residual risk:
- The daemon was not started, so live IPC/HTTP behavior was not exercised.
