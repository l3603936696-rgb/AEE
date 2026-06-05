# Task Package: xia-systems-index-cleanup-pass-1

## Goal

Clean and strengthen `XIA_SYSTEMS.md` as the canonical system map for XIA.

This task should not create a new codebase map. It should improve the existing
system index so humans, Codex, Claude Code, and Cursor can quickly navigate the
project before planning or reviewing complex work.

## Background

- Why this matters: XIA already has `XIA_SYSTEMS.md`, but the file contains
  encoding/mojibake issues in some readers and is dense for agent navigation.
- Current behavior: the document has a broad module list and data-flow sections,
  but it is hard to scan and inconsistent in format.
- Desired behavior: the document becomes the first reliable map for system
  ownership, entry files, inputs, outputs, risks, and tests.

## Non-Goals

- Do not modify production code.
- Do not change application behavior.
- Do not create a competing system map elsewhere.
- Do not delete module sections unless they are clearly duplicate headings.
- Do not invent architecture that is not supported by the existing document or
  obvious file names.
- Do not edit `src/`, `tests/`, `data/`, `models/`, `frontend/`, `channel/`,
  `net/`, or `config/`.

## Files In Scope

Primary:

- `XIA_SYSTEMS.md`

Task records:

- `.agents/tasks/2026-05-30_xia-systems-index-cleanup-pass-1/CURSOR_RESULT.md`

Do not edit other files unless the task result explains why and the change is
strictly documentation-only.

## Required Improvements

1. Preserve the existing module coverage:
   - `pipeline_runner`
   - `daemon`
   - `entity_state`
   - `drive_system`
   - `emotion_system`
   - `decision_system`
   - `thinking_system`
   - `language_system`
   - `action_system`
   - `world_model_update`
   - `state_update`
   - `memory_hub`
   - `core`
   - `weathering`
   - `response_cache`
   - `tool_introspection`
   - `tool_synthesizer`
   - `observability`
   - `jepa`
   - data file locations
   - key data flows
   - maintenance checklist

2. Add an `Agent Quick Navigation` section near the top:
   - if changing language output, inspect ...
   - if changing daemon/tick behavior, inspect ...
   - if changing state updates, inspect ...
   - if changing world model learning, inspect ...
   - if changing tool synthesis/introspection, inspect ...
   - if changing frontend/status display, inspect ...
   - if reviewing risky changes, inspect ...

3. Normalize each major system section toward this shape where practical:
   - Responsibility
   - Entry files
   - Inputs
   - Outputs
   - Key dependencies
   - Common change risks
   - Recommended checks/tests

4. Keep encoding safe:
   - Prefer ASCII punctuation in Markdown syntax and diagrams.
   - Avoid special arrows, box drawing, emoji, superscripts, and multiplication
     symbols.
   - Chinese explanatory text is allowed if it reads correctly in UTF-8.
   - If text is already mojibake and the intended meaning is unclear, preserve a
     short note in `CURSOR_RESULT.md` instead of guessing silently.

## Acceptance Criteria

- [ ] `XIA_SYSTEMS.md` remains the canonical system map.
- [ ] The document has a clear `Agent Quick Navigation` section.
- [ ] Existing module coverage is preserved.
- [ ] Major sections are easier to scan.
- [ ] No production code or data directories are changed.
- [ ] `CURSOR_RESULT.md` lists changed sections and any uncertain recoveries.
- [ ] No obvious mojibake markers or replacement characters remain.

## Open Questions

- Question: Should the document be fully English, fully Chinese, or bilingual?
- Decision: For this pass, keep it readable and encoding-safe. Do not translate
  everything just for style.
