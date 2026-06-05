# Task Package: clarification-memory-record-only (v1)

> 承接语言理解线（失明地图 → honest uncertainty + proposition frame + targeted clarification，
> 已由 Codex 完成第一阶段并在线标定）。本任务**只做 record-only v1**：把"她问出了一个
> 澄清问题"这件事忠实地记录下来并持久化。**不接 observe_reply、不补槽、不改驱动力、不碰世界模型。**
>
> **修订版（Codex review #1：Revise before implementation，6 条已并入）。**

## Goal

她在锚点输出路径**真正说出口**一个澄清问题时（generic："这句……我没太懂"；targeted：
"你说的是谁，或者什么呢……"等），把这次澄清作为一条可观测、可持久化、带完整时间字段
的记忆条目记录下来，供后续阶段（observe_reply / 补槽）和在线分析使用。

本阶段交付的是"她问了什么"的**忠实账本** + 统计视图，不产生任何行为或状态改变。

## Background

- 现状（已落地）：`uncertainty_expression.py` 提供 5 个澄清模板（2 generic + 3 targeted）；
  `proposition_frame.py` 产出可检查的命题骨架（actor/predicate/patient/polarity/tense/modality
  + slot_relevance + slot_confidence），存于 `_cx_parse_result["proposition_frame"]`；
  s06c 在 [line 214](src/pipeline_runner/stages/s06c_anchor_core.py:214) 把澄清模板经 `_extra`
  喂进 `compose_sentence`，并在 [line 229-246](src/pipeline_runner/stages/s06c_anchor_core.py:229)
  做 narrative vs anchor 的 softmax **显示竞争**（`_d_idx`、`_chosen_mode`、`_chosen_text`）。
- **真实模板顺序**（[s06c line 190→195→212](src/pipeline_runner/stages/s06c_anchor_core.py:190)）：
  `_extra = runtime_templates + uncertainty_patterns + CxG candidates`；`compose_sentence` 内
  `all_templates = PATTERNS + _extra`。故完整快照 = **PATTERNS + runtime_templates +
  uncertainty_patterns + CxG candidates**。
- 缺口：澄清"问没问出口"目前无人记录；`_understanding_confidence` 已算出但无下游账本。
- 为什么 record-only 先行：澄清记忆要成为学习入口，前提是先有忠实、可持久、可统计的原始账本；
  且 missing_slot 质量受限于 `parse_svo`（见风险 1），必须先用真实数据验证分布，再决定 v2。

## Non-Goals（严格边界）

- **不实现 observe_reply / 槽位假设 / 补槽 / pending 消费**（v2 范围）。
- **v1 不引入独立 pending deque**（Codex #2）：回答归属与消费语义未定义前，pending 没有意义。
- **不修改驱动力、世界模型、unresolved 或任何 entity 状态变量**（除新增记忆镜像字段本身）。
- 不与 `expression_feedback.consume_response` 交互、不抢用户回答。
- 不改 `compose_sentence` 的返回签名（保持纯函数）。
- 不新增 LLM 调用点。
- **parse_svo 风险在 record-only 阶段只忠实记录，不提前加任何行为护栏**（Codex 确认）。
- 不碰糯糯（KNuoNuo，PID/端口 8767-8768；XIA 用 8765/8766）。

## Constraints

- 禁 if/else 逻辑门控（连续函数 + dict 派发 + clamp + deque(maxlen)）；记录闸的"非空/显示/
  是否澄清模板/索引边界"为**数据有效性 guard**，非行为门控，允许但保持最小。
- 常量须命名并注明来源（偏小先跑再调，待 Owner 追认）。
- 单文件 ≤400 行；外科手术式改动。**s06c 当前 397 行 → 新逻辑必须封装进独立函数，
  s06c 只留一次短调用，保持 ≤400 行**（Codex #4）。
- 优先 code-review-graph MCP 工具再退回 Grep/Read。
- 改动前先告知 Owner、得确认再动手。

## Scope（五项，严格限定）

### 1. 新建 `src/language_system/clarification_memory.py`

- 数据结构 `ClarificationEpisode`，**完整保留时间维度**：
  - `original_input: str`
  - `proposition_frame: dict`（记录时的骨架快照）
  - `clarification_kind: str`（"generic" | "targeted"）
  - `clarification_slot: Optional[str]`（None | "actor" | "patient" | "predicate"）
  - `question_text: str`（她**真说出口**的那句 = `_chosen_text`）
  - `confidence: float`（记录时的 `_understanding_confidence`）
  - `tick: int`（审计/测试用）
  - `timestamp: float`（`time.time()`，**recency 主基准**）
- 容器（Codex #2）：**v1 只保留 `history: deque(maxlen=_HISTORY_MAXLEN)`，不要独立 pending deque。**
- `ClarificationMemory` 类：
  - `record(episode) -> None` —— 入 history。
  - `recent_records(now_timestamp) -> list` —— **按 recency 派生的只读视图**（不改 history），
    每项带 `recency = exp(-age/_RECENCY_TAU_SECONDS)`，`age = max(0.0, now_timestamp - episode.timestamp)`。
  - `stats() -> dict` —— generic/targeted 计数、actor/patient/predicate 分布、
    slot_confidence/slot_relevance 分布（见 inspection）。
  - `to_dict() / from_dict()` —— history 的 list-of-dict 序列化。
- recency（Codex #1）：**主基准用 timestamp（墙钟），停机时间也计入流逝；tick 仅审计/测试。**
  `_RECENCY_TAU_SECONDS = 240.0`（来源：8 tick × 30s/tick）。v1 **计算但不消费**，为 v2 备好。
- 命名常量（提议值，先跑再调，待 Owner 追认）：`_HISTORY_MAXLEN`、`_RECENCY_TAU_SECONDS = 240.0`。

### 2. `src/language_system/uncertainty_expression.py`

- 5 个澄清模板各加 metadata：
  - `clarification_kind`："generic"（"这句……我没太懂"、"是说什么呢……"）/ "targeted"（其余三条）。
  - `clarification_slot`：generic → `None`；targeted → "actor"（是谁在这样呢）/ "patient"
    （你说的是谁，或者什么呢）/ "predicate"（你说的这是怎么回事呢）。
- 新增 helper：`clarification_meta(template: dict) -> Optional[dict]` —— 给定模板 dict，
  返回 `{"kind":..., "slot":...}` 或 `None`（非澄清模板）。**"什么算澄清"的知识收敛在本模块。**

### 3. `src/pipeline_runner/stages/s06c_anchor_core.py`

- **新逻辑封装进** `maybe_record_displayed_clarification(...)`（置于 `clarification_memory.py`，
  s06c 只调一次），保持 s06c ≤400 行（Codex #4）。
- 该函数承担全部记录闸（数据有效性 guard）：
  1. `raw_input` 非空（`min(1, len(raw_input.strip()))`）。
  2. `_chosen_mode == "anchor_auto"`（`_d_idx==1`，anchor 真赢过 narrative 显示出口）。
  3. `_tmpl_idx >= 0`（**compound 负索引不记录**）。
  4. 经 metadata helper 判定为澄清模板（`clarification_meta` 返回非 None）。
- **模板快照 + 禁裸索引推槽**（Codex #5）：调用方传入**本次 compose 使用的同一份模板列表快照**
  `all_templates = PATTERNS + _extra`（其中 `_extra = runtime_templates + uncertainty + CxG`，
  与 s06c line 190/195/212 同序）。helper 内 `0 <= tmpl_idx < len(all_templates)` 边界 guard →
  取 `all_templates[tmpl_idx]` → `clarification_meta(template)` 读 kind/slot。**禁止任何索引算术
  推导 slot**；越界/负索引一律返回 None → 不记录。slot 取**中选模板自带 metadata**，不从 frame 重推。
- 命中时构造 `ClarificationEpisode` 并记录；6 字段从该点现成取：`raw_input`、
  `_cx_parse_result["proposition_frame"]`、kind/slot（metadata）、`_chosen_text`、
  `entity._understanding_confidence`、`entity.tick`、`time.time()`。

### 4. `src/entity_state.py` —— 运行时对象 / 持久化镜像分离（Codex #3）

- **运行时对象**：`entity._clarification_memory`（`ClarificationMemory` 实例，瞬态，不声明为字段）。
- **JSON 镜像**：`entity._clarification_memory_data`（声明为持久 `dict` 字段，进 persist/load）。
- `_get_memory(entity)`（置于 `clarification_memory.py`）：懒恢复——运行时对象存在则返回；
  否则从 `entity._clarification_memory_data`（`from_dict`，空 dict 也安全）重建并挂上。
- **每次 record 后立即写回** `entity._clarification_memory_data = memory.to_dict()`，
  保证镜像与运行时对象同步（镜像随 entity_state 落盘）。
- 重启后 history 完整恢复，timestamp 不变 → recency 跨重启连续（且停机时间计入）。
- 接法镜像 `_cxg_data`（运行时 `_cxg_learner` 瞬态 + 持久镜像 `_cxg_data`）。

### 5. 测试与 inspection

- 单测（`tests/test_clarification_memory.py`）：
  - 候选入选但 **narrative 最终显示**（`_chosen_mode!="anchor_auto"`）→ **不记录**。
  - targeted 真正说出口 → 记录，且 `clarification_slot` 正确（actor/patient/predicate）。
  - generic 真正说出口 → 记录，`clarification_slot is None`、`kind=="generic"`。
  - **daemon 空拍（raw_input 为空）** → 不记录。
  - **compound 负索引（`_tmpl_idx < -1`）** → 不记录。
  - **越界 `_tmpl_idx`** → 不记录（边界 guard）。
  - **record 后镜像同步**：record 后 `entity._clarification_memory_data` 即与 `memory.to_dict()` 一致。
  - **entity_state 落盘恢复**：persist→load roundtrip，history 完整（含 tick/timestamp），
    `from_dict` 后 `recent_records(now)` 能正确按 timestamp 算 recency。
- inspection 探针（Codex #6）：喂若干"会触发澄清"的输入，dump 记录的 episode + 统计：
  - generic / targeted 比例
  - actor / patient / predicate 分布
  - 对应 slot_confidence 与 slot_relevance 分布
  - recency 视图（`recent_records(now)`）
  - record 后镜像同步 + entity_state 落盘恢复验证

## Acceptance Criteria

- [ ] 澄清模板真正显示出口才记录；候选入选但 narrative 胜出不记录；空拍不记录。
- [ ] targeted 记录正确 slot；generic slot=None / kind=generic。
- [ ] compound 负索引、越界索引均不记录（metadata helper + 边界 guard，无裸索引推导）。
- [ ] recency 用 timestamp 主基准（`_RECENCY_TAU_SECONDS=240.0`），tick 仅审计；v1 不消费。
- [ ] v1 无独立 pending deque，只有 history + `recent_records` 只读视图。
- [ ] 运行时对象 / JSON 镜像分离，`_get_memory` 懒恢复，record 后即写回镜像；entity_state 持久 + 恢复。
- [ ] 重启后 history 完整、timestamp 不变、recency 连续。
- [ ] 全程不改驱动力/世界模型/unresolved；不接 observe_reply；不提前加 parse_svo 行为护栏。
- [ ] s06c 仅一次短调用，新逻辑封装在 `clarification_memory.py`；s06c ≤400 行。
- [ ] 单测覆盖上述全部分支；inspection 输出全部统计项。
- [ ] 无 if/else 逻辑门控；常量命名并标注；单文件 ≤400 行；无关文件无格式漂移。
- [ ] Codex 独立评审通过。

## Risks（随实现一起跟踪）

1. **parse_svo 槽位质量风险（最高）**：失明地图显示她基本未真解析句法，proposition_frame 的
   actor/patient 多为方向猜测（默认 "external" → slot_confidence 0.10）。后果：targeted 澄清可能
   频繁落 actor/patient，哪怕句子很清楚 → missing_slot 分布失真。**record-only 阶段只忠实记录、
   不加行为护栏**（Codex 确认）；交付后先看在线统计（targeted/generic 占比、slot 分布、对应
   slot_confidence/relevance 分布）是否合理，**这是 v2 接 observe_reply 的前置闸**。

2. **索引错位风险**：`_extra = runtime_templates + uncertainty + CxG`（顺序见 s06c line 190/195/212），
   顺序变动会让 `_tmpl_idx → 模板` 静默错位、槽位归属出错。缓解：helper 必须拿**本次 compose 用的
   同一份 `PATTERNS + _extra` 快照**，metadata 查 + 边界 guard，**禁裸索引算术**；用 compound 负索引、
   越界两条单测钉死；若 `_extra` 拼接顺序调整需同步复核本记录点。

3. **重启后陈旧 history 风险**：长停机后 history 里残留很旧的澄清。v1 不消费，风险仅在残留 +
   将来（v2）被误匹配。缓解：timestamp 主基准 → `age=now-timestamp` 把停机时间计入 → recency 自然
   趋零使旧条目惰性化；`deque(maxlen)` 限容自动驱逐最旧。**v2 的 observe_reply 必须按 recency 加权，
   使陈旧条目无法主导**——在 SPEC 与代码注释显式标注这条对 v2 的约束。

## Open Questions / 待 Owner 追认

- 常量取值：`_HISTORY_MAXLEN`（建议偏大些以保留统计样本，如 200，先跑再调）、
  `_RECENCY_TAU_SECONDS = 240.0`（= 8 tick × 30s，Codex 建议值）。
- recency 基准已定：**timestamp 主基准**（Codex #1，停机时间计入），tick 保留审计/测试。

## 评审

- 本 SPEC（修订版）回 Codex 复核确认 6 条已并入。
- 实现交付后补 `THREADS.md`（决策日志）与 `VALIDATION.md`（单测 + 在线统计）；
  评审往来记入 `REVIEW_CODEX.md`。
