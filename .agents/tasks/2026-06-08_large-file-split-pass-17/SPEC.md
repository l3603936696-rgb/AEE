# SPEC — Pass 17

## 目标

拆分 `src/language_system/interpretation_competition.py`（614行），保持原功能不变。

## 拆分方案

按函数簇垂直拆分：

1. **`interpretation_schema.py`**（~160行）— dataclass 定义
   - `ExperienceCandidate`
   - `CompetitionResult`
   - `_COMPETITION_EPS` / `_BASE_EXPERIENCE_CONFIDENCE`

2. **`interpretation_compute.py`**（~200行）— 竞争力计算
   - `compute_competitive_score()`
   - `_softmax_weights()`
   - `build_candidates_from_stereotype()`

3. **`interpretation_competition.py`**（~280行）— 主入口 + 张力注入
   - `TENSION_THRESHOLD` / `MAX_CANDIDATES` / `CONFIDENCE_DECAY_RATE` 常量
   - `run_interpretation_competition()`
   - `run_interpretation_stage()`
   - `compute_prelinguistic_tension()`
   - `apply_prelinguistic_tension()`
   - `apply_tension_to_candidates()`
   - re-export dataclass

4. **`interpretation_test.py`**（~123行）— 原 `if __name__` 测试块独立

## 约束

- 不改变任何 public API 名称和签名
- 原文件改为瘦入口，re-export 所有公开函数和类
- 新模块均低于 400 行
