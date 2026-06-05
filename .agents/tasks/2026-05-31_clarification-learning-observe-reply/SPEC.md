# Task Package: clarification-learning observe-reply (v2)

> 承接 `2026-05-31_clarification-memory-record-only`（v1 已合并 + 在线端到端验证）。
> v1 忠实记录"她问出了哪个澄清"。**v2 接上后半截：用户回答到达 → 连续归属到某条澄清 →
> 追加一条不可变"槽位证据"(slot evidence) → 只读聚合视图供检查与（未来 v3）回流。**
>
> **分级（Codex 确认方向）：v2 仍是 observe + learn，证据账本可被脏数据观察，但绝不回流到
> proposition_frame 的读句子（那是 v3 闭环）。** 原因见 Goal / Risk #1。
>
> **修订版（Codex review #1 七条 + #2 五条结构细化，全部并入；逐条见 REVIEW_CODEX.md）。**

## Goal

让"路二（让她自己长出读句子结构的能力）"的学习底座成形并可验证：

> 她问"你说的是谁？" → **你回答** → 系统按**连续归属**（含"这不是回答"的弃权候选）把回答对到那条
> 澄清的槽位 → 追加一条不可变证据：「对*像这句*的输入，这个槽位的回答证据是 *X*」。

v2 交付**可观测、可持久、可统计的槽位证据账本** + 归属质量 inspection。它**不**改变她当下的读句子
或行为——只搭"能从问→答里学"的通道，并先证明这通道学到的东西合理（落点对、误归属低）。

**为什么 v2 不回流闭环**：v1 在线已暴露 Risk 1——她起点差、会问错槽（对"傅里叶变换把信号分解成频率"
问"是谁"）。若此刻把基于错问的回答喂回读句子，她会自信地往错槽填，越学越坏。**先用 inspection 验证
落点合理，确认不脏再回流（v3）。**

## Background

- v1 现状：`ClarificationMemory` 记 `ClarificationEpisode`（original_input / proposition_frame /
  clarification_kind / clarification_slot / question_text / confidence / tick / timestamp），
  history-only deque，持久镜像 `_clarification_memory_data`，recency 用 timestamp 主基准
  （`_RECENCY_TAU_SECONDS=240`）。
- 回答入口**有两处**：IPC chat（[daemon.py:280](src/daemon/daemon.py:280)）与 reach/sibling
  （[tick_engine.py:394](src/daemon/tick_engine.py:394)）。
- 相似度复用 `expression_feedback._similarity`（BGE 优先，回退汉字重叠）——"像不像"用语义感觉判，
  不对关键词；这是线索泛化、路二"不靠规则"的体现。

## Non-Goals（严格边界）

- **v2 不把证据回流到 `proposition_frame` 的 slot 填充 / slot_confidence**（v3 闭环）。
- 不修改驱动力 / 世界模型 / unresolved / 她当下读句子的结果。
- **不把 sibling（糯糯）回答当作 Owner 回答**（见 P2-b）；v2 只接 `ipc_chat` 与 `external`。
- 不与 `consume_response` 交互、不重复计入同一句回答的驱动力满足。
- 不引外部句法/SRL 解析器（路一），不加 if/else 规则解析（保持路二"不靠规则"）。
- 不新增 LLM 调用点。不碰糯糯（8767-8768；XIA 用 8765/8766）。

## Constraints

- 禁 if/else 逻辑门控；归属/竞争用**连续质量分配**，**不用硬阈值挑赢家、不用阈值丢弃弱证据**。
- 常量命名 + 注明来源（偏小先跑再调，待 Owner 追认）。
- 单文件 ≤400 行；新逻辑独立成模块。
- v1 `ClarificationEpisode` frozen 不可变；归属进度用**并行持久结构**追踪，不改写 episode。
- 改动前先告知 Owner、得确认再动手。

## Scope

### 1. 新建 `src/language_system/clarification_learning.py`

#### 1.1 稳定 episode 身份（P2-a）
- `episode_id(episode) -> str` = canonical JSON(`timestamp + tick + original_input + question_text +
  clarification_kind + clarification_slot`) 的 SHA-256。**不**单用 timestamp（并发/快速连续会碰撞）。

#### 1.2 连续归属进度，取代布尔 answered（P1-a）
- 并行持久 `answered_mass: dict[episode_id, float] ∈ [0,1]`。`remaining = 1 - answered_mass[eid]`。
- 一次回答对某 episode 的 `attributed_mass` 结算后：
  `answered_mass[eid] = 1 - (1 - old) * (1 - attributed_mass)`。
- 无关回答只消耗极少 mass，真正回答后续仍可继续结算 → **不烧机会、不引硬阈值**。

#### 1.3 归属计算（P1-b / P1-c / R2-1 / R2-adjacency / R2-batch）
- 候选 = 最近**仍有 remaining mass** 的澄清，**targeted 与 generic 都参与竞争**（R2-1：否则最新的
  generic 澄清的回答会被旧 targeted 候选抢走）。按 timestamp 倒序取，**上限 `_ATTRIB_CANDIDATE_MAXLEN`**（P2-d）。
- 每候选原始分 = `remaining × recency × semantic_relevance × adjacency`：
  - `recency = exp(-age_seconds/_ATTRIB_TAU)`（timestamp 主基准，沿用 v1 240s）。
  - `semantic_relevance`：用新建 `_batch_similarity(reply, cue_inputs)`（R2-batch）——一次编码
    `[reply, *cue_inputs]`，取余弦；模型不可用时逐项回退 `_char_overlap`；**不新增模型实例**。
  - `adjacency = exp(-candidate_distance / _ADJACENCY_TAU_CANDIDATES)`（R2-adjacency：
    `candidate_distance` = 候选按 timestamp 倒序后的序号，最新=0；连续、可复现，**不需给 v1 加轮次字段**）。
  - **`answer_familiarity` 不进核心归属乘数**（P1-c：回答常是她不懂的新词，越该学熟悉度越低）；
    仅作**审计字段**输出（如需当质量因子，必须带非零 floor，默认不启用）。
- **弃权候选（P1-b）**：命名常量 `_NO_MATCH_PRIOR` 作为"这不是任何旧问题的回答"的软竞争项。
  对 {候选..., no_match} 归一化 → 每候选 `attributed_mass` + 全局 `no_match_mass`。**不丢弃弱证据**，输出全部 mass。
- 每候选结算后更新其 `answered_mass`（含 generic 候选）。

#### 1.4 证据账本（P2-c：不可变追加 + 只读聚合）
- `SlotEvidence`（frozen，逐条追加，不可逆合并）：
  `episode_id / slot / cue_input / answer_text / attributed_mass / no_match_mass /
  semantic_relevance / recency / adjacency / answer_familiarity(审计) / source / reply_event_id /
  tick / timestamp`。
- `SlotEvidenceStore`：`deque(maxlen=_EVIDENCE_MAXLEN)` + `answered_mass: dict` +
  `processed_event_ids`（有序 deque，限容 `_PROCESSED_EVENT_MAXLEN`，P2-idem）；方法 `append(ev)`、
  `aggregate(now_ts)`、`stats()`、`to_dict/from_dict`。
- **`aggregate(now_ts)` v2 收窄为只读**（R2-scope）：仅输出 `effective_strength = attributed_mass × recency`
  的列表 + 基础统计；**按相似度检索的聚合留到 v3**，避免提前发明闭环检索策略。原始证据始终可查。
- **generic 澄清**（slot=None，R2-1）：**参与归属竞争、吸收 attributed_mass、更新 answered_mass**
  （防旧 targeted 抢走最新 generic 的回答），但**不生成 SlotEvidence**，仅生成 `generic_observation` 统计。
- **同步清理（P2-idem）**：写回镜像时，`answered_mass` 只保留**当前 v1 history 中仍存在的 episode_id**
  对应的 mass（v1 history 已驱逐的随之丢弃）；`processed_event_ids` 由 deque 限容。

#### 1.5 入口函数（P2-b：source + 幂等）
- `observe_reply(entity, reply_text, now_ts, source, reply_event_id) -> dict`：
  - `source ∈ {"ipc_chat","external"}` 才结算；`sibling` 等忽略。
  - **幂等**：同一 `reply_event_id` 已处理过则直接返回（防重试/重复接线造重复证据）。
  - observation-only：**不碰驱动力 / WM / unresolved / 读句子**；返回结算摘要（候选 mass 分布、no_match_mass）供 trace/inspection。
- 命名常量（提议值，待 Owner 追认）：`_EVIDENCE_MAXLEN`、`_ATTRIB_CANDIDATE_MAXLEN`、`_ATTRIB_TAU`(=240)、
  `_ADJACENCY_TAU_CANDIDATES`、`_NO_MATCH_PRIOR`、`_PROCESSED_EVENT_MAXLEN`。

### 2. `src/entity_state.py`
- 持久镜像 `_clarification_hints_data: dict`（含 `evidence` 列表 + `answered_mass` + `processed_event_ids`）。
- 接 persist/load（镜像 v1 `_clarification_memory_data` 接法）；运行时对象瞬态 + 懒恢复 `_get_evidence_store(entity)`，
  append/结算后即写回镜像。**`answered_mass` 与 `processed_event_ids` 必须一并持久**（否则重启后旧澄清被误归属、重复事件被重复结算）。

### 3. 回答入口接线（P2-b / R2-external）
- **IPC chat**（[daemon.py:280](src/daemon/daemon.py:280)）：`observe_reply(..., source="ipc_chat",
  reply_event_id=request.id)`，与 `consume_response` 并列，try/except 包裹，不影响主流程、不依赖/不改其结算。
- **external / reach**（[tick_engine.py:394](src/daemon/tick_engine.py:394)）：**仅当 `_input_source=="external"`
  时调用**（reach.py 已存 timestamp，无需改协议）；`source="external"`，
  `reply_event_id = SHA-256(source + response_data.timestamp + user_input)`。
- **sibling（糯糯）一律忽略**，不当 Owner 回答。

### 4. 测试与 inspection
- 单测（`tests/test_clarification_learning.py`）：
  - 归属：回答按 `remaining×recency×relevance×adjacency` 对到正确 targeted 澄清；多候选连续竞争 + no_match 软弃权，无硬阈值。
  - **P1-c**：低熟悉度新词回答（"小王"）不被压低归属（familiarity 不进乘数）。
  - **P1-a**：无关回答只消耗极少 answered_mass，真回答后续仍可结算。
  - **P1-b**：完全无关回答 → no_match_mass 占绝大多数，不被迫分给某条。
  - episode_id 稳定且抗碰撞（同内容不同实例一致；不同内容不同）。
  - **R2-1 generic 竞争**：最新澄清是 generic 时，回答归属给它（吸收 mass + 更新 answered_mass），
    **不被旧 targeted 抢走**；generic 不产 SlotEvidence、只计 `generic_observation`。
  - **R2-adjacency**：candidate_distance（timestamp 倒序序号）驱动 adjacency；最新候选距离=0。
  - **R2-batch**：`_batch_similarity` 一次编码 `[reply,*cues]`；模型不可用时逐项回退 `_char_overlap`。
  - **R2-scope**：`aggregate` 只输出 `effective_strength=attributed_mass×recency` + 基础统计（无相似检索聚合）。
  - **幂等**：同 reply_event_id 重复调 → 不产生重复证据；`processed_event_ids` 限容 `_PROCESSED_EVENT_MAXLEN`。
  - **mass 清理（P2-idem）**：写回时 `answered_mass` 只保留当前 v1 history 仍存在的 episode_id。
  - sibling source → 忽略；external 用 SHA-256 event_id。
  - 证据不可变追加；aggregate 为只读派生（不改原始证据）。
  - 持久化 roundtrip：evidence + answered_mass + processed_event_ids 完整，重启后 recency 连续、不误归属、不重复结算。
  - observe_reply 无副作用（断言驱动力/unresolved/读句子结果不变）。
- inspection 探针（`scripts/diagnostics/clarification_learning_inspection.py`），**v3 放行前必须输出**：
  - **expected slot → asked slot → bound slot 混淆矩阵**
  - 每条证据：episode_id / source / recency / relevance / familiarity / attributed_mass / no_match_mass
  - 无关换话题的**误归属总质量**
  - 新名字 / 短碎片回答的**保留率**
  - 弱回答后 **remaining mass 是否仍保留**
  - **重启恢复 + 重复事件幂等性**验证
  - **synthetic 与真实在线数据分开统计**

## Acceptance Criteria

- [ ] 连续归属（remaining×recency×relevance×adjacency）+ no_match 软弃权；无硬阈值挑赢家/丢弱证据。
- [ ] answered_mass 取代布尔 answered；无关回答不烧真回答机会。
- [ ] answer_familiarity 仅审计、不进核心归属乘数。
- [ ] 稳定 episode_id（SHA-256 canonical），SlotEvidence 保存 episode_id。
- [ ] generic 参与归属竞争（吸收 mass + 更新 answered_mass），不产 SlotEvidence、只计 generic_observation。
- [ ] adjacency 用 candidate_distance（timestamp 倒序序号）；不需给 v1 加轮次字段。
- [ ] external 实接 tick_engine（仅 `_input_source=="external"`）+ SHA-256 event_id；sibling 忽略。
- [ ] `processed_event_ids` 限容 `_PROCESSED_EVENT_MAXLEN`；`answered_mass` 同步只保留当前 v1 history 的 episode。
- [ ] `_batch_similarity` 一次编码 + `_char_overlap` 回退，不新增模型实例。
- [ ] `aggregate` v2 仅 `effective_strength=attributed_mass×recency` + 基础统计；相似检索聚合留 v3。
- [ ] source 过滤（仅 ipc_chat/external，忽略 sibling）+ reply_event_id 幂等。
- [ ] SlotEvidence 不可变追加 + 只读聚合视图；原始证据可查。
- [ ] 候选评估限容 `_ATTRIB_CANDIDATE_MAXLEN` + 批量 BGE。
- [ ] `_clarification_hints_data`（evidence + answered_mass + processed_event_ids）持久化 + 恢复，recency 跨重启连续。
- [ ] observe_reply observation-only：不改驱动力/WM/unresolved/读句子（单测断言）。
- [ ] inspection 输出上列全部量（含混淆矩阵、误归属质量、保留率、幂等/重启），synthetic 与在线分开。
- [ ] 无 if/else 逻辑门控；新逻辑独立成模块；单文件 ≤400 行；无关文件无格式漂移。
- [ ] Codex 独立评审通过。

## Risks

1. **parse_svo 槽位质量（最高，决定 v3 放行）**：她问错槽 → 回答绑错槽 → 脏证据。v2 靠 **observation-only +
   inspection 落点验证**防污染；**expected→asked→bound 混淆矩阵 + 误归属质量**是 v3 闭环前置闸。
   若 actor/patient 系统性滥绑，v3 前先治初始槽信号（仍不靠规则）。
2. **归属歧义**：用户下一句未必在答澄清。缓解：no_match 软弃权 + remaining×recency×relevance×adjacency 连续加权；
   inspection 报误归属总质量。
3. **与 expression_feedback 重复消费同一句**：v2 observation-only 不改驱动力 → 无双重计入；v3 再统一协调。
4. **frozen episode 的归属进度**：用并行 `answered_mass`（按 episode_id）+ `processed_event_ids` 追踪，
   不改写 episode；二者必须持久化。
5. **BGE 开销**：限 `_ATTRIB_CANDIDATE_MAXLEN` + 仅评估仍有 remaining mass 的最近 targeted episode + 批量编码。

## Open Questions / 待 Owner 追认

- 是否在 v2 放一条严格连续门控的闭环试水：默认**不放，留 v3**（Codex 同意 observation-only 先行）。
- 常量取值：`_EVIDENCE_MAXLEN`、`_ATTRIB_CANDIDATE_MAXLEN`、`_ATTRIB_TAU`(=240)、`_ADJACENCY_TAU_CANDIDATES`、
  `_NO_MATCH_PRIOR`、`_PROCESSED_EVENT_MAXLEN`。
- recency 沿用 v1：timestamp 主基准，tick 审计；adjacency 用 candidate_distance（timestamp 倒序序号，与 recency 互补）。

## 评审

- 本 SPEC（修订版）回 Codex 复核确认 7 条已并入。
- 实现交付后补 `THREADS.md` / `VALIDATION.md`（单测 + 在线归属命中率/落点/误归属/幂等统计）。
