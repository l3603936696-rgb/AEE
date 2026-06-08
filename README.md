# XIA / AEE - Persistent Autonomous Agent Runtime

XIA is a solo research engineering project for building a persistent autonomous
agent runtime. Instead of treating an AI system as a single chat prompt, XIA is
structured as a long-running process with internal state, memory, background
ticks, language modules, and optional tool execution.

This repository is useful to review as an engineering portfolio project because
it shows system design work across background runtime orchestration, state modeling,
modularization, memory, language, tool execution, testing, and multi-agent
development workflow.

## What I Built

- A Python background runtime that advances entity state over time and exposes IPC/HTTP endpoints.
- A multi-stage cognitive pipeline for perception, thinking, language, state update, and persistence.
- A continuous state model for variables such as fatigue, stress, curiosity, loneliness, boredom, and unresolved tension.
- An autonomous action system that can decide to reach out, search, browse, write files, or call tools.
- A language system that maps internal state into anchor words, sentence patterns, and expression feedback.
- Episodic memory and world-model update modules that record experience and feed later behavior.
- A multi-agent engineering workflow using `.agents/tasks/` packages for specs, plans, validation notes, and review handoff.

## Quick Review Guide

If you only have a few minutes, start here:

| What to inspect | Why it matters |
| --- | --- |
| `src/daemon/tick_engine.py` | Main background tick orchestration, now split below the 400-line module limit |
| `src/daemon/` | Background runtime helpers for input, status, action execution, maintenance, reading, source tracking, and HTTP/chat handling |
| `src/action_system/` | Autonomous action execution, tool parsing, feedback, and failure handling |
| `src/language_training.py` + `src/language_anchor_match.py` | Anchor-based language training and expression matching |
| `src/language_system/narrative_fragments.py` + `narrative_context.py` | Narrative expression scoring and context construction |
| `XIA_SYSTEMS.md` | System map used by agents to navigate the codebase |
| `.agents/tasks/` | Evidence of scoped implementation plans, validation, and review workflow |

## Technical Highlights

### Background Runtime

The runtime service is responsible for keeping XIA moving outside direct chat
requests. It handles:

- background ticks
- IPC/HTTP request dispatch
- chat/status/training endpoints
- response cache prewarming
- source identity tracking
- autonomous action trigger wiring

Relevant files:

- `src/daemon/daemon.py`
- `src/daemon/tick_engine.py`
- `src/daemon/http_server.py`
- `src/daemon/ipc_chat_handler.py`

### State-Driven Behavior

XIA tracks continuous internal values and uses them as inputs to downstream
drive, decision, language, and action modules. The project contains dedicated
systems for:

- drive computation
- state update
- language expression
- memory write-back
- world-model induction
- long-term parameter drift

This is not presented as a production-ready cognitive model. It is a prototype
showing how to structure an agent runtime around persistent state rather than a
single stateless prompt.

### Autonomous Actions

`src/action_system/` contains the code path for self-initiated actions:

- tool-call extraction
- action parsing
- voice/manifest writing
- somatic feedback after tool use
- failure analysis
- capability-gap handling

Recent cleanup split the old large executor into:

- `executor.py`
- `executor_prompts.py`
- `executor_feedback.py`
- `executor_failure_resolution.py`
- `tools.py`
- `tools_nl_extractors.py`

### Language and Expression

The language layer is not only an LLM wrapper. It includes modules for:

- anchor matching
- sentence composition
- construction grammar
- narrative fragments
- expression relief
- quenching / feedback
- source and speaker modeling

Relevant files:

- `src/language_training.py`
- `src/language_anchor_match.py`
- `src/language_system/sentence_composer.py`
- `src/language_system/narrative_fragments.py`
- `src/language_system/expression_relief.py`

### Memory and World Model

The repository includes memory and world-model modules for recording and using
experience:

- episodic records
- state snapshots
- insight tracking
- TetraMem adapter fallback
- rule induction
- contradiction and tension tracking

Relevant files:

- `src/memory_hub/`
- `src/world_model_update/`
- `src/daemon/periodic_maintenance.py`

## Architecture

```text
IPC / optional desktop status UI
        |
        v
daemon.py
        |
        +--> tick_engine.py
        |       |
        |       +--> pipeline_runner
        |       +--> runtime maintenance helpers
        |       +--> action execution
        |       +--> source tracking
        |       +--> memory/world-model updates
        |
        +--> http_server.py
        +--> ipc_chat_handler.py

pipeline_runner
        |
        +--> perception
        +--> thinking
        +--> behavior emergence
        +--> language
        +--> state update
        +--> persistence
```

## System Map

| Area | Purpose |
| --- | --- |
| `src/daemon/` | Background runtime process, ticks, IPC/HTTP, autonomous wiring |
| `src/pipeline_runner/` | Cognitive pipeline orchestration |
| `src/drive_system/` | Drive computation and pressure signals |
| `src/state_update/` | State transition and write-back |
| `src/language_system/` | Anchor language, grammar, expression, source modeling |
| `src/action_system/` | Tool use, reach behavior, autonomous action execution |
| `src/memory_hub/` | Episodic memory, insights, TetraMem integration |
| `src/world_model_update/` | Rule induction, contradiction handling, decay |
| `src/thinking_system/` | Internal reasoning, semantic base, covariance tracking |
| `src/observability/` | Runtime instrumentation and reporting |
| `frontend/` | Optional Electron/Vite status display |
| `.agents/tasks/` | Multi-agent task packages and validation notes |

## Engineering Work Demonstrated

- Designed and maintained a background runtime with persistent state ticks.
- Split oversized files into focused modules while preserving public behavior.
- Added system documentation to support agent-assisted development.
- Maintained task packages with specs, plans, validation, and review notes.
- Used smoke tests, `py_compile`, targeted pytest runs, and diff checks during refactors.
- Kept runtime data, logs, caches, model artifacts, and secrets out of code changes.

## Validation Examples

Common checks used during recent refactors:

```powershell
python -m pytest tests\test_source_identity.py tests\test_expression_relief.py -q
git diff --check
```

For Python compilation in PowerShell, explicit file lists are safer than
wildcards:

```powershell
$files = Get-ChildItem -Path .\src\daemon -Filter *.py | ForEach-Object { $_.FullName }
python -m py_compile @files
```

## Running Locally

Requirements:

- Python 3.12+
- Node.js 18+ if using the optional desktop status UI
- Optional LLM provider configuration via `.env`

Background runtime:

```powershell
pip install -r requirements.txt
copy .env.example .env
python -m src.daemon.daemon
```

Optional desktop status UI:

```powershell
cd frontend
npm install
npm run electron:dev
```

## Current Status

This is an active research prototype, not a polished product or production
framework. The strongest parts of the repository are the runtime architecture,
subsystem boundaries, and refactoring/validation workflow. Some older modules
are still being split and cleaned up.

Recent cleanup reduced several large files below the project 400-line module
limit, including background runtime, action-system, narrative, and
language-training files.

## Author

Independent research and engineering project.

Contact: l3603936696@gmail.com
