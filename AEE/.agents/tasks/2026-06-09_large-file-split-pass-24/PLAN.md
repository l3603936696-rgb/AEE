# Plan: update_engine.py Split

## 文件分析

`update_engine.py`（716行）包含：
1. 模块 doc + imports（~44行）
2. 辅助函数（~25行）：`_safe_float`, `_clamp`, `_param`
3. 行为判断（~15行）
4. pending_surprises 管理（~65行）
5. relief_debt（~35行）
6. 主入口 `update_state`（342行）
7. 内联测试（168行）

## 拆分方案

### 新建 `update_engine_helpers.py`（316行）
- 所有辅助函数
- pending_surprises 管理逻辑
- relief_debt 逻辑
- Step 4 中的 6 个独立步进函数

### 新建 `update_engine_test.py`（184行）
- 提取所有内联测试

### 重写 `update_engine.py`（271行）
- 仅保留主入口 `update_state`
- 调用 helpers 中的所有工具函数

## 行数目标

- update_engine.py: 716 → 271
- update_engine_helpers.py: 新建 316
- update_engine_test.py: 新建 184
