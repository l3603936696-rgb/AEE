# SPEC — Pass 19

## 目标

拆分 `src/language_system/stereotype_learner.py`（586行）。

## 拆分方案

提取常量 + 辅助函数到子模块，主文件变为瘦入口：

1. **`stereotype_markers.py`**（~42行）— 标记词常量
   - `FEATURE_WINDOW`
   - `PHILOSOPHICAL_MARKERS` / `METACOGNITIVE_MARKERS` / `ANALYTICAL_MARKERS` / `FIRST_PERSON_MARKERS` / `EMOTIONAL_MARKERS`

2. **`stereotype_learner.py`**（~540行）— 瘦入口
   - 保留 `FeatureExtractor` + `TagInferrer` + `StereotypeLearner` 三个类
   - 保留 `extract_tags_from_memory` + `init_tree_from_memory` + `learn_speaker` + `quick_learn`
   - 添加 re-export from `stereotype_markers`

> 注：`StereotypeLearner` 类（~165行）和 `FeatureExtractor`（~98行）紧密耦合，无法按类拆分。目标是提取纯数据常量到子模块。

## 约束

- 不改变任何 public API 名称和签名
- 原文件改为瘦入口，re-export 所有公开类和函数
- 新模块均低于 400 行
