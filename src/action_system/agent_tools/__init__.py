"""
Agent Tools — XIA 操作世界的能力

权限边界：
    - 文件操作：只限 XIA/workspace/ 目录
    - Shell 执行：无限制（已在 governance 层信任）
    - 浏览器：Playwright 自动化

工具注册表：
    每个工具包含：
        name        : str   — LLM 调用时的工具名
        description : str   — LLM prompt 中描述
        parameters  : dict  — JSON Schema 参数定义
        execute     : func  — 实际执行函数

工具执行后，结果写入 logs/agent_audit.jsonl（治理审计日志）。
"""

from .registry import (
    TOOL_DEFINITIONS,
    execute_tool_call,
    list_tools,
)

__all__ = [
    "TOOL_DEFINITIONS",
    "execute_tool_call",
    "list_tools",
]
