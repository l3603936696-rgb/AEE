# Threads: 2026-05-30_instruction-cleanup-pass-1

## Task Directory

`.agents/tasks/2026-05-30_instruction-cleanup-pass-1/`

## Thread Map

| Thread role | Status | Owner/agent | Notes |
| --- | --- | --- | --- |
| Main control | complete | Owner + Codex | Decided Cursor should clean instructions |
| Task | complete | Cursor | See `CURSOR_RESULT.md` |
| Review | complete | Codex | See `REVIEW.md` |
| Experiment | none | - | Not used |

## Current Status

- Status: accepted.
- Last reliable decision: `AGENTS.md` is the shared instruction entry; agent
  files are adapters; `CLAUDE.md` keeps Claude-specific project guidance.
- Current blocker: none.

## Open Questions

- Whether Claude Code should do a later independent review.

## Cross-Thread Rules

- This task's durable context lives in this directory.
- Do not import assumptions from another thread unless linked here.
- If a new scope appears, create a new task id instead of extending this one.
