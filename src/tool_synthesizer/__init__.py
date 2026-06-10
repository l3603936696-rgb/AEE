"""
tool_synthesizer — XIA 的工具合成层

让她能够：
    - 从失败经验中合成新的工具定义（LLM 辅助）
    - 用模板组合快速生成简单工具（备用路径）

设计原则：
    - LLM 作为拐杖，语言系统成熟后替换为内生合成
    - 每次 tick 至多合成 1 个工具（防止资源耗尽）
    - 合成结果注册到 agent_tools/registry.py
"""

from .llm_synthesizer import LLMSynthesizer, synthesize_tool, get_synthesizer
from .template_synthesizer import TemplateSynthesizer, synthesize_from_template

__all__ = [
    "LLMSynthesizer",
    "synthesize_tool",
    "get_synthesizer",
    "TemplateSynthesizer",
    "synthesize_from_template",
]
