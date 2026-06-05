# Threads: 2026-05-30_agent-workflow

## Task Directory

`.agents/tasks/2026-05-30_agent-workflow/`

## Thread Map

| Thread role | Status | Owner/agent | Notes |
| --- | --- | --- | --- |
| Main control | active | Owner + Codex | Designed the shared workflow |
| Task | complete | Codex | Created initial workflow scaffolding |
| Review | complete | Codex | See `REVIEW.md` |
| Experiment | none | - | Not used |

## Current Status

- Status: complete
- Last reliable decision: use repo files as shared memory for Owner, Codex,
  Claude Code, and Cursor.
- Current blocker: none.

## Open Questions

- Whether to connect an external orchestrator after this file protocol proves
  useful.

## Cross-Thread Rules

- This task's durable context lives in this directory.
- Do not import assumptions from another thread unless linked here.
- If a new scope appears, create a new task id instead of extending this one.
