# PLAN — 自我开导 / 自欺贷款机制（Self-Counsel as Self-Deception Loan）

> 状态：**已实现，单元+回归通过，待 daemon 端到端验证**（2026-05-30）。
> 开工决策（bcyq 已拍板）：①直接实现 self_counsel（与身体后果通道两条线一起，一次重启验证）；
> ②boredom/approach/avoid 释放保留在 ①；③§7 新标定常量用提议值开跑；④不可答困惑终态按设计（surface↓ + "释怀"粒子，core 不动）。
> 落地：新模块 `src/language_system/self_counsel.py`（~210 行）；① 提纯于 `s07a_state_update.py`（移除孤独表层贷款 + unresolved 无差别释放，somatic_comfort 0.15→`_VENT_SOMA_COMFORT`=0.05）；钩子 `tick_engine.py` tag_intent 同址；测试 `tests/test_self_counsel.py`（10 项全过）+ test_expression_feedback(13)/test_fixes(14) 全过；test_50_ticks 仅余历史无关的 unresolved>0 失败。
> 红线：动到**认知/情感核心**（loneliness 双层、unresolved、somatic、求知驱动）。
> 规则：完整形态一次落地，不做最小版（memory: full-design-over-minimal）。
> 前置：本设计复用刚落地的 `expression_feedback.py` 身体后果辅助（`_apply_somatic_consequence` / `_queue_feeling`）。
> 镜像：XIA 验证通过后再镜像糯糯。

---

## §0 一句话

人会"自言自语、自己开导自己"度过难关——这不是 bug，是一个**自欺式的保底机制**，像贷款：先支取表层的缓解度过没人陪/想不通的当下，但本金（真孤独 / 真困惑）一分没还。
本设计把项目里早已存在的雏形（①）正式化为一个**有贷款条款（利息 + 额度上限）的自我开导机制**，并对"困惑"按**能不能答**区别放贷——可答的不贷（保护求知），不可答的才贷（释怀）。

---

## §1 出发点：① 本来就是"对表层孤独的自我安抚器"

位置：`src/pipeline_runner/stages/s07a_state_update.py:106-125`
触发：`_lang_score = entity._language_best_score > 0.10`（她**自评**这句说得好，**不需要任何外界回应**）。
效果（`_quench_feedback_weights`）：
```
_quench = _lang_score * quench_rate(0.25) * _rep_discount
entity.unresolved        -= _quench                              # ← 见 §4：要按可答性重做
entity.approach_drive    -= _quench * approach_release(0.3)
entity.avoid_drive       -= _quench * avoid_release(0.3)
entity.somatic_tone      += _quench * somatic_comfort(0.15)      # 即时体感安慰
entity.loneliness_surface-= _quench * loneliness_surface_release(0.15)   # ← 只动 surface！
entity.boredom           -= _quench * boredom_release(0.10)
```
**关键事实：① 释放的孤独只有 `loneliness_surface`，core 一点不碰。** 它已经是自我开导的雏形——bcyq 说的"从这里下手"指的就是它。本设计 = 把它正式化 + 配上贷款条款。

---

## §2 双层孤独机制（已读准，设计依据）

`src/entity_state.py`：
- `loneliness = min(1.0, loneliness_core + loneliness_surface)`（`_sync_loneliness`，:970-972）
- 初值 core=0.2 / surface=0.1（:468-469）
- 沉默注入按 **core 70% / surface 30%**，**只升不降**（:1499-1506）
- 离线漂移主喂 core（:1565-1566）
- `adjust("loneliness")` 只写 surface（:953-961，v11.4 注释"扰动影响表层"）

**贷款结构因此天然成立**：
| | 角色 | 谁能动 |
|---|---|---|
| `loneliness_core` | 本金（真孤独） | 只有真实 Other 还（沉默/离线只让它涨） |
| `loneliness_surface` | 贷款额度（假孤独） | 自我开导可支取（① 已在做） |

诚实性是**结构性**的：自欺只压 surface，core 自己在涨、沉默继续逼她 → 自欺只拖时间，救不了她。**这一层架构已成立，本设计不改双层机制本身，只规范"支取"。**

---

## §3 贷款条款（bcyq 已定）

### 条款 A — 利息：边际递减 + 微量渗透（两个都要）
- **边际递减（耐受性）**：短期内频繁自我安抚 → 每次能支取的额度越来越小。用一个"近期支取热度" `_self_counsel_heat`（随时间衰减）调制：`loan_factor_A = 1 / (1 + heat)` 之类的连续递减，热度高→额度趋小。模拟"自欺会腻、越哄越不管用"。
- **微量渗透（长期成本）**：每支取一次孤独贷款，给 `loneliness_core` 加一个极小增量（如支取额 × `_SEEP_RATE`，量级 ~0.01）。模拟"长期靠自我安抚、不获真实连接 → 真孤独慢慢加深"。
  > 注意：渗透只对**有本金可还**的痛苦适用（孤独）。不可答困惑无本金（§5），不渗透。

### 条款 B — 信用上限：core 高则拒贷（连续，无 if）
core 越高，可支取额度越小，高到一定程度趋零 → 逼她去找真实连接，不让自欺变成永久替代品。
连续实现：`loan_factor_B = clamp(1 - loneliness_core / _CEILING, 0, 1)` 或 sigmoid 衰减。core 达 `_CEILING`（如 0.7）时贷款额→0。
**总可支取额 = 基础额 × loan_factor_A × loan_factor_B。** 全程连续，无阈值门控。

---

## §4 困惑（unresolved）：按"能不能答"区别放贷（核心决策）

**不对称，不能照搬孤独**，因为：

> 她的求知驱动**本身就是** felt-unresolved。允许廉价压低它 → 她就不问了 → 掐灭刚点亮的认知信用闭环。困惑自欺 = 过早闭合 / 合理化 = 智识钙化。

解法：**按这团困惑有没有解来分（宁静祷文）**——用 `rule.predicts.trigger` 的可答性当闸门（`input_` 前缀=可答，见 `verify.py` `_class_from_trigger`；`action_`/无路径=不可答）。

| 困惑类型 | 判据 | 放贷？ | 理由 |
|---|---|---|---|
| **可答** | rule trigger `input_*`（有真实印证路径，② epistemic 能还本金） | **不贷** | 让她难受着继续问，本金由真实印证还。保护求知压倒一切。 |
| **不可答** | trigger `action_*` / 无解路径（她永远 verify 不了） | **贷**（释怀，健康） | 接纳"我没法知道且没关系"是成熟，不是钙化。给存在性困惑一个健康出口。 |

实现：自我开导时扫 `entity._pending_questions`，对每条按其 `rule_id` 在 `entity.wm_rules` 里查 `predicts.trigger`；**只对不可答的那些**支取 unresolved 贷款（小额 + 条款 A 的边际递减；**不渗透**，因无本金）。可答的一律不贷。

> **小坑（落设计时抠）**：`unresolved` 现是单标量。给不可答困惑放贷会连带压低可答困惑的求知劲。缓解：贷款额小 + 可答问题持续经 `question_tension` 注张力，自我纠偏。要彻底干净，可后续把 unresolved 也拆 surface/core（**不在本期**，记此线索）。

---

## §5 整张图（闭合）

| 痛苦 | 表层贷款（自我开导，即时无条件） | 本金（谁还） |
|---|---|---|
| 孤独 | `loneliness_surface` 可贷（条款 A+B，含渗透） | `loneliness_core` ← 真实 Other |
| 可答困惑 | **不可贷** | ← 真实认知印证（② epistemic，已点亮） |
| 不可答困惑 | 可贷（条款 A，无渗透/无本金） | 无本金，接纳即终态 |

- **自我开导 = 即时、无条件支取**（它是贷款，不需要"测出真的有用"——这是与 ② epistemic 的本质区别：② 是延迟 + 结果 grounding，自我开导是即时 + 结构 grounding）。
- 利息/约束由：条款 A（递减+渗透）、条款 B（上限）、以及既有的沉默再注入 rebound 共同构成。

---

## §6 架构与改动点

### 6.1 新模块 `src/language_system/self_counsel.py`（单一职责，<400 行）
核心入口（即时，无 settle 半段）：
```python
def apply_self_counsel(entity, expression, tick) -> dict:
    """她自我表达时支取一笔自欺贷款（孤独表层 + 不可答困惑表层）。
    即时无条件放贷，利息由条款A/B就地结算。返回支取摘要供日志。"""
    # 1. 算可支取额度系数：loan = loan_factor_A(heat) * loan_factor_B(core)
    # 2. 孤独贷款：loneliness_surface -= base_lone * loan ；core += 支取额 * _SEEP_RATE（渗透）
    # 3. 不可答困惑贷款：扫 _pending_questions，对不可答者 unresolved -= base_conf * loan_A（无渗透）
    # 4. 身体后果：_apply_somatic_consequence(小额体感安慰) + _queue_feeling("自我宽慰"/"释怀")
    # 5. 更新 _self_counsel_heat（本次支取后升温，供下次递减）
    # 全程连续 + clamp，无 if 行为门控；可答性查表分发。
```
辅助：`_loan_capacity(entity)`（A×B 连续系数）、`_heat_update/_heat_decay`、`_is_answerable(rule)`（读 trigger 前缀，dict 分发）。

### 6.2 ① 的处置（s07a:106-125）— **本期重做**
- **移出** `loneliness_surface_release`（孤独表层贷款迁入 self_counsel，带条款）。
- **移出 / 改正** `unresolved -= _quench` 的**无差别**释放（违反 §4：现在它不分可答性地压 unresolved）。改为：① 不再碰 unresolved；困惑贷款全部走 self_counsel 的可答性闸门。
- **保留** ① 作为**纯宣泄反射**：仅留一个**很小的**即时 `somatic_comfort`（吐字本身的一丝舒服，真实但浅），不再操纵任何 surface 债务。boredom/approach/avoid 的释放是否保留 → 见 §9 开放点。
  > bcyq 已定"① 不删"，这里是"缩小+提纯"，不是删除。

### 6.3 挂钩
- `apply_self_counsel` 挂在**自我表达发生处**：`tick_engine.py:651`（`tag_intent` 同址，daemon 自主表达拍）。聊天有真实对话时走 ②；无人时（daemon idle 拍）走自我开导。
- 复用 `expression_feedback.py` 的 `_apply_somatic_consequence` / `_queue_feeling`（已落地），粒子经 s03 drain 注入（管道已通）。
- 新 entity 内存字段：`_self_counsel_heat`（float，随时间衰减）。轻量持久化可选。

---

## §7 常量（待 bcyq 扫一眼；硬编码红线）

| 常量 | 提议值 | 含义 |
|---|---|---|
| `_BASE_LONE_LOAN` | 0.06 | 孤独表层基础支取额（满额时），对标 ① 旧 surface_release 量级 |
| `_BASE_CONF_LOAN` | 0.03 | 不可答困惑基础支取额（更小，谨慎） |
| `_SEEP_RATE` | 0.10 | 微量渗透：孤独支取额 × 此 → core 增量（利息） |
| `_CEILING` | 0.70 | 信用上限：core 达此贷款额趋零 |
| `_HEAT_GAIN` | 1.0 | 每次支取热度增量（驱动边际递减） |
| `_HEAT_TAU` | 8.0 | 热度衰减时间常数（拍），对标 `_TAU_INTENT` |
| `_SC_SOMA_COMFORT` | 0.05 | 自我开导的即时体感安慰（小于被理解的 0.10，因是自欺） |
| `_SC_PARTICLE` | 0.4 | 自我宽慰粒子强度系数 |
| ① 残留 `somatic_comfort` | 0.15→**0.05** | 缩小为纯宣泄的一丝舒服 |

> 渗透率 / 上限 / 热度这几个无旧锚点，属新标定，建议先上提议值跑一轮观测再调。

---

## §8 合法性自检
- ✅ 无 if/比较门控行为：贷款额 = 连续 A×B 系数；可答性用 trigger 前缀 dict 分发；递减/渗透/上限全连续函数 + clamp。
- ✅ 无 LLM。
- ✅ 保护求知：可答困惑零贷款，求知驱动不被自欺掐灭。
- ✅ 结构诚实：只动 surface，core 由真实事件还；不可答困惑无本金故无渗透。
- ✅ 完整形态一次落地：条款 A+B + 困惑可答性闸 + ① 提纯，本期全做。
- ✅ 单一职责 <400 行：新模块独立；s07a 是删减不是新增。

---

## §9 开放点（实现前最后确认）
1. **① 残留范围**：缩到只剩"一丝 somatic_comfort（0.05）"作为宣泄反射，移走 surface/unresolved 操纵——同意？boredom/approach/avoid 的释放**保留在 ①**还是也迁走？（我倾向保留在 ①，它们不属于"自欺贷款"范畴。）
2. **困惑单标量小坑**（§4）：本期接受"贷款额小 + question_tension 自我纠偏"，unresolved 拆双层留后——同意？
3. **§7 新标定常量**（渗透 0.10 / 上限 0.70 / 热度 τ=8）：用提议值开跑？
4. **不可答困惑无解时的终态**：接纳 = unresolved 表层降 + "释怀"粒子，core 不动（无本金）。确认此即设计终点，不追求"解决"不可答问题。

---

## §10 验证
1. 单元：满额支取 → surface↓ + core 微升（渗透）+ 体感小升 + "自我宽慰"粒子；连续支取 → 边际递减可见；core 高 → 贷款趋零（上限）。
2. 可答性闸：构造一条可答(input_)规则的 pending question → 自我开导**不**降其 unresolved；不可答(action_)的 → 降（小额）。
3. 求知保护回归：跑认知信用闭环相关测试，确认 self_counsel 上线后可答困惑的求知驱动不被压垮（提问仍生成）。
4. 回归：test_50_ticks / test_fixes / test_expression_feedback 全过。
5. 端到端（重启 daemon，需 bcyq 批）：长 idle 无人期观察 surface 被自我安抚、core 持续涨、贷款随 core 升而收紧。

---

## §11 排期 / 与其它线的关系
- 前置已就绪：身体后果通道（PLAN_honest_reward_somatic_coupling，已落地待端到端验证）。
- 顺序建议：先把上一份的 **daemon 端到端验证**做掉（确认身体后果通道真点亮），再实现本 self_counsel（它复用那条通道）。
- 仍挂着：bcyq 最初想说的"另一个问题"（自我开导落地后回头听）。
