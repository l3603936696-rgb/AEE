"""
capability_gap_detector — 能力缺口检测器

被动触发：每次工具执行失败后调用 detect_gap()
主动自省：think 阶段由 decision_system 模块调用

设计原则：
    - 缺口强度是连续的 [0, 1]，不设硬阈值门
    - 缓存机制防止重复计算（TTL=60s）
    - 缺口信号同时触发 curiosity 和 unresolved（让她既想知道，也感到压力）
"""

from dataclasses import dataclass, field
from typing import Optional
import time
import logging

logger = logging.getLogger(__name__)


@dataclass
class GapSignal:
    """能力缺口信号"""
    intent: str                          # 她想做什么
    gap_intensity: float                 # 缺口强度 [0, 1]
    matched_tools: list[str]             # 已匹配到的工具
    unmatched_aspects: list[str]         # 未匹配到的方面
    capability_types: list[str]          # 推断的能力类型
    confidence: float                   # 推断置信度
    timestamp: float = field(default_factory=time.time)
    ttl: int = 60                        # 缓存生存期（秒）

    def is_expired(self) -> bool:
        return (time.time() - self.timestamp) > self.ttl

    def to_dict(self) -> dict:
        return {
            "intent": self.intent,
            "gap_intensity": self.gap_intensity,
            "matched_tools": self.matched_tools,
            "unmatched_aspects": self.unmatched_aspects,
            "capability_types": self.capability_types,
            "confidence": self.confidence,
            "timestamp": self.timestamp,
        }


class CapabilityGapDetector:
    """
    能力缺口检测器。

    工作模式：
        1. 被动触发：工具执行失败后，接收 intent + error
           → 检测是否真的缺工具，还是工具用错了

        2. 主动自省：decision_system 的 ToolSelfCheck 模块调用
           → 在 think 阶段检查"我有没有这个能力"

    核心信号：
        gap_intensity ∈ [0, 1]
            0.0 — 完全匹配到工具，无缺口
            0.1-0.3 — 有模糊工具但不精确
            0.4-0.6 — 工具存在但能力不足
            0.7-1.0 — 完全缺少该能力

    缺口强度公式：
        gap = (1 - best_match_confidence) × intent_confidence × unresolved_weight

    缺口信号输出到：
        → tool_need_queue（被动触发）
        → entity.curiosity / entity.unresolved（主动自省）
        → thinking_system 的 tool_capability 问题
    """

    def __init__(self):
        self._gap_cache: dict[str, GapSignal] = {}
        self._cache_ttl: int = 60  # 秒

    def _cache_key(self, intent: str) -> str:
        """生成缓存 key（取前 100 字符做截断）"""
        return intent[:100].lower().strip()

    def _clean_cache(self) -> None:
        """清理过期缓存"""
        expired = [k for k, sig in self._gap_cache.items() if sig.is_expired()]
        for k in expired:
            del self._gap_cache[k]
        if expired:
            logger.debug(f"[GapDetector] Cleaned {len(expired)} expired cache entries")

    def detect_gap(
        self,
        intent: str,
        context: Optional[dict] = None,
        unresolved_intensity: float = 0.5,
        force_refresh: bool = False,
    ) -> GapSignal:
        """
        检测给定意图的能力缺口。

        参数：
            intent               : 她想做什么（自然语言描述）
            context              : 额外上下文（error_type, action_type, tool_used 等）
            unresolved_intensity : 当前 unresolved 水平 [0, 1]，影响缺口放大
            force_refresh        : 强制刷新缓存

        返回：
            GapSignal — 包含缺口强度和匹配结果

        算法：
            1. 查缓存（有且未过期则直接返回）
            2. 调用 RegistryWatcher.match_tool() 找最匹配工具
            3. 计算缺口强度
            4. 推断未匹配方面和能力类型
            5. 写入缓存
        """
        if not intent:
            return GapSignal(
                intent="",
                gap_intensity=0.0,
                matched_tools=[],
                unmatched_aspects=[],
                capability_types=[],
                confidence=0.0,
            )

        context = context or {}
        cache_key = self._cache_key(intent)
        self._clean_cache()

        # 缓存命中
        if not force_refresh and cache_key in self._gap_cache:
            cached = self._gap_cache[cache_key]
            if not cached.is_expired():
                logger.debug(f"[GapDetector] Cache hit for intent='{intent[:50]}'")
                return cached

        # ---- 核心检测逻辑 ----
        from .registry_watcher import get_registry_watcher

        watcher = get_registry_watcher()
        matches = watcher.match_tool(intent, context)
        cap_types = watcher.suggest_capability_type(intent)

        # 最佳匹配分数
        best_conf = max((m.confidence for m in matches), default=0.0)

        # 匹配到的工具名列表
        matched_tool_names = [m.tool_name for m in matches if m.confidence > 0.1]

        # 未匹配到的能力类型
        matched_caps = set()
        for cap in cap_types:
            tools_for_cap = watcher.find_tools_for_capability(cap)
            if any(t in {m.tool_name for m in matches} for t in tools_for_cap):
                matched_caps.add(cap)

        unmatched_caps = [c for c in cap_types if c not in matched_caps]

        # 如果没有匹配到工具且没有推断到能力类型，
        # 用 context 中的 error_type 推断一个兜底
        if not matched_tool_names and not unmatched_caps:
            error_type = context.get("error_type", "") if context else ""
            if error_type:
                fallback_map = {
                    "ModuleNotFoundError": "code_execution",
                    "ConnectionError": "network_access",
                    "Timeout": "task_persistence",
                    "PermissionDenied": "permission_handling",
                    "NotFound": "resource_locating",
                    "SyntaxError": "code_correctness",
                    "DependencyError": "dependency_resolution",
                }
                fallback_cap = fallback_map.get(error_type, "debugging")
                unmatched_caps = [fallback_cap]

        # 缺口强度 = (1 - 最佳匹配) × 意图置信 × unresolved 放大
        intent_confidence = 1.0 - (best_conf * 0.5)
        gap_intensity = (1.0 - best_conf) * intent_confidence * (0.5 + unresolved_intensity * 0.5)

        signal = GapSignal(
            intent=intent,
            gap_intensity=min(1.0, max(0.0, gap_intensity)),
            matched_tools=matched_tool_names,
            unmatched_aspects=unmatched_caps,
            capability_types=cap_types,
            confidence=best_conf,
            timestamp=time.time(),
        )

        self._gap_cache[cache_key] = signal
        logger.debug(
            f"[GapDetector] intent='{intent[:60]}' gap={gap_intensity:.3f} "
            f"best_match={best_conf:.3f} matched={matched_tool_names}"
        )

        return signal

    def detect_gap_from_failure(
        self,
        failure_record,
        unresolved_intensity: float = 0.5,
    ) -> GapSignal:
        """
        从失败记录检测能力缺口（被动触发入口）。

        参数：
            failure_record       : FailureRecord 实例
            unresolved_intensity : 当前 unresolved 水平

        逻辑：
            从 failure_record 提取：
                - error_type → 推断缺失能力
                - intended_action → 作为 intent
                - error_message → 作为 context
        """
        if not hasattr(failure_record, "intended_action") and not hasattr(failure_record, "error_type"):
            # 兼容旧版 FailureRecord
            intent = getattr(failure_record, "tool_name", "未知操作")
            error_type = getattr(failure_record, "error_type", "")
        else:
            intent = getattr(failure_record, "intended_action", "")
            error_type = getattr(failure_record, "error_type", "")

        if not intent:
            intent = f"使用 {getattr(failure_record, 'tool_name', '某工具')}"

        context = {
            "error_type": error_type,
            "error_message": getattr(failure_record, "error_message", ""),
            "command": getattr(failure_record, "command_or_input", ""),
            "trigger": "failure",
        }

        return self.detect_gap(intent, context, unresolved_intensity)

    def get_gap_for_thinking(
        self,
        thought_suggestions: list[dict],
        entity_core,
    ) -> list[GapSignal]:
        """
        主动自省：为 think 阶段的建议生成缺口信号。

        参数：
            thought_suggestions : think() 返回的 suggestions 列表
            entity_core         : 当前实体状态

        返回：
            为每个建议生成的 GapSignal 列表

        逻辑：
            对每个 suggestion.action，检查是否有对应工具
            无工具的建议 → 生成高强度缺口
        """
        signals: list[GapSignal] = []
        unresolved = getattr(entity_core, "unresolved", 0.5)

        for sugg in thought_suggestions:
            action = sugg.get("action", "")
            if not action:
                continue

            # 推断该 action 所需工具
            inferred_intent = self._infer_intent_from_action(action)
            if inferred_intent:
                gap = self.detect_gap(inferred_intent, context={"action": action}, unresolved_intensity=unresolved)
                if gap.gap_intensity > 0.2:
                    signals.append(gap)

        return signals

    def _infer_intent_from_action(self, action: str) -> str:
        """从 action 类型推断她想做什么（用于匹配工具）"""
        intent_map: dict[str, str] = {
            "explore": "探索新领域，查找相关信息",
            "seek": "寻找信息，理解当前情况",
            "repair": "修复问题，调试代码",
            "comfort": "社交连接，与人交流",
            "rest": "休息，恢复精力",
            "avoid": "回避危险，保护自己",
        }
        return intent_map.get(action, action)

    def get_pending_gaps(self, min_gap: float = 0.3) -> list[GapSignal]:
        """返回所有未解决的高强度缺口（供 LLM 合成器使用）"""
        self._clean_cache()
        return [sig for sig in self._gap_cache.values() if sig.gap_intensity >= min_gap]


# ============================================================================
# 单例访问
# ============================================================================

_detector_instance: Optional[CapabilityGapDetector] = None


def get_gap_detector() -> CapabilityGapDetector:
    global _detector_instance
    if _detector_instance is None:
        _detector_instance = CapabilityGapDetector()
    return _detector_instance
