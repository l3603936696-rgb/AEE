# CURSOR_RESULT.md — Pass 31: Large File Split

## Summary

拆分 `core/behavior_patterns.py` (742L) 为 3 个模块，全部低于 400 行。

## Files Changed

### Modified Files

| File | Before | After | Change |
| --- | --- | --- | --- |
| `src/core/behavior_patterns.py` | 742 | 192 | -550 lines |

### New Files

| File | Lines | Extracted From | Content |
| --- | --- | --- | --- |
| `src/core/behavior_patterns_schema.py` | 221 | behavior_patterns | BehaviorPattern dataclass + PRIMITIVE_ACTIONS + ACTION_TO_TYPE + INTENT_RULES + INTENT_TO_DRIVE + _band + _make_context_signature + _make_wm_key + _classify_intent + update_long_term_bias |
| `src/core/behavior_patterns_pool.py` | 365 | behavior_patterns | PatternPool class + _WorldModelDB class + _wm_db singleton + wm_predict alias |

## Design Notes

- `behavior_patterns.py` now acts as a thin entry module: imports from schema + pool, re-exports all public names, provides 6 scoring/top-level convenience functions.
- All callers (`s05b_pattern_feedback.py`, `life_protocol.py`) import via `from src.core import behavior_patterns` — unchanged.
- `behavior_patterns_schema.py` is the "data layer" (dataclass + constants + pure functions).
- `behavior_patterns_pool.py` is the "state layer" (PatternPool singleton + _WorldModelDB singleton with threading locks).
- `_wm_db` and `wm_predict` are shared between pool and main module (same import path resolves correctly).

## Validation

### Compile Check
```
python -m py_compile src/core/behavior_patterns_schema.py  # OK
python -m py_compile src/core/behavior_patterns_pool.py    # OK
python -m py_compile src/core/behavior_patterns.py         # OK
```

### Pytest
```
python -m pytest tests/test_source_identity.py tests/test_expression_relief.py -q
8 passed in 0.18s
```

### Git Diff Check
```
git diff --check -- src/core/behavior_patterns.py  # OK (CRLF warning only)
```

## Documentation Updated

- `XIA_SYSTEMS.md`: Added entries for `behavior_patterns_schema.py`, `behavior_patterns_pool.py`, and updated `behavior_patterns.py` description in core submodule table.

## Known Risks

- `PatternPool` and `_WorldModelDB` now live in `behavior_patterns_pool.py` but are accessed via `from src.core import behavior_patterns` from caller code. The `from .behavior_patterns_pool import PatternPool, _wm_db, wm_predict` in `behavior_patterns.py` ensures the shared instance is correctly aliased.
- No live daemon test performed (daemon not started per rules).

## Not Done This Pass

- `evaluation/life_protocol.py` (711L) — next priority
- `output_layer/output_layer.py` (667L) — high risk
- `observability/registry.py` (634L) — medium risk
- `entity_state.py` (1512L) — legacy core container, deferred
