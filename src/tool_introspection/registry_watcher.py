"""
registry_watcher — 工具注册表自省器

维护 XIA 当前可用工具的影子索引，支持：
    - has_tool(intent) → 连续匹配强度 [0, 1]
    - match_tool(intent, context) → 排序后的 [(tool_name, confidence), ...]
    - 监听 TOOL_DEFINITIONS 变化，自动同步

核心思想：XIA 需要知道"自己能做什么"，才能知道自己"不能做什么"。
"""

from dataclasses import dataclass, field
from typing import Optional
import logging

logger = logging.getLogger(__name__)


# ============================================================================
# 工具能力指纹库
# ============================================================================
#
# 每个工具的指纹定义了它能处理的"能力关键词"。
# 用于意图匹配——给定一个未知意图，判断哪个工具能处理。
#
# 格式：tool_name → list of (keyword, weight)
# weight 表示该关键词对工具能力的贡献强度 [0.1, 1.0]

TOOL_FINGERPRINTS: dict[str, list[tuple[str, float]]] = {
    # ---- 文件系统 ----
    "file_read": [
        ("读", 0.9), ("查看", 0.8), ("打开", 0.7), ("内容", 0.6),
        ("文件", 0.8), ("目录", 0.5), ("查看代码", 0.8), ("检查", 0.6),
    ],
    "file_write": [
        ("写", 0.9), ("创建", 0.8), ("保存", 0.8), ("修改", 0.7),
        ("文件", 0.8), ("记录", 0.6), ("输出", 0.6), ("生成", 0.5),
    ],
    "file_list": [
        ("列出", 0.9), ("列表", 0.8), ("查看目录", 0.8), ("有哪些", 0.7),
        ("目录", 0.8), ("文件", 0.7), ("搜索文件", 0.6),
    ],
    "file_delete": [
        ("删除", 0.9), ("移除", 0.8), ("清空", 0.7), ("销毁", 0.6),
    ],
    # ---- Shell ----
    "shell_run": [
        ("运行", 0.9), ("执行", 0.9), ("命令", 0.8), ("终端", 0.7),
        ("安装", 0.6), ("编译", 0.7), ("脚本", 0.6), ("系统", 0.5),
        ("python", 0.7), ("git", 0.6), ("curl", 0.7),
    ],
    "shell_bg_run": [
        ("后台", 0.9), ("异步", 0.7), ("长时间", 0.8), ("启动服务", 0.8),
        ("守护进程", 0.7), ("持续运行", 0.8),
    ],
    # ---- 浏览器 ----
    "browser_open": [
        ("打开网页", 0.9), ("访问", 0.8), ("浏览", 0.7), ("网站", 0.8),
        ("网址", 0.8), ("页面", 0.6),
    ],
    "browser_screenshot": [
        ("截图", 0.9), ("截屏", 0.9), ("屏幕截图", 0.9), ("保存页面", 0.6),
    ],
    "browser_click": [
        ("点击", 0.9), ("按钮", 0.8), ("交互", 0.7), ("操作网页", 0.7),
    ],
    "browser_fill": [
        ("填写", 0.9), ("输入", 0.8), ("表单", 0.8), ("搜索框", 0.7),
    ],
    "browser_get_text": [
        ("获取文本", 0.9), ("提取文字", 0.8), ("读取页面", 0.7), ("内容", 0.5),
    ],
    "browser_navigate": [
        ("导航", 0.9), ("翻页", 0.7), ("前进后退", 0.8), ("切换", 0.6),
    ],
    # ---- 搜索 ----
    "web_search": [
        ("搜索", 0.9), ("查询", 0.8), ("查", 0.7), ("找", 0.6),
        ("网上", 0.7), ("信息", 0.5), ("了解", 0.5),
    ],
    # ---- Hermes ----
    "ask_hermes": [
        ("问", 0.8), ("请教", 0.9), ("导师", 0.8), ("求助", 0.8),
        ("建议", 0.6), ("帮助", 0.5), ("修复", 0.5),
    ],
}


# ============================================================================
# 能力类型 → 典型工具映射
# ============================================================================
#
# 用于从"缺失的能力类型"推断需要什么工具。
# 这是一种反向推理：给定能力缺口，找到可能填补它的工具。

CAPABILITY_TOOL_MAP: dict[str, list[str]] = {
    "web_access": ["browser_open", "web_search"],
    "file_manipulation": ["file_read", "file_write", "file_list"],
    "code_execution": ["shell_run", "shell_bg_run"],
    "information_search": ["web_search"],
    "mentor_guidance": ["ask_hermes"],
    "api_call": ["shell_run"],
    "data_processing": ["shell_run"],
    "code_editing": ["file_write", "file_read"],
    "debugging": ["ask_hermes", "shell_run"],
}


# ============================================================================
# 意图关键词库
# ============================================================================
#
# 高层意图关键词 → 所需能力类型
# 用于从用户意图或失败描述中提取"她想做什么"

INTENT_KEYWORDS: dict[str, list[str]] = {
    "web_access": ["浏览网页", "打开网站", "访问网址", "看网页", "网上", "查资料"],
    "file_manipulation": ["写文件", "读文件", "创建文件", "修改代码", "编辑"],
    "code_execution": ["运行", "执行", "跑", "编译", "python", "shell", "命令"],
    "information_search": ["搜索", "查询", "找信息", "网上找", "查一下"],
    "mentor_guidance": ["问导师", "请教", "求助", "不会", "不知道"],
    "api_call": ["调api", "调用接口", "发送请求", "http"],
    "data_processing": ["处理数据", "分析", "统计", "计算"],
    "code_editing": ["写代码", "改代码", "编辑代码"],
    "debugging": ["调试", "修bug", "报错", "错误", "失败"],
    "web_scraping": ["爬虫", "抓取", "网页内容", "解析html"],
}


@dataclass
class ToolMatch:
    """单个工具匹配结果"""
    tool_name: str
    confidence: float  # [0, 1]
    matched_keywords: list[str] = field(default_factory=list)


class RegistryWatcher:
    """
    工具注册表自省器。

    功能：
        1. 维护工具影子索引（从 TOOL_DEFINITIONS 构建）
        2. 判断"给定意图，能否用现有工具处理"
        3. 匹配最合适的工具列表（按 confidence 排序）

    使用方式：
        watcher = RegistryWatcher()
        matches = watcher.match_tool("我想搜索最近的AI新闻", {})
        # → [ToolMatch(tool_name="web_search", confidence=0.9, ...), ...]

        has_it = watcher.has_tool_for_intent("搜索AI")
        # → 0.9  （高分表示有工具）
    """

    def __init__(self):
        self._tool_names: set[str] = set()
        self._tool_descriptions: dict[str, str] = {}
        self._sync()

    def _sync(self) -> None:
        """同步工具列表（从 agent_tools.registry 导入）"""
        try:
            from ..action_system.agent_tools import registry as reg_module
            all_tools = reg_module.TOOL_DEFINITIONS
            self._tool_names = {d["function"]["name"] for d in all_tools}
            self._tool_descriptions = {
                d["function"]["name"]: d["function"].get("description", "")
                for d in all_tools
            }
            logger.debug(f"[RegistryWatcher] Synced {len(self._tool_names)} tools")
        except Exception as e:
            logger.warning(f"[RegistryWatcher] Sync failed: {e}, using fingerprints only")
            self._tool_names = set(TOOL_FINGERPRINTS.keys())
            self._tool_descriptions = {}

    def reload(self) -> None:
        """手动重新同步（热加载）"""
        self._sync()

    def list_tools(self) -> list[str]:
        """返回所有可用工具名"""
        if not self._tool_names:
            self._sync()
        return sorted(self._tool_names)

    def has_tool(self, tool_name: str) -> bool:
        """检查指定工具是否存在"""
        return tool_name in self._tool_names

    def has_tool_for_intent(self, intent: str, context: Optional[dict] = None) -> float:
        """
        判断意图是否能用现有工具处理。

        返回：[0, 1]
            0.0 = 完全无匹配工具
            0.1-0.3 = 模糊匹配（部分关键词命中）
            0.4-0.7 = 中等匹配
            0.8-1.0 = 高置信匹配

        逻辑：
            1. 计算所有工具对该意图的匹配分数
            2. 取最高分
            3. 缺口 = 1 - match_score
        """
        matches = self.match_tool(intent, context or {})
        if not matches:
            return 0.0
        return max(m.tool_name for m in matches)

    def match_tool(
        self,
        intent: str,
        context: Optional[dict] = None,
        top_k: int = 5,
    ) -> list[ToolMatch]:
        """
        匹配最合适的工具列表。

        参数：
            intent  : 意图描述（自然语言）
            context : 额外上下文（action_type, error_type 等）
            top_k   : 最多返回多少个匹配

        返回：
            按 confidence 降序排列的 ToolMatch 列表

        算法：
            对每个工具，计算其指纹关键词与意图的匹配强度：
                - 意图包含关键词 → 贡献 weight
                - 工具描述包含意图关键词 → 贡献 0.3 * weight
            最终 confidence = 归一化后的总权重
        """
        if not intent:
            return []

        intent_lower = intent.lower()
        intent_chars = set(intent_lower.replace(" ", ""))

        scores: dict[str, float] = {}
        matched_keywords_map: dict[str, list[str]] = {}

        for tool_name, fingerprints in TOOL_FINGERPRINTS.items():
            if tool_name not in self._tool_names:
                continue

            score = 0.0
            matched: list[str] = []

            for keyword, weight in fingerprints:
                kw_lower = keyword.lower()
                intent_lower_kw = kw_lower  # 已 lower
                # 精确匹配（包含关键词，大小写不敏感）
                if kw_lower in intent_lower:
                    score += weight
                    matched.append(keyword)
                else:
                    # 字符集重叠（宽松匹配，中文友好）
                    kw_chars = set(kw_lower.replace(" ", ""))
                    overlap = len(kw_chars & intent_chars) / max(len(kw_chars), 1)
                    if overlap > 0.6:
                        score += weight * overlap * 0.5
                        matched.append(f"{keyword}*")

            if score > 0:
                scores[tool_name] = score
                matched_keywords_map[tool_name] = matched

        if not scores:
            return []

        # 归一化到 [0, 1]
        max_score = max(scores.values()) if scores else 1.0
        results = []
        for tool_name, raw_score in sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]:
            confidence = min(1.0, raw_score / max_score)
            results.append(ToolMatch(
                tool_name=tool_name,
                confidence=confidence,
                matched_keywords=matched_keywords_map.get(tool_name, []),
            ))

        return results

    def suggest_capability_type(self, intent: str) -> list[str]:
        """
        从意图推断所需的能力类型。

        返回：可能的能力类型列表（按可能性降序）
        """
        intent_lower = intent.lower()
        results: list[tuple[str, float]] = []

        for cap_type, keywords in INTENT_KEYWORDS.items():
            score = 0.0
            for kw in keywords:
                if kw in intent_lower:
                    score += 1.0
            if score > 0:
                results.append((cap_type, score))

        results.sort(key=lambda x: x[1], reverse=True)
        return [cap for cap, _ in results]

    def find_tools_for_capability(self, capability: str) -> list[str]:
        """给定能力类型，返回能填补该能力的工具列表"""
        return CAPABILITY_TOOL_MAP.get(capability, [])


# ============================================================================
# 单例访问
# ============================================================================

_watcher_instance: Optional[RegistryWatcher] = None


def get_registry_watcher() -> RegistryWatcher:
    global _watcher_instance
    if _watcher_instance is None:
        _watcher_instance = RegistryWatcher()
    return _watcher_instance
