# Plan: instruction-cleanup-pass-1

## Approach

Create a clean shared instruction hierarchy:

1. `AGENTS.md` becomes the canonical cross-agent instruction file.
2. Agent-specific files become small adapters that defer to `AGENTS.md`.
3. `CLAUDE.md` remains detailed enough for Claude Code but loses repeated or
   corrupted sections.

## Required Content For `AGENTS.md`

Include these sections:

- `Project Context`
- `Graph-First Exploration`
- `Multi-Agent Workflow`
- `Coding Rules`
- `Workspace Hygiene`
- `Review Expectations`

Keep these constraints explicit:

- Use code-review-graph MCP tools before grep/glob/read when available.
- Fall back to local search only when graph tools are unavailable or insufficient.
- Cursor is primarily implementation for delegated tasks.
- Codex and Claude Code are primarily planning/review unless the Owner asks
  otherwise.
- Do not edit generated logs, caches, model artifacts, secrets, or unrelated
  memory files.
- Prefer small scoped changes.
- Avoid adding new logic to oversized legacy files when a scoped module can be
  used instead.
- No new LLM dependency without Owner discussion.
- Keep continuous-control style constraints from `CLAUDE.md`.

## Adapter File Content

For `.cursorrules`:

- State that Cursor should read `AGENTS.md`.
- State that Cursor implements from `.agents/tasks/<task>/CURSOR_PROMPT.md`.
- State that Cursor must update `CURSOR_RESULT.md`.
- State hard boundaries: no unrelated refactors, no source edits outside task.

For `.windsurfrules`, `GEMINI.md`, `QODER.md`:

- State that the file is an adapter.
- Point to `AGENTS.md`.
- Preserve graph-first and scoped-change reminders.

For `CLAUDE.md`:

- Fix mojibake where the intended meaning is obvious.
- Preserve project overview, commands, architecture summary, coding rules.
- Replace duplicate graph section with a compact reference to `AGENTS.md`.
- Keep "respond/reason in Chinese" only if it can be represented clearly.

## Verification

Run:

```powershell
git diff -- AGENTS.md CLAUDE.md .cursorrules .windsurfrules GEMINI.md QODER.md
git status --short -- AGENTS.md CLAUDE.md .cursorrules .windsurfrules GEMINI.md QODER.md src tests data models frontend channel net config
```

Then write `CURSOR_RESULT.md`.

## Important Caution

This is an instruction cleanup, not a policy rewrite. Preserve meaning even when
removing duplicated or garbled text.
