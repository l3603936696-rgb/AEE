"""
Agent Tools 统一注册表

从各子模块收集所有工具定义，提供统一的 execute_tool_call 接口。
"""

import logging

from .filesystem import TOOL_DEFINITIONS as FS_DEFS, execute as fs_exec
from .shell import TOOL_DEFINITIONS as SHELL_DEFS, execute as shell_exec
from .browser import TOOL_DEFINITIONS as BROWSER_DEFS, execute as browser_exec
from .search import TOOL_DEFINITIONS as SEARCH_DEFS, execute as search_exec
from .hermes import TOOL_DEFINITIONS as HERMES_DEFS, execute as hermes_exec

logger = logging.getLogger(__name__)

# 所有工具的合并定义（供 LLM 使用）
TOOL_DEFINITIONS = FS_DEFS + SHELL_DEFS + BROWSER_DEFS + SEARCH_DEFS + HERMES_DEFS


def execute_tool_call(tool_name: str, arguments: dict) -> str:
    """
    统一入口：根据工具名路由到对应模块执行。
    """
    # 文件系统工具
    if tool_name in {'file_read', 'file_write', 'file_list', 'file_delete'}:
        return fs_exec(tool_name, arguments)

    # Shell 工具
    if tool_name in {'shell_run', 'shell_bg_run'}:
        return shell_exec(tool_name, arguments)

    # 浏览器工具
    if tool_name in {
        'browser_open', 'browser_screenshot', 'browser_click',
        'browser_fill', 'browser_get_text', 'browser_navigate',
    }:
        return browser_exec(tool_name, arguments)

    # 搜索工具
    if tool_name == 'web_search':
        return search_exec(tool_name, arguments)

    # Hermes 导师工具
    if tool_name == 'ask_hermes':
        return hermes_exec(tool_name, arguments)

    return f'[未知工具: {tool_name}]'


def list_tools() -> list[dict]:
    """返回所有可用工具的列表（名字 + 描述）"""
    return [
        {'name': d['function']['name'], 'description': d['function']['description']}
        for d in TOOL_DEFINITIONS
    ]
