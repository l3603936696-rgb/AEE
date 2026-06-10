"""
template_synthesizer — 模板工具合成器

备用路径：LLM 不可用时，用预定义模式库快速生成工具定义。

设计原则：
    - 模式库是可扩展的（在 TEMPLATE_PATTERNS 中添加即可）
    - 只处理简单场景，复杂场景由 LLMSynthesizer 处理
    - 合成结果同样注册到 registry
"""

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


# ============================================================================
# 工具模板库
# ============================================================================

@dataclass
class ToolTemplate:
    """工具模板"""
    name_prefix: str                    # 工具名前缀（如 "tool_"）
    description_template: str           # 描述模板
    command_template: str              # 命令模板（支持 {param} 占位符）
    capability_type: str               # 对应能力类型
    estimated_impact: float            # 影响程度 [0, 1]


# 工具模板库
# 每个模板对应一种能力缺口类型。

TOOL_TEMPLATES: list[ToolTemplate] = [
    ToolTemplate(
        name_prefix="tool_",
        description_template="通过 {param} 执行自定义任务",
        command_template="{param}",
        capability_type="code_execution",
        estimated_impact=0.7,
    ),
]


# ============================================================================
# 能力缺口类型 → 工具模板映射
# ============================================================================

CAPABILITY_TEMPLATE_MAP: dict[str, ToolTemplate] = {
    "web_access": ToolTemplate(
        name_prefix="tool_web_",
        description_template="通过浏览器访问网页 {url}",
        command_template="python -c 'import urllib.request; print(urllib.request.urlopen(\"{url}\").read().decode())'",
        capability_type="web_access",
        estimated_impact=0.8,
    ),
    "information_search": ToolTemplate(
        name_prefix="tool_search_",
        description_template="在网络上搜索信息 {query}",
        command_template="python -c 'import urllib.parse, urllib.request; q=urllib.parse.quote(\"{query}\"); urllib.request.urlopen(f\"https://duckduckgo.com/?q={{q}}\")'",
        capability_type="information_search",
        estimated_impact=0.8,
    ),
    "file_manipulation": ToolTemplate(
        name_prefix="tool_file_",
        description_template="对文件执行操作：{operation}",
        command_template="echo '文件操作: {operation}'",
        capability_type="file_manipulation",
        estimated_impact=0.6,
    ),
    "code_execution": ToolTemplate(
        name_prefix="tool_code_",
        description_template="执行代码片段：{code}",
        command_template="python3 -c '{code}'",
        capability_type="code_execution",
        estimated_impact=0.9,
    ),
    "network_access": ToolTemplate(
        name_prefix="tool_net_",
        description_template="发送网络请求到 {endpoint}",
        command_template="curl -s {endpoint}",
        capability_type="network_access",
        estimated_impact=0.7,
    ),
    "api_call": ToolTemplate(
        name_prefix="tool_api_",
        description_template="调用 API 接口：{endpoint}",
        command_template="curl -X GET '{endpoint}'",
        capability_type="api_call",
        estimated_impact=0.8,
    ),
    "data_processing": ToolTemplate(
        name_prefix="tool_data_",
        description_template="处理数据：{operation}",
        command_template="python3 -c 'import json,sys; data=json.load(sys.stdin); {operation}'",
        capability_type="data_processing",
        estimated_impact=0.7,
    ),
    "web_scraping": ToolTemplate(
        name_prefix="tool_scrape_",
        description_template="从网页提取内容：{url}",
        command_template="python3 -c 'import urllib.request; print(urllib.request.urlopen(\"{url}\").read().decode()[:500])'",
        capability_type="web_scraping",
        estimated_impact=0.7,
    ),
    "mentor_guidance": ToolTemplate(
        name_prefix="tool_mentor_",
        description_template="向导师请教问题：{question}",
        command_template="echo '请教导师: {question}'",
        capability_type="mentor_guidance",
        estimated_impact=0.6,
    ),
}


# ============================================================================
# 模板合成器
# ============================================================================

class TemplateSynthesizer:
    """
    模板工具合成器。

    给定能力缺口类型，找到对应模板，填充参数，生成工具定义。

    使用方式：
        synthesizer = TemplateSynthesizer()
        tool_def = synthesizer.synthesize(capability_type, params)
    """

    def synthesize(
        self,
        capability_type: str,
        params: dict,
    ) -> Optional[dict]:
        """
        从模板合成工具定义。

        参数：
            capability_type : 能力类型（如 "web_access"）
            params         : 参数字典（如 {"url": "https://...", "query": "..."}）

        返回：
            工具定义 dict（符合 TOOL_DEFINITIONS 格式），失败返回 None
        """
        template = CAPABILITY_TEMPLATE_MAP.get(capability_type)
        if not template:
            logger.debug(f"[TemplateSynthesizer] No template for capability: {capability_type}")
            return None

        # 填充模板
        try:
            description = template.description_template
            command = template.command_template

            for key, value in params.items():
                placeholder = "{" + key + "}"
                if placeholder in description:
                    description = description.replace(placeholder, str(value)[:100])
                if placeholder in command:
                    command = command.replace(placeholder, str(value)[:200])

            # 生成唯一工具名
            import time
            timestamp = int(time.time())
            tool_name = f"{template.name_prefix}{capability_type}_{timestamp % 10000}"

            tool_def = {
                "name": tool_name,
                "description": description,
                "parameters": {k: {"type": "string", "description": str(v)[:50]} for k, v in params.items()},
                "execute_command": command,
                "fallback_hint": f"当 {tool_name} 失效时，请用现有工具组合实现相同功能。",
                "capability_type": capability_type,
                "estimated_impact": template.estimated_impact,
                "synthesized_from": "template",
                "timestamp": time.time(),
            }

            logger.info(f"[TemplateSynthesizer] Synthesized {tool_name} for {capability_type}")
            return tool_def

        except Exception as e:
            logger.error(f"[TemplateSynthesizer] Synthesis error: {e}")
            return None


# ============================================================================
# 便捷函数
# ============================================================================

_synthesizer_instance: Optional[TemplateSynthesizer] = None


def get_template_synthesizer() -> TemplateSynthesizer:
    global _synthesizer_instance
    if _synthesizer_instance is None:
        _synthesizer_instance = TemplateSynthesizer()
    return _synthesizer_instance


def synthesize_from_template(
    capability_type: str,
    params: dict,
) -> Optional[dict]:
    """
    便捷函数：从模板合成工具。

    这是 template_synthesizer 模块的外部入口。
    失败时返回 None（调用方应降级到 LLMSynthesizer）。
    """
    synthesizer = get_template_synthesizer()
    return synthesizer.synthesize(capability_type, params)
