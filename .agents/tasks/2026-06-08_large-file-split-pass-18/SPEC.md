# SPEC — Pass 18

## 目标

拆分 `src/language_system/construction_grammar.py`（711行），保持原功能不变。

## 拆分方案

按数据类型 / 计算逻辑分离：

1. **`construction_schema.py`**（~150行）— 超参数 + 数据结构
   - `_MAX_INSTANCES` 等所有常量
   - `ExpressionInstance` dataclass
   - `Construction` dataclass
   - `_drive_match_score()` 辅助函数

2. **`construction_grammar.py`**（~560行）— 主类 + 辅助函数
   - `ConstructionLearner` 类（完整保持）
   - `_infer_anchor_pos()` 辅助函数
   - 移入 import + logger

## 约束

- 不改变任何 public API 名称和签名
- 原文件改为瘦入口，re-export 所有公开类和函数
- 新模块均低于 400 行
- 不引入新的 LLM 调用点
