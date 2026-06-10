# XIA Project Structure

This document is a compact map of the current repository layout. It is meant
for reviewers and future agents who need to understand where a change belongs
before touching code.

## Root Files

| Path | Purpose |
| --- | --- |
| `README.md` | Portfolio-facing project overview and run/validation guide |
| `XIA_SYSTEMS.md` | Maintainer-facing system index and cross-module contracts |
| `requirements.txt` | Python dependency list |
| `.env.example` | Template for local runtime configuration |
| `xia_admin.py` | Local administrative helper |
| `*.bat`, `start_xia.ps1` | Windows launch helpers |
| `test_stage3.py`, `verify_fixes.py`, `test_*.py` | Historical/manual validation scripts |

Runtime logs, cache files, and local state are intentionally ignored by Git.
Do not treat `data/`, `logs/`, `daemon*.log`, or `__pycache__/` as source.

## Source Layout

| Path | Purpose |
| --- | --- |
| `src/daemon/` | Long-running process, tick loop, IPC/HTTP handlers, autonomous runtime hooks |
| `src/pipeline_runner/` | Ordered cognitive pipeline and stage context |
| `src/entity_state.py` | EntityState dataclass, runtime state methods, singleton API |
| `src/entity_io.py` | Entity state paths and safe JSON IO |
| `src/entity_lifecycle.py` | Startup recovery, offline drift, silence injection, stereotype setup |
| `src/entity_persistence.py` | Persistence/load schema implementation |
| `src/entity_core_wrapper.py` | Compatibility wrapper for behavior emergence |
| `src/entity_experience.py` | Experience-log and prediction-error helpers |
| `src/core/` | Behavior emergence, drive-field interaction, state-to-context helpers |
| `src/drive_system/` | Drive vector computation |
| `src/state_update/` | State write-back, connection/coherence, dopamine/oxytocin signals |
| `src/emotion_system/` | Emotion particles, projection, decay, insight writing |
| `src/decision_system/` | Multi-module perception and decision assembly |
| `src/thinking_system/` | Thinking packet, semantic tables, question emergence |
| `src/language_system/` | Anchor language, composition, source/speaker modeling, feedback loops |
| `src/action_system/` | Tool execution, reach behavior, failure feedback, capability gaps |
| `src/memory_hub/` | Episodes, insights, TetraMem fallback/persistence |
| `src/world_model_update/` | Rule induction, contradiction resolution, decay, verification |
| `src/world_model_reader/` | World-model query interface |
| `src/observability/` | Instrumentation registry, reports, LLM wrapper hooks |
| `src/evaluation/` | Life-protocol evaluation and non-invasive simulation |
| `src/weathering/` | Long-term parameter drift and shattering/baseline logic |
| `src/jepa/` | I-JEPA/V-JEPA style prediction helpers |
| `src/tool_introspection/` | Capability-gap and tool registry inspection |
| `src/tool_synthesizer/` | Tool template/LLM synthesis helpers |
| `channel/` | Local IPC chat client for the daemon |
| `reach_client.py` | Local listener for active reach-out messages |

## Important Compatibility Paths

| Compatibility path | Notes |
| --- | --- |
| `src/entity_zero_iteration.py` | Re-exports core public objects from the split implementation |
| `src/language_training.py` | Training tick entry point; anchor matching lives in `language_anchor_match.py` |
| `src/quenching_system.py` | Compatibility wrapper over `src/quenching/` |
| `src/pipeline_runner/__init__.py` | Main `run_pipeline()` entry and stage orchestration |

## Documentation Responsibilities

| Document | When to update |
| --- | --- |
| `README.md` | Project-level positioning, run commands, review guide |
| `XIA_SYSTEMS.md` | Cross-system interfaces, stage order, module splits |
| `docs/PROJECT_STRUCTURE.md` | Directory/file responsibility changes |
| `src/{system}/README.md` | Subsystem internals and local module tables |
| `.agents/tasks/` | Implementation plans, validation notes, review handoff |
