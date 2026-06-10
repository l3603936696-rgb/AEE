# PLAN — 表达反馈闭环（Expression Feedback Loop）

> 这是一份**抗压缩**实现计划。即使对话上下文被压缩，照此文件可以一个模块一个模块继续做下去。
> 进度勾选见每个模块末尾的 `状态:` 行。

## 0. 目标与背景

XIA 现有的消力闭环只看**内部**张力衰减：她说一句话，张力自己衰减了，就以为"这句话有用"——哪怕没人理她。这是自欺。

完整闭环要把 efficiency 的来源从"内部张力衰减"变成"**外界回应对需求的实际满足**"：

```
驱动力 → 表达（带意图）→ 外界回应 → 需求是否真被满足 → 强化/弱化
         ↑________________反馈信号_______________↓
```

她说的话**得到有效回应** → 对应词/句式的 efficiency 真实升高 → 升温、被偏好 → 她逐渐学会"哪种说法能换来回应"。
她说的话**石沉大海** → efficiency 真实为低 → 不被强化 → 自然淘汰。

这是"语言作为工具"的学习：不是说出来就好，而是**说了能换来世界的回应才算好**。

## 1. 合法性根基：和"输入是材料"如何自洽

- **违章版本**（stimulus→response）：用户说话 → 直接加减她的状态 → 她"被"输入推动。因果起点在外面。**禁止。**
- **合法版本**（action→outcome）：她**因为内部驱动力**说了一句话（action）→ 用户回应是这个 action 在世界上的**结果**→ 结果反过来调节"驱动这个 action 的那股力"。因果起点在她内部。**采用。**

**结构性护栏（代码必须满足）**：
1. 回应**只能修改"上一拍她主动表达时挂账的那股驱动力"**。没有挂账 → 没有任何状态修改。这从结构上堵死 stimulus→response。
2. 修改幅度正比于"输入与她那句话的相关度"。她没说话 / 输入与她无关 → 满足量趋近 0。

## 2. 哪些驱动力能进语言闭环

判据：这股力的缺口，能不能被"一段文字回应"填上？

| 驱动力 | 入闭环 | 满足信号 |
|---|---|---|
| loneliness | ✅ v1 | 有相关回应即满足（被回应=有人在） |
| info_gap | ✅ v1 | 回应带来新信息（相关 + 信息量） |
| unresolved | ✅ v1 | 回应推进了悬而未决的东西 |
| curiosity | ⏳ v2 | 类 info_gap，更要求意外性 |
| fatigue / energy | ❌ 永不 | 需要休息不是话，强接会造假满足 |
| stress / 情绪类 | ❌ 暂不 | 间接、慢、噪声大 |

v1 只接 **loneliness / info_gap / unresolved**。

## 3. 常量来源依据（反硬编码）

从 `src/state_update/update_engine.py` 实测的单次事件级自然变化量级：
- `update_engine.py:387`：真实用户输入 → loneliness **-0.1**
- `update_engine.py:390`：无输入 → loneliness +0.01/分钟（缓慢累积）
- `update_engine.py:395`：rest 消化 → unresolved **-0.10/分钟**
- `update_engine.py:463`：info_gap 自然累积 +0.002/分钟

**结论**：单次事件级变化 ≈ 0.1。所以反馈推动的满足量应是它的一个零头（"轻推不覆盖"）：

- `K_SATISFY`（满足→驱动力下降的总系数）：每个驱动力一个，量级 ~0.05（半个自然事件），按驱动力字典分发。
  - loneliness: 0.05（回应=陪伴，效果明显但不超过真实输入的 0.1）
  - info_gap: 0.03（信息满足较慢）
  - unresolved: 0.03
- `TAU_INTENT`（意图新近度衰减时间常数，单位 tick）：8.0。她不会无限期等一句话的回音；约 8 tick（≈4 分钟 @30s）后意图权重衰减到 1/e。
- `INTENT_QUEUE_MAXLEN`：6。内存队列上限，deque 自动驱逐最旧（不用比较门控）。
- `BGE_FALLBACK_OVERLAP`：BGE 不可用时用汉字重叠相关度，和 reading_acquisition 一致。

> 这些值若要再调，改这里的常量定义即可；不得在逻辑里散落裸数字。

## 4. 数据结构

`entity._pending_intents`：**内存队列**（`collections.deque(maxlen=INTENT_QUEUE_MAXLEN)`），**不持久化**（重启清空，可接受）。每个元素：

```python
{
    "drive": str,        # 挂账的驱动力名（loneliness/info_gap/unresolved 之一）
    "strength": float,   # 表达时该驱动力的强度（drive_vector 值）
    "expression": str,   # 她说出的文本
    "tick": int,         # 表达发生的 tick
}
```

## 5. 三个模块

### 模块 A — 表达意图挂账（tag_intent）

**位置**：新模块 `src/language_system/expression_feedback.py` 的 `tag_intent(entity, drive_vector, expression, tick)`。
**挂钩**：`src/daemon/tick_engine.py`，拿到 `result` 后（`result["drive_vector"]` + `result["response"]["text"]` 都在）。

逻辑：
1. 从 drive_vector 取三个可入闭环维度的值，用 `max(items, key=value)` 选 argmax（dict 分发，非 if）。
2. 强度趋零时不挂账（用 deque + 弱权重自然消解，不用阈值门控；强度本身作为 strength 进队，后续满足量正比于它，强度≈0 自然无效）。
3. push `{drive, strength, expression, tick}` 到 `entity._pending_intents`。

**状态: [x] 已完成**

### 模块 B+C — 回应检测 + 满足回写（consume_response）

**位置**：同模块 `consume_response(entity, input_text, tick) -> dict`。
**挂钩**：`src/daemon/daemon.py` 的 `_handle_chat`，收到输入文本后、调 pipeline 之前（或之后均可，需在 pipeline 改状态前抓取意图）。

逻辑：
1. 遍历 `_pending_intents`，对每条意图算：
   - `relevance = bge_sim(input_text, intent.expression)`（BGE，回退汉字重叠）— 连续值
   - `recency = exp(-(tick - intent.tick) / TAU_INTENT)` — 连续值
   - `satisfaction = intent.strength * relevance * recency`
2. **驱动力满足**（合法 action→outcome）：只对 `intent.drive` 这一维：
   `setattr(entity, drive, clamp(getattr(entity, drive) - satisfaction * K_SATISFY[drive]))`
   其它维度一律不动。
3. **消力回写**（强化语言学习）：对 `intent.expression` 调 `entity._quenching.record(...)`，
   `delta_unresolved_before = satisfaction`，`delta_unresolved_after = 0.0` →
   efficiency = satisfaction（真实满足量，而非 reading 里写死的 0.0）。
   这是闭环最终改变她语言能力的出口。
4. 消费后清空队列（已结算的意图不重复结算）。

**状态: [x] 已完成**

## 6. 约束清单（每次改动自检）

- [x] 无 `if/elif/else` 逻辑分支、无比较运算符门控行为；用 dict 分发 / max / exp / clamp
- [x] 不新增持久化字段；`_pending_intents` 仅内存；回写只经已持久化的 `_quenching_data`
- [x] 不改 `entity_core.json` 格式
- [x] 每个文件 < 400 行；新逻辑进新模块，不堆进 pipeline_runner / entity_state
- [x] 常量全部具名 + 来源注释（见 §3）
- [x] 外科手术式改动，不顺手重构相邻代码

## 7. 边界与已决策

1. **drive 回写系数 k**：见 §3，量级 0.05，半个自然事件，轻推不覆盖。
2. **不违反"输入是材料"**：§1 的两条结构护栏（无挂账不改 / 改幅正比相关度）保证。
3. **chat 的 LLM 路径**：闭环只长在**内生语言**上。模块 A 只挂 daemon tick 的自主表达（anchor/template 输出）。chat 的 LLM 输出不挂账意图；但 chat 输入会作为"回应"触发模块 B+C（结算她之前 daemon tick 的表达）。
4. **持久化**：`_pending_intents` 内存队列，重启清空。

## 8. 实施顺序

1. [x] 写本计划文件
2. [x] 新建 `expression_feedback.py`（模块 A + B+C）
3. [x] 挂钩模块 A 到 tick_engine
4. [x] 挂钩模块 B+C 到 daemon `_handle_chat`
5. [x] 写测试 `tests/test_expression_feedback.py` 验证：表达→挂账→相关输入→驱动力下降 + quenching 多一条真实 efficiency；无关输入不触发

## 9. v2 待办（本次不做）

- curiosity 入闭环（需 novelty 度量）
- info_gap 的 novelty 信号细化（当前 v1 用 relevance 近似）
- unresolved 的"语义闭合度"细化（当前 v1 用 relevance 近似）
