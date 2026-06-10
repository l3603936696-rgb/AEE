"""
Agent Tools 统一注册表

从各子模块收集所有工具定义，提供统一的 execute_tool_call 接口。

架构说明：
    XIA 有两个实例：
    - 初号机（xia_proto）：primitive 集合是动态的，可以自己注册新工具
    - 糯糯（nuonuo）：primitive 集合是锁死的，只同步经过验证的功能

    DYNAMIC_PRIMITIVES 字段用于初号机的动态注册，
    糯糯读取时只看 TOOL_DEFINITIONS（不含动态注册）。
    同步流程：初号机实验 → candidate 审核 → 手动同步到糯糯。
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

# v11.6: 动态注册的工具（由 LLM 合成器生成）
_DYNAMIC_TOOL_DEFS: list[dict] = []


def execute_tool_call(tool_name: str, arguments: dict) -> str:
    """
    统一入口：根据工具名路由到对应模块执行。
    """
    # 动态注册的工具
    if tool_name.startswith("tool_"):
        return execute_dynamic_tool(tool_name, arguments)

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


# ============================================================================
# v11.6: 动态工具注册（LLM 合成器调用）
# ============================================================================

def register_tool_definition(tool_def: dict) -> bool:
    """
    注册一个由 LLM 合成的新工具定义。

    参数：
        tool_def : 工具定义 dict，必须包含：
            name            : 工具名（必须以 "tool_" 开头）
            description     : 描述
            execute_command : 执行命令

    返回：
        bool — 注册是否成功
    """
    name = tool_def.get("name", "")
    if not name or not name.startswith("tool_"):
        logger.warning(f"[Registry] Invalid tool name: {name}")
        return False

    # 检查重名
    all_tools = TOOL_DEFINITIONS + _DYNAMIC_TOOL_DEFS
    for existing in all_tools:
        if existing["function"]["name"] == name:
            logger.debug(f"[Registry] Tool {name} already exists, skipping")
            return False

    # 构建标准 function schema
    parameters = tool_def.get("parameters", {})
    func_schema: dict = {
        "name": name,
        "description": tool_def.get("description", ""),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    }
    for param_name, param_def in parameters.items():
        if isinstance(param_def, dict):
            func_schema["parameters"]["properties"][param_name] = {
                "type": param_def.get("type", "string"),
                "description": param_def.get("description", ""),
            }
        else:
            func_schema["parameters"]["properties"][param_name] = {"type": "string"}

    wrapped_def = {"function": func_schema, "_meta": tool_def}
    _DYNAMIC_TOOL_DEFS.append(wrapped_def)
    logger.info(f"[Registry] Registered dynamic tool: {name} (total: {len(_DYNAMIC_TOOL_DEFS)})")
    return True


def reload_tools() -> None:
    """
    热重载工具注册表（供 XIA 发现新工具时调用）。

    目前是 no-op——动态工具在 list_tools() 中已经包含。
    后续可用于通知缓存失效等。
    """
    logger.debug(f"[Registry] reload_tools called (dynamic tools: {len(_DYNAMIC_TOOL_DEFS)})")


def get_all_tools() -> list[dict]:
    """返回所有工具（包括动态注册的工具）"""
    return TOOL_DEFINITIONS + _DYNAMIC_TOOL_DEFS


def get_dynamic_tools() -> list[dict]:
    """返回所有动态注册的工具"""
    return list(_DYNAMIC_TOOL_DEFS)


def execute_dynamic_tool(tool_name: str, arguments: dict) -> str:
    """
    执行一个动态注册的工具（由 LLM 合成）。

    动态工具目前通过 shell_run 方式执行。
    """
    tool_def = None
    for t in _DYNAMIC_TOOL_DEFS:
        if t["function"]["name"] == tool_name:
            tool_def = t
            break

    if not tool_def:
        return f"[未知动态工具: {tool_name}]"

    meta = tool_def.get("_meta", {})
    cmd = meta.get("execute_command", "")
    if not cmd:
        return f"[动态工具 {tool_name} 缺少执行命令]"

    try:
        return shell_exec("shell_run", {"command": cmd})
    except Exception as e:
        return f"[动态工具执行失败: {e}]"
