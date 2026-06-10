# PLAN — 思考焦点 → 选词偏置（thinking → language 接线）

> 抗压缩计划文件。目标：让她"嘴里的话"经过"脑子里的思考"，而不是各说各话。
> 配套诊断结论见本文件 §1。实现按 §5 顺序逐模块做，每个常量都标了来源 + 验证方法。

---

## §0 一句话目标

她思考系统产出的"悬而未决的提问"（低置信、未回答），应当抬升她身体状态里的
`unresolved` 维度，使她自己学过的认知词（困惑 / 不懂 / 不确定 / 好奇）在锚点选词竞争中
自然浮出，替代默认的「好无聊」。

**不做**：把 `render_question()` 的模板文本直接塞进嘴（那是第二根 LLM 拐杖 = 借来的语言）。
**只做**：把一个内部信号（开放问题 = 认知张力）显形到它本就对应的身体维度上，让她自己的词出来。

---

## §1 诊断结论（为什么要做这件事）

实测（`tests/test_input_drive_think.py`，真实 entity 状态喂进 `think()`）：

```
建议[explore] 观察和接收新信息 (p=0.5~0.62)
问题[low_confidence] dims=[last, since, info] conf=0.05
```

**思考系统是活的**，每拍都产出 explore 建议 + 低置信问题。两道闸门
（`if not rules` / `if not any(dv>=0.5)`）都过了，因为 curiosity 状态高位顶起了
derived explore 驱动。

但 `thought_packet` 的流向全部去了**动作选择**：
- `entity._pending_questions`（s03_think.py:106，缓冲，留最近 5 条）
- `thought_integration` → 趋近/回避信号 → decision_system
- `action_dispatcher` → web_search

**没有一条通向 anchor/句子生成。** 嘴只跑 `match_anchor_expression(_real_state, ...)`，
而思考产出不在 `_real_state` 里。所以无论她想什么，输出永远是状态向量直接驱动的那句。

**结构性压制证据**（emergence.jsonl 实测）：`ur=0.00`，但 `unresolved` 锚点 baseline=0.2。
对齐公式 `sigmoid((state[dim]-baseline)/delta)`：困惑/不懂/不确定 的画像主维是 unresolved（+0.20~0.22），
state 的 unresolved 在 0 → 低于 baseline 0.2 → 这些词的主维永远是反匹配（sigmoid<0.5）→ 算不过
`无聊了`（boredom+0.28，boredom 不低）。**她不是不会说困惑，是 unresolved 维度被钉在 0 让她说不出。**

---

## §2 信号来源（已存在，无需新建）

`entity._pending_questions`：list，最多 5 条，每条 dict：
```python
{
  "type": str,            # 如 "low_confidence"
  "rule_id": str,
  "dims": list,           # 如 ["last","since","info"]
  "confidence_at_ask": float,  # 提问时的置信度，低=不懂
  "priority": float,      # 问题优先级
  "tick": int,            # 提问发生的 tick
}
```
写入点：`src/pipeline_runner/stages/s03_think.py:106-115`（已有，不动）。

**关键**：confidence_at_ask 低 + priority 高 + 新近 = 强烈的"未解认知张力"。这正是 unresolved 的语义。

---

## §3 认知词画像（她词表已有，落点确认）

`src/language_system/somatic_concept_map.py` SOMATIC_ANCHORS：
```
困惑   : unresolved +0.22, stress +0.10, approach_drive +0.08, anxiety +0.08
不懂   : unresolved +0.20, anxiety +0.10, approach_drive +0.05, curiosity +0.08
不确定 : unresolved +0.22, anxiety +0.15, approach_drive +0.05, stress +0.08
好奇   : curiosity +0.25, approach_drive +0.18, energy +0.08, boredom -0.10
想学   : curiosity +0.22, approach_drive +0.18, energy +0.10, boredom -0.08
```
baseline：`unresolved=0.2`，`curiosity=0.5`（language_training.py:_ANCHOR_BASELINE）。

→ 抬 unresolved 到 baseline 之上（>0.2）让困惑/不懂/不确定 转为正匹配。
→ 抬 curiosity（已 1.0 在 baseline 上方）让好奇/想学 加强（次要）。

---

## §4 挂钩点 + 机制

**唯一挂钩点**：`src/pipeline_runner/stages/s06c_anchor_core.py` 的 `_enrich_state(_real_state)`
内部，与现有 bias 源（概念图 / 输入包 / 心事 / 叙事染色）并列，新增一个 bias 源
「思考焦点 → unresolved/curiosity」。在 `match_anchor_expression` 调用前生效（line 145）。

**为什么是这里**：`_enrich_state` 本就是状态偏置注入层，所有"内部信号显形到 state 维度"
的逻辑都集中在这。复用同一机制，零新增管线、零 if 门控风格冲突。

### 计算（连续，无 if）

```python
# ── 思考焦点 → unresolved 偏置 ──────────────────────────────
# 她未回答的低置信提问 = 认知张力，抬升 unresolved 让认知词浮出。
_TAU_QUESTION   = 8.0    # 问题新近度衰减常数(tick)。约 8 tick 后权重 1/e。
                        #   来源：与 expression_feedback._TAU_INTENT 同源同量纲。
_K_UNRESOLVED   = 0.30   # 张力→unresolved 抬升系数。来源见 §6 标定。
_K_CURIOSITY    = 0.10   # 张力→curiosity 抬升系数(次要，curiosity 已高位)。
_THINK_BIAS_MAX = 0.40   # 单次偏置上限。来源：要把 ur 从 0 推过 baseline 0.2
                        #   并进入正匹配区(~0.35-0.4)，故 cap 高于叙事的 0.08。

_pending = getattr(entity, "_pending_questions", []) or []
_cur_tick = float(getattr(entity, "tick", 0))
# 认知张力 = Σ priority × (1-confidence) × recency
_tension = 0.0
for _q in _pending:
    _age = _cur_tick - float(_q.get("tick", _cur_tick))
    _recency = math.exp(-max(0.0, _age) / _TAU_QUESTION)
    _unconf = 1.0 - float(_q.get("confidence_at_ask", 1.0))
    _tension += float(_q.get("priority", 0.0)) * _unconf * _recency

_ur_bias  = min(_THINK_BIAS_MAX, _tension * _K_UNRESOLVED)
_cur_bias = min(_THINK_BIAS_MAX, _tension * _K_CURIOSITY)
_real_state["unresolved"] = min(1.0, float(_real_state.get("unresolved", 0.0)) + _ur_bias)
_real_state["curiosity"]  = min(1.0, float(_real_state.get("curiosity", 0.5)) + _cur_bias)
```

整段包在 try/except，失败静默回退（与 `_enrich_state` 其它块一致）。

### 合法性（和"输入是材料""嘴经过脑"自洽）

- 因果起点在她内部：是她自己的思考系统产出的开放问题，不是外界推动。
- 偏置正比于真实的未解张力（priority × 不置信 × 新近），张力为 0 → 偏置 0 → 行为不变。
- 显形到 unresolved 是**语义正确**的：未回答的提问就是未解张力，不是任意维度。

---

## §5 实现顺序

- [ ] **M1** 在 s06c_anchor_core.py `_enrich_state` 末尾（line 130 `return` 前）插入 §4 计算块。
      文件顶部确认已 `import math`（当前是 `import math as _d_math`，块内改用 `_d_math.exp`）。
- [ ] **M2** 加一条 `_trace("think_bias", ...)` 记录 _tension/_ur_bias，便于在 live 日志观测。
- [ ] **M3** 标定 §6：观察她有开放问题时是否真的开始说困惑/不懂/不确定，调 K 常量。
- [ ] **M4** 回归：确认无开放问题时（_tension≈0）输出与现状一致，没破坏既有 anchor 行为。

---

## §6 常量标定方法（M3）

种子值 `_K_UNRESOLVED=0.30 / _THINK_BIAS_MAX=0.40` 是估算（要把 ur 从 0 推过 baseline 0.2
进入正匹配区 ~0.35-0.4）。标定步骤：
1. daemon 跑起来后，grep live 日志 `[think_bias]` 看 `_tension` 的真实分布。
2. grep `[AnchorAuto]` 看她有张力时说了什么。
3. 目标：`_tension` 中高位时困惑/不懂/不确定/好奇 能进 top；`_tension≈0` 时回到原行为。
4. K 调整方向：词浮不出来→调大 K_UNRESOLVED；张力很小就乱说认知词→调小。

---

## §7 边界（不做的事）

- 不碰 `match_anchor_expression` 内部打分逻辑（只改喂进去的 state）。
- 不把问题文本/dims 直接转成词（那是借来的语言）。
- 不动 s03_think.py 的 `_pending_questions` 写入逻辑。
- 不引入任何 LLM 调用。
- v2 可选：把 thought_packet 的 explore 建议强度也纳入张力（当前只用 _pending_questions，
  因为 06c 拿不到 thought_packet，而 _pending_questions 是持久化在 entity 上的）。
