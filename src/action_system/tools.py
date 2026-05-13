"""
XIA 可用的工具集

给她搜索的能力，作为可调用的工具。
她选择何时使用、用什么词搜，由她自己决定。

工具设计原则：
- 最小集合：只给搜索（够用）
- 工具用 JSON 描述，LLM 输出 tool_calls 格式
- 解析 → 执行 → 结果回填 → LLM 给出最终回答
"""

import json
import logging
import re
import sys
import time
from pathlib import Path
from typing import Any, Optional

# net/ 在项目根目录（与 src/ 同级），需要把项目根加到 sys.path
_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from net.search_engine import search_web

logger = logging.getLogger(__name__)


# ============================================================================
# 工具定义（Ollama function calling 格式）
# ============================================================================

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "搜索互联网获取最新信息。当你需要知道某个事实、新闻、数据、或想了解某个话题的最新情况时使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索查询词。尽量用简洁的关键词，中英文均可。",
                    },
                    "num_results": {
                        "type": "integer",
                        "description": "返回结果数量，默认5条",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ask_hermes",
            "description": "向 Hermes 导师请教代码/技术问题。只问代码、依赖、环境问题，其他话题 Hermes 会拒绝回答。当你不理解某段代码、不知道某个错误、缺少某个依赖时使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "你想问 Hermes 的技术问题。尽量描述清楚你遇到的具体问题、错误信息、或你想实现的代码功能。",
                    },
                },
                "required": ["question"],
            },
        },
    },
]

TOOL_NAME = "web_search"


# ============================================================================
# 工具执行器
# ============================================================================

def execute_tool_call(tool_name: str, arguments: dict) -> str:
    """
    执行单个工具调用。

    参数：
        tool_name : 工具名（如 "web_search", "file_read", "shell_run"）
        arguments : 工具参数（如 {"query": "..."}）

    返回：
        str — 工具执行结果（人类可读格式）
    """
    # 先尝试 agent_tools（文件/shell/浏览器）
    from . import agent_tools as at
    result = at.execute_tool_call(tool_name, arguments)
    if not result.startswith("[未知工具"):
        return result

    # 兜底：原有 web_search
    if tool_name == "web_search":
        return _do_web_search(
            query=arguments.get("query", ""),
            num_results=arguments.get("num_results", 5),
        )
    return f"[未知工具: {tool_name}]"


def _do_web_search(query: str, num_results: int = 5) -> str:
    """执行网页搜索，返回格式化结果"""

    if not query or not query.strip():
        return "[搜索失败：查询词为空]"

    query = query.strip()
    # 安全截断：避免超长 query 导致搜不到
    if len(query) > 80:
        query = query[:80]
        truncated = True
    else:
        truncated = False

    try:
        results = search_web(
            query=query,
            num_results=num_results,
            timeout_seconds=15.0,
        )

        if not results:
            suffix = "（已截断）" if truncated else ""
            return f"[搜索无结果：{query}]{suffix}"

        lines = [f"[搜索结果：{query}]"]
        for i, r in enumerate(results, 1):
            lines.append(f"  {i}. {r.title}")
            lines.append(f"     {r.url}")
            snippet = r.snippet.strip()[:150]
            if snippet:
                lines.append(f"     {snippet}")
            lines.append("")

        return "\n".join(lines)

    except Exception as e:
        logger.error(f"[Tools] web_search failed: {e}")
        return f"[搜索出错：{e}]"


def _nl_extract_tools(llm_text: str) -> list[tuple[str, dict]]:
    """
    自然语言意图识别：从中文文本中推断工具调用意图。

    LLM 经常用自然语言描述想做的事（如"我会先打开浏览器搜索"），
    这个函数把这些描述映射到具体工具。

    返回：[(tool_name, arguments), ...]
    """
    calls = []
    text = llm_text.strip()
    if not text:
        return calls

    # 提取 REACH 部分（优先，如果存在）
    reach_match = re.search(r'REACH[：:]\s*(.+)', text, re.IGNORECASE)
    reach_part = reach_match.group(1).strip() if reach_match else ""
    # 非 REACH 部分
    non_reach = re.sub(r'REACH[：:].+', '', text, flags=re.IGNORECASE).strip()

    # ---- 意图关键词映射 ----
    # (关键词列表, 工具名, 参数提取函数)
    # 注意：用 non_reach 做匹配，避免 REACH 文本被误识别
    intent_rules = [
        # 搜索
        (['搜索', '搜一下', '查一下', '网上搜', 'google', '查新闻', '查找'],
         'web_search', lambda t: _nl_extract_query(t)),
        # 写文件 / 写笔记
        (['写日记', '写下来', '写下此刻', '做个笔记', '记录', '写下'],
         'file_write', lambda t: _nl_extract_write(t)),
        # 读文件 / 查看
        (['查看', '看日志', '翻看', '读一下', '读取', '阅读', '查阅'],
         'file_read', lambda t: _nl_extract_path(t, ['查看', '读一下', '读取', '阅读', '查阅', '日志', '笔记', '文件', 'workspace'])),
        # 列出文件
        (['看看里面', '列出', '目录下有什么', 'ls '],
         'file_list', lambda t: _nl_extract_path(t, ['workspace'])),
        # 浏览器打开（去掉单字 "读"、"看看" 等过短关键词，避免描述性文本误触发）
        (['读新闻', '读文章', '读帖子', '读一下新闻', '读一下文章', '打开浏览器',
          '访问网站', '去网页', '开个网页', '去浏览', '看看新闻', '去看看'],
         'browser_open', lambda t: _nl_extract_url(t)),
        # 截图
        (['截图', '截屏', '拍张照'],
         'browser_screenshot', lambda t: _nl_extract_screenshot(t)),
        # Shell 命令（只匹配明确的命令意图短语，不匹配描述性出现）
        (['我要运行', '我想运行', '运行一下', '帮我运行', '运行命令'],
         'shell_run', lambda t: _nl_extract_shell(t)),
    ]

    # 优先扫描浏览器/搜索意图（因为这些是常见主动行为）
    search_intents = [
        (['打开浏览器搜索', '浏览器搜索', '网上搜索', '搜索一下'],
         'web_search', lambda t: _nl_extract_query(t)),
        (['打开浏览器', '开个网页', '访问网页', '去网站'],
         'browser_open', lambda t: _nl_extract_url(t)),
    ]

    # 先检查 search_intents（更具体）
    for keywords, tool, arg_fn in search_intents:
        for kw in keywords:
            if kw in non_reach:
                args = arg_fn(non_reach)
                if args:
                    calls.append((tool, args))
                    break
        if calls:
            break

    # 再检查通用意图
    if not calls:
        for keywords, tool, arg_fn in intent_rules:
            for kw in keywords:
                if kw in non_reach:
                    args = arg_fn(non_reach)
                    if args:
                        calls.append((tool, args))
                        break
            if calls:
                break

    return calls


def _nl_extract_query(text: str) -> dict | None:
    """从文本中提取搜索query，只取第一句或前60字（避免段落当query）"""
    # 找关键词及其位置
    kw_list = ['google', '查一下', '搜一下', '搜索', '搜么', '查', '搜']
    idx = -1
    kw_len = 0
    for kw in kw_list:
        i = text.find(kw)
        if i >= 0:
            idx = i
            kw_len = len(kw)
            break
    if idx < 0:
        return None
    # 从关键词之后开始提取
    after = text[idx + kw_len:]
    # 去掉"一下"/"么"等常见填充词
    after = re.sub(r'^(一下|么)?\s*', '', after)
    after = after.rstrip('，。、？！…—–"\'').strip()
    # 去掉 REACH 部分
    after = re.sub(r'\s*REACH[：:].*$', '', after, flags=re.IGNORECASE).strip()

    # 取第一句话（以句号/问号/感叹号/换行分段）
    for sep in ['。', '！', '？', '\n', '\r']:
        if sep in after:
            after = after.split(sep)[0].strip()
            break

    # 截断到60字
    if len(after) > 60:
        after = after[:60]
    # 清理引号
    after = after.strip('""\'\'「」""''').strip()

    if after and len(after) >= 2:
        return {"query": after}
    return None


def _nl_extract_write(text: str) -> dict | None:
    """从文本中提取写文件内容和路径"""
    non_reach = re.sub(r'REACH[：:].+', '', text, flags=re.IGNORECASE).strip()
    # 尝试提取文件名
    path = "workspace/xia_note.txt"
    # 找引号内的路径
    m = re.search(r'["""\'""\']([^"""\']+\.txt)["""\'\'\'"]', non_reach)
    if m:
        path = m.group(1)
        if not path.startswith('workspace/'):
            path = 'workspace/' + path
    # 提取内容：REACH 之后的是内容，或者正文中的引号内容
    content = ""
    if re.search(r'REACH[：:]', text, re.IGNORECASE):
        m2 = re.search(r'REACH[：:]\s*(.+)', text, re.IGNORECASE)
        content = m2.group(1).strip() if m2 else non_reach
    else:
        # 用引号提取内容
        m3 = re.search(r'["""\'""\']([^"""\']{10,500})["""\'\'\'"]', non_reach)
        if m3:
            content = m3.group(1).strip()
        else:
            content = non_reach[:500]
    if content:
        return {"path": path, "content": content}
    return None


def _nl_extract_path(text: str, hint_words: list[str]) -> dict | None:
    """从文本中提取文件路径"""
    non_reach = re.sub(r'REACH[：:].+', '', text, flags=re.IGNORECASE).strip()
    # 找 workspace 路径
    m = re.search(r'workspace/[^\s，、。！？]+', non_reach)
    if m:
        return {"path": m.group(0)}
    # 找常见文件名
    for hint in hint_words:
        idx = non_reach.find(hint)
        if idx >= 0:
            rest = non_reach[idx:].split()[0] if non_reach[idx:].split() else ""
            if rest and '.' in rest:
                p = rest if rest.startswith('workspace/') else 'workspace/' + rest
                return {"path": p}
    return {"path": "workspace/"}


def _nl_extract_url(text: str) -> dict | None:
    """从文本中提取 URL"""
    m = re.search(r'https?://[^\s，、。！？\)]+', text)
    if m:
        return {"url": m.group(0)}
    # 新闻类意图
    if any(kw in text for kw in ['新闻', '帖子', '社交媒体', 'twitter', '微博', 'reddit', '文章', '博客']):
        if 'news.google' not in text:
            return {"url": "https://news.google.com"}
    # Hacker News
    if any(kw in text.lower() for kw in ['hacker news', 'hn', 'hackernews']):
        return {"url": "https://news.ycombinator.com"}
    # 尝试提取网站名
    site_match = re.search(r'(打开|访问|去|浏览)\s*(.+)', text)
    if site_match:
        query = site_match.group(2).strip().rstrip('，。、？！…')
        if query and query not in ['看看', '看看新闻', '新闻', '网页']:
            return {"url": f"https://www.google.com/search?q={query}"}
    return None


def _nl_extract_screenshot(text: str) -> dict | None:
    """从文本中提取截图名称"""
    m = re.search(r'截图\s*(.+)', text)
    name = m.group(1).strip().rstrip('。，、？！') if m else "screenshot"
    return {"name": name}


def _nl_extract_shell(text: str) -> dict | None:
    """从文本中提取 shell 命令"""
    m = re.search(r'运行[命令]?\s*(.+)', text)
    if not m:
        return None
    cmd = m.group(1).strip().rstrip('。，、？！')
    if not cmd or len(cmd) < 2:
        return None
    return {"command": cmd}


# ============================================================================
# LLM 响应解析（提取 tool_calls）
# ============================================================================

def extract_tool_calls(llm_text: str) -> list[tuple[str, dict]]:
    """
    从 LLM 输出中解析 tool_calls。

    支持两种格式：
    1. JSON 格式 tool_calls（如 qwen 的 function calling）
    2. 文本格式，如 "SEARCH: xxx" 或 "【搜索】xxx"

    返回：
        [(tool_name, arguments), ...]
    """
    calls = []

    # 剥离 REACH 段落，避免 REACH 文本被误识别为工具调用
    llm_text_for_tools = re.sub(
        r'REACH[：:]\s*.+?(?=\n\n|\Z)', '', llm_text,
        flags=re.IGNORECASE | re.DOTALL,
    ).strip()
    if not llm_text_for_tools:
        return calls

    # 格式1：JSON tool_calls
    try:
        # 尝试提取 ```json ... ``` 包裹的块
        json_blocks = re.findall(r'```(?:json)?\s*\n?(.*?)\n?```', llm_text_for_tools, re.DOTALL)
        for block in json_blocks:
            block = block.strip()
            if block.startswith('{') or block.startswith('['):
                data = json.loads(block)
                if isinstance(data, dict) and "tool_calls" in data:
                    for call in data["tool_calls"]:
                        name = call.get("function", {}).get("name", "")
                        args = call.get("function", {}).get("arguments", {})
                        if isinstance(args, str):
                            args = json.loads(args)
                        if name:
                            calls.append((name, args))
                elif isinstance(data, dict) and "name" in data:
                    name = data.get("name", "")
                    args = data.get("arguments", data.get("parameters", {}))
                    if isinstance(args, str):
                        args = json.loads(args)
                    if name:
                        calls.append((name, args))
                elif isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and "name" in item:
                            name = item.get("name", "")
                            args = item.get("arguments", item.get("parameters", {}))
                            if isinstance(args, str):
                                args = json.loads(args)
                            if name:
                                calls.append((name, args))
    except Exception:
        pass

    # 格式2：文本中的工具调用模式
    # 通用格式：TOOL_NAME: arguments 或 【TOOL_NAME】arguments
    tool_patterns = [
        # 原有搜索
        (r'SEARCH[：:]\s*(.+?)(?:\n|$)', "web_search", {"query": 1}),
        (r'【搜索】\s*(.+?)(?:\n|$)', "web_search", {"query": 1}),
        (r'搜索[：:]\s*(.+?)(?:\n|$)', "web_search", {"query": 1}),
        # 文件工具
        (r'file_read[：:]\s*(.+?)(?:\n|$)', "file_read", {"path": 1}),
        (r'【文件读取】\s*(.+?)(?:\n|$)', "file_read", {"path": 1}),
        (r'读文件[：:]\s*(.+?)(?:\n|$)', "file_read", {"path": 1}),
        (r'file_write[：:]\s*(\S+?)\s*\n([\s\S]+?)(?=\n(?:file_|shell_|browser_|REACH|$)|$)', "file_write", None),
        (r'【写文件】\s*(.+?)(?:\n|$)', "file_write", {"content": 1}),
        (r'写文件[：:]\s*(.+?)(?:\n|$)', "file_write", {"content": 1}),
        (r'file_list[：:]\s*(.+?)(?:\n|$)', "file_list", {"path": 1}),
        (r'ls[：:]\s*(.+?)(?:\n|$)', "file_list", {"path": 1}),
        # Shell 工具
        (r'shell_run[：:]\s*(.+?)(?:\n|$)', "shell_run", {"command": 1}),
        (r'【运行命令】\s*(.+?)(?:\n|$)', "shell_run", {"command": 1}),
        (r'运行命令[：:]\s*(.+?)(?:\n|$)', "shell_run", {"command": 1}),
        (r'执行[：:]\s*(.+?)(?:\n|$)', "shell_run", {"command": 1}),
        # 浏览器工具
        (r'browser_open[：:]\s*(https?://\S+)', "browser_open", {"url": 1}),
        (r'【打开网页】\s*(https?://\S+)', "browser_open", {"url": 1}),
        (r'打开[：:]\s*(https?://\S+)', "browser_open", {"url": 1}),
        (r'browser_screenshot[：:]\s*(.+)', "browser_screenshot", {"name": 1}),
        (r'截图[：:]\s*(.+)', "browser_screenshot", {"name": 1}),
    ]

    # 格式3：中文自然语言意图识别（正则匹配失败后使用）
    if not calls:
        calls = _nl_extract_tools(llm_text_for_tools)

    for pattern, name, _ in tool_patterns:
        for match in re.finditer(pattern, llm_text_for_tools, re.IGNORECASE):
            raw = match.group(1).strip() if match.lastindex and match.lastindex >= 1 else match.group(0)
            if raw and len(raw) > 0:
                if name == "file_write":
                    # file_write 需要额外捕获内容（多行）
                    full = match.group(0)
                    # 找下一段文本作为内容
                    end_pos = match.end()
                    rest = llm_text_for_tools[end_pos:].split("\n\n")[0].strip()
                    calls.append((name, {"path": raw, "content": rest[:2000]}))
                else:
                    args = {}
                    if name == "web_search":
                        args = {"query": raw}
                    elif name == "file_read":
                        args = {"path": raw}
                    elif name == "file_list":
                        args = {"path": raw or ""}
                    elif name == "shell_run":
                        args = {"command": raw}
                    elif name == "browser_open":
                        url = raw.strip()
                        args = {"url": url}
                    elif name == "browser_screenshot":
                        args = {"name": raw.strip()}
                    calls.append((name, args))

    return calls


# ============================================================================
# 工具循环：解析 → 执行 → 回填 → 最终回答
# ============================================================================

def run_with_tools(
    initial_response: str,
    max_loops: int = 2,
    timeout_seconds: float = 30.0,
) -> str:
    """
    给 LLM 一个机会：用工具搜索，然后用结果回答。

    流程：
        初始 LLM 调用 → 检查是否有 tool_calls
        → 有：执行工具 → 把结果注入 prompt → 再次调用 LLM
        → 无：直接返回初始回答

    参数：
        initial_response : LLM 首次回答
        max_loops        : 最多执行几轮工具（防止无限循环）
        timeout_seconds  : 工具执行总超时

    返回：
        str — 最终回答（可能已被工具结果更新）
    """
    if not initial_response:
        return ""

    calls = extract_tool_calls(initial_response)
    if not calls:
        return initial_response

    results_text = []
    start = time.time()

    for tool_name, args in calls[:max_loops]:  # 限制总调用数
        if time.time() - start > timeout_seconds:
            results_text.append(f"[工具执行超时，剩余结果跳过]")
            break

        logger.info(f"[Tools] Executing {tool_name}({args})")
        result = execute_tool_call(tool_name, args)
        results_text.append(result)

    if not results_text:
        return initial_response

    # 工具执行完成后，追加工具结果到回答
    # LLM 已经给出回答，我们只是补充信息
    combined = initial_response.strip()
    combined += "\n\n[我搜索了一下：]\n" + "\n".join(results_text)

    return combined
