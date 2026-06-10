# Codex 独立评审记录

## Round 1（SPEC 评审）：Revise before implementation

Codex 对 record-only v1 SPEC 给出 6 条修订要求，全部并入修订版 SPEC：

1. **recency 改 timestamp 主基准**（不用 tick 主基准）。tick 保留审计/测试。
   `_RECENCY_TAU_SECONDS = 240.0`（= 8 tick × 30s）。`age = max(0.0, now - episode.timestamp)`。
   → 已并入 Scope §1 + Open Questions（recency 基准已定）。

2. **v1 删除独立 pending deque**，只保留 history deque；提供 `recent_records(now)` 按 recency
   派生的只读视图；pending 等 v2 定义回答归属与消费语义后再引入。
   → 已并入 Non-Goals + Scope §1。

3. **运行时对象与持久化镜像同步**：`entity._clarification_memory`（运行时对象）/
   `entity._clarification_memory_data`（JSON 镜像）/ `_get_memory(entity)` 懒恢复 /
   每次 record 后立即写回 `memory.to_dict()`。
   → 已并入 Scope §4（镜像 `_cxg_data` 接法）。

4. **s06c 当前 397 行**：新逻辑封装进 `maybe_record_displayed_clarification(...)`，s06c 只留一次
   短调用，保持 ≤400 行。
   → 已并入 Constraints + Scope §3。

5. **修正模板顺序**：`PATTERNS + runtime_templates + uncertainty_patterns + CxG candidates`
   （Claude 复核 s06c line 190/195/212 确认无误——原 SPEC 漏了 runtime_templates）。helper 必须拿
   本次 compose 用的同一份模板列表快照，metadata 查，禁索引算术推导 slot。
   → 已并入 Background（真实顺序）+ Scope §3 + 风险 2。

6. **inspection 增加**：generic/targeted 比例、actor/patient/predicate 分布、对应 slot_confidence 与
   slot_relevance 分布、recency 视图、record 后镜像同步 + entity_state 落盘恢复测试。
   → 已并入 Scope §5。

**Codex 同时确认**：四个原始记录闸 guard 概念通过；parse_svo 风险在 record-only 阶段**只忠实记录即可，
不要提前加行为护栏**（已并入 Non-Goals + 风险 1）。

## 状态

修订版 SPEC 待 Codex 复核确认 6 条已正确并入 → 通过后进入实现。
