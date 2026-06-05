# Review: instruction-cleanup-pass-1

## Reviewer

- Name: Codex
- Date: 2026-05-30
- Diff reviewed: instruction files edited by Cursor.

## Context Used

- Graph tools used: requested, but code-review-graph tools were not available in
  this Codex session.
- Files inspected: `AGENTS.md`, `CLAUDE.md`, `.cursorrules`, `.windsurfrules`,
  `GEMINI.md`, `QODER.md`, `CURSOR_RESULT.md`, git diff/status.
- Tests inspected: not applicable; instruction-file cleanup only.

## Findings

### High Risk

- None.

### Medium Risk

- Resolved by Codex follow-up: remaining non-ASCII arrows, em dashes, warning
  symbols, multiplication signs, sigma, superscript, and greater-than-or-equal
  symbols were replaced with ASCII equivalents in instruction files.

### Low Risk

- The graph tool table in `AGENTS.md` no longer lists `refactor_tool`, which was
  present in the old duplicated instructions. This is acceptable for now because
  the most-used graph review/exploration tools remain listed.
- `CLAUDE.md` still contains more duplicate project guidance than the adapter
  files. This is acceptable for now because the task allowed it to remain more
  detailed than other adapters.

## Review Checklist

- [x] `AGENTS.md` preserves graph-first guidance.
- [x] Agent-specific files point to `AGENTS.md` instead of duplicating large
  corrupted blocks.
- [x] `CLAUDE.md` remains useful and does not lose project constraints.
- [x] Cursor workflow is explicit.
- [x] No production code or data directories were changed by this pass.
- [x] `CURSOR_RESULT.md` lists changed files and preserved rules.
- [x] Instruction files are safe to read in PowerShell without mojibake.

## Follow-up Applied

Codex applied the ASCII symbol cleanup after Cursor's revision and re-ran the
mojibake scan against the six instruction files.

## Merge Recommendation

Merge. The structure is good, important rules are preserved, and the encoding
cleanup objective is now complete for the instruction files in scope.
