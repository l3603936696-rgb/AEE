# Validation

## 编译检查

```bash
python -m py_compile src/quenching/quenching_event.py
python -m py_compile src/quenching/quenching_channels.py
python -m py_compile src/quenching_system.py
python -m py_compile src/thinking_system/semantic_tables.py
python -m py_compile src/thinking_system/semantic_base.py
python -m py_compile src/memory_hub/tetramem_persistence.py
python -m py_compile src/memory_hub/tetramem_adapter.py
```

## Import Smoke Test

```bash
python -c "from src.quenching_system import apply_all_quenching, QuenchingEvent, QuenchingJournal; from src.quenching_system import expression_quenching, temporal_quenching, decision_quenching, social_quenching, behavioral_quenching, structural_quenching; print('quenching OK')"
python -c "from src.thinking_system.semantic_base import get_dim_meaning, get_action_essence, check_rule_against_seeds; from src.thinking_system.semantic_base import DIMENSION_SEMANTICS, CAUSAL_SEEDS; print('semantic_base OK')"
python -c "from src.memory_hub.tetramem_adapter import retrieve_memories, get_topology_metrics; from src.memory_hub.tetramem_persistence import _load_staged; print('tetramem OK')"
```

## 测试

```bash
python -m pytest tests/test_source_identity.py tests/test_expression_relief.py -q
```

## Diff Check

```bash
git diff --check -- src/quenching_system.py src/thinking_system/semantic_base.py src/memory_hub/tetramem_adapter.py
```
