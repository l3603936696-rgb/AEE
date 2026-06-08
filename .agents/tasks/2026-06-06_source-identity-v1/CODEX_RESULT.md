# CODEX_RESULT.md - source-identity-v1

## Implemented

- Added `src/language_system/source_identity.py`.
- Updated `source_profiler.py` to expose `get_source_identity()` and support
  identity metadata in profiles.
- Updated `run_pipeline()` and `PipelineContext` to carry `source_identity`.
- Updated `daemon.py` IPC chat path to default to `bcyq/direct_chat`.
- Updated `tick_engine.py` reach-client external path to default to
  `bcyq/direct_chat`.
- Updated `s02_perception.py` so stereotype matching and construction parsing
  use `speaker_id`, not generic `external`.
- Added `tests/test_source_identity.py`.

## Compatibility

Existing profile dicts are upgraded in place with:

```text
speaker_id
content_origin_counts
```

Old calls to `get_source_id(input_source, entity)` still work.

## Files

- `src/language_system/source_identity.py`
- `src/language_system/source_profiler.py`
- `src/pipeline_runner/context.py`
- `src/pipeline_runner/__init__.py`
- `src/pipeline_runner/stages/s02_perception.py`
- `src/daemon/daemon.py`
- `src/daemon/tick_engine.py`
- `tests/test_source_identity.py`
- `scripts/diagnostics/source_relief_validation.py`

## Residual Risk

This is still identity plumbing only. It does not yet decide how much deeper XIA
should think based on source trust. That belongs to `processing_depth-v1`.
