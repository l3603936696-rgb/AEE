# observe-reply v2 实现结果

## 回填说明

本文件为实现完成后的事实回填。Cursor 完成主体，Claude Code 与 Codex 继续收尾、
修复和验证。v2 保持 observation-only，不把证据回流到读句子、驱动力或世界模型。

## 交付文件

- 新建 `src/language_system/clarification_learning.py`
  - `observe_reply()`、稳定 episode ID、批量 BGE、软弃权归属、幂等。
- 新建 `src/language_system/clarification_evidence.py`
  - frozen `SlotEvidence`、`GenericObservation`、持久化 `SlotEvidenceStore`。
- 修改 `src/entity_state.py`
  - 持久化 `_clarification_hints_data`。
- 修改 `src/daemon/daemon.py`
  - IPC chat 与 `consume_response` 并列调用 `observe_reply()`。
- 修改 `src/daemon/tick_engine.py`
  - 仅 external 输入接 `observe_reply()`，sibling 忽略。
- 新建 `tests/test_clarification_learning.py`
- 新建 `tests/test_clarification_attribution.py`
- 新建 `scripts/diagnostics/clarification_learning_inspection.py`

## 收尾修复

- evidence append 不再提前 mark processed，避免一轮多候选只落第一条。
- processed event 在整轮候选落盘后统一标记。
- answered mass prune 使用完整 v1 history，不误删候选上限之外的旧进度。
- episode ID 使用完整 timestamp 表示，避免亚毫秒碰撞。
- Risk-1：外部槽置信度按具体指称落地度计算；命名实体高置信，裸代词和占位词低置信。
- 槽位追问局部缺口不再乘全局陌生度。
- inspection 场景替换 v1 镜像时同步清空运行时缓存，避免 synthetic 串场。

## 状态

v2 已上线运行，但 v3 暂不放行。在线探针显示命名主语修复生效；悬空代词仍偏向
generic 澄清，需先积累真实分布并讨论参数语义。
