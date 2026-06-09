# XIA Systems Index

> **Maintenance Note**: This document provides system navigation for AI agents.
> After modifying any module, **you must update the corresponding system section**
> (including submodule list, inputs, outputs, and key functions).
> When adding a new system, **you must add it to this document**.

---

## Maintenance Rules

- **System overview** (this section): update when adding/removing systems
- **Per-system sections**: update when adding/removing submodules, changing interfaces, or changing input/output contracts
- **Data file locations**: update when changing file paths
- **Key data flows**: update when changing the pipeline
- **README files**: each subsystem root must have a `README.md` describing responsibility, data flow, and key function signatures

When modifying subsystem code:
1. Modify the code
2. Sync the corresponding `src/{system}/README.md`
3. If the change affects cross-system interfaces (e.g. `thinking_system` output structure), also update this document
4. Update the `Last updated` date at the bottom

---

## Agent Quick Navigation

Use this section to quickly find which files to inspect when working on a specific area.

| If you are changing... | Inspect these files first |
| --- | --- |
| Language output (anchor/templating) | `src/language_system/` |
| Language training anchor matching | `src/language_training.py`, `src/language_anchor_match.py` |
| Language output (LLM response) | `src/pipeline_runner/stages/s06_language/` |
| Daemon tick behavior | `src/daemon/tick_engine.py`, `src/daemon/daemon.py` |
| State update mechanics | `src/state_update/`, `src/entity_state.py` |
| World model learning | `src/world_model_update/` |
| Tool synthesis or introspection | `src/tool_synthesizer/`, `src/tool_introspection/` |
| Action execution (V7) | `src/action_system/` |
| Frontend / status display | `frontend/src/`, `src/daemon/protocol.py` |
| Reviewing risky changes | `src/core/drive_vector_field.py`, `src/core/emergent_behavior.py` |

---

## System Overview

```
run_pipeline() <- pipeline orchestrator (main entry)
     |
     +---> daemon.tick_now() <- background tick advancement
     |         |
     |         +---> entity_state      <- central state container
     |         +---> drive_system     <- drive computation
     |         +---> emotion_system   <- emotion computation
     |         +---> decision_system   <- nine-module perception
     |         +---> thinking_system  <- thinking and question emergence
     |         +---> language_system  <- language expression loop
     |         +---> action_system    <- autonomous action
     |         +---> state_update     <- state write-back
     |         +---> world_model_update <- world model induction
     |         +---> jepa             <- world prediction (JEPA)
     |         +---> integrity_monitor <- integrity monitoring
     |         +---> memory_hub       <- memory persistence
     |
     +---> daemon IPCServer <- chat request entry (HTTP/Unix Socket)
```

---

## 1. pipeline_runner - Cognitive Pipeline Orchestrator

**Responsibility**: Orchestrates all cognitive stages in order. A thin orchestrator for `run_pipeline()`.

**Entry files**:
- `src/pipeline_runner/__init__.py`
- `src/pipeline_runner/context.py`
- `src/pipeline_runner/stages/s*.py`

**Inputs**: `raw_input` (str, optional), `daemon_mode` (bool), `no_llm` (bool), `llm_callable` (func)

**Outputs**:
```python
{
    "response": {"text": str, "confidence": float, "generation_time_ms": int},
    "decision": {"action_type": str, "target": str, "priority": float, ...},
    "state_snapshot": dict,
    "tick": int,
    "trace": List[PipelineTrace],
}
```

**Key dependencies**: `entity_state`, `drive_system`, `emotion_system`, `decision_system`, `thinking_system`, `language_system`, `state_update`, `world_model_update`, `memory_hub`

**Common change risks**:
- Reordering stages breaks the tick contract
- Changing `PipelineContext` field names breaks cross-stage communication

**Recommended checks**: `python tests/test_50_ticks.py`

### Pipeline Stage Order

```
s01_init
  -> s02_perception
    -> s02b_input_drive_map (drive_map_layer1/2/utils)
    -> [interpretation_competition]
    -> s02c_delayed_understand
  -> s03_think
  -> s04a_meta
  -> s04b_emerge
  -> s05_behavior
  -> s06_language (s06a_candidates/s06b_output/s06c_anchor_core)
  -> s07a_state_update
  -> s07b_persist
  -> s07c_language_finalize
```

### PipelineContext (`src/pipeline_runner/context.py`)

All stages share a mutable context container (SimpleNamespace). Stage functions share the signature `run_stage(ctx, entity)`. Cross-stage variables are passed via `ctx.var`.

### Key Parameters

- `daemon_mode`: background ticks skip LLM output
- `no_llm`: force the anchor/narrative path
- `llm_callable`: LLM invocation function

### Understanding Mechanism Stages

- `s02b_input_drive_map`: input text -> BGE embedding -> drive centroid similarity matching against SPM named symbols
- `drive_map_layer1`: `get_symbol_drive_vectors()` - collects all named-symbol drive vectors from SPM, builds centroid lookup table
- `drive_map_layer2`: `compute_input_drive()` - looks up input embedding, returns `drive_weighted`
- `drive_map_utils`: shared utility functions
- `interpretation_competition.py`: multiple experience candidates compete continuously; competitiveness = experience_strength * f(state) * conversion_coefficient; tension suspension state permeates language output
- `s02c_delayed_understand`: when confidence is below threshold, enters pending queue, reactivated by similar input on future ticks

### Submodules

| File | Function |
| --- | --- |
| `stages/s01_init.py` | Initialization |
| `stages/s02_perception.py` | Semantic perception + drives + somatic |
| `stages/s02b_input_drive_map/` | Input to drive mapping (BGE) |
| `stages/s02c_delayed_understand.py` | Delayed understanding |
| `interpretation_competition/` | Interpretation competition submodules |
| `stages/s03_think.py` | Emotion particles + thinking |
| `stages/s04a_meta.py` | Meta-cognitive adjustment |
| `stages/s04b_emerge.py` | Behavior emergence |
| `stages/s04b_self_mapping.py` | Self-mapping + narrative generation (extracted from s04b) |
| `stages/s05_behavior.py` | Connection depth + decision assembly |
| `stages/s05b_pattern_feedback.py` | BP feedback loop (extracted from s05) |
| `stages/s06_language/` | LLM output stage |
| `stages/s06a_candidates.py` | Language candidate generation |
| `stages/s06a_candidates.py` | Language candidate generation |
| `stages/s06a_training_mode.py` | Training mode somatic help (extracted from s06a) |
| `stages/s07a_state_update.py` | State write-back |
| `stages/s07a_integrity_tick.py` | Integrity monitor tick (extracted from s07a) |
| `stages/s07b_persist.py` | Snapshots + memory |
| `stages/s07c_language_finalize.py` | Quenching loop + persistence |
| `context.py` | Shared pipeline context object |

---

## 2. daemon - Long-Running Process

**Responsibility**: Long-term memory service main process. Contains IPCServer, HTTPServer, and TickEngine.

**Entry files**: `src/daemon/daemon.py`

**Inputs**: User IPC/HTTP requests, tick interval

**Outputs**: Tick events, persisted state, IPC/HTTP responses

**Key dependencies**: `pipeline_runner`, `entity_state`

**Common change risks**:
- Changing port numbers breaks IPC clients
- Changing tick interval affects entity rhythm

**Recommended checks**: daemon starts and responds to IPC requests

### Submodules

| File | Function |
| --- | --- |
| `daemon.py` | Main entry, IPCServer/HTTPServer/TickEngine assembly |
| `http_server.py` | Windows-compatible HTTP API forwarding to IPC handlers |
| `ipc_chat_handler.py` | IPC chat handling, cache probing, pipeline dispatch, and source profiling |
| `tick_engine.py` | Background tick advancement (every 30s calls `run_pipeline`) |
| `action_execution.py` | Bridges pipeline decisions into daemon-triggered actions |
| `async_updates.py` | Submits fire-and-forget experience/world-model update coroutines |
| `autonomous_action_memory.py` | Writes autonomous action results into episodes, snapshots, and behavior rules |
| `causal_observation.py` | Records source/state-delta causal observations with rolling retention |
| `covariance_update.py` | Updates covariance tracker state and attention weights |
| `environment_vector.py` | Maintains per-tick semantic residue and social prediction tension |
| `expression_postprocess.py` | Applies expression feedback, self-counsel, and epistemic credit settling |
| `output_causal_observation.py` | Tracks output-caused state deltas across daemon ticks |
| `periodic_maintenance.py` | Runs scheduled causal learning, weathering drift, and tension snapshots |
| `reading_cycle.py` | Runs reading intake and reading-derived sentence pattern extraction |
| `reflection_jepa_tick.py` | Runs inner diary, reflection, and JEPA learning steps |
| `response_prewarm.py` | Pre-warms response cache entries from drive vectors and output text |
| `sibling_tick.py` | Handles sibling-channel social credit, fork checks, and anchor posting |
| `source_tick.py` | Updates source profiles, reply drive, semantic residue, and familiarity effects |
| `state_pattern_tick.py` | Runs StatePatternMemory internal symbol emergence per tick |
| `tick_input.py` | Prepares reach/sibling input, source identity, and input feedback hooks |
| `tick_status.py` | Builds daemon status summaries |
| `world_model_tick.py` | Runs world-model induction, question tension release, and reading taste updates |
| `ipc_client.py` | Unix Socket/TCP client |
| `protocol.py` | IPC request/response format |
| `reading_source.py` | Reads text from `library/` for vocabulary acquisition |
| `reading_taste.py` | Reading taste tracking |

### Communication Ports

- Windows: TCP `127.0.0.1:8766` (IPC), `127.0.0.1:8765` (HTTP)
- Linux: Unix Socket `data/xia_daemon.sock`

### Startup

```bash
python -m src.daemon.daemon
```

---

## 3. entity_state - Central State Container

**Responsibility**: Holds all of XIA's internal state: drives, emotions, memory snapshots, world model rules, and more.

**Entry files**: `src/entity_state.py`

**Inputs**: All subsystems write to it

**Outputs**: State snapshots written to `data/entity_core.json` every tick

**Key dependencies**: All subsystems

**Common change risks**: Adding a new state variable requires persistence schema migration

**Recommended checks**: `python tests/test_50_ticks.py`

### Key State Variables

| Variable | Range | Description |
| --- | --- | --- |
| `energy` | [0, 1] | Available activation energy |
| `loneliness` | [0, 1] | Loneliness (surface) |
| `loneliness_core` | [0, 1] | Loneliness (core) |
| `fatigue` | [0, 1] | Fatigue level |
| `boredom` | [0, 1] | Boredom level |
| `stress` | [0, 1] | Stress level |
| `somatic_tone` | [-1, 1] | Overall somatic tone |
| `approach_drive` | [0, 1] | Approach drive |
| `avoid_drive` | [0, 1] | Avoidance drive |
| `unresolved` | [0, 1] | Unresolved tension |
| `info_gap` | [0, 1] | Information gap |
| `curiosity` | [0, 1] | Curiosity intensity |

### Emotion Dimensions

joy, sadness, anger, fear, anxiety, surprise, disgust, serenity, excitement, curiosity

### Persistence

`data/entity_core.json` (written every tick)

---

## 4. drive_system - Drive Computation

**Responsibility**: Computes raw drives from entity state (curiosity, loneliness, fatigue avoidance, etc.).

**Entry files**: `src/drive_system/drive_system.py` (main entry), `src/drive_system/drive_system_helpers.py` (curves, data structures)

**Inputs**: Entity state

**Outputs**: `drive_vector` dict

**Key dependencies**: `entity_state`

**Common change risks**: Changing drive names breaks `drive_vector_field.py`

**Recommended checks**: `python tests/test_50_ticks.py`

### Output Drives

- `curiosity`
- `info_hunger`
- `loneliness_drive`
- `fatigue_avoid`
- `obsolescence_anxiety`

### Core Function

`compute_drive_vector(state, params) -> dict`

### Design Note

Pure sensor, no decision logic. Shape table lookup + linear interpolation.

---

## 5. emotion_system - Emotion Computation

**Responsibility**: Three-layer emotion projection (main thread, daily layer, memory layer).

**Entry files**: `src/emotion_system/__init__.py`

**Inputs**: Entity state, event triggers

**Outputs**: Emotion values, particle field, insight writes

**Key dependencies**: `entity_state`, `memory_hub`

**Common change risks**: Changing decay half-lives changes emotional rhythm

**Recommended checks**: Visual inspection of emotion traces

### Submodules

| File | Function |
| --- | --- |
| `particle_field.py` | Daily layer particle field (background texture) |
| `projection_controller.py` | Three-layer projection damping control |
| `decay_engine.py` | Emotion decay engine (independent half-lives) |
| `insight_writer.py` | Surprise -> Insights writing |
| `emotion_compute.py` | Ten-dimensional emotion computation (main thread) |

### Emotion Dimensions

joy, excitement, serenity, sadness, anger, fear, disgust, anxiety, surprise, curiosity

### Decay Half-Lives (default)

joy=3600s, fear=1800s, anger=2400s, sadness=5400s, surprise=600s

---

## 6. decision_system - Decision System (Nine-Module Perception)

**Responsibility**: Parallel perception + decision assembly.

**Entry files**: `src/decision_system/decision_system.py`

**Inputs**: Entity core, semantic packet, concept tags, wm_context, drive_vector, thought_packet, state_snapshot

**Outputs**: Modified drive vectors, assembled decisions

**Key dependencies**: `entity_state`, `drive_system`, `world_model_update`, `thinking_system`

**Common change risks**: Module ordering affects final decision

**Recommended checks**: `python tests/test_50_ticks.py`

### Core Function

`perceive_all(entity_core, semantic_packet, concept_tags, wm_context, drive_vector, thought_packet, state_snapshot, params)`

### Submodules (`src/decision_system/submodules/`)

| Module | Modified State |
| --- | --- |
| `situation_assessment` | approach_drive |
| `context_awareness` | loneliness, approach_drive, avoid_drive, danger_level |
| `thought_integration` | approach_drive, avoid_drive |
| `signal_activation` | avoid_drive, approach_drive, somatic_tone |
| `mainline_constraint` | avoid_drive, approach_drive |
| `temporal_pressure` | fatigue, approach_drive |
| `self_state` | avoid_drive, somatic_tone |
| `preference` | approach_drive, avoid_drive |
| `world_model` | curiosity, approach_drive, avoid_drive |
| `web_search` | (no direct modification) |
| `tool_self_check` | (tool introspection) |

---

## 7. thinking_system - Thinking System

**Responsibility**: Emergent questions and suggestions, data-driven, no hardcoded templates.

**Entry files**: `src/thinking_system/thinking_system.py` (main entry), `src/thinking_system/thinking_system_helpers.py` (dimensions, focal rules, suggestions), `src/thinking_system/thinking_system_questions.py` (question generation, rendering)

**Inputs**: wm_context, drive_vector, state_snapshot, somatic_signals, entity_state

**Outputs**: `ThoughtPacket` with suggestions, questions, branch_memories

**Key dependencies**: `world_model_update`, `drive_system`, `entity_state`

**Common change risks**: Changing output structure breaks `pipeline_runner`

**Recommended checks**: `python tests/test_50_ticks.py`

### Core Function

`think(wm_context, drive_vector, state_snapshot, params, somatic_signals, entity_state, ...) -> ThoughtPacket`

### Output

```python
{
    "suggestions": [{"action": str, "reason": str, "priority": float}],
    "questions": [{"type": str, "rule_id": str, "dims": list, "confidence": float}],
    "branch_memories": [dict],
}
```

### Core Flow

```
drive field -> active dimensions -> focal rules (by overlap) -> questions + suggestions -> somatic modulation -> mental simulation verification
```

### Submodules

| File | Function |
| --- | --- |
| `semantic_tables.py` | Semantic constants (dimensions, actions, causal seeds) |
| `semantic_base.py` | Semantic query interface (delta interpretation) |
| `mental_simulation.py` | Mental simulation for suggestion verification |
| `covariance_tracker.py` | Covariance tracking (dimensional attention weights) |

---

## 8. language_system - Language Expression Loop

**Responsibility**: Somatic anchor -> candidate words -> sentence composition -> quenching feedback. v7.0 includes six sovereignty controllers, all-BGE local reasoning, interpretation competition, and delayed understanding.

**Entry files**: `src/language_system/__init__.py`

**Inputs**: Somatic signals, drive vector, entity state

**Outputs**: Language output text, quenching records, learned templates

**Key dependencies**: `entity_state`, `drive_system`, `bge_analyzer`

**Common change risks**: Changing word warmup thresholds breaks vocabulary acquisition

**Recommended checks**: `python tests/test_integration_language.py`

### Core Submodules (30+ files)

| File | Function |
| --- | --- |
| `quenching.py` | Quenching efficiency tracking |
| `quenching_schema.py` | QuenchingRecord dataclass |
| `quenching_helpers.py` | Hash + serialization helpers |
| `word_warmup.py` | Vocabulary cold->warm unlocking (>=3 quenchings unlock, v11.3 separates activation from forgetting) |
| `word_warmup_helpers.py` | Hash decoding + rest consolidation |
| `sentence_composer.py` | Anchor words -> sentences, softmax sampling (thin entry) |
| `sentence_composer_schema.py` | Hyperparameters + math helpers |
| `sentence_composer_helpers.py` | Template fill helpers |
| `somatic_anchors.py` | Thin re-export (somatic_anchors_data.py) |
| `somatic_anchors_data.py` | SOMATIC_ANCHORS / ANCHOR_CLUSTERS / ALL_DIMENSIONS data tables |
| `somatic_concept_map.py` | Somatic word <-> drive field mapping (core API) |
| `somatic_concept_map_helpers.py` | BGE propagation + clustering helpers |
| `strategy_map.py` | Strategy map immediate cache layer |
| `connector_map.py` | Intensity prefix / mood opening / suffix scoring |
| `template_learner.py` | Template learning |
| `construction_grammar.py` | Construction learning ("mouth" - output side, thin entry) |
| `construction_schema.py` | Hyperparameters + ExpressionInstance + Construction class |
| `construction_utils.py` | Standalone helper functions |
| `construction_parser.py` | Construction parsing ("ear" - input side, three-layer parsing) |
| `construction_learning.py` | Learn constructions from input (3-fold efficiency) |
| `source_profiler.py` | Other modeling (familiarity / trust / status_belief) |
| `reply_motivator.py` | Reply motivation: relationship weight * intent weight * state modulation |
| `reflection_layer.py` | **Rumination layer**: LLM acts as a mirror for deep episode review |
| `state_pattern_memory.py` | **Internal symbol emergence**: hit >=3 forges internal symbols (e.g. "null-curious-lonely") |
| `state_pattern_memory_schema.py` | Constants, InternalPattern dataclass, bootstrap data |
| `state_pattern_memory_helpers.py` | Math tools (cosine sim, EMA update, forge, bootstrap) |
| `somatic_self_awareness.py` | **Somatic meta-awareness**: somatic decoding -> self-reference -> awareness intensity modulation |
| `narrative_fragments.py` | **Narrative fragments**: action self-reference / causal narrative / state trajectory, softmax sampling |
| `narrative_context.py` | Context and lookup-table construction for narrative fragment scoring |
| `bge_analyzer.py` | BGE-small-zh-v1.5 embedding anchor matching (LLM-replacement approach) |
| `concept_graph.py` | Concept graph: somatic words -> material/force/shape/abstract attribute combinations |
| `input_packet.py` | Input packet: topic_anchor / relational_direction / social_intent |
| `pronoun_direction.py` | Subject direction recognition (you/I/external thing) |
| `syntax_parser.py` | Lightweight syntactic analysis: subject-predicate-object + SVO + negation/question |
| `expression_feedback.py` | **Expression feedback loop**: drive -> expression -> external response -> need satisfaction -> reinforcement/weakening |
| `interpretation_competition.py` | **Interpretation competition**: competitiveness = experience_strength * f(state) * conversion_coefficient, tension suspension permeates output |
| `interpretation_schema.py` | Competition dataclass definitions (ExperienceCandidate, CompetitionResult) |
| `interpretation_compute.py` | Scoring & candidate building |
| `delayed_understanding.py` | **Delayed understanding**: below-threshold confidence enters pending queue, awaits triggering activation |
| `preoccupation_engine.py` | **Preoccupation system**: worry/miss/anticipate/anxious/nostalgic/curious - thoughts with object and time span |
| `social_comprehension.py` | Understand sibling channel input, generate resonance and credit quenching |
| `stereotype_tree.py` | **Stereotype tree**: hierarchical speaker cognitive structure (category->region->situation->individual) |
| `stereotype_tree_nodes.py` | StereotypeNode / StereotypeContext dataclasses |
| `stereotype_learner.py` | **Stereotype learner**: extract speaker characteristic labels (thin entry) |
| `stereotype_markers.py` | Linguistic marker constants |
| `stereotype_memory.py` | MEMORY.md tag extraction and tree initialization |
| `teacher.py` | Teaching module |
| `teacher_lexicon.py` | Teacher lexicon: concept -> somatic entry -> her words -> reflective sentences |
| `mirror.py` | Mirror learning, build own version of understanding |
| `five_rights.py` | **Six sovereignty controllers**: self-closure right / boredom right / misunderstanding right / forgetting right / contradiction right / physical gravity |
| `five_rights_helpers.py` | Serialization helpers + check_defy impl |
| `semantic_analyzer.py` | LLM semantic anchor matching (v1, replaced by BGE) |
| `thermal.py` | Adaptive temperature control |
| `meta_cognitive.py` | Meta-cognitive snapshot analysis |
| `abundance_monitor.py` | Language abundance monitoring |

### New Core Mechanisms

- **Expression feedback loop** (`expression_feedback.py`): drive -> expression -> external response -> need satisfaction -> reinforcement/weakening. Solves the "self-deception" problem.
- **Interpretation competition** (`interpretation_competition.py` + `interpretation_schema.py` + `interpretation_compute.py`): multiple experiences competing in parallel, tension_level permeates language output
- **Delayed understanding** (`delayed_understanding.py`): below-threshold understanding enters pending queue, awaits similar input activation
- **Preoccupation system** (`preoccupation_engine.py`): worry/miss/anticipate/anxious/nostalgic/curious - thoughts with object and time span
- **Rumination layer** (`reflection_layer.py`): every 10 ticks uses LLM to deeply review dialogue, updates preoccupations and self-narrative
- **Somatic meta-awareness** (`somatic_self_awareness.py`): three layers (decoding -> reference -> modulation), pure rules without LLM
- **Internal symbol emergence** (`state_pattern_memory.py`): state exists but word does not -> forges internal symbols like "null-curious-lonely"

### Core Concepts

- **Quenching**: after speaking, unresolved truly decreases
- **Vocabulary unlocking**: words hit >=3 times are permanently unlocked (v11.3: activation and forgetting are separated)
- **Template learning**: efficient expressions solidify into templates
- **Six sovereignties**: self-closure / boredom / misunderstanding / forgetting / contradiction / physical gravity (fragmentation mapped to output parameters)

---

## 9. action_system - Autonomous Action System (V7)

**Responsibility**: Trigger evaluation + execution of XIA's self-chosen actions. She has the right to decide what she wants to do; we only execute.

**Entry files**: `src/action_system/__init__.py`

**Inputs**: Entity state, tick events, trigger evaluation

**Outputs**: Tool executions, voice files, governance audit records

**Key dependencies**: `entity_state`, `pipeline_runner`, `language_system`

**Common change risks**: Changing action types breaks executor tool filtering

**Recommended checks**: Manual inspection of action executions and voice files

### V7 Architecture

```
TickEngine.tick_now()
  -> run_pipeline(daemon_mode=True)    state advancement
  -> evaluate_triggers(entity)         does she qualify for action now?
  -> if triggered:
        ask_xia_what_to_do()          ask her: what do you want to do?
        execute_xia_choice(entity)     whatever she says, we execute
```

### Trigger Conditions (state-driven, no hardcoded thresholds)

- loneliness at sustained high level
- silence duration exceeds threshold
- boredom at high level
- info_gap at high level
- stress at high level

### Action Types (`types.py`)

| Type | Description |
| --- | --- |
| `voice` | Write silently, text for herself to read |
| `reach` | Proactively knock, wants user to know immediately (REACH: prefix) |
| `write` | Use file_write tool |
| `run` | Use shell_run tool |
| `browse` | Use browser tool |
| `search` | Web search |
| `mixed` | Multiple operations combined |

### Tool Filtering by Type (`executor.py`, `ACTION_TOOL_WHITELIST`)

- `seek` -> no tools (expression only)
- `explore` -> web_search / browser_* / file_read
- `repair` -> shell_run / ask_hermes
- `comfort` / `rest` / `avoid` / `idle` -> no tools
- `write` -> file_write / file_read

### Executor Flow (`executor.py`)

```
1. Build state description (_build_state_description)
2. Build tool description (_build_tool_notice, filtered to only what is needed)
3. Call LLM (XIA decides what she wants to do)
4. Extract and execute tool calls
5. Parse REACH: prefix to determine if knocking
6. Write voice file to data/xia_voice/
7. Write manifest to data/xia_voice/manifest.jsonl
8. Tool execution somatic feedback (state write-back)
9. Failure attempt repair (_attempt_failure_resolution)
10. Trigger capability gap analysis
```

### Failure Handling (`_analyze_tool_failures`)

- `ModuleNotFoundError` / `ConnectionError` / `Timeout` / `PermissionDenied` / `NotFound` / `SyntaxError` / `DependencyError`
- Severity evaluation + write to failure_records
- Auto-inject fix_rule into wm_rules

### Tool Registry (`agent_tools/registry.py`)

- File tools (file_read / write / list / delete)
- Shell tools (shell_run / bg_run)
- Browser tools (browser_open / screenshot / click / fill / get_text / navigate)
- Search tools (web_search)
- Hermes tools (ask_hermes)
- Dynamic tool registration (`register_tool_definition`)

### Governance Audit (`executor._write_governance_audit`)

Records every tool usage to `logs/governance_audit.jsonl`

### Submodules

| File | Function |
| --- | --- |
| `types.py` | XIAction / FailureRecord data structures, error classification |
| `triggers.py` | Continuous trigger intensity evaluation |
| `executor.py` | V7 executor entry, action parsing, voice file and manifest writing |
| `executor_prompts.py` | Action prompt, state description, tool notice, and LLM call helpers |
| `executor_feedback.py` | Tool failure analysis and somatic state feedback |
| `executor_failure_resolution.py` | Failure resolution, fix-rule injection, and capability-gap analysis |
| `tools.py` | Tool definitions (TOOL_DEFINITIONS) |
| `tools_nl_extractors.py` | Natural-language tool intent extraction helpers |
| `reach.py` | reach_out knocking mechanism |
| `agent_tools/registry.py` | Tool registry + execute_tool_call |
| `agent_tools/filesystem.py` | File operation tool set |
| `agent_tools/shell.py` | Shell execution tool set |
| `agent_tools/browser.py` | Browser control tool set |
| `agent_tools/search.py` | Search tool set |
| `agent_tools/hermes.py` | Hermes diagnostic tools |

---

## 10. world_model_update - World Model Induction and Update

**Responsibility**: Induce causal rules from snapshots and dialogue, verify/decay/merge.

**Entry files**: `src/world_model_update/__init__.py`

**Inputs**: Old rules, snapshots, dialogue log, state snapshots, param snapshots

**Outputs**: New rules, CycleStats

**Key dependencies**: `memory_hub`, `entity_state`

**Common change risks**: Changing rule schema breaks persistence

**Recommended checks**: `python tests/test_50_ticks.py`

### Core Function

`run_update_cycle(old_rules, snaps, dialogue_log, state_snapshot, param_snapshot) -> (new_rules, CycleStats)`

### Execution Order

`load -> induct -> merge -> decay -> verify -> persist`

### Submodules

| File | Function |
| --- | --- |
| `rules.py` | Rule and snapshot data structures |
| `defaults.py` | Default parameters |
| `induct.py` | Induction (v11.2 prediction-error driven) |
| `induct_helpers.py` | Helper functions for induction (generators, pruning, formatters) |
| `induct_test.py` | Test entry point |
| `verify.py` | Verification (Bayesian learning rate) |
| `decay.py` | Decay (endocrine regulation + stability protection) |
| `merge.py` | Merge (O(N) incremental embedding similarity) |
| `core.py` | Orchestration layer + external dispatch interface |
| `contradiction.py` | Contradiction detection |
| `dimension_cost.py` | Dimension maintenance cost (Occam's razor) |

---

## 11. state_update - State Update Engine

**Responsibility**: Computes natural decay of internal state, behavior feedback, and state interactions. Unified compute ledger v2.0.

**Entry files**: `src/state_update/__init__.py`

**Inputs**: Entity state, load contributions from all subsystems

**Outputs**: Updated entity state

**Key dependencies**: `entity_state`, all subsystems

**Common change risks**: Changing energy computation affects the entire rhythm

**Recommended checks**: `python tests/test_50_ticks.py`

### Core Ideas

- `energy` = total compute - all current loads (instantaneous, not cumulative)
- Recovery = compute naturally flows back after load decreases, not "charging"
- `stress` = number of unprocessed unexpected signals, does not use half-life decay

### Unified Compute Ledger v2.0 (`update_engine.py`)

```
energy = total compute
         - social load
         - cognitive load
         - info load
         - meta load
         - emotional load
         - stress load
         - fatigue_delay
         - frontload
         - idle
```

### Oxytocin Tone (`oxytocin_signal.py`): "warm afterglow after successful connection"

- Three-gate trigger: `connection_depth > 0` * `has_social_input` * `somatic_tone_delta > 0`
- Rise: boost_k controls magnitude
- Decay: regresses toward 0.5, regression_rate controls half-life (~230 minutes)
- Effect: when oxytocin > 0.5, amplifies approach_social, suppresses boredom_futility, slows loneliness_core accumulation

### Submodules

| File | Function |
| --- | --- |
| `update_engine.py` | State update main engine (unified compute ledger v2.0) |
| `update_engine_helpers.py` | Helpers + state-field step functions |
| `update_engine_test.py` | Inline tests (extracted) |
| `info_queue.py` | Information queue (intake -> digest -> gap) |
| `compute_load.py` | Compute load calculation |
| `compute_coherence.py` | Coherence computation |
| `compute_connection.py` | Connection depth / loneliness goals |
| `compute_connection_helpers.py` | Helpers + extended versions |
| `compute_connection_test.py` | Inline tests (extracted) |
| `dopamine_tone.py` | Dopamine tone |
| `oxytocin_signal.py` | Oxytocin tone (three-gate trigger + natural decay) |
| `quenching/` | Six-channel quenching sub-package |

---

## 12. memory_hub - Memory System

**Responsibility**: Raw event log persistence + visceral sensation center.

**Entry files**: `src/memory_hub/__init__.py`

**Inputs**: Tick events, state snapshots, dialogue

**Outputs**: SQLite records, visceral sensation markers

**Key dependencies**: `entity_state`, `observability`

**Common change risks**: Changing the SQLite schema breaks existing data

**Recommended checks**: `python tests/test_50_ticks.py`

### Submodules

| File | Function |
| --- | --- |
| `episodes_db.py` | SQLite event log (always writes first) |
| `episodes_db_schema.py` | DB init, table definitions |
| `episodes_db_helpers.py` | Dataclasses, importance, builders |
| `insula_hub.py` | Visceral sensation center (topological indicators -> somatic markers) |
| `tetramem_adapter.py` | TetraMem HTTP adapter (external memory service) |
| `tetramem_persistence.py` | Fallback persistence layer (local JSON read/write) |
| `insights_db.py` | Insights DB init & path management |
| `insights_schema.py` | Insight dataclass & field extraction |
| `insights_api.py` | Insights read/write API |
| `insights.py` | Insights entry (re-exports) |

### Core Table Schema (episodes.db)

```sql
CREATE TABLE episodes (
    iteration_id, timestamp, raw_input, output_text,
    decision, state_snapshot, drive_vector, tags, summary
);
```

---

## 13. core - Core Mechanisms

**Responsibility**: Entity core, somatic signals, behavior emergence, V6 drive vector field.

**Entry files**: `src/core/__init__.py`

**Inputs**: Entity state, drive vector

**Outputs**: Somatic signals, emergent behavior, behavior vector

**Key dependencies**: `entity_state`, `drive_system`, `world_model_update`

**Common change risks**: Changing the antagonism matrix changes behavior emergence

**Recommended checks**: `python tests/test_50_ticks.py`

### V6 Drive Vector Field (`drive_vector_field.py`)

- 7-dimensional state-layer drives: curiosity / info_hunger / loneliness / fatigue / unresolved / somatic_tone_p / danger
- Antagonism matrix + exponential decay: `net[dst] = raw[dst] * exp(-sum(raw[src] * weight[src->dst]))`
- Continuous phase-transition alpha (fragmentation coefficient): gives behavior texture instead of hard switching
- behavior_vector = net * (1 - alpha^2)
- Rule effect is fully endogenous (induced from historical snapshots, not manually preset)

### Integrity System

- `integrity_monitor.py`: scans expression / perception / cognition / continuity four regions, generates change_magnitude
- `integrity_signal.py`: change events -> active_harm / drive_delta / behavior_bias (three-gate trigger + natural healing)
- `self_binding.py`: region binding strength = frequency * 0.4 + perturbation_depth * 0.6, cold start automatic transition

### Submodules

| File | Function |
| --- | --- |
| `entity_core.py` | Lightweight state container (for V6 system) |
| `somatic_signals.py` | Somatic signals and DoS protection |
| `emergent_behavior.py` | Behavior emergence mechanism (antagonism matrix -> behavior type) |
| `behavior_vector.py` | Regularized behavior vector |
| `state_to_context.py` | State -> situation description generator |
| `drive_vector_field.py` | V6 drive vector field (7-dim + antagonism + continuous phase transition) |
| `drive_tables.py` | Constants table (DRIVE_DIMS, antagonism matrix, math tools) |
| `integrity_monitor.py` | Integrity monitoring | (scans expression/perception/cognition/continuity four regions) |
| `integrity_signal.py` | Integrity change signal generation (active_harm / drive_delta / behavior_bias) |
| `self_binding.py` | Self-binding strength calculation (frequency + perturbation_depth) |
| `behavior_patterns_schema.py` | Dataclass + schema constants + update_long_term_bias (extracted from behavior_patterns.py) |
| `behavior_patterns_pool.py` | PatternPool + _WorldModelDB (extracted from behavior_patterns.py) |
| `behavior_patterns.py` | Entry module: re-exports + scoring functions (192L) |

---

## 14. weathering - Weathering System

**Responsibility**: Long-term parameter drift and collapse simulation.

**Entry files**: `src/weathering/__init__.py`

**Inputs**: Entity state, parameter registry

**Outputs**: Drifted parameter values, shattering events

**Key dependencies**: `entity_state`, `param_store`

**Common change risks**: Aggressive drift destroys learned patterns

**Recommended checks**: Monitor parameter drift over long runs

### Submodules

| File | Function |
| --- | --- |
| `registry.py` | Drifting parameter registry |
| `baseline.py` | Baseline storage |
| `drift.py` | Normal / acute drift |
| `shattering.py` | Collapse detection and handling |
| `signal_bridge.py` | Correlation -> drift signal |
| `param_writer.py` | Parameter read/write |
| `domain_map.py` | Domain parameter mapping |

### Execution Frequency

- Normal drift: every 300 entity ticks (covariance samples >= 50)
- Tension snapshots: every 600 entity ticks

---

## 15. response_cache - Response Cache

**Responsibility**: Response cache acceleration based on drive similarity.

**Entry files**: `src/response_cache/response_cache.py`

**Inputs**: drive_vector

**Outputs**: (text, similarity) tuple or None

**Key dependencies**: `drive_system`

**Common change risks**: Cache invalidation on state change

**Recommended checks**: Cache hit rate monitoring

### Core Class: `ResponseCache`

### Method: `match(drive_vector) -> (text, similarity)`

### Use Case

When a chat request arrives, if the cache hits with high similarity, return the cached response directly, skipping the LLM call.

---

## 16. tool_introspection - Tool Capability Introspection

**Responsibility**: Makes XIA aware of her own tool boundaries and discover capability gaps.

**Entry files**: `src/tool_introspection/__init__.py`

**Inputs**: Tool execution results, entity state

**Outputs**: Capability gap signals injected into curiosity / unresolved

**Key dependencies**: `action_system`, `entity_state`

**Common change risks**: Gap detection noise pollutes curiosity

**Recommended checks**: Review gap analysis output logs

### How It Works

- Passive: triggered by `executor._trigger_capability_gap_analysis` after tool execution failure
- Active: decision_system Module 10 (`tool_self_check.py`) introspects during think stage

### Submodules

| File | Function |
| --- | --- |
| `registry_watcher.py` | Tool registry watcher (has_tool / match_tool) |
| `capability_gap_detector.py` | Capability gap detection (gap_intensity -> curiosity / unresolved injection) |
| `intent_analyzer.py` | Failed intent extraction (infer intended_action from error type) |

### Design Principles

Continuous signals, no if-else, caching prevents duplicate computation (TTL=60s)

---

## 17. tool_synthesizer - Tool Synthesis

**Responsibility**: Synthesize new tool definitions from failure experience.

**Entry files**: `src/tool_synthesizer/__init__.py`

**Inputs**: Failure records, entity state

**Outputs**: New tool definitions registered in `agent_tools/registry.py`

**Key dependencies**: `tool_introspection`, `action_system`

**Common change risks**: Synthesizing invalid tools causes execution failures

**Recommended checks**: Verify synthesized tool definitions before execution

### Submodules

| File | Function |
| --- | --- |
| `llm_synthesizer.py` | LLM-assisted tool synthesis (fallback path) |
| `template_synthesizer.py` | Template composition for fast generation (main path) |

### Design Principles

- LLM as a crutch; replace with endogenous synthesis once the language system matures
- At most 1 tool synthesized per tick
- Result registered in `agent_tools/registry.py`

---

## 18. observability - Observability

**Responsibility**: Structured event logs for debugging and monitoring.

**Entry files**: `src/observability/__init__.py`

**Inputs**: Subsystem event signals

**Outputs**: Structured log entries

**Key dependencies**: All subsystems

**Common change risks**: Adding event types requires updating consumers

**Recommended checks**: Log file integrity checks

### Event Types

`DriftEvent`, `RuleLifecycleEvent`, `ShatteringEvent`, `TensionSnapshot`

### Core Functions

`emit_event(event)`, `read_events()`, `clear_events()`

---

## 19. jepa - World Prediction Model

**Responsibility**: JEPA (Joint Embedding Predictive Architecture) world model. Learns internal structural dependencies and temporal dynamics from state sequences.

**Entry files**: `src/jepa/__init__.py`

**Inputs**: 7-dimensional state vector (energy, fatigue, loneliness, curiosity, somatic_tone, unresolved, info_gap)

**Outputs**: reconstruction_error, surprise_density, transition_ticks

**Key dependencies**: `entity_state`, `memory_hub`

**Common change risks**: Encoder weight corruption breaks world predictions

**Recommended checks**: Monitor reconstruction error over long runs

### Core Dimensions

- Input: 7-dim state vector
- Latent: 4-dim (empirically, major change directions in 7-dim input do not exceed 4-5)

### I-JEPA (`IJepa`, called `step(entity)` every tick)

```
1. Randomly mask 1-2 state dimensions
2. Encode visible dimensions -> latent z
3. predictor heads[i] @ z -> predict masked dimension values
4. MSE loss -> gradient backprop to update predictor heads + encoder
5. Return reconstruction_error (rolling mean, used by V-JEPA for structural stability)
```

- Learning rate: encoder=0.005, predictor=0.01 (predictor is shallower and larger)
- Every 100 ticks saves weights to `data/jepa_encoder.npz` + `data/i_jepa_predictor.npz`

### V-JEPA (`VJepa`, called `summarize(entity)` every V_JEPA_INTERVAL=200 ticks)

```
1. Read last 60 state snapshots from episodes.db
2. Encode -> latent sequence z_seq
3. Train temporal predictor z_t -> z_{t+1} (3 passes)
4. Compute prediction_error temporal distribution
5. surprise_density = sigmoid(SURPRISE_SCALE * (mean_err - 0.3)), normalized to [0, 1]
6. transition_ticks = high-error moments (quantile > 0.85 ticks)
7. Write back entity._jepa_surprise_density for pipeline use
```

- Weights saved to `data/v_jepa_predictor.npz`
- surprise_density calibrates entity.curiosity baseline

### Submodules

| File | Function |
| --- | --- |
| `jepa_encoder.py` | Shared encoder, state -> latent mapping + online SGD gradient update |
| `i_jepa.py` | I-JEPA long-term background: random mask 1-2 dimensions, predict masked from visible latent |
| `v_jepa.py` | V-JEPA short-term summarization: train temporal predictor (z_t -> z_{t+1}), compute surprise_density |

### Core Functions

- `get_encoder() -> JepaEncoder` - encoder singleton
- `get_i_jepa() -> IJepa` - I-JEPA singleton
- `get_v_jepa() -> VJepa` - V-JEPA singleton
- `IJepa.rolling_error() -> float` - last 50 steps average reconstruction error
- `VJepa.last_result() -> dict` - last summarization result (surprise_density, transition_ticks, ...)

---

## Data File Locations

| File | Description |
| --- | --- |
| `data/entity_core.json` | Entity state (written every tick) |
| `data/episodes.db` | SQLite event log |
| `data/world_model_db.json` | World model rules |
| `data/behavior_patterns.json` | Behavior pattern database |
| `data/library/` | Reading source texts |
| `data/xia_voice/` | Autonomous action outputs |
| `data/jepa_encoder.npz` | JEPA encoder weights |
| `data/i_jepa_predictor.npz` | I-JEPA predictor weights |
| `data/v_jepa_predictor.npz` | V-JEPA temporal predictor weights |
| `data/integrity_snapshot.json` | Integrity monitoring snapshot |
| `data/self_binding.json` | Self-binding strength data |
| `logs/daemon_live.log` | Runtime log |

---

## Key Data Flows

### Chat Request Flow

```
IPCServer._handle_chat(text)
  -> run_pipeline(raw_input=text)
    -> s01_init: parameter snapshot
    -> s02_perception: semantic perception + drives + somatic
    -> s02b_input_drive_map: BGE embedding -> drive centroid matching
    -> [interpretation_competition]: experience candidates competing
    -> s02c_delayed_understand: delayed understanding
    -> s03_think: emotion particles + thinking
    -> s04a_meta: meta-cognitive adjustment
    -> s04b_emerge: behavior emergence
    -> s05_behavior: connection depth + decision assembly
    -> s06_language: language generation (LLM or anchor)
    -> s07a_state_update: state write-back
    -> s07b_persist: snapshots + memory
    -> s07c_language_finalize: quenching loop + persistence
  -> return response
```

### Background Tick Flow

```
TickEngine.tick_now()
  -> run_pipeline(daemon_mode=True)  # no user input, skip LLM
    -> (same as above, without LLM output)
  -> evaluate_triggers()  # check if active action is triggered
  -> execute_xia_choice()  # if triggered, execute XIA's choice
  -> write_diary_entry()  # inner diary
  -> persist_to_file()  # state persistence
```

---

## Maintenance Checklist

When modifying these areas, **you must update** this index and the corresponding README:

| Change Type | Update Location |
| --- | --- |
| New system | Add to "System Overview" + create `src/{system}/README.md` |
| New submodule | Add to corresponding system section + update system README |
| Change core interface (e.g. `run_pipeline` parameters) | Update "Key Parameters" in section 1 |
| Change data file location | Update "Data File Locations" |
| New event type | Update section 18 (observability) |
| Change subsystem internal logic | Update corresponding system README.md |
| New language_system submodule | Update section 8 submodule table |
| Pipeline stage split | Update section 1 stage order |

### README Maintenance Principles

- Each subsystem root directory must have a `README.md` (thinking_system, world_model_update, language_system, core take priority)
- README describes the system's **responsibility, data flow, and core interfaces**. Do not duplicate single-file docstrings
- Update README promptly after changes; do not leave stale documentation
- Required format: **data flow diagram + submodule responsibility table + key function signatures**. All three are required.

### Subsystem Code Change Maintenance Process

1. Finish modifying the code -> sync the corresponding `src/{system}/README.md`
2. If the change affects cross-system interfaces (e.g. `thinking_system` output structure changed) -> also update XIA_SYSTEMS.md
3. Finally update the `Last updated` date at the bottom

---

*Last updated: 2026-06-09*
