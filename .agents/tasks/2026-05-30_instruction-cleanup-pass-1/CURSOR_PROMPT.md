# Cursor Handoff: instruction-cleanup-pass-1

You are the implementation agent for instruction cleanup.

Read first:

1. `AGENTS.md`
2. `CLAUDE.md`
3. `.agents/workflow/README.md`
4. `.agents/tasks/2026-05-30_instruction-cleanup-pass-1/SPEC.md`
5. `.agents/tasks/2026-05-30_instruction-cleanup-pass-1/PLAN.md`

## Mission

Clean the repository's agent instruction files so future agents receive clear,
non-duplicative guidance.

## Hard Boundaries

- Do not edit production code.
- Do not edit `src/`, `tests/`, `data/`, `models/`, `frontend/`, `channel/`,
  `net/`, or `config/`.
- Do not change project behavior.
- Do not remove important constraints. Preserve them in cleaner wording.
- Do not introduce new tools, dependencies, scripts, or automation.
- Do not edit secrets, generated logs, caches, model artifacts, or runtime data.

## Files To Edit

Primary:

- `AGENTS.md`
- `CLAUDE.md`
- `.cursorrules`
- `.windsurfrules`
- `GEMINI.md`
- `QODER.md`

Optional only if needed:

- `.cursor/rules/agent-workflow.mdc`
- `.agents/workflow/README.md`

## Required Result

1. `AGENTS.md` is the canonical shared instruction file.
2. `.cursorrules`, `.windsurfrules`, `GEMINI.md`, and `QODER.md` become concise
   adapters that point to `AGENTS.md`.
3. `CLAUDE.md` remains useful for Claude Code but has obvious mojibake fixed and
   duplicate graph guidance reduced.
4. Cursor-specific workflow is clear: implement from task `CURSOR_PROMPT.md`,
   update task `CURSOR_RESULT.md`, and avoid scope creep.

## Preserve These Rules

- Use code-review-graph MCP tools before grep/glob/read when available.
- Fall back to local search only when graph tools are unavailable or insufficient.
- Keep changes scoped.
- Avoid unrelated refactors.
- Avoid new LLM dependencies unless the Owner approves.
- Keep project constraints around continuous-control logic and module size.
- Do not add logic to oversized legacy files when a smaller module can own it.
- Review should focus on bugs, risks, missing tests, and behavioral regression.

## Verification

Run:

```powershell
git diff -- AGENTS.md CLAUDE.md .cursorrules .windsurfrules GEMINI.md QODER.md
git status --short -- AGENTS.md CLAUDE.md .cursorrules .windsurfrules GEMINI.md QODER.md src tests data models frontend channel net config
```

## CURSOR_RESULT.md Must Include

- Summary.
- Exact files changed.
- Important rules preserved.
- Any meaning that could not be confidently recovered from mojibake.
- Verification commands run and results.
- Follow-up recommendations.

If you are unsure about a garbled sentence's meaning, do not guess silently.
Either preserve it nearby or record it in `CURSOR_RESULT.md`.
