# XIA / AEE - Persistent Autonomous Agent Runtime

XIA is a solo research engineering project for building a persistent autonomous
agent runtime. Instead of treating an AI system as a single stateless chat
prompt, XIA is structured as a long-running Python process with internal state,
background ticks, memory, language modules, world-model updates, and optional
tool execution.

The repository is useful as an engineering portfolio project because it shows
runtime orchestration, state modeling, modular refactoring, persistence,
observability, testing, and multi-agent development workflow.

## What XIA Does

- Runs a local daemon that advances entity state over time.
- Exposes IPC/HTTP entry points for chat, status, and training requests.
- Maintains persistent internal variables such as energy, fatigue, curiosity,
  loneliness, boredom, stress, and unresolved tension.
- Routes each tick through a staged cognitive pipeline: perception, thinking,
  behavior emergence, language, state update, and persistence.
- Uses language modules for anchor matching, sentence composition, source
  identity, expression relief, and feedback loops.
- Records episodic memory and updates a lightweight world model from observed
  state changes.
- Supports autonomous action plumbing through the action system and daemon
  trigger loop.

This is an active research prototype, not a production framework.

## Current Interface Scope

XIA currently ships as a backend/runtime project, not as a desktop or web app.

- The daemon is started with `python -m src.daemon.daemon`.
- Chat access is available through the local `channel/` IPC client.
- Active reach-out messages are surfaced through `reach_client.py`.
- There is no maintained frontend in the current codebase. Earlier Electron/Vite
  experiments were removed and archived so the runtime can keep iterating without
  carrying an inactive UI surface.

## Quick Review Guide

If you only have a few minutes, start here:

| Area | Why inspect it |
| --- | --- |
| `src/daemon/` | Long-running background process, IPC/HTTP server, tick loop, action execution |
| `src/pipeline_runner/` | Staged cognitive pipeline and cross-stage context |
| `src/entity_state.py` + `src/entity_*.py` | Persistent state model, lifecycle, persistence, compatibility wrappers |
| `src/language_system/` | Anchor language, sentence composition, expression feedback, source modeling |
| `src/action_system/` | Tool execution, action parsing, reach behavior, failure handling |
| `src/memory_hub/` | Episodic memory, insights, TetraMem fallback/persistence |
| `src/world_model_update/` | Rule induction, contradiction handling, decay/merge/verification |
| `XIA_SYSTEMS.md` | Maintainer-facing system index and cross-module map |
| `.agents/tasks/` | Task packages with specs, plans, validation notes, and review handoff |

## Technical Highlights

### Background Runtime

The daemon keeps XIA moving outside direct chat requests. It handles background
ticks, IPC/HTTP request dispatch, chat/status/training endpoints, response cache
prewarming, source identity tracking, and autonomous action trigger wiring.

Relevant files:

- `src/daemon/daemon.py`
- `src/daemon/tick_engine.py`
- `src/daemon/http_server.py`
- `src/daemon/ipc_chat_handler.py`

### State-Driven Behavior

XIA tracks continuous internal values and uses them as inputs to downstream
drive, decision, language, and action modules. The project contains dedicated
systems for drive computation, state update, language expression, memory
write-back, world-model induction, and long-term parameter drift.

This is a prototype showing how to structure an agent runtime around persistent
state rather than a single stateless prompt.

### Autonomous Actions

`src/action_system/` contains the code path for self-initiated actions:

- tool-call extraction
- action parsing
- active reach-out messages
- voice/manifest writing
- somatic feedback after tool use
- failure analysis
- capability-gap handling

### Active Reach-Out Path

XIA has an experimental path for initiating contact instead of only replying
when the user sends a message. When the action system chooses a `reach` action,
`src/action_system/reach.py` writes the message into runtime-generated files:

- `data/xia_messages/pending.json`
- `data/xia_messages/notification_queue.jsonl`
- `data/xia_messages/history/`

The response path is file-based. The local listener writes the user's reply to
`data/xia_messages/response.json`, and the background runtime reads that reply
on a later tick through `src/daemon/tick_input.py`.

Relevant files:

- `src/action_system/reach.py`
- `reach_client.py`

Current limitation: this is a working local message path, not a polished push
notification system. If `reach_client.py` is not running, the message is still
written to disk but may not be visible to the user.

## Architecture

```text
IPC / local HTTP clients
        |
        v
src.daemon.daemon
        |
        +--> TickEngine
        |       |
        |       +--> run_pipeline(...)
        |       +--> lifecycle/maintenance helpers
        |       +--> autonomous action execution
        |       +--> source and causal observation
        |       +--> memory/world-model updates
        |
        +--> http_server.py
        +--> ipc_chat_handler.py

pipeline_runner
        |
        +--> s01_init
        +--> s02_perception / input-drive mapping / delayed understanding
        +--> s03_think
        +--> s04a_meta / s04b_emerge
        +--> s05_behavior
        +--> s06_language / candidates / anchor core
        +--> s07_state update / persistence / language finalization
```

## Current Module Map

| Area | Purpose |
| --- | --- |
| `src/daemon/` | Background runtime process, ticks, IPC/HTTP, autonomous wiring |
| `src/pipeline_runner/` | Cognitive pipeline orchestration |
| `src/entity_state.py` | EntityState dataclass, runtime state methods, singleton API |
| `src/entity_io.py` | Entity state paths and atomic JSON IO |
| `src/entity_lifecycle.py` | Recovery, offline drift, silence injection, stereotype setup |
| `src/entity_persistence.py` | `persist_to_file` / `load_from_file` implementation |
| `src/entity_core_wrapper.py` | Compatibility wrapper for emergent behavior |
| `src/entity_experience.py` | Experience-log and prediction-error helpers |
| `src/drive_system/` | Drive computation and pressure signals |
| `src/state_update/` | State transition and write-back |
| `src/language_system/` | Anchor language, grammar, expression, source modeling |
| `src/action_system/` | Tool use, reach behavior, autonomous action execution |
| `src/memory_hub/` | Episodic memory, insights, TetraMem integration |
| `src/world_model_update/` | Rule induction, contradiction handling, decay |
| `src/thinking_system/` | Internal reasoning, semantic base, covariance tracking |
| `src/observability/` | Runtime instrumentation, LLM wrappers, reporting |
| `.agents/tasks/` | Multi-agent task packages and validation notes |

## Engineering Work Demonstrated

- Designed a background runtime around persistent state ticks.
- Preserved compatibility while splitting large files into focused modules.
- Separated state definition from lifecycle, IO, persistence, and wrapper logic.
- Maintained task packages with implementation specs, validation, and review notes.
- Used targeted pytest runs, `compileall`, smoke scripts, and `git diff --check`
  during refactors.
- Kept runtime data, logs, caches, model artifacts, and secrets out of commits.

## Running Locally

Requirements:

- Python 3.12+
- Optional LLM provider configuration through `.env`

Background runtime:

```powershell
pip install -r requirements.txt
copy .env.example .env
python -m src.daemon.daemon
```

Chat client:

```powershell
python -m channel
```

Optional active reach-out listener:

```powershell
python reach_client.py
```

There is currently no maintained frontend in this repository.

## Validation Examples

```powershell
python -m compileall -q src tests
python -m pytest tests\test_expression_relief.py tests\test_source_identity.py tests\test_clarification_learning.py tests\test_clarification_memory_state.py
python test_stage3.py
git diff --check
```

## Repository Hygiene

The repository intentionally ignores runtime state and local artifacts:

- `data/`
- `logs/`
- `daemon*.log`
- `__pycache__/`
- `.pytest_cache/`
- local assistant/IDE configuration directories

Tracked root-level scripts such as `test_stage3.py`, `verify_fixes.py`, and
`train_curriculum.py` are historical/manual validation utilities. They are not
daemon entry points.

## Current Status

This is an active research prototype. The strongest parts of the repository are
the runtime architecture, subsystem boundaries, and refactoring/validation
workflow.

The active reach-out feature is implemented as a local file-backed loop. It can
record and surface messages, but the user experience still depends on running a
listener. A stronger version would make active messages appear directly in the
chat surface or as reliable desktop notifications.

Recent cleanup reduced several large files below the project 400-line module
limit, including background runtime, action-system, narrative, and
language-training files.

## Author

Independent research and engineering project.

Contact: l3603936696@gmail.com
