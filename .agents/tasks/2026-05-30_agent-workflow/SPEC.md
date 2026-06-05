# Task Package: agent-workflow

## Goal

Create a lightweight durable workflow so the Owner, Codex, Claude Code, and
Cursor can collaborate on complex tasks without the Owner manually relaying
conversation context between tools.

The workflow should make Cursor the primary implementation agent while Codex
and Claude Code focus on planning, review, risk analysis, and merge advice.

## Background

- Why this matters: XIA tasks are expected to grow more complex, and manual
  copy-paste between agents will become expensive and error-prone.
- Current behavior: agents can collaborate only through ad hoc chat and scattered
  instructions.
- Desired behavior: each complex task has durable task files, a Cursor handoff,
  and structured review artifacts.

## Non-Goals

- Do not install or bind the project to an external orchestrator yet.
- Do not change production code.
- Do not replace Git, tests, or PR review with chat transcripts.

## Constraints

- Follow `AGENTS.md`, `CLAUDE.md`, and existing module boundaries.
- Use code-review-graph MCP tools first when available.
- Keep the initial process light enough to use immediately.
- Avoid secrets, generated logs, caches, and model files.

## Expected Files or Areas

- Likely area: `.agents/workflow/`, `.agents/tasks/`, `.cursor/rules/`.
- Likely tests: documentation verification only.
- Files to avoid: production source files.

## Acceptance Criteria

- [x] Workflow documentation exists.
- [x] Task, handoff, and review templates exist.
- [x] Cursor has a rule telling it how to participate.
- [x] The first task directory records this setup.
- [ ] Future tasks can be started from the checklist.

## Open Questions

- Question: Should this later be connected to OpenCastle, Fusion, Bernstein, or
  a custom MCP room?
- Decision: Keep this first version tool-agnostic and Git-centered.
