# SPEC — Pass 20

## 目标

拆分两个 language_system 文件。

## 1. `src/language_system/stereotype_tree.py`（1158行）

拆分策略：提取常量和独立函数。

| 子模块 | 职责 |
|---|---|
| `stereotype_tree_schema.py`（~60行） | `FEATURE_DIMS` + `DEFAULT_FEATURE_WEIGHTS` 常量 |
| `stereotype_tree.py`（~1098行） | 保留 `StereotypeNode` + `StereotypeContext` + `StereotypeTree` + `StereotypeForks` + `StereotypeTreeStage3` + 其他类 |

## 2. `src/language_system/somatic_concept_map.py`（1143行）

拆分策略：提取大数据锚点表。

| 子模块 | 职责 |
|---|---|
| `somatic_anchors.py`（~560行） | `SOMATIC_ANCHORS` 字典 + 锚点嵌入初始化 |
| `somatic_concept_map.py`（~583行） | 保留所有计算函数 + `list_anchors` + `find_closest_anchor` 等 |

## 约束

- 不改变任何 public API 名称和签名
- 原文件 re-export 子模块内容
- 新模块均低于 400 行
