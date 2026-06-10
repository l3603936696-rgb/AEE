# Plan: agent-workflow

## Recommended Shape

Use repository files as the shared memory layer:

- `.agents/workflow/` contains reusable process docs and templates.
- `.agents/tasks/YYYY-MM-DD_short-name/` contains per-task artifacts.
- `.cursor/rules/agent-workflow.mdc` tells Cursor how to use the artifacts.

## Steps

1. Add reusable workflow documentation and templates.
2. Add a Cursor rule that activates for agent workflow tasks.
3. Add this task directory as a concrete example.
4. Verify the files are present and review git status.

## Later Automation Options

- Add a script to scaffold a task directory from templates.
- Add an MCP room or external orchestrator after the file protocol works.
- Add CI checks that require `CURSOR_RESULT.md` and `REVIEW.md` for large tasks.
