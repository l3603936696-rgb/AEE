# Thread Protocol

This project may use several parallel AI conversations. Keep them separated by
task id and role so context does not leak between unrelated work.

## Thread Types

### Main Control Thread

Purpose:

- decide priorities,
- split work into tasks,
- approve or reject recommendations,
- avoid implementation details unless needed for planning.

Opening label:

```text
Main control thread: XIA agent workflow
Scope: planning and decisions only.
```

### Task Thread

Purpose:

- create or update one task package,
- inspect one Cursor implementation result,
- keep all durable task context in `.agents/tasks/<task-id>/`.

Opening label:

```text
Task thread: <task-id>
Scope: only .agents/tasks/<task-id>/ and files named by its SPEC/PLAN.
```

### Review Thread

Purpose:

- review one diff or one Cursor result,
- produce `REVIEW.md` or `REVIEW_<agent>.md`,
- avoid implementation unless the Owner explicitly asks for a tiny fix.

Opening label:

```text
Review thread: <task-id>
Scope: review only; do not edit files unless explicitly asked.
```

### Experiment Thread

Purpose:

- run probes,
- explore uncertain behavior,
- test ideas before converting them into tasks.

Opening label:

```text
Experiment thread: <short-topic>
Scope: exploration only; no durable change until promoted to a task.
```

## Anti-Mixing Rules

- Do not solve two unrelated tasks in one thread.
- Do not carry implementation assumptions from another thread unless they are in
  the task directory or the Owner repeats them.
- If a conversation drifts, create a new task id and record the split in
  `THREADS.md`.
- If the thread type is unclear, ask for the task id before editing code.
- The task directory is the source of truth, not chat memory.

## Durable Handoff

Each task should keep a `THREADS.md` file with:

- thread role,
- owner intent,
- linked task files,
- current status,
- last reliable decision,
- open questions.

Use `thread-index-template.md` when creating it.
