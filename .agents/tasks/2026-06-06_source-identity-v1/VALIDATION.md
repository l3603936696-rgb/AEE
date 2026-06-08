# VALIDATION.md - source-identity-v1

## Commands

```powershell
python -m pytest tests/test_source_identity.py -q
python -m pytest tests/test_source_identity.py tests/test_expression_relief.py tests/test_proposition_frame.py tests/test_clarification_memory.py tests/test_clarification_learning.py tests/test_clarification_attribution.py -q
python -m py_compile src/language_system/source_identity.py src/language_system/source_profiler.py src/pipeline_runner/context.py src/pipeline_runner/__init__.py src/pipeline_runner/stages/s02_perception.py src/daemon/daemon.py src/daemon/tick_engine.py
python scripts/diagnostics/source_relief_validation.py
git diff --check
```

## Results

```text
tests/test_source_identity.py
4 passed

source + expression + proposition + clarification subset
62 passed, 1 warning

py_compile
passed

diagnostic script
failed: []

git diff --check
passed, CRLF warnings only
```

The warning is from `jieba/pkg_resources` deprecation in existing tests.

## Diagnostic Output Summary

From `python scripts/diagnostics/source_relief_validation.py`:

| Case | speaker_id | content_origin | author_id | source_id |
| --- | --- | --- | --- | --- |
| direct Owner input | bcyq | direct_chat | bcyq | bcyq |
| pasted text | bcyq | pasted_text | unknown | pasted_text:unknown |
| sibling | sibling:nuonuo | sibling_channel | sibling:nuonuo | sibling:nuonuo |

Profile update also records:

```text
profile["speaker_id"] = "bcyq"
profile["content_origin_counts"]["direct_chat"] = 1
```

## Offline Pipeline Probe

Ran `run_pipeline(..., source_identity=build_source_identity("ipc_chat", ...))`
with debug trace. `stereotype_match` reported:

```text
speaker_id = bcyq
source_id = bcyq
```

This confirms source identity reaches perception/stereotype context.

## Live Status

No XIA daemon process was running during this validation. I did not restart or
touch live runtime state. This validation is offline and repeatable.
