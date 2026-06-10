# Threads: 2026-05-30_xia-systems-index-cleanup-pass-1

## Task Directory

`.agents/tasks/2026-05-30_xia-systems-index-cleanup-pass-1/`

## Thread Map

| Thread role | Status | Owner/agent | Notes |
| --- | --- | --- | --- |
| Main control | active | Owner + Codex | Decided to improve existing `XIA_SYSTEMS.md` |
| Task | pending | Cursor | Use `CURSOR_PROMPT.md` |
| Review | pending | Codex/Claude Code | Review after Cursor result |
| Experiment | none | - | Not used |

## Current Status

- Status: ready for Cursor.
- Last reliable decision: improve the existing system index instead of creating
  a new codebase map.
- Current blocker: Cursor implementation pending.

## Open Questions

- Whether to keep future versions bilingual or mostly Chinese.

## Cross-Thread Rules

- This task's durable context lives in this directory.
- Do not import assumptions from another thread unless linked here.
- If a new scope appears, create a new task id instead of extending this one.
