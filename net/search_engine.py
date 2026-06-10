"""
Web Search Engine — 搜索引擎后端封装

支持以下后端（按优先级尝试）：
    1. duckduckgo-search（免费，无需 API Key）
    2. requests + DuckDuckGo HTML API（备选，无需安装额外包）

降级策略：任一后端失败 → 返回空列表，不抛异常。
"""

from __future__ import annotations

import logging
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Optional

# 优先从本地 lib/ 目录加载 duckduckgo-search（沙箱环境）
_LOCAL_LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib")
if os.path.isdir(_LOCAL_LIB) and _LOCAL_LIB not in sys.path:
    sys.path.insert(0, _LOCAL_LIB)

logger = logging.getLogger(__name__)


# ============================================================================
# 数据结构
# ============================================================================

@dataclass
class SearchResult:
    """标准化搜索结果"""
    title: str
    url: str
    snippet: str
    source: str = "unknown"  # 搜索引擎名称
    relevance_score: float = 1.0  # 内部相关性参考分

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "source": self.source,
            "relevance_score": round(self.relevance_score, 3),
        }


# ============================================================================
# 后端实现
# ============================================================================

def _search_duckduckgo(query: str, num_results: int = 5) -> list[SearchResult]:
    """
    使用 duckduckgo-search 库进行搜索。

    安装：pip install duckduckgo-search
    """
    try:
        from duckduckgo_search import DDGS

        results: list[SearchResult] = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=num_results):
                results.append(SearchResult(
                    title=r.get("title", ""),
                    url=r.get("href", ""),
                    snippet=r.get("body", ""),
                    source="duckduckgo",
                    relevance_score=1.0,
                ))
        return results

    except ImportError:
        logger.debug("duckduckgo-search 未安装，尝试备选方案")
    except Exception as e:
        logger.warning(f"DuckDuckGo 搜索失败: {e}")

    return []


def _search_bing_html(query: str, num_results: int = 5) -> list[SearchResult]:
    """
    使用 urllib 直接访问 Bing 搜索（中国境内可访问，无需 API Key）。
    """
    try:
        import html as _html_mod
        import re
        import urllib.error
        import urllib.parse
        import urllib.request

        results: list[SearchResult] = []

        encoded_query = urllib.parse.quote_plus(query)
        url = f"https://cn.bing.com/search?q={encoded_query}&setlang=zh-cn"

        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "zh-CN,zh;q=0.9",
            },
        )

        # 先尝试正常 SSL 连接；失败则降级为不验证证书
        html_text = None
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                html_text = resp.read().decode("utf-8", errors="replace")
        except Exception as _e1:
            logger.debug(f"Bing SSL 正常连接失败: {_e1}，尝试跳过证书验证")
            import ssl as _ssl
            _ctx = _ssl.create_default_context()
            _ctx.check_hostname = False
            _ctx.verify_mode = _ssl.CERT_NONE
            with urllib.request.urlopen(req, timeout=10, context=_ctx) as resp:
                html_text = resp.read().decode("utf-8", errors="replace")

        # Bing 搜索结果在 <li class="b_algo"> 中
        for block in re.finditer(
            r'<li class="b_algo"[^>]*>(.*?)</li>',
            html_text,
            re.DOTALL,
        ):
            block_html = block.group(1)

            # 从 <h2> 中提取标题和链接
            h2_match = re.search(
                r'<h2[^>]*>(.*?)</h2>',
                block_html,
                re.DOTALL,
            )
            if not h2_match:
                continue
            h2_html = h2_match.group(1)

            link_match = re.search(
                r'<a[^>]*href="(https?://[^"]+)"[^>]*>(.*?)</a>',
                h2_html,
                re.DOTALL,
            )
            if not link_match:
                continue

            url_match = link_match.group(1)
            title_raw = link_match.group(2)
            # 去掉 <strong> 等标签，解码 HTML 实体
            title_text = re.sub(r"<[^>]+>", "", title_raw).strip()
            title_text = _html_mod.unescape(title_text)

            # 提取摘要：<p class="b_lineclamp2"> 或 <div class="b_caption"><p>
            snippet = ""
            snippet_match = re.search(
                r'<p class="b_lineclamp2">(.*?)</p>',
                block_html,
                re.DOTALL,
            )
            if not snippet_match:
                snippet_match = re.search(
                    r'<div class="b_caption"[^>]*>.*?<p[^>]*>(.*?)</p>',
                    block_html,
                    re.DOTALL,
                )
            if snippet_match:
                snippet = re.sub(r"<[^>]+>", "", snippet_match.group(1)).strip()
                snippet = _html_mod.unescape(snippet)[:300]

            results.append(SearchResult(
                title=title_text,
                url=url_match,
                snippet=snippet,
                source="bing_html",
                relevance_score=0.85,
            ))

            if len(results) >= num_results:
                break

        return results

    except Exception as e:
        logger.warning(f"Bing HTML 搜索失败: {e}", exc_info=True)

    logger.info(f"Bing HTML 返回 {len(results)} 条结果 (query='{query[:30]}')")
    return results


def _search_httpx_ddg(query: str, num_results: int = 5) -> list[SearchResult]:
    """
    使用 urllib 直接访问 DuckDuckGo HTML API（无 Cookie）。
    """
    try:
        import re
        import urllib.error
        import urllib.parse
        import urllib.request

        encoded_query = urllib.parse.quote_plus(query)
        url = f"https://duckduckgo.com/html/?q={encoded_query}&kl=zh-cn"

        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "zh-CN,zh;q=0.9",
            },
        )

        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="replace")

        results: list[SearchResult] = []

        for match in re.finditer(
            r'<a class="result__a" href="([^"]+)"[^>]*>([^<]+)</a>',
            html,
        ):
            url_match = match.group(1)
            title_match = match.group(2).strip()
            snippet = ""

            snippet_match = re.search(
                rf'href="{re.escape(url_match)}"[^>]*>[^<]*</a>(.*?)</p>',
                html,
                re.DOTALL,
            )
            if snippet_match:
                snippet = re.sub(r"<[^>]+>", "", snippet_match.group(1)).strip()[:200]

            if url_match.startswith("http"):
                results.append(SearchResult(
                    title=title_match,
                    url=url_match,
                    snippet=snippet,
                    source="duckduckgo_html",
                    relevance_score=0.9,
                ))

            if len(results) >= num_results:
                break

        return results

    except Exception as e:
        logger.warning(f"DuckDuckGo HTML 备选方案失败: {e}")

    return []


def _search_tavily(query: str, num_results: int = 5, api_key: Optional[str] = None) -> list[SearchResult]:
    """
    使用 Tavily Search API。

    安装：pip install tavily-python
    需要：TAVILY_API_KEY 环境变量或传入 api_key 参数
    """
    if not api_key:
        api_key = os.environ.get("TAVILY_API_KEY")

    if not api_key:
        return []

    try:
        from tavily import TavilyClient

        client = TavilyClient(api_key=api_key)
        response = client.search(
            query=query,
            max_results=num_results,
            search_depth="basic",
        )

        results: list[SearchResult] = []
        for item in response.get("results", []):
            results.append(SearchResult(
                title=item.get("title", ""),
                url=item.get("url", ""),
                snippet=item.get("content", ""),
                source="tavily",
                relevance_score=item.get("score", 1.0),
            ))
        return results

    except ImportError:
        logger.debug("tavily-python 未安装")
    except Exception as e:
        logger.warning(f"Tavily 搜索失败: {e}")

    return []


def _search_google_serpapi(
    query: str,
    num_results: int = 5,
    api_key: Optional[str] = None,
) -> list[SearchResult]:
    """
    使用 SerpAPI Google Search。

    安装：pip install google-search-results
    需要：SERPAPI_API_KEY 环境变量或传入 api_key 参数
    """
    if not api_key:
        api_key = os.environ.get("SERPAPI_API_KEY")

    if not api_key:
        return []

    try:
        from serpapi import GoogleSearch

        params = {
            "q": query,
            "num": num_results,
            "api_key": api_key,
            "hl": "zh-cn",
        }

        search = GoogleSearch(params)
        results = search.get_dict()

        search_results: list[SearchResult] = []
        for item in results.get("organic_results", [])[:num_results]:
            search_results.append(SearchResult(
                title=item.get("title", ""),
                url=item.get("link", ""),
                snippet=item.get("snippet", ""),
                source="serpapi_google",
                relevance_score=1.0,
            ))
        return search_results

    except ImportError:
        logger.debug("google-search-results 未安装")
    except Exception as e:
        logger.warning(f"SerpAPI 搜索失败: {e}")

    return []


# ============================================================================
# 主入口 — 按优先级尝试各后端
# ============================================================================

def search_web(
    query: str,
    num_results: int = 5,
    timeout_seconds: float = 10.0,
    preferred_backend: Optional[str] = None,
    api_key: Optional[str] = None,
) -> list[SearchResult]:
    """
    通用网页搜索接口。

    按以下顺序尝试后端（首个成功者返回）：
        1. Bing HTML（中国境内可访问，无需 API Key）
        2. Tavily（需 API Key，质量最高）
        3. SerpAPI Google（需 API Key）
        4. DuckDuckGo（duckduckgo-search 包）
        5. DuckDuckGo HTML（纯标准库，无需安装）

    参数：
        query            : 搜索词
        num_results      : 返回结果数量（默认 5）
        timeout_seconds  : 超时秒数
        preferred_backend: 优先使用某后端（"bing_html" | "tavily" | "serpapi" | "duckduckgo" | "ddg_html"）
                          若为 None，按默认优先级自动选择
        api_key          : 通用 API Key（同时用于 Tavily / SerpAPI）

    返回：
        List[SearchResult]，失败时返回空列表
    """
    if not query or not query.strip():
        return []

    query = query.strip()
    start = time.time()

    backends: list[tuple[str, callable]]
    if preferred_backend:
        backend_map = {
            "bing_html": ("bing_html", lambda: _search_bing_html(query, num_results)),
            "tavily": ("tavily", lambda: _search_tavily(query, num_results, api_key)),
            "serpapi": ("serpapi", lambda: _search_google_serpapi(query, num_results, api_key)),
            "duckduckgo": ("duckduckgo", lambda: _search_duckduckgo(query, num_results)),
            "ddg_html": ("ddg_html", lambda: _search_httpx_ddg(query, num_results)),
        }
        if preferred_backend in backend_map:
            name, fn = backend_map[preferred_backend]
            backends = [(name, fn)]
        else:
            backends = []
    else:
        backends = [
            ("bing_html", lambda: _search_bing_html(query, num_results)),
            ("tavily", lambda: _search_tavily(query, num_results, api_key)),
            ("serpapi", lambda: _search_google_serpapi(query, num_results, api_key)),
            ("duckduckgo", lambda: _search_duckduckgo(query, num_results)),
            ("ddg_html", lambda: _search_httpx_ddg(query, num_results)),
        ]

    for name, fn in backends:
        elapsed = time.time() - start
        remaining = timeout_seconds - elapsed
        if remaining <= 0:
            break

        results = fn()
        if results:
            logger.info(f"[WebSearch] {name} 返回 {len(results)} 条结果 (query='{query[:30]}')")
            return results

    logger.info(f"[WebSearch] 所有后端均失败，query='{query[:30]}'")
    return []


# ============================================================================
# 测试入口
# ============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("Web Search 模块测试")
    print("=" * 60)

    test_queries = [
        "Python asyncio 异步编程教程",
        "人工智能最新进展 2026",
    ]

    for q in test_queries:
        print(f"\n【搜索】{q}")
        results = search_web(q, num_results=3)

        if results:
            for i, r in enumerate(results, 1):
                print(f"  [{i}] {r.title}")
                print(f"      {r.url}")
                print(f"      {r.snippet[:100]}...")
        else:
            print("  （无结果，所有后端均失败）")

    print("\n" + "=" * 60)
    print("搜索测试完成")
