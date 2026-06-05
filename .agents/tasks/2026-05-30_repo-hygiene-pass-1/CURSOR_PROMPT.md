# Cursor Handoff: repo-hygiene-pass-1

You are the implementation agent for this repository hygiene pass.

Read first:

1. `AGENTS.md`
2. `CLAUDE.md`
3. `.agents/workflow/README.md`
4. `.agents/tasks/2026-05-30_repo-hygiene-pass-1/SPEC.md`
5. `.agents/tasks/2026-05-30_repo-hygiene-pass-1/PLAN.md`

## Mission

Organize obvious root-directory noise without changing application behavior.

## Hard Boundaries

- Do not edit or move anything under `src/`, `data/`, `models/`, `frontend/`,
  `channel/`, `net/`, `config/`, or `tests/`.
- Do not delete files.
- Do not refactor code.
- Do not run broad formatting.
- Do not change runtime commands.
- Do not move root files listed under "Files To Leave In Root For This Pass" in
  `SPEC.md`.

## Implementation Steps

1. Create the directories listed in `PLAN.md`.
2. Move only the files listed by pattern in `PLAN.md`, using `git mv` when a file
   is tracked and normal move when it is untracked.
3. Before moving root `daemon*.log`, check whether a daemon process is currently
   writing them. If unsure, skip logs and document the skip.
4. Update `.gitignore` with root-level runtime artifact patterns if they are not
   already covered.
5. Run the verification commands from `PLAN.md`.
6. Create `.agents/tasks/2026-05-30_repo-hygiene-pass-1/CURSOR_RESULT.md`.

## CURSOR_RESULT.md Must Include

- Summary.
- Every moved file, source -> destination.
- `.gitignore` changes.
- Files intentionally skipped and why.
- Verification commands run and results.
- Any follow-up recommendations.

## Review Focus

Reviewers will check that the pass is conservative, reversible, and behavior
neutral. If a file's role is unclear, leave it in place.
