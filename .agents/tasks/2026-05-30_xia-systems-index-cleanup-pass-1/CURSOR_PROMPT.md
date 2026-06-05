# Cursor Handoff: xia-systems-index-cleanup-pass-1

You are the implementation agent for a documentation cleanup task.

Read first:

1. `AGENTS.md`
2. `CLAUDE.md`
3. `.agents/workflow/README.md`
4. `.agents/workflow/thread-protocol.md`
5. `.agents/tasks/2026-05-30_xia-systems-index-cleanup-pass-1/SPEC.md`
6. `.agents/tasks/2026-05-30_xia-systems-index-cleanup-pass-1/PLAN.md`

## Mission

Clean and strengthen `XIA_SYSTEMS.md` as the canonical XIA system map for
humans and agents.

## Hard Boundaries

- Edit `XIA_SYSTEMS.md` only, plus this task's `CURSOR_RESULT.md`.
- Do not edit production code.
- Do not edit `src/`, `tests/`, `data/`, `models/`, `frontend/`, `channel/`,
  `net/`, or `config/`.
- Do not create a competing system map.
- Do not invent architecture.
- Do not delete module coverage.
- Do not broaden scope into code refactoring.

## Required Work

1. Add an `Agent Quick Navigation` section near the top.
2. Preserve existing module coverage.
3. Make major sections easier to scan.
4. Normalize system sections where practical with:
   - Responsibility
   - Entry files
   - Inputs
   - Outputs
   - Key dependencies
   - Common change risks
   - Recommended checks
5. Replace unsafe punctuation and obvious mojibake when meaning is clear.
6. Record any uncertain text in `CURSOR_RESULT.md`.

## Encoding Rules

- Prefer ASCII punctuation for diagrams and Markdown syntax.
- Avoid special arrows, box drawing, emoji, superscripts, multiplication signs,
  and other symbols that may render as mojibake in PowerShell.
- Chinese text is allowed if it is valid UTF-8 and readable.
- If you cannot confidently recover a mojibake sentence, do not guess silently.

## Verification

Run:

```powershell
git diff -- XIA_SYSTEMS.md
rg -n "\x{922B}|\x{9225}|\x{8133}|\x{5371}|\x{864F}|\x{FFFD}|\x{2014}|\x{2192}|\x{00D7}|\x{03A3}|\x{00B2}|\x{2265}|\x{26A0}" XIA_SYSTEMS.md
git status --short -- XIA_SYSTEMS.md src tests data models frontend channel net config
```

## CURSOR_RESULT.md Must Include

- Summary.
- Exact sections changed.
- Module coverage preserved.
- Any uncertain mojibake recovery.
- Verification commands and results.
- Follow-up recommendations.

Do not edit anything else.
