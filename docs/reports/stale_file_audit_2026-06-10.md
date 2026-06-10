# Stale File Audit - 2026-06-10

Scope: remove the inactive frontend and check files that look old or unwired.

## Removed Or Archived

- `frontend/` was removed. The Electron/Vite UI is no longer an active surface.
- Old Cursor frontend task notes were moved to `docs/archive/frontend_experiment/`.
- `scripts/verify_training_tick.py` was moved to
  `docs/archive/frontend_experiment/verify_training_tick_frontend.py` because it
  still modeled the removed xia-bridge/frontend path.

## Confirmed Still Wired

These looked suspicious in a simple import scan, but are still used by the
runtime or package exports:

- `src/causal_learner.py`
- `src/weathering/param_sync.py`
- `src/language_system/output_state_bias.py`
- `src/observability/llm_wrapper.py`
- `src/memory_hub/episodes_search.py`
- `src/pipeline_runner/utils.py`
- `src/action_system/types.py`
- `src/decision_system/submodules/base.py`

## Needs Human Decision Before Removal

These are standalone tools, experiments, or legacy validation entrypoints. They
are not part of the main daemon pipeline, but may still be useful during manual
debugging:

- `scripts/analyze_behavior.py`
- `scripts/auto_interact.py`
- `scripts/fix_manifest.py`
- root-level ad hoc tests: `test_first.py`, `test_stage3.py`,
  `test_hermes.py`, `test_loneliness_chain.py`, `test_loneliness_training.py`,
  `test_training.py`, `test_training_episode.py`
- root-level training helpers: `train_curriculum.py`, `train_new_anchors.py`
- root-level verification helpers: `verify_emotion_quenching.py`,
  `verify_fixes.py`
- old shell helpers: `check_last_lines.ps1`, `check_run_daemon.ps1`,
  `read_docx.ps1`, `daemon_watchdog.sh`

Recommendation: keep these out of core refactors for now. If they are not used
in the next cleanup pass, move them into a `docs/archive/legacy_tools/` folder or
delete them after confirming no manual workflow depends on them.
