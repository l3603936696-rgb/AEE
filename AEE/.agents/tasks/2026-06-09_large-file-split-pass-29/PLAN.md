# PLAN.md — Pass 29 执行计划

## 执行顺序

每次只处理一个文件，验证通过后再处理下一个。

### 步骤 1: `somatic_anchors.py` (560 → ~20 + 545)

**分析**：文件几乎全是静态数据（`SOMATIC_ANCHORS` dict 482行），逻辑极少。
- `somatic_anchors_data.py` 新建，copy 全部数据（`SOMATIC_ANCHORS`/`ANCHOR_CLUSTERS`/`ALL_DIMENSIONS`）
- `somatic_anchors.py` 改为 thin re-export stub
- 更新所有 import 调用点

**调用点**：2个文件
- `src/language_system/somatic_concept_map_helpers.py`
- `src/language_system/somatic_concept_map.py`

### 步骤 2: `state_pattern_memory.py` (453 → ~220)

**分析**：有清晰的 schema/dataclass + helper 函数 + 主类分离。
- `state_pattern_memory_schema.py`：`_DIMS`, `_DIM_HIGH_LABELS`, EMA 常量, `InternalPattern` dataclass, `_BOOTSTRAP_PATTERNS`
- `state_pattern_memory_helpers.py`：`_cosine_similarity`, `_ema_update`, `_forge_symbol`, `_bootstrap_spm`
- `state_pattern_memory.py`：保留 `StatePatternMemory` 类 + `run_symbol_tick()`，import schema 和 helpers

**调用点**：3个文件
- `src/language_system/__init__.py`
- `src/daemon/state_pattern_tick.py`
- `src/daemon/tick_engine.py`

### 步骤 3: `five_rights.py` (448 → ~280)

**分析**：类方法紧凑，强行拆类破坏性大。抽取独立模块函数和数据常量。
- `five_rights_schema.py`：中性词列表常量、默认值参数表
- `five_rights_helpers.py`：`_current_time()` 等工具函数
- `five_rights.py`：保留主类，import schema 和 helpers

**调用点**：2个文件
- `src/language_system/__init__.py`
- `src/pipeline_runner/stages/s01_init.py`

### 步骤 4: `quenching.py` (427 → ~330)

**分析**：`QuenchingRecord` dataclass 可抽离为 schema。
- `quenching_schema.py`：`QuenchingRecord` dataclass + 字段默认值常量
- `quenching.py`：删除 dataclass，改为 import，保留 `QuenchingTracker` 类

**调用点**：9个文件（见 agent 分析）

### 步骤 5: `word_warmup.py` (410 → ~130)

**分析**：有清晰的 warmup 主逻辑 + rest consolidation 逻辑 + helper 函数。
- `word_warmup_helpers.py`：解码表 + `_decode_state_hash` + `_build_word_profile` + 常量
- `word_warmup_rest.py`：rest consolidation 相关常量和函数
- `word_warmup.py`：保留主 API 函数，import helpers

**调用点**：9个文件

### 步骤 6: `stereotype_tree.py` (386 → ~320)

**分析**：`StereotypeNode` + `StereotypeContext` dataclass 可抽离。
- `stereotype_tree_nodes.py`：`StereotypeNode` + `StereotypeContext` dataclass
- `stereotype_tree.py`：删除 dataclass，import nodes

**调用点**：约12个文件

## 每步验证流程

1. 完成拆分，写入新文件
2. `python -m py_compile` 新文件 + 改动的原文件
3. smoke test: `python -c "import src.language_system.xxx; import src.language_system"`
4. `python -m pytest tests\test_source_identity.py tests\test_expression_relief.py -q`
5. `git diff --check`
6. 更新 `XIA_SYSTEMS.md` 和语言系统 `README.md`
7. 继续下一步

## 文档更新

每步完成后：
- 更新 `XIA_SYSTEMS.md` 中的 submodule 列表（添加新文件）
- 更新 `src/language_system/README.md`（如有）
