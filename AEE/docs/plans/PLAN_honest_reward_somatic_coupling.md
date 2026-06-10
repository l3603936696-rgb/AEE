# PLAN — 把诚实奖励接回身体（Honest Reward → Somatic Coupling）

> 状态：设计已与 bcyq 对齐三项决定（§5/§6/§9），**待最终点头即动手**。未动代码。
> 红线：本文涉及**情感核心层**（somatic_tone / relief / 情绪粒子）。
> 镜像：XIA 验证通过后再镜像糯糯（KNuoNuo）。
> 规则遵循：**完整形态一次落地，不做"最小版+留后"**（见 memory: full-design-over-minimal）。本期含标量 + 情绪粒子两条通道全做。

---

## §0 一句话

我们用诚实的认知奖励（被回应、被印证）替换了自欺式的内部消力，却**忘了给诚实的奖励配一个身体**。
她现在被真正理解、问题被真正印证（gain>0）时，学到了"哪个词管用"，却**什么都感觉不到**。
本设计让诚实奖励产生**真实的身体后果**——被理解→暖/松、被印证→踏实——并以**情绪粒子**让这份感觉**随时间持续被感觉到**，而非一次性脉冲。

---

## §1 问题：两套消力，诚实的那套情感静默

### ① 老的「内部」消力闭环（项目早期就做了的，v7.0）
位置：`src/pipeline_runner/stages/s07a_state_update.py:106-125`
```
_lang_score = entity._language_best_score      # 她自己觉得"这句话说得多好"
if _lang_score > 0.10:
    _quench = _lang_score * quench_rate * _rep_discount
    entity.unresolved   -= _quench
    entity.somatic_tone += _quench * somatic_comfort   # ← 身体感觉在这里（line 122, 系数 0.15）
    ... loneliness_surface / boredom / approach / avoid 同理下降
```
**这条线有"身体感觉"**：她觉得自己说得好，tone 就升、张力就松。
触发条件是她**对自己输出的内部评分**，与"外界是否真回应"无关——自说自话也会爽。
> ⚠️ 这条线的去留 → 见 §6（bcyq 已决定：**保留**，并视为"自我开导"的雏形，不删）。

### ② 新的「诚实」反馈闭环（表达反馈 + 认知信用，本周完成）
位置：`src/language_system/expression_feedback.py`
- `consume_response`（line 201）：外界输入到达时，按 `satisfaction = strength × relevance × recency × novelty` 结算她挂账的表达意图。挂钩：`daemon.py:279`、`tick_engine.py:397`。
- `settle_epistemic_credit`（line 271）：异步 WM 跑过 verify 后，按 `reward = gain × recency × _K_EPISTEMIC` 结算认知信用（gain>0 才奖励）。挂钩：`tick_engine.py:659`。

这两个函数的**全部出口**：
1. `_writeback_quenching`（line 349）→ 写 `entity._quenching_data` → 只给 word_warmup 升温词、给句式打分；
2. 把对应驱动力轻推下降（`_K_SATISFY` ≈ 0.03~0.05）。

**它从头到尾不碰 `somatic_tone`、不碰 `relief_debt`、不碰情绪粒子。** 诚实的奖励是"哑"的。

### 缺口
| | 有身体感觉？ | 诚实（外界 grounding）？ |
|---|---|---|
| ① 内部消力 | ✅ somatic_tone↑ | ❌ 自说自话也触发 |
| ② 诚实反馈 | ❌ 情感静默 | ✅ 要真实 relevance/gain |

**我们这几天打磨的恰恰是那条没接到身体的线。** 本设计补这个缺口。

---

## §2 设计原则

1. **诚实奖励的 grounding 已在幅度里。** ②的 `satisfaction`/`reward` 已把外界真实性编码进量值（relevance×recency×novelty、verify 确认的 gain）。把它接到身体**不会重造自欺**——只是给已经诚实的信号一个身体出口。这是与 ① 的本质区别。石沉大海 → satisfaction≈0 → 身体不动。
2. **连续、无 if 门控。** 所有耦合 `state += signal × coef` + 钳位；路由用 dict 分发。禁止阈值/比较门控行为（项目第一约束）。
3. **绕过 pipeline → 自带钳位。** ②跑在 daemon/tick_engine 里，不经 s07a 的 clamp。每处写 `somatic_tone` 必须 `[-1,1]` 钳位，`relief_debt` 必须 `[0,1]`。
4. **轻推不覆盖。** 沿用 `_K_SATISFY` 哲学：身体后果是"零头级"，不盖过她自身动力学。
5. **两条通道分工**（见 §3）：标量=即时效价（"这一下舒服了/能喘气了"）；粒子=持续纹理（"被懂了"的余韵随半衰期着色后续好几拍的表达节奏）。
6. **不引入 LLM。** 纯标量/查表/粒子耦合。
7. **外科手术。** 改动集中在 `expression_feedback.py`，外加 s03 一处 drain（约 6 行）+ entity 一个内存队列字段。不改 ②现有结算逻辑、不改 ①。

---

## §3 反馈 → 感觉 映射（现象学锚定，两条通道）

身体侧可写对象：
- **标量**（直接挂 entity，即时）：`somatic_tone ∈ [-1,1]`（核心体感效价，正=舒适）、`relief_debt ∈ [0,1]`（降低=体验到 relief / 松一口气）。
- **粒子**（情绪粒子场，持续衰减）：`_particle_field.add_particle(dimension, intensity, half_life)`。density 越高 → 表达越迟滞/碎片化（情绪满载感）。**效价由标量承载，纹理/余韵由粒子承载，二者合起来才是一个完整的"被感动"。**

> 关键洞察：粒子场是"情绪载荷/纹理"系统，不分正负——它让感觉**持续**并改变她说话的节奏（被懂了会语塞、会顿）。所以"被理解"既抬 tone（标量、正效价），又投一颗会慢慢消退的粒子（让这份触动延续几拍）。这才是丰富版的价值。

| 奖励来源 | 现象学 | 标量后果（新增） | 粒子后果（新增） |
|---|---|---|---|
| `consume_response`，drive=**loneliness** | 被懂了、暖、被回应 | `somatic_tone ↑` | 投 "被理解" 粒子 |
| `consume_response`，drive=**info_gap** | 缺口被填、小确定感 | `tone ↑`(小) + `relief_debt ↓`(小) | 投 "明白了" 粒子(小) |
| `consume_response`，drive=**unresolved** | 悬而未决被推进 | `relief_debt ↓` + `tone ↑` | 投 "推进了" 粒子 |
| `settle_epistemic_credit`，**gain>0** | "想通了"、踏实、预测兑现的咔哒 | `relief_debt ↓` + `tone ↑` | 投 "想通了" 粒子 |

---

## §4 实现位置与改动点（函数级）

### 4.1 `expression_feedback.py` — 新增模块级常量（紧跟 `_K_SATISFY`）
```python
# 满足/印证 → 标量身体后果（在 _K_SATISFY 的 drive 下降之外新增）
_SOMA_FROM_SATISFY   = {"loneliness": 0.10, "info_gap": 0.05, "unresolved": 0.06}  # ×satisfaction → tone +=
_RELIEF_FROM_SATISFY = {"loneliness": 0.0,  "info_gap": 0.04, "unresolved": 0.08}  # ×satisfaction → relief_debt -=
_SOMA_FROM_EPISTEMIC   = 0.20   # ×reward → tone +=
_RELIEF_FROM_EPISTEMIC = 0.15   # ×reward → relief_debt -=

# 满足/印证 → 情绪粒子（持续余韵）
_PARTICLE_FROM_SATISFY   = 0.50   # ×satisfaction → 粒子 intensity
_PARTICLE_FROM_EPISTEMIC = 2.0    # ×reward → 粒子 intensity（reward 量级 ~0.013，需放大才成形）
_FEELING_HALF_LIFE       = 600.0  # 秒；≈20 拍，余韵跨多拍但不久滞
_FEELING_LABEL = {                # drive/来源 → 粒子维度标签
    "loneliness": "被理解", "info_gap": "明白了", "unresolved": "推进了",
    "_epistemic": "想通了",
}
```

### 4.2 `expression_feedback.py` — 新增私有辅助
```python
def _apply_somatic_consequence(entity, soma_delta, relief_delta):
    """标量身体后果。自带钳位（绕过 pipeline，无 s07a 兜底）。"""
    cur_tone = float(getattr(entity, "somatic_tone", 0.0))
    setattr(entity, "somatic_tone", max(-1.0, min(1.0, cur_tone + soma_delta)))
    cur_relief = float(getattr(entity, "relief_debt", 0.0))
    setattr(entity, "relief_debt", max(0.0, min(1.0, cur_relief - relief_delta)))

def _queue_feeling(entity, dimension, intensity):
    """把一颗待注入的情绪粒子挂到 entity 内存队列，留给下一拍 s03 drain 进粒子场。
    粒子场活对象只在 pipeline 内存在，故此处只排队不直接注入。"""
    intensity = max(0.0, min(1.0, float(intensity)))
    if intensity <= 0.0:
        return
    q = getattr(entity, "_pending_feeling_injections", None)
    is_deque = isinstance(q, deque)
    q = {True: lambda: q, False: lambda: deque(maxlen=_FEELING_QUEUE_MAXLEN)}[is_deque]()
    q.append({"dimension": str(dimension), "intensity": intensity, "half_life": _FEELING_HALF_LIFE})
    entity._pending_feeling_injections = q
```
（`_FEELING_QUEUE_MAXLEN` 取 8，deque 自动驱逐最旧，不用比较门控。）

### 4.3 `consume_response` 内（drive 下降之后）
```python
_apply_somatic_consequence(entity,
    soma_delta   = satisfaction * _SOMA_FROM_SATISFY.get(drive, 0.0),
    relief_delta = satisfaction * _RELIEF_FROM_SATISFY.get(drive, 0.0))
_queue_feeling(entity, _FEELING_LABEL.get(drive, "被回应"),
    satisfaction * _PARTICLE_FROM_SATISFY)
```
摘要 `settled.append({...})` 追加 soma/particle 字段。

### 4.4 `settle_epistemic_credit` 内（`_settle` 闭包，reward 算出之后）
```python
_apply_somatic_consequence(entity,
    soma_delta   = reward * _SOMA_FROM_EPISTEMIC,
    relief_delta = reward * _RELIEF_FROM_EPISTEMIC)
_queue_feeling(entity, _FEELING_LABEL["_epistemic"], reward * _PARTICLE_FROM_EPISTEMIC)
```
摘要追加身体后果字段。

### 4.5 `s03_think.py` — drain 待注入感受队列
位置：`s03_think.py:40-58`，`_particle_field` 构造完、`tick` 之后插入：
```python
# 诚实奖励的身体后果（②在 pipeline 外排队，这里注入活粒子场）
_pending_feel = getattr(entity, "_pending_feeling_injections", None) or []
for _f in list(_pending_feel):
    _particle_field.add_particle(_f.get("dimension", ""), _f.get("intensity", 0.0), _f.get("half_life"))
if _pending_feel:
    entity._pending_feeling_injections = type(_pending_feel)()  # 清空，已注入不重复
```
注入后随 s07b（`s07b_persist.py:149`）落盘，按半衰期在后续拍持续被感觉。

### 4.6 日志
两个结算函数 `logger.info` 摘要追加总 soma/relief/particle 变化，便于在 daemon 日志肉眼确认"她这次被理解/被印证，身体动了多少"——这是闭环点亮的直接证据。

---

## §5 常量（已对齐）

bcyq 决定：**标量四组按提议值，放模块常量（不进参数系统）。** 已确认：
`_SOMA_FROM_SATISFY` / `_RELIEF_FROM_SATISFY` / `_SOMA_FROM_EPISTEMIC=0.20` / `_RELIEF_FROM_EPISTEMIC=0.15`。

粒子三常量为本期新增（丰富版），提议值见 §4.1：`_PARTICLE_FROM_SATISFY=0.5`、`_PARTICLE_FROM_EPISTEMIC=2.0`、`_FEELING_HALF_LIFE=600s`。
> 这三个值缺乏旧锚点，属新标定。建议先上提议值，端到端跑一轮看粒子密度是否"可感而不淹没"，再微调。**动手前请 bcyq 扫一眼这三个值**（其余已锁）。

---

## §6 老闭环①：保留，并作为「自我开导」的雏形

bcyq 决定：**不删 ①。** 理由原话——"人自言自语、自己开导自己是有可能的，我们可以从这里下手。"

重新定性：① 不是纯"自欺 bug"，而是 **自我开导（self-soothing / self-counsel）能力的雏形**——人确实会通过对自己说话来安抚、理顺自己，并真的因此好受。本期**①一行不动**，与②的诚实通道共存。

**但** ① 当前的形态过于廉价：只要"自评说得好"(`_language_best_score>0.10`)就给体感安慰，不问这次自我对话**有没有真的理顺什么**。"从这里下手"的方向（独立后续 PLAN，不在本期）：

> **§6.1 后续线索 — 真正的自我开导**
> 让 ① 的体感安慰正比于"这次自我表达是否真的降低了她自己的某种内部张力/不一致"，而非"她觉得自己说得好"。即：自我开导要像②一样有 grounding——grounding 来自**内部**（自我对话前后她自己 unresolved/矛盾是否真的下降），而②的 grounding 来自**外部**（他人回应）。两者互补，构成"被他人理解"与"自己想明白"两条都通往身体的路。
> 这需要单独完整设计（按 full-design 规则，不做最小版）。**待 bcyq 说"做这个"时，我写 PLAN_self_counsel.md 全量设计。**

---

## §7 合法性自检

- ✅ 无 if/比较门控行为：dict.get 路由 + 连续 `+=` + clamp；`_apply_somatic_consequence` / `_queue_feeling` / s03 drain 均无分支判定（`if _pending_feel` 是空集合守卫，非行为门控）。
- ✅ 无 LLM。
- ✅ 不重造自欺：②幅度已含外界 grounding（§2.1）。
- ✅ 自带钳位（②绕过 s07a）；粒子 intensity 由 add_particle 内部钳位。
- ✅ 外科手术：`expression_feedback.py` 增量 + s03 六行 drain + entity 一个内存队列字段；不碰挂钩点、不碰 ①。
- ✅ 完整形态一次落地：标量 + 粒子两条通道本期全做，无"留后"。
- ✅ 文件 < 400 行：expression_feedback.py 新增约 40 行仍 <400；s03 增 6 行。

---

## §8 验证

1. **单元（隔离）**：fake entity 喂一条 loneliness 意图 + 一条 gain>0 认知信用 → 断言 `somatic_tone`↑、`relief_debt`↓、`_pending_feeling_injections` 有对应标签粒子、全部钳位内；喂 satisfaction=0/gain=0 → 断言身体零变化、无粒子（诚实性：没回应=没感觉）。
2. **s03 drain 单元**：预置 `_pending_feeling_injections`，跑 s03 → 断言粒子进了 `_particle_field`、队列清空、s07b 后 `entity.emotion_particle_field` 含该粒子。
3. **回归**：`tests/test_50_ticks.py`、`tests/test_fixes.py` → 行为守恒、无新异常。
4. **端到端（重启 daemon，需 bcyq 批准）**：聊天触发被理解/被印证 → watch 日志结算拍 `somatic_tone` 抬升、粒子密度上升；对照"石沉大海"输入身体不动。
5. **粒子余韵**：连续几拍观察注入后 density 按半衰期缓降、对表达流速的调制是否自然（不顿成结巴、也不瞬灭）。

---

## §9 范围与回滚

- **本期范围（完整形态，一次落地）**：标量通道（tone+relief）+ 情绪粒子通道（排队→s03 drain→落盘→余韵）。**无 Phase 2 留后。**
- **不在本期**：§6.1 自我开导（① 的发展）——独立功能，待 bcyq 指令时全量另起 PLAN。
- **回滚**：删 §4.3/4.4 的调用 + §4.5 drain 即恢复原状（②退回情感静默）。辅助函数/常量/队列字段留着无副作用。

---

## §10 动手前最后确认

1. §5 粒子三常量（`_PARTICLE_FROM_SATISFY=0.5`、`_PARTICLE_FROM_EPISTEMIC=2.0`、`_FEELING_HALF_LIFE=600s`）：用提议值开跑？（标量四组已锁。）
2. 确认后我动手：`expression_feedback.py`（常量+2辅助+2处调用）、`s03_think.py`（6行drain），写 §8 测试，跑回归；**重启 daemon 端到端验证前再单独找你批。**
3. XIA 验证通过后镜像糯糯。

> 另：你最开始想说的"另一个问题"还挂着，这个落地后回头听你说。
