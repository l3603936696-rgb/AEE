"""
intent_analyzer — 意图提取器

从失败记录和世界模型规则中提取：
    - 她当时真正想做什么（intended_action）
    - 缺失的能力类型（missing_capability）
    - 意图置信度（confidence）

设计原则：
    - 意图不是硬编码的，而是从失败经验中归纳
    - 连续置信度，不设 if-else 阈值
    - 兼容旧版 FailureRecord（不破坏现有系统）
"""

from dataclasses import dataclass, field
from typing import Optional
import logging

logger = logging.getLogger(__name__)


@dataclass
class IntentCapture:
    """
    意图捕获结果。

    她从失败中学到的"我想做什么"。
    """
    intended_action: str      # 她想做的动作描述
    missing_capability: str   # 她推断自己缺失的能力类型
    confidence: float         # 推断置信度 [0, 1]
    context: dict = field(default_factory=dict)  # 原始上下文

    def to_dict(self) -> dict:
        return {
            "intended_action": self.intended_action,
            "missing_capability": self.missing_capability,
            "confidence": self.confidence,
            "context": self.context,
        }


# ============================================================================
# 错误类型 → 能力类型映射
# ============================================================================
#
# 从失败类型推断缺失的能力维度。
# 这是经验性的归纳，不是逻辑定义。

ERROR_CAPABILITY_MAP: dict[str, str] = {
    "ModuleNotFoundError": "code_execution",      # 缺少某个库的能力
    "ConnectionError": "network_access",          # 缺少网络访问能力
    "Timeout": "network_access",                  # 网络慢/不稳定
    "PermissionDenied": "permission_handling",     # 缺少权限处理能力
    "NotFound": "resource_locating",              # 缺少资源定位能力
    "SyntaxError": "code_correctness",            # 缺少代码正确性检查能力
    "DependencyError": "dependency_resolution",     # 缺少依赖解析能力
    "Unknown": "debugging",                        # 一般性调试能力
}

# 工具名 → 能力类型映射（她用某工具失败 → 缺的是该工具代表的能力）
TOOL_CAPABILITY_MAP: dict[str, str] = {
    "file_read": "file_manipulation",
    "file_write": "file_manipulation",
    "file_list": "file_manipulation",
    "file_delete": "file_manipulation",
    "shell_run": "code_execution",
    "shell_bg_run": "code_execution",
    "browser_open": "web_access",
    "browser_screenshot": "web_capture",
    "browser_click": "web_interaction",
    "browser_fill": "web_interaction",
    "browser_get_text": "web_capture",
    "browser_navigate": "web_navigation",
    "web_search": "information_search",
    "ask_hermes": "mentor_guidance",
}


# ============================================================================
# 意图推断规则库
# ============================================================================
#
# 格式：(关键词 pattern, 推断意图, 推断能力, 置信度加成)
# 匹配时按顺序，第一个匹配为准。

INTENT_RULES: list[tuple[str, str, str, float]] = [
    # ---- 网络类失败 ----
    ("搜索", "搜索信息", "information_search", 0.9),
    ("网上", "访问网络资源", "web_access", 0.8),
    ("网站", "浏览网页", "web_access", 0.8),
    ("http", "发送网络请求", "api_call", 0.85),
    ("请求", "发送网络请求", "api_call", 0.85),
    ("连接", "建立网络连接", "network_access", 0.9),
    ("超时", "执行长时间任务", "task_persistence", 0.7),

    # ---- 代码类失败 ----
    ("python", "运行Python代码", "code_execution", 0.9),
    ("pip", "安装Python依赖", "dependency_resolution", 0.9),
    ("import", "导入模块", "code_correctness", 0.8),
    ("编译", "编译代码", "code_execution", 0.8),
    ("语法", "修正语法错误", "code_correctness", 0.9),
    ("git", "使用版本控制", "version_control", 0.85),
    ("命令", "执行系统命令", "code_execution", 0.8),

    # ---- 文件类失败 ----
    ("文件", "操作文件", "file_manipulation", 0.9),
    ("目录", "查看目录结构", "file_manipulation", 0.8),
    ("权限", "处理权限问题", "permission_handling", 0.9),
    ("找不到", "定位资源", "resource_locating", 0.8),

    # ---- 调试类失败 ----
    ("错误", "修复错误", "debugging", 0.8),
    ("失败", "处理失败情况", "debugging", 0.7),
    ("报错", "分析错误信息", "debugging", 0.85),
]


class IntentAnalyzer:
    """
    意图提取器。

    从失败记录和上下文推断：
        1. 她当时想做什么（intended_action）
        2. 缺失什么能力（missing_capability）
        3. 推断的置信度（confidence）

    使用方式：
        analyzer = IntentAnalyzer()
        capture = analyzer.extract_from_failure(failure_record, wm_context)
    """

    def extract_from_failure(
        self,
        failure_record,
        wm_context: Optional[dict] = None,
    ) -> IntentCapture:
        """
        从失败记录提取意图。

        参数：
            failure_record : FailureRecord 实例或 dict
            wm_context    : 世界模型上下文（可选，用于经验匹配）

        返回：
            IntentCapture — 推断的意图和能力缺口
        """
        if isinstance(failure_record, dict):
            tool_name = failure_record.get("tool_name", "")
            error_type = failure_record.get("error_type", "Unknown")
            error_message = failure_record.get("error_message", "")
            command = failure_record.get("command_or_input", "")
        else:
            tool_name = getattr(failure_record, "tool_name", "")
            error_type = getattr(failure_record, "error_type", "Unknown")
            error_message = getattr(failure_record, "error_message", "")
            command = getattr(failure_record, "command_or_input", "")

        # 合并错误消息和命令作为分析文本
        text = f"{error_message} {command}".strip()
        wm_context = wm_context or {}

        # ---- 推断意图和能力缺口 ----
        intended_action, cap_confidence = self._infer_intent(text, tool_name, error_type)
        missing_capability = self._infer_capability(error_type, tool_name, text)

        # ---- 用 WM 经验修正置信度 ----
        experience_bonus = self._wm_experience_bonus(wm_context, missing_capability, intended_action)
        final_confidence = min(1.0, cap_confidence + experience_bonus)

        return IntentCapture(
            intended_action=intended_action,
            missing_capability=missing_capability,
            confidence=final_confidence,
            context={
                "tool_name": tool_name,
                "error_type": error_type,
                "error_message": error_message,
                "command": command,
            },
        )

    def _infer_intent(
        self,
        text: str,
        tool_name: str,
        error_type: str,
    ) -> tuple[str, float]:
        """
        从文本推断她想做什么。

        返回：(意图描述, 置信度)
        """
        text_lower = text.lower()

        # 优先：规则匹配
        for pattern, intent, capability, base_conf in INTENT_RULES:
            if pattern.lower() in text_lower:
                return intent, base_conf

        # 次优：工具推断
        if tool_name:
            tool_intent_map: dict[str, str] = {
                "shell_run": "执行系统命令",
                "shell_bg_run": "执行长时间后台任务",
                "web_search": "搜索网络信息",
                "browser_open": "打开网页浏览",
                "file_write": "写入文件保存内容",
                "file_read": "读取文件内容",
                "ask_hermes": "请教导师解决问题",
            }
            if tool_name in tool_intent_map:
                return tool_intent_map[tool_name], 0.75

        # 兜底：错误类型推断
        error_intent_map: dict[str, str] = {
            "ModuleNotFoundError": "导入并使用Python库",
            "ConnectionError": "建立网络连接",
            "Timeout": "执行需要较长时间的操作",
            "PermissionDenied": "执行需要权限的操作",
            "NotFound": "定位并访问某个资源",
            "SyntaxError": "编写正确语法的代码",
            "DependencyError": "安装缺失的依赖",
            "Unknown": "完成某个操作",
        }
        fallback_intent = error_intent_map.get(error_type, "完成某个操作")
        return fallback_intent, 0.4

    def _infer_capability(
        self,
        error_type: str,
        tool_name: str,
        text: str,
    ) -> str:
        """
        推断缺失的能力类型。

        优先级：工具能力 > 错误类型 > 文本关键词
        """
        # 工具能力
        if tool_name and tool_name in TOOL_CAPABILITY_MAP:
            return TOOL_CAPABILITY_MAP[tool_name]

        # 错误类型
        if error_type in ERROR_CAPABILITY_MAP:
            return ERROR_CAPABILITY_MAP[error_type]

        # 文本关键词
        text_lower = text.lower()
        keyword_cap_map = [
            ("python", "code_execution"),
            ("network", "network_access"),
            ("http", "api_call"),
            ("file", "file_manipulation"),
            ("permission", "permission_handling"),
            ("install", "dependency_resolution"),
            ("search", "information_search"),
        ]
        for keyword, cap in keyword_cap_map:
            if keyword in text_lower:
                return cap

        return "debugging"  # 默认：调试能力

    def _wm_experience_bonus(
        self,
        wm_context: dict,
        capability: str,
        intended_action: str,
    ) -> float:
        """
        用世界模型经验修正置信度。

        逻辑：
            如果 WM 中有类似意图的成功经验 → 置信度提升
            如果 WM 中有类似意图的失败经验 → 置信度降低
        """
        if not wm_context:
            return 0.0

        bonus = 0.0
        matched_rules = wm_context.get("matched_rules", [])
        if not matched_rules:
            return 0.0

        for rule in matched_rules:
            content = str(rule.get("content", "")).lower()
            # 匹配相同意图
            if intended_action[:5].lower() in content:
                conf = float(rule.get("confidence", 0.5))
                # 高置信经验 → 正向奖励
                if conf >= 0.7:
                    bonus += 0.1
                else:
                    bonus -= 0.05

        return max(-0.2, min(0.2, bonus))


# ============================================================================
# 单例访问
# ============================================================================

_analyzer_instance: Optional[IntentAnalyzer] = None


def get_intent_analyzer() -> IntentAnalyzer:
    global _analyzer_instance
    if _analyzer_instance is None:
        _analyzer_instance = IntentAnalyzer()
    return _analyzer_instance
