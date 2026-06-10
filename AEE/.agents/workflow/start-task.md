# Starting a Three-Agent Task

Use this checklist when the Owner says "enter three-agent mode" or asks to hand
implementation to Cursor.

1. Create `.agents/tasks/YYYY-MM-DD_short-name/`.
2. Copy `task-package-template.md` to `SPEC.md` and fill it in.
3. Write `PLAN.md` with the recommended implementation path.
4. Copy `thread-index-template.md` to `THREADS.md` and fill current thread role.
5. Copy `cursor-handoff-template.md` to `CURSOR_PROMPT.md` and fill task paths.
6. Ask Cursor to implement from `CURSOR_PROMPT.md`.
7. After Cursor finishes, review the diff and write `REVIEW.md`.
8. If Claude Code also reviews, append or add `REVIEW_CLAUDE.md`.
9. Summarize the final recommendation for the Owner.

## Naming

Use short lowercase names:

- `.agents/tasks/2026-05-30_agent-workflow/`
- `.agents/tasks/2026-06-02_daemon-status-api/`

## Minimal Task Directory

```text
.agents/tasks/YYYY-MM-DD_short-name/
  SPEC.md
  PLAN.md
  THREADS.md
  CURSOR_PROMPT.md
  CURSOR_RESULT.md
  REVIEW.md
```
