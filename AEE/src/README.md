# `src/` Source Map

`src/` contains the runtime implementation for XIA. The codebase is organized
around a persistent entity state, a background daemon, and a staged pipeline.

## Root-Level Entry Files

| File | Purpose |
| --- | --- |
| `entity_state.py` | `EntityState` dataclass, state methods, singleton access |
| `entity_io.py` | State file paths and atomic JSON IO |
| `entity_lifecycle.py` | Startup recovery, offline drift, silence injection |
| `entity_persistence.py` | Full persistence/load implementation |
| `entity_core_wrapper.py` | Compatibility wrapper for behavior emergence |
| `entity_experience.py` | Experience-log and prediction-error helpers |
| `entity_zero_iteration.py` | Backward-compatible public re-export layer |
| `language_training.py` | Language training tick entry point |
| `language_anchor_match.py` | Anchor expression matching implementation |
| `inner_diary.py` | Internal diary helpers |
| `session_recovery.py` | Session recovery helpers |
| `sibling_channel.py` | Sibling-channel integration |
| `endogenous_calibration.py` | Internal calibration helpers |
| `feedback_loop.py` | Feedback loop helpers |
| `causal_learner.py` | Causal association learning helper |

## Main Runtime Directories

| Directory | Purpose |
| --- | --- |
| `daemon/` | Background process, tick engine, IPC/HTTP, autonomous hooks |
| `pipeline_runner/` | Main pipeline and stage modules |
| `core/` | Behavior emergence, drive fields, state-to-context |
| `drive_system/` | Drive vector computation |
| `decision_system/` | Decision/perception submodules |
| `thinking_system/` | Thought packet and semantic thinking |
| `language_system/` | Language expression, anchors, grammar, source modeling |
| `state_update/` | State transition and connection/coherence updates |
| `memory_hub/` | Episodes, insights, TetraMem integration |
| `world_model_update/` | Rule induction, verification, contradiction handling |
| `action_system/` | Tool/action execution and failure feedback |
| `observability/` | Instrumentation and reporting |
| `evaluation/` | Life-protocol and validation harnesses |

## Compatibility Rule

Several public imports are intentionally preserved after refactors. Before
renaming or removing root files, check:

- `src/entity_zero_iteration.py`
- `src/pipeline_runner/__init__.py`
- `src/language_system/__init__.py`
- `src/memory_hub/__init__.py`

These modules act as public surfaces for older scripts and tests.
