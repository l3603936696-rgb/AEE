# CURSOR_RESULT — pass-29: state_to_context 重构

## 摘要

将 `state_to_context.py` 重构为三模块结构，符合 400 行文件限制。

## 变更

### 新文件

- `src/core/state_to_context_data.py`（342 行）— 所有静态数据
  - `SYSTEM_PROMPT_FIXED`、`SYSTEM_PROMPT_CONSTRAINTS`（提示词常量）
  - `_interpolate_bands()` — 连续谱阈值查表
  - 9 个维度 bands（loneliness、fatigue、curiosity、somatic_tone、danger、stress、energy、unresolved、boredom）
  - `_CONFLICT_RULES`、`_check_conflict()` — 冲突区规则
  - `_DRIVE_LABEL`、`_dominant_drive_label()` — 驱动力标签
  - `_DIM_CATEGORY`、`_DIM_VALUE_KEYS`、`_DIM_BANDS`、`_get_category_score()` — 分类覆盖
  - `_TEMPORAL_BANDS`、`_build_temporal_descriptions()` — 时序变化描述
  - `_check_comfort_zone()` — 舒适区锚定
  - `_TONE_INSTRUCTIONS`、`_LENGTH_INSTRUCTIONS`、`_ACTION_INITIATIVE_CAPS` — 渲染指令
  - `_table_lookup()`、`_apply_action_consistency()` — 辅助函数

- `src/core/state_to_context_helpers.py`（241 行）— 函数实现
  - `generate_context_description()` — 生成处境描述（主描述 + 时序描述）
  - `_inject_rendering_instructions()` — 注入渲染指令
  - `build_system_prompt()` — 组装完整 LLM system_prompt
  - `derive_rendering_params()` — 从状态派生渲染参数

- `src/core/state_to_context_test.py`（29 个测试）— 独立测试文件

### 重写文件

- `src/core/state_to_context.py`（29 行）— 纯重导出模块，从 `data` + `helpers` 导入，向后兼容

### 更新文件

- `src/core/README.md` — 子模块职责表更新

## 测试结果

```
29 passed in 0.16s
```

覆盖：
- `generate_context_description`: 空状态、孤独、疲劳、好奇、冲突、时序、舒适区、驱动力向量、体感衰减
- `build_system_prompt`: 基本提示词、紧急行为、体感信号、渲染参数、动作结果、碎片化音色
- `derive_rendering_params`: 基础、低能量、高接近、高紧张、seek/avoid action
- 公开 API 导出、data 模块导出
- 工具函数: `_table_lookup`、`_interpolate_bands`、`_check_conflict`、`_dominant_drive_label`、`_check_comfort_zone`

## 验证

- `py_compile` — 全部文件编译通过
- smoke test — 三个公开函数全部可导入调用

## 已知风险

- `build_system_prompt` 中仍存在 `if action == "rest": ... elif action == "seek" and dominant == "loneliness": ...` 等硬分支逻辑，用于注入行为描述。这是已有的设计模式，符合当前系统风格。
- `generate_context_description` 中的痛苦衰减逻辑：pain 高时 somatic_tone 的 score 乘以 `(1 - pain * 0.8)`，这导致 pain=1 时 score 变为负数，实际排序中会被压制。行为正确但语义略怪。
