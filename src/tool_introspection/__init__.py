"""
tool_introspection — XIA 的工具自省层

让她能够：
    - 意识到自己当前有哪些工具（工具自省）
    - 发现能力缺口（能力缺口检测）
    - 理解失败背后的真实意图（意图提取）

设计原则：
    - 连续信号，无 if-else 硬阈值
    - 缓存防止重复计算（TTL=60s）
    - 完全独立于 LLM，纯规则驱动
"""

from .registry_watcher import RegistryWatcher, get_registry_watcher
from .capability_gap_detector import CapabilityGapDetector, get_gap_detector
from .intent_analyzer import IntentCapture, IntentAnalyzer, get_intent_analyzer

__all__ = [
    "RegistryWatcher",
    "get_registry_watcher",
    "CapabilityGapDetector",
    "get_gap_detector",
    "IntentCapture",
    "IntentAnalyzer",
    "get_intent_analyzer",
]
