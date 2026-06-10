"""Natural-language tool intent extraction helpers."""

from __future__ import annotations

import re
from pathlib import Path

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
