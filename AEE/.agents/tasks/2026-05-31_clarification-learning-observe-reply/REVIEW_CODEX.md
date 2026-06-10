# Codex 独立评审记录

## Round 1（SPEC 评审）：Revise before implementation

方向确认：v2/v3 拆分正确，observation-only 先行、不提前闭环。7 条结构问题全部并入修订版 SPEC：

| # | 级 | 问题 | 处置 |
|---|---|---|---|
| P1-a | P1 | 连续归属与布尔 answered 冲突（弱相关也标 answered 会烧真回答机会；"不够强不标"又偷引硬阈值）| `answered_mass: dict[eid,float]∈[0,1]`，`remaining=1-mass`，`new=1-(1-old)(1-attributed)`；候选分 ×remaining。→ Scope §1.2 |
| P1-b | P1 | "显著候选"未定义；无 abstain 会强行把无关回答分给某条 | 加 `_NO_MATCH_PRIOR` 软弃权候选，输出每条 attributed_mass + no_match_mass，不丢弱证据。→ §1.3 |
| P1-c | P1 | answer_familiarity 不应压低归属（回答常是她不懂的新词，越该学熟悉度越低）| familiarity 移出核心乘数、仅审计；归属=remaining×recency×relevance×adjacency vs no_match。→ §1.3 |
| P2-a | P2 | episode 身份只用 timestamp 会碰撞 | 稳定 `episode_id`=SHA-256(canonical: ts+tick+input+question+kind+slot)；证据保存 episode_id。→ §1.1 |
| P2-b | P2 | 接线范围未写清（IPC chat vs reach/sibling）| v2 只接 ipc_chat/external，**不把 sibling/糯糯当 Owner 回答**；`observe_reply(...,source,reply_event_id)` 幂等。→ §1.5/§3 |
| P2-c | P2 | observation 阶段不可逆合并线索 | `SlotEvidence` frozen 逐条追加；`aggregate()` 只读派生；原始证据可查。→ §1.4 |
| P2-d | P2 | 最坏对 200 条 history 逐条 BGE | `_ATTRIB_CANDIDATE_MAXLEN` 只评最近仍有 remaining 的 targeted；批量编码。→ §1.3 |

**新增因子**：`adjacency = exp(-turns_since/_ADJACENCY_TAU_TURNS)`（对话轮距，与 recency 互补，Codex P1-c 建议）。

**inspection（v3 放行前必须输出，已并入 §4）**：expected→asked→bound 混淆矩阵；每条证据全字段；
无关换话题误归属总质量；新名字/短碎片保留率；弱回答后 remaining 是否保留；重启恢复 + 重复事件幂等；
synthetic 与在线分开统计。

**Codex 确认**：Risk 1 防线够用——v2 只做证据账本，允许脏线索被**观察**但不回流。修订并入后可进入实现。

## Round 2（SPEC 复核）：Revise before implementation（方向仍正确，5 条细化）

| # | 级 | 问题 | 处置 |
|---|---|---|---|
| R2-1 | P1 | generic 不能只"不产证据"——最新若是 generic，回答会被旧 targeted 抢走 | generic **参与归属竞争、吸收 mass、更新 answered_mass**，但不产 SlotEvidence、只计 generic_observation。→ §1.3/§1.4 |
| R2-adjacency | P1 | adjacency 的 `turns_since` 无数据源（v1 episode 无轮次字段）| 改 `candidate_distance`（timestamp 倒序序号，最新=0）；`adjacency=exp(-dist/_ADJACENCY_TAU_CANDIDATES)`，不动 v1。→ §1.3 |
| R2-external | P1 | external 实际调用漏写 | daemon.py source=ipc_chat/event=request.id；tick_engine 仅 `_input_source=="external"` 调、event=SHA-256(source+ts+input)；sibling 忽略。→ §3 |
| R2-idem | P2 | processed_event_ids 无限增长；answered_mass 残留已驱逐 episode | `_PROCESSED_EVENT_MAXLEN` 有序 deque；同步时 answered_mass 只保留当前 v1 history 的 episode_id。→ §1.4/§2 |
| R2-batch | P2 | "批量 BGE" 与逐对 `_similarity` 矛盾 | 新建 `_batch_similarity(reply,cues)` 一次编码 `[reply,*cues]`，回退 `_char_overlap`，不新增模型。→ §1.3 |
| R2-scope | — | aggregate "按相似度聚合" 仍模糊 | v2 收窄为只读 `effective_strength=attributed_mass×recency` + 基础统计；相似检索聚合留 v3。→ §1.4 |

## 状态

修订版 SPEC（含 Round 1 七条 + Round 2 五条）待 Codex 复核 → 通过后进入实现。
