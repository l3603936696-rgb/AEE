# Task Package: instruction-cleanup-pass-1

## Goal

Make the repository's agent instruction files readable, non-duplicative, and
safe for future multi-agent work.

This pass should clean mojibake in instruction files, clarify which file is the
source of truth for each agent, and preserve all important project constraints.

## Background

- Why this matters: every agent reads these files before working. Garbled text
  and duplicated rules waste context and increase the risk of bad edits.
- Current behavior: `AGENTS.md`, `.cursorrules`, `.windsurfrules`, `GEMINI.md`,
  and `QODER.md` are near-duplicates of the code-review-graph section, with
  mojibake in table descriptions. `CLAUDE.md` is more complete but also contains
  mojibake and duplicate graph guidance.
- Desired behavior: instruction files are clean UTF-8 Markdown, concise, and
  point to canonical docs instead of repeating large blocks everywhere.

## Non-Goals

- Do not modify production code.
- Do not modify project behavior.
- Do not edit `src/`, `tests/`, `data/`, `models/`, `frontend/`, `channel/`,
  `net/`, or `config/`.
- Do not rewrite architecture docs beyond instruction-file references.
- Do not remove important XIA constraints such as graph-first exploration,
  continuous-control coding rules, LLM minimization, module size limit, and
  surgical change discipline.

## Files In Scope

Primary:

- `AGENTS.md`
- `CLAUDE.md`
- `.cursorrules`
- `.windsurfrules`
- `GEMINI.md`
- `QODER.md`

Optional if useful:

- `.cursor/rules/agent-workflow.mdc`
- `.agents/workflow/README.md`

## Desired Structure

Use `AGENTS.md` as the shared source of truth for all agents. It should include:

- short project context,
- graph-first rule,
- task workflow rule,
- coding constraints,
- files/directories to avoid by default,
- review expectations.

Use agent-specific files as small adapters:

- `.cursorrules`: Cursor-specific implementation role plus "read AGENTS.md".
- `.windsurfrules`, `GEMINI.md`, `QODER.md`: small adapters plus "read AGENTS.md".
- `CLAUDE.md`: Claude-specific guidance plus project overview. It may stay more
  detailed than other adapters, but should not duplicate the entire graph table
  if `AGENTS.md` already contains it.

## Acceptance Criteria

- [ ] Instruction files are readable UTF-8 Markdown.
- [ ] `AGENTS.md` clearly preserves the code-review-graph first rule.
- [ ] Cursor is clearly told to use `.agents/tasks/.../CURSOR_PROMPT.md` for
  delegated implementation work.
- [ ] Claude Code is clearly told to review or implement according to task
  context and to use graph tools first when available.
- [ ] Duplicated graph tables are reduced.
- [ ] No production source, tests, data, models, or frontend files are changed.
- [ ] `CURSOR_RESULT.md` lists exact files changed and rules preserved.

## Open Questions

- Question: Should Chinese instructions be kept in Chinese?
- Decision: Keep this pass mostly English ASCII for encoding safety. Use Chinese
  only where already clear and needed by the Owner.
