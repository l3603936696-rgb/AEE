# Core — 核心机制

> **维护人**：每次修改 V6 行为涌现逻辑后更新此文档
> **最后更新**：2026-05-26

## 职责

V6 驱动力场行为涌现引擎：将连续内部状态映射为可执行的行为决策，输出渲染参数。

## 核心原则

- 行为从拮抗驱动力场的合力中**涌现**，无需人工预设类别
- 驱动力不做 argmax，所有维度完整保留
- 拮抗矩阵决定量的相互抑制
- 连续质变输出 fragmentation，让行为有质地而非硬切换
- rule effect 完全内生（从历史 snapshots 归纳）

## V6 行为涌现链路

```
EntityCore 原始状态
    ↓
drive_vector_field.compute_drive_field()
    ├→ raw_drives: 从 EntityCore 提取 7 维驱动力
    ├→ antagonism_matrix: 驱动力之间的拮抗权重
    ├→ net_drives: 拮抗后各维度的有效强度
    ├→ fragmentation alpha: 连续质变系数
    └→ behavior_vector: intensity + fragmentation
    ↓
behavior_vector.apply_rule_bias()
    从 wm_rules 归纳 rule effect
    作为连续偏置加到 behavior_vector
    ↓
intensity 最大维度 → action_type
    (via _DRIVE_TO_ACTION 映射)
    ↓
渲染参数
    derive_rendering_params() → pace/length/tone_stability/initiative
```

## 7 维驱动力

| 维度 | 来源 | 拮抗关系 |
|------|------|---------|
| `curiosity` | EntityCore.curiosity | 被 fatigue/danger 抑制 |
| `info_hunger` | EntityCore.info_hunger | 被 fatigue/danger 抑制 |
| `loneliness` | EntityCore.loneliness | 被 fatigue 抑制 |
| `fatigue` | EntityCore.fatigue | 抑制所有主动行为 |
| `unresolved` | EntityCore.unresolved | 被 fatigue/danger 抑制 |
| `somatic_tone_p` | (somatic_tone + 1) / 2 | [-1,1] → [0,1] |
| `danger` | EntityCore.danger_level | 抑制探索 |

## 行为类型映射

```
curiosity/influence  → explore
loneliness          → seek
fatigue             → rest
unresolved          → repair
danger               → avoid
somatic_tone_p      → comfort
```

## 行为质地

fragmentation 高时行为不稳定，tone 描述从正常→破碎的过渡：

| action | fragmentation=0 | fragmentation=1 |
|--------|-----------------|----------------|
| seek | 社交渴望强烈 | 社交欲望断断续续、犹豫不决 |
| explore | 好奇心强烈 | 好奇心飘忽不定、注意力分散 |
| rest | 疲惫感强烈 | 想休息但停不下来、身体很矛盾 |
| idle | 平静无事 | 内心有些拉扯但还算平静 |

## 子模块职责

| 文件 | 职责 |
|------|------|
| `emergent_behavior.py` | V6 主逻辑 + V5 fallback |
| `drive_vector_field.py` | 拮抗矩阵 + 连续质变（fragmentation）|
| `behavior_vector.py` | 内生 rule effect 偏置 |
| `entity_core.py` | 轻量状态容器（V6 系统用） |
| `somatic_signals.py` | 感质信号与 DoS 保护 |
| `state_to_context.py` | 入口重导出（向后兼容）|
| `state_to_context_data.py` | 静态数据（bands、冲突规则、常量）|
| `state_to_context_helpers.py` | 函数实现（generate/build/derive）|
| `action_dispatcher.py` | 行为分发器 |
| `behavior_patterns.py` | 行为模式数据库 |
| `emergent_behavior_v5.py` | V5 fallback（历史逻辑） |

## 关键函数签名

```python
emerge_behavior(
    entity_core,    # EntityCore 实例
    drive_vector,    # 可选，来自 v1 的驱动力向量
) → EmergentBehavior {
    action_type: str,
    target: str,
    priority: float,
    tension_level: float,
    dominant_state: str,
    state_snapshot: dict,
    suggested_tool: str,
    behavior_vector: dict,  # V6 附加
    fragmentation_tone: str,  # V6 附加
}

derive_rendering_params(
    emergent_behavior,  # EmergentBehavior
    entity_state,        # EntityState
) → {pace, length, tone_stability, initiative}
```

## V5 Fallback

若 V6 计算失败，自动降级到 V5（原有排序逻辑）。V5 逻辑在 `emergent_behavior_v5.py`。

## 管线位置

`s04b_emerge` 阶段调用 `core.emergent_behavior.emerge_behavior()`。
`s06_language` 阶段使用 `derive_rendering_params()` 生成输出参数。

## 注意事项

- 所有输出连续，无 argmax 硬切换
- tool weights 是连续计算，不是 if-else
- behavior_vector 的 alpha 系数（fragmentation）影响所有维度
- rule bias 完全从历史经验归纳，不预设 effect 值
