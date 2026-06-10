# Thinking System — 思考系统

> **维护人**：每次修改思考逻辑后更新此文档
> **最后更新**：2026-05-26

## 职责

从驱动力场中**数据驱动地涌现问题和行动建议**，不依赖硬编码模板。问题和建议从同一个焦点规则集合中并行生成。

## 核心原则

- 相关性从数据计算，不从查表获取
- 驱动力之间的"接近度"从当前活跃维度与规则维度的重叠度计算
- 行动类型从焦点规则的 `expected_deltas` 推断，不套模板
- 所有思考有代价（energy_cost）

## 数据流

```
驱动力场 (drive_vector)
    ↓
活跃维度集合 ← _active_dimensions(dv, state_snapshot)
    ↓
焦点规则 ← _select_focal_rules(rules, active_dims)
    ↓
┌───────────────────────────────────────────────┐
│  统一流：同一焦点规则并行生成                 │
│                                               │
│  _build_question(rule) → 结构化问题           │
│     类型: contradiction / novel / low_conf /  │
│           high_conf / causal / tool_capability │
│                                               │
│  _build_suggestions(focal_rules, dv, state)   │
│     → action + reason + priority              │
│     → _infer_action_type(rule) ← 三信号投票    │
│                                               │
│  感质调制 ← _somatic_modulation(somatic)      │
│  注意力调制 ← _attention_to_drive_boost(attn)│
│                                               │
│  心智模拟 ← mental_simulation.simulate_suggestions
│     预测每个行动的张力变化，修正优先级         │
│                                               │
│  工具能力缺口自省 ← _build_tool_capability_question
│     从 _pending_tool_gaps 生成 tool_capability 问题
│                                               │
│  枝干联想检索 ← branch_retrieval(concept_tags)
└───────────────────────────────────────────────┘
    ↓
ThoughtPacket {
    suggestions: [{action, reason, priority}],
    questions:   [{type, rule_id, dims, confidence, priority}],
    branch_memories: [dict],
}
```

## 子模块职责

| 文件 | 职责 |
|------|------|
| `thinking_system.py` | 主入口 `think()` + 统一流逻辑 |
| `semantic_base.py` | 维度语义表（polarity/connects）+ 因果种子 |
| `mental_simulation.py` | 心智模拟：预测行动效果（能量成本 0.005/次） |
| `covariance_tracker.py` | 滑动窗口协方差追踪：维度→预测误差相关性 |

## 关键函数签名

```python
think(
    wm_context,        # 世界模型上下文（含 matched_rules）
    drive_vector,      # 5维驱动力向量
    state_snapshot,    # 实体状态快照
    params,           # 阈值参数
    somatic_signals,   # 感质信号（tone, intensity）
    entity_state,      # 实体对象（用于心智模拟和枝干检索）
    concept_tags,      # 语义标签
    attention_weights, # 协方差追踪器的注意力权重
) → ThoughtPacket
```

## 关键参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `thinking_activation_threshold` | 0.5 | 驱动力触发阈值 |
| `max_thinking_steps` | 3 | 最多处理规则数 |
| `thinking_time_budget_ms` | 500.0 | 时间预算（超时截断） |
| `max_suggestions` | 2 | 最多输出建议数 |

## 重要设计

### 三信号投票推断行动类型

`_infer_action_type` 用三个信号源投票：

1. **规则 deltas**：预期上升→explore票，下降→rest票
2. **驱动力强度**：按映射投票（loneliness_drive→comfort等）
3. **状态高值维度**：按极性投票

赢家需要比第二名高出 20% 才输出，否则返回 None。

### 工具能力缺口自省（v11.6）

从 `entity._pending_tool_gaps` 提取高强度缺口（>0.3），生成 `tool_capability` 类型问题，格式：

```
"我想 [action]，但我好像缺少 [aspect] 的能力。我有办法做到吗？"
```

### 语义基座

`semantic_base.py` 是纯数据表，给维度名附上含义（polarity/connects），让规则解读和问题渲染有语义支撑，不只是裸数字。

## 管线位置

`s03_think` 阶段调用 `thinking_system.think()`。

## 注意事项

- 思考是**昂贵的**：每次模拟消耗 `energy_cost=0.005`
- 心智模拟有门控：`willingness = tension × energy × (1 - fatigue)`，低于 0.08 不运行
- 协方差追踪器滑动窗口默认 200 tick，最少 20 样本才输出相关性
