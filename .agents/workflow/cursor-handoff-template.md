# Cursor Handoff: <short-name>

You are the implementation agent for this task. Read these files first:

1. `AGENTS.md`
2. `CLAUDE.md`
3. `.agents/workflow/README.md`
4. `.agents/tasks/<task-dir>/SPEC.md`
5. `.agents/tasks/<task-dir>/PLAN.md`

## Mission

Implement only the behavior described in the task package.

## Boundaries

- Do not broaden scope without writing the reason in the task directory.
- Do not rewrite unrelated modules.
- Do not add speculative architecture.
- Do not edit secrets, generated logs, local caches, or model artifacts.
- Preserve existing behavior unless the task explicitly changes it.

## Implementation Expectations

- Work in a dedicated branch or worktree when possible.
- Keep commits or diffs small enough to review.
- Prefer existing patterns and helpers over new abstractions.
- Add tests for changed behavior.
- Run the narrowest meaningful test command first, then broader checks if
  needed.

## Delivery Format

When done, update `.agents/tasks/<task-dir>/CURSOR_RESULT.md` with:

- Summary of changes.
- Files changed.
- Tests run and results.
- Known risks or incomplete areas.
- Anything reviewers should inspect first.
