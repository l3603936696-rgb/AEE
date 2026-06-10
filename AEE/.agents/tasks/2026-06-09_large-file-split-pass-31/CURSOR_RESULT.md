# CURSOR_RESULT.md — Pass 31: Large File Split

## Summary

拆分 `evaluation/life_protocol.py` (889L → 4 个模块，全部低于 400 行。

## Files Changed

### Modified Files

| File | Before | After | Change |
| --- | --- | --- | --- |
| `src/evaluation/life_protocol.py` | 889 | 128 | -761 lines |

### New Files

| File | Lines | Extracted From | Content |
| --- | --- | --- | --- |
| `src/evaluation/life_protocol_schema.py` | 87 | life_protocol | TickMetrics dataclass + TH_* constants + helper functions |
| `src/evaluation/life_protocol_runner.py` | 121 | life_protocol | SimulationRunner class |
| `src/evaluation/life_protocol_tests.py` | 233 | life_protocol | Level1/2/3 test classes |

## Design Notes

- `life_protocol.py` now acts as a thin entry module: imports from schema + runner + tests, re-exports public names, provides `run_life_protocol()` + CLI.
- Tests import SimulationRunner from `life_protocol_runner` via relative import (lazy import to avoid circular dependency).
- All data file paths (`DATA_DIR`, `LOG_FILE`, `RESULT_FILE`) centralized in schema (schema) and runner (LOG_FILE) — no duplication.

## Validation

### Compile Check
```
python -m py_compile src/evaluation/life_protocol_schema.py   # OK
python -m py_compile src/evaluation/life_protocol_runner.py  # OK
python -m py_compile src/evaluation/life_protocol_tests.py   # OK
python -m py_compile src/evaluation/life_protocol.py          # OK
```

### Pytest
```
python -m pytest tests/test_source_identity.py tests/test_expression_relief.py -q
8 passed in 0.18s
```

### Line Counts
```
life_protocol.py: 128 lines  (was 889)
life_protocol_runner.py: 121 lines
life_protocol_schema.py: 87 lines
life_protocol_tests.py: 233 lines
```

## Documentation Updated

- `src/evaluation/README.md` created with submodule table and usage.

## Not Done This Pass

- `output_layer/output_layer.py` (667L) — high risk
- `observability/registry.py` (634L) — medium risk
- `entity_state.py` (1512L) — legacy core container, deferred
