# World Model Update — 世界模型归纳更新

> **维护人**：每次修改世界模型逻辑后更新此文档
> **最后更新**：2026-05-26

## 职责

从实体的亲身经历快照和逐字段预测误差中**归纳因果规律**，并持续验证/衰减/合并世界模型规则。

## 核心原则

- 所有核心函数（induct / merge / decay / verify）是**纯函数**，不写文件
- 所有 IO 由外层调度器（entity_zero_iteration）负责
- **禁止硬编码**：反事实模板、动作标签、trigger/expect/content 均自动生成
- 纯数据驱动：预测误差 → 规则创建/更新

## 执行顺序

```
加载 (from JSON/DB)
    ↓
归纳 ← induct_rules(snaps, param_snapshot)
    ↓
合并 ← merge_rules(old + new, embedding_provider)
    ↓
衰减 ← decay_rules(merged, state_snapshot, snapshots)
    ↓
验证 ← verify_pending(active + pending, snap)
    ↓
种群上限检查（按 confidence 淘汰）
    ↓
持久化 (to JSON/DB)
```

## 子模块职责

| 文件 | 职责 |
|------|------|
| `core.py` | 编排层，`run_update_cycle()` 主入口 |
| `induct.py` | 归纳：预测误差驱动规则创建/EMA更新（v11.2） |
| `verify.py` | 验证：pending规则用最新快照激活，贝叶斯学习率 |
| `decay.py` | 衰减：内分泌调节 + 稳定性保护 + 奥卡姆剃刀 |
| `merge.py` | 合并：O(N) 增量嵌入相似度，合并高相似度规则 |
| `contradiction.py` | 矛盾检测 |
| `rules.py` | 规律和快照数据结构（Rule / Snap / Predicts） |
| `defaults.py` | 默认参数 |
| `dimension_cost.py` | 维度维护成本（奥卡姆剃刀动力学） |
| `model_inertia.py` | 模型惯性（高惯性保护稳定规律） |
| `resolve.py` | 矛盾解决策略 |

## v11.2 归纳算法

```
对每个快照的 prediction_error_map：
    if |error| > threshold:
        if 已有匹配规则:
            EMA 更新 expected_deltas，调整 confidence
        else:
            创建新规则（confidence=0.3 起步）

冷启动：无规则时预测=0，任何 |actual| > threshold 触发规则创建
```

## 关键函数签名

```python
run_update_cycle(
    old_rules,          # 当前存储的规律列表
    snaps,              # 最近 N 轮迭代快照
    dialogue_log,       # 对话日志（当前占位）
    state_snapshot,     # 最新状态快照（必须重新拉取）
    param_snapshot,     # 参数快照
    embedding_provider, # 嵌入相似度计算器（可选）
) → (List[Rule], CycleStats)
```

## CycleStats 统计字段

| 字段 | 说明 |
|------|------|
| `inducted` | 本轮新归纳的规则数 |
| `merged` | 合并消失的规则数 |
| `decayed` | 发生衰减的规则数 |
| `verified` | 验证的规则数 |
| `protected` | 被稳定性保护未衰减的规则数 |
| `promoted` | pending → active 的规则数 |
| `demoted` | active → pending 的规则数 |
| `pruned` | 因种群上限淘汰的规则数 |

## 关键参数

| 参数 | 说明 |
|------|------|
| `world_model_max_rules` | 规律种群上限（默认 200） |
| 归纳阈值 | 从 `defaults.py` 读取，控制规则创建灵敏度 |
| 衰减半衰期 | 从快照计算内分泌调节曲线 |
| 奥卡姆剃刀阈值 | 从 `dimension_cost.py` 计算维度维护成本 |

## 管线位置

在后台 tick 或反思周期中由外层调度器调用，不属于 `run_pipeline` 主流程。

## 注意事项

- `state_snapshot` 必须传入**最新**快照，不能用缓存旧值
- 嵌入相似度计算器可选，不提供时 merge 用纯文本相似度兜底
- 合并是高开销操作（O(N²)），但有增量优化，实际 O(N)
