# Cursor Handoff: Large File Split Pass 23

你已完成以下准备工作：
1. 读取了 AGENTS.md、CLAUDE.md、.agents/workflow/README.md
2. 读取了 .agents/tasks/2026-06-09_large-file-split-pass-23/SPEC.md
3. 读取了 .agents/tasks/2026-06-09_large-file-split-pass-23/PLAN.md

## 任务

拆分 `src/language_system/somatic_concept_map.py`（599行）：

1. 创建 `src/language_system/somatic_concept_map_helpers.py`：
   - 从主模块移入：
     - `_ensure_anchor_embeddings()`
     - `get_somatic_delta()`
     - `get_top_matches()`
     - `get_cluster_peers()`
     - `find_closest_anchor()`
     - `list_anchors()`
     - `training_exploration_nudge()`（含 NEUTRAL 常量提取）
   - 主模块 import helpers 模块的公开函数

2. 重写 `src/language_system/somatic_concept_map.py`：
   - 保留核心 API：`get_state_match_score`, `get_counter_delta`, `get_match_and_help`, `apply_help_delta`
   - 保留兼容别名
   - 从 helpers 模块 import BGE 相关函数
   - 目标 < 400 行

3. 更新 `XIA_SYSTEMS.md`：
   - language_system 子模块表新增 `somatic_concept_map_helpers.py`

## 验证命令

```powershell
python -m py_compile src/language_system/somatic_concept_map.py src/language_system/somatic_concept_map_helpers.py
python -c "from src.language_system.somatic_concept_map import get_state_match_score, get_counter_delta, get_match_and_help, apply_help_delta, list_anchors; print('OK')"
python -m pytest tests\test_source_identity.py tests\test_expression_relief.py -q
git diff --check -- src/language_system/somatic_concept_map.py src/language_system/somatic_concept_map_helpers.py
```

## 边界

- 不要改动 `somatic_anchors.py`（已是数据模块）
- 不要改动 `bge_analyzer.py`
- 不要启动 daemon
- 不要重构无关逻辑
