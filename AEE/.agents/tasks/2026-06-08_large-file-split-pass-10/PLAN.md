# Plan

1. Extract `HTTPServer` into `src/daemon/http_server.py`.
2. Extract IPC chat/cache/pipeline handling into `src/daemon/ipc_chat_handler.py`.
3. Wire imports and thin delegation methods in `daemon.py`.
4. Compile daemon modules and run target tests.
5. Update daemon README and `XIA_SYSTEMS.md`.
