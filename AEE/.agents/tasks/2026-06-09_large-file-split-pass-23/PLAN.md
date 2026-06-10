# Plan: somatic_concept_map.py Split

## 文件结构分析

`somatic_concept_map.py`（599行）包含以下函数簇：

1. **BGE 传播层**（约 160 行）：
   - `_ensure_anchor_embeddings()`（懒加载嵌入）
   - `get_somatic_delta()`（核心传播算法）
   这些依赖 `bge_analyzer`，适合拆分到 helpers

2. **匹配评分层**（约 180 行）：
   - `get_state_match_score()`（诊断精度）
   - `get_counter_delta()`（反向帮助向量）
   - `get_match_and_help()`（一站式 API）
   - `apply_help_delta()`（主执行函数）
   这些是核心 API，保留在主模块

3. **探索与聚类辅助**（约 200 行）：
   - `training_exploration_nudge()`
   - `get_top_matches()`
   - `get_cluster_peers()`
   - `find_closest_anchor()`
   - `list_anchors()`
   这些是辅助工具，适合拆分到 helpers

4. **常量与兼容别名**：
   - `get_somatic_expected_score = get_state_match_score`（兼容别名）
   - NEUTRAL 常量（内联在函数中）

## 拆分策略

**新建 `somatic_concept_map_helpers.py`**：
- BGE 嵌入懒加载（`_ensure_anchor_embeddings`）
- `get_somatic_delta()`（传播算法）
- `get_top_matches()`
- `get_cluster_peers()`
- `find_closest_anchor()`
- `list_anchors()`
- `training_exploration_nudge()` 中的 NEUTRAL 常量提取

**主模块保留**：
- `get_state_match_score()`
- `get_counter_delta()`
- `get_match_and_help()`
- `apply_help_delta()`
- 兼容别名
- 简洁的 `__all__`
- `import` 语句

## 预计行数

- 主模块：`imports(10) + 兼容别名(1) + 保留函数(5) ≈ 50-70 行`
- helpers 模块：剩余部分 `< 350 行`
