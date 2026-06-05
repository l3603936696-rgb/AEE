# Threads: 2026-05-30_repo-hygiene-pass-1

## Task Directory

`.agents/tasks/2026-05-30_repo-hygiene-pass-1/`

## Thread Map

| Thread role | Status | Owner/agent | Notes |
| --- | --- | --- | --- |
| Main control | complete | Owner + Codex | Decided Cursor should do hygiene pass |
| Task | complete | Cursor | See `CURSOR_RESULT.md` |
| Review | complete | Codex | See `REVIEW.md` |
| Experiment | none | - | Not used |

## Current Status

- Status: accepted for local workspace cleanup.
- Last reliable decision: root hygiene pass is acceptable, but tracked moved
  files must be staged carefully if committing.
- Current blocker: none.

## Open Questions

- Whether to archive active daemon logs in a later pass.
- Whether to move root-level test files in a later pass.

## Cross-Thread Rules

- This task's durable context lives in this directory.
- Do not import assumptions from another thread unless linked here.
- If a new scope appears, create a new task id instead of extending this one.
