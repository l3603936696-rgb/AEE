"""
ToolSelfCheck — 主动自检模块（决策系统 Module 10）

在 think 阶段主动自省："我现在有这个能力吗？"

工作方式：
    - 检查 thought_packet["suggestions"] 中的 action
    - 调用 capability_gap_detector 检测缺口
    - 缺口大 → 增加 curiosity 和 unresolved，让她更想知道
    - 生成 self-reflection 问题供 think 阶段输出

这是主动预防机制（对应被动触发是 executor 的 _trigger_capability_gap_analysis）。
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


class ToolSelfCheck:
    """
    主动自检模块。

    在 perceive() 中：
        1. 检查当前 thought_packet 的 suggestions
        2. 如果 suggestion 需要工具 → 检测能力缺口
        3. 缺口强度 > 阈值 → 增加 curiosity / unresolved
        4. 将 tool_capability 问题注入 thought_packet["questions"]

    影响的 entity 状态：
        - curiosity         ↑ （她想知道）
        - unresolved       ↑ （感到压力）
        - somatic_tone     ↓ （轻微不适）
    """

    def perceive(self, inputs: dict, entity_core: Any) -> None:
        """
        主感知函数。

        参数：
            inputs     : 包含 thought_packet, state_snapshot, params 等
            entity_core: EntityCore 或 EntityState 实例
        """
        try:
            thought_packet = inputs.get("thought_packet", {})
            suggestions = thought_packet.get("suggestions", [])
            if not suggestions:
                return

            state_snapshot = inputs.get("state_snapshot", {})
            params = inputs.get("params", {})

            # 获取能量水平（能量太低时不自省）
            energy = float(state_snapshot.get("energy", 0.5))
            if energy < 0.15:
                return

            # 加载能力缺口检测器
            try:
                from ...tool_introspection import get_gap_detector
                gap_detector = get_gap_detector()
            except Exception:
                return

            # 获取当前 unresolved 水平（用于缺口放大）
            unresolved = float(getattr(entity_core, "unresolved", 0.3))

            # 检查每个 suggestion 的工具可用性
            total_gap_signal = 0.0
            high_gap_actions = []

            for sugg in suggestions:
                action = sugg.get("action", "")
                priority = float(sugg.get("priority", 0.0))

                if not action:
                    continue

                # 从 action 推断意图
                inferred_intent = self._infer_intent_from_action(action)
                if not inferred_intent:
                    continue

                # 检测缺口
                gap = gap_detector.detect_gap(
                    intent=inferred_intent,
                    context={"action": action, "priority": priority},
                    unresolved_intensity=unresolved,
                )

                if gap.gap_intensity > 0.15:
                    total_gap_signal += gap.gap_intensity * priority
                    high_gap_actions.append({
                        "action": action,
                        "gap": gap.gap_intensity,
                        "intent": inferred_intent,
                        "matched_tools": gap.matched_tools,
                        "missing_caps": gap.unmatched_aspects,
                    })

            # 根据总缺口信号调整实体状态
            if total_gap_signal > 0:
                self._apply_gap_drive(entity_core, total_gap_signal, high_gap_actions)

        except Exception as e:
            logger.debug(f"[ToolSelfCheck] perceive error: {e}")

    def _infer_intent_from_action(self, action: str) -> str:
        """从 action 类型推断她想做什么（用于匹配工具）"""
        intent_map: dict[str, str] = {
            "explore": "探索新领域，搜索相关信息",
            "seek": "寻找信息，理解当前情况",
            "repair": "修复问题，调试代码",
            "comfort": "社交连接，与人交流",
            "rest": "休息恢复精力",
            "avoid": "回避危险",
        }
        return intent_map.get(action, action)

    def _apply_gap_drive(
        self,
        entity_core: Any,
        total_gap_signal: float,
        high_gap_actions: list,
    ) -> None:
        """
        将缺口信号注入驱动力。

        设计原则：
            - 缺口驱动是连续累加的（不是二值开关）
            - curiosity 和 unresolved 的提升比例不同（好奇心 vs 压力）
            - 高优先级 action 的缺口权重更高
        """
        # 平滑到 [0, 1] 范围，防止过度放大
        norm_signal = min(1.0, total_gap_signal * 0.5)

        if norm_signal <= 0:
            return

        # curiosity ↑（她想知道缺口是什么）
        # 强度正比于缺口大小
        entity_core.adjust("curiosity", norm_signal * 0.04)

        # unresolved ↑（她感到自己"不能做"的压迫）
        entity_core.adjust("unresolved", norm_signal * 0.03)

        # somatic_tone 轻微负向（发现能力缺口会带来轻微不适）
        current_tone = float(getattr(entity_core, "somatic_tone", 0.0))
        tone_delta = -norm_signal * 0.02 * max(0.0, 1.0 - abs(current_tone))
        entity_core.adjust("somatic_tone", tone_delta)

        logger.debug(
            f"[ToolSelfCheck] Gap signal={norm_signal:.3f} "
            f"from {len(high_gap_actions)} actions: "
            f"{[a['action'] for a in high_gap_actions[:3]]}"
        )
