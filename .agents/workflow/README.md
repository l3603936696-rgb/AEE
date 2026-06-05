# XIA Agent Workflow

This directory is the shared operating space for complex work involving:

- Owner: the human product and technical decision maker.
- Codex: planning, architecture review, risk review, and final synthesis.
- Claude Code: independent implementation review and edge-case review.
- Cursor: primary code implementation agent.

The purpose is to keep the human out of copy-paste relay work. Agents should
write durable artifacts here, then use Git diffs and tests as the source of
truth.

## Default Flow

1. Discuss the goal with the Owner until the outcome and non-goals are clear.
2. Create a task package from `task-package-template.md`.
3. Create a Cursor handoff from `cursor-handoff-template.md`.
4. Cursor implements in a dedicated branch or worktree.
5. Codex and Claude Code review the diff using `review-template.md`.
6. The Owner decides whether to merge, revise, split, or abandon.

## Thread Rule

Use one conversation thread for one purpose. Do not mix unrelated task work in
the same chat.

- Main control thread: planning, sequencing, and Owner decisions.
- Task thread: one `.agents/tasks/YYYY-MM-DD_short-name/` directory only.
- Review thread: review one implementation result only.
- Experiment thread: probes and diagnostics; promote durable conclusions into a
  task file before acting on them.

Every task thread should start with:

```text
Task thread: YYYY-MM-DD_short-name
Scope: only this task directory.
```

See `thread-protocol.md` for the full rule.

## Artifact Rules

- Keep one task per directory under `.agents/tasks/YYYY-MM-DD_short-name/`.
- Every task directory should contain `SPEC.md`, `PLAN.md`, `CURSOR_PROMPT.md`,
  `THREADS.md`, and `REVIEW.md`.
- Do not store secrets, API keys, tokens, or private credentials in task files.
- Put durable decisions in the task files or project docs, not only in chat.
- Prefer small branches and small diffs. If a task grows, split it.

## Review Gate

A task is not ready until the review artifact states:

- what changed,
- what tests were run,
- what remains risky,
- whether the reviewers recommend merge or revision.

When code-review-graph MCP tools are available, reviewers must use them before
manual file scanning, following `AGENTS.md`.
