"""
搜索工具 — XIA 联网搜索的能力

这是 XIA 联网了解世界的核心工具。
已在 agent_tools 注册体系中，通过 registry.execute_tool_call 统一路由。
"""

import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

# 把项目根加到 sys.path
_project_root = Path(__file__).parent.parent.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

try:
    from net.search_engine import search_web
except ImportError:
    search_web = None


TOOL_DEFINITIONS = [
    {
        'type': 'function',
        'function': {
            'name': 'web_search',
            'description': '搜索互联网获取最新信息。当她需要知道某个事实、新闻、数据，或想了解某个话题的最新情况时使用。',
            'parameters': {
                'type': 'object',
                'properties': {
                    'query': {
                        'type': 'string',
                        'description': '搜索查询词，尽量用简洁的关键词，中英文均可',
                    },
                    'num_results': {
                        'type': 'integer',
                        'description': '返回结果数量，默认 5 条',
                        'default': 5,
                    },
                },
                'required': ['query'],
            },
        },
    },
]


def execute(name: str, arguments: dict) -> str:
    if name != 'web_search':
        return f'[未知搜索工具: {name}]'

    query = arguments.get('query', '')
    num_results = arguments.get('num_results', 5)

    if not query or not query.strip():
        return '[搜索失败：查询词为空]'

    if search_web is None:
        return '[搜索失败：search_engine 模块无法导入]'

    try:
        results = search_web(
            query=query.strip(),
            num_results=num_results,
            timeout_seconds=15.0,
        )
        if not results:
            return f'[搜索无结果：{query}]'

        lines = [f'[搜索结果：{query}]']
        for i, r in enumerate(results, 1):
            lines.append(f'  {i}. {r.title}')
            lines.append(f'     {r.url}')
            snippet = r.snippet.strip()[:150]
            if snippet:
                lines.append(f'     {snippet}')
            lines.append('')

        return '\n'.join(lines)

    except Exception as e:
        logger.error(f'[SearchTools] web_search failed: {e}')
        return f'[搜索出错：{e}]'
