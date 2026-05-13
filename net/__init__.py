"""
XIA — 联网与通信模块

包含：
    - search_engine : 网页搜索后端（DuckDuckGo / Tavily / SerpAPI）
    - channel       : 对话通道（CLI / API 等），见 channel/ 模块
"""

from .search_engine import search_web, SearchResult

__all__ = ["search_web", "SearchResult"]
