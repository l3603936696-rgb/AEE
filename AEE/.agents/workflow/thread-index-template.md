# Threads: <task-id>

## Task Directory

`.agents/tasks/<task-id>/`

## Thread Map

| Thread role | Status | Owner/agent | Notes |
| --- | --- | --- | --- |
| Main control | active | Owner + Codex | Planning and decisions only |
| Task | pending | Cursor/Codex | Implementation handoff and result |
| Review | pending | Codex/Claude Code | Review only |
| Experiment | none | - | Create only if needed |

## Current Status

- Status:
- Last reliable decision:
- Current blocker:

## Open Questions

- None.

## Cross-Thread Rules

- This task's durable context lives in this directory.
- Do not import assumptions from another thread unless linked here.
- If a new scope appears, create a new task id instead of extending this one.
