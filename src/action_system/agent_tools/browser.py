"""
浏览器工具 — XIA 用 Playwright 控制真实浏览器

功能：
    - 打开任意 URL（无头或可视模式）
    - 截图保存到 workspace/screenshots/
    - 点击元素、填表单、读取页面内容

依赖：playwright
    pip install playwright
    playwright install chromium

无 Playwright 时的降级行为：返回友好错误提示。
"""

import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)

AUDIT_DIR = Path(__file__).parent.parent.parent.parent / 'logs'
AUDIT_DIR.mkdir(exist_ok=True)

SCREENSHOT_DIR = Path(__file__).parent.parent.parent.parent / 'workspace' / 'screenshots'
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

# ============================================================================
# 工具定义
# ============================================================================

TOOL_DEFINITIONS = [
    {
        'type': 'function',
        'function': {
            'name': 'browser_open',
            'description': '用无头浏览器打开一个网页。返回页面标题和主要内容文本。',
            'parameters': {
                'type': 'object',
                'properties': {
                    'url': {
                        'type': 'string',
                        'description': '网页地址（完整 URL，以 http:// 或 https:// 开头）',
                    },
                    'wait_seconds': {
                        'type': 'number',
                        'description': '等待页面加载的秒数，默认 2',
                        'default': 2,
                    },
                    'headless': {
                        'type': 'boolean',
                        'description': '是否无头模式（无窗口可见），默认 True',
                        'default': True,
                    },
                },
                'required': ['url'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'browser_screenshot',
            'description': '对当前浏览器页面截图，保存为 PNG 图片到 workspace/screenshots/',
            'parameters': {
                'type': 'object',
                'properties': {
                    'name': {
                        'type': 'string',
                        'description': '截图文件名（不含扩展名），例如 github_homepage',
                        'default': '',
                    },
                    'full_page': {
                        'type': 'boolean',
                        'description': '是否截取整个可滚动页面（True）还是只截视口（False）',
                        'default': False,
                    },
                },
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'browser_click',
            'description': '在当前页面上点击一个链接或按钮。',
            'parameters': {
                'type': 'object',
                'properties': {
                    'selector': {
                        'type': 'string',
                        'description': 'CSS 选择器（如 button.submit）或页面上可见的文本（如 登录）',
                    },
                    'by_text': {
                        'type': 'boolean',
                        'description': 'selector 是否按可见文本匹配（True）还是 CSS 选择器（False）',
                        'default': False,
                    },
                },
                'required': ['selector'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'browser_fill',
            'description': '在输入框里填写文本。',
            'parameters': {
                'type': 'object',
                'properties': {
                    'selector': {
                        'type': 'string',
                        'description': '输入框的 CSS 选择器，例如 input[name=q]',
                    },
                    'text': {
                        'type': 'string',
                        'description': '要填入的文本内容',
                    },
                    'submit': {
                        'type': 'boolean',
                        'description': '填完后是否自动按回车键提交',
                        'default': False,
                    },
                },
                'required': ['selector', 'text'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'browser_get_text',
            'description': '读取当前页面或某个元素中的文本内容。',
            'parameters': {
                'type': 'object',
                'properties': {
                    'selector': {
                        'type': 'string',
                        'description': 'CSS 选择器，不填则返回整个页面的文本',
                        'default': '',
                    },
                    'max_length': {
                        'type': 'integer',
                        'description': '最大返回字符数，默认 3000',
                        'default': 3000,
                    },
                },
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'browser_navigate',
            'description': '在当前浏览器会话中导航到新 URL（复用已打开的页面）。',
            'parameters': {
                'type': 'object',
                'properties': {
                    'url': {
                        'type': 'string',
                        'description': '目标 URL',
                    },
                    'wait_seconds': {
                        'type': 'number',
                        'description': '等待加载秒数',
                        'default': 2,
                    },
                },
                'required': ['url'],
            },
        },
    },
]


# ============================================================================
# Playwright 会话管理（单例模式）
# ============================================================================

_browser_instance = None
_page_instance = None
_installed = None


def _check_installed() -> bool:
    global _installed
    if _installed is None:
        try:
            import playwright  # noqa: F401
            _installed = True
        except ImportError:
            _installed = False
    return _installed


def _get_page(headless: bool = True):
    global _browser_instance, _page_instance

    if not _check_installed():
        raise ImportError('playwright not installed')

    if _page_instance is None or _browser_instance is None or not _browser_instance.is_connected():
        import asyncio
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None:
            # 在 asyncio 事件循环中，用 to_thread 避免 "Sync API inside asyncio loop" 错误
            import functools
            _init_browser_sync = functools.partial(_init_browser_sync_mode, headless)
            _browser_instance, _page_instance = asyncio.get_event_loop().run_until_complete(
                asyncio.to_thread(_init_browser_sync)
            )
        else:
            _init_browser_sync_mode(headless)

    return _page_instance


def _init_browser_sync_mode(headless: bool):
    """同步方式初始化浏览器（在 to_thread 中调用）"""
    global _browser_instance, _page_instance
    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=headless)
    page = browser.new_page()
    _browser_instance = browser
    _page_instance = page
    return browser, page


# ============================================================================
# 执行函数
# ============================================================================

def execute(name: str, arguments: dict) -> str:
    if name == 'browser_open':
        return _do_open(
            url=arguments['url'],
            wait_seconds=arguments.get('wait_seconds', 2),
            headless=arguments.get('headless', True),
        )
    elif name == 'browser_screenshot':
        return _do_screenshot(
            name=arguments.get('name', ''),
            full_page=arguments.get('full_page', False),
        )
    elif name == 'browser_click':
        return _do_click(
            selector=arguments['selector'],
            by_text=arguments.get('by_text', False),
        )
    elif name == 'browser_fill':
        return _do_fill(
            selector=arguments['selector'],
            text=arguments['text'],
            submit=arguments.get('submit', False),
        )
    elif name == 'browser_get_text':
        return _do_get_text(
            selector=arguments.get('selector', ''),
            max_length=arguments.get('max_length', 3000),
        )
    elif name == 'browser_navigate':
        return _do_navigate(
            url=arguments['url'],
            wait_seconds=arguments.get('wait_seconds', 2),
        )
    else:
        return f'[未知浏览器工具: {name}]'


def _format_page_info(page) -> str:
    try:
        title = page.title()
        url = page.url
        return f'[页面标题] {title}\n[当前 URL] {url}'
    except Exception:
        return ''


def _do_open(url: str, wait_seconds: float, headless: bool) -> str:
    if not url.startswith(('http://', 'https://')):
        return '[错误：URL 必须以 http:// 或 https:// 开头]'
    try:
        page = _get_page(headless=headless)
        page.goto(url, wait_until='domcontentloaded')
        if wait_seconds > 0:
            page.wait_for_timeout(int(wait_seconds * 1000))
        info = _format_page_info(page)
        _write_audit('browser_open', url, f'[已打开] {info}')
        text = page.inner_text('body')[:500]
        return f'[已打开] {info}\n\n[页面内容预览]\n{text}'
    except ImportError:
        return '[错误：playwright 未安装]\n请在 WSL 终端运行：\n  pip install playwright\n  playwright install chromium'
    except Exception as e:
        logger.error(f'[Browser] open failed: {e}')
        return f'[打开失败: {e}]'


def _do_screenshot(name: str, full_page: bool) -> str:
    try:
        page = _get_page()
        if not name:
            name = f'screenshot_{int(time.time())}'
        safe_name = ''.join(c for c in name if c.isalnum() or c in '._-')
        filepath = SCREENSHOT_DIR / f'{safe_name}.png'
        page.screenshot(path=str(filepath), full_page=full_page)
        size = filepath.stat().st_size
        _write_audit('browser_screenshot', str(page.url), f'[截图已保存] {filepath} ({size} bytes)')
        return f'[截图已保存] {filepath} ({size} bytes)'
    except ImportError:
        return '[错误：playwright 未安装]'
    except Exception as e:
        logger.error(f'[Browser] screenshot failed: {e}')
        return f'[截图失败: {e}]'


def _do_click(selector: str, by_text: bool) -> str:
    try:
        page = _get_page()
        if by_text:
            page.get_by_text(selector, exact=False).click()
        else:
            page.click(selector)
        _write_audit('browser_click', selector, '[点击成功]')
        return f'[点击成功: {selector}]'
    except ImportError:
        return '[错误：playwright 未安装]'
    except Exception as e:
        return f'[点击失败: {e}]'


def _do_fill(selector: str, text: str, submit: bool) -> str:
    try:
        page = _get_page()
        page.fill(selector, text)
        if submit:
            page.press(selector, 'Enter')
            page.wait_for_timeout(1000)
        _write_audit('browser_fill', selector, f'[已填写] {text[:50]}...')
        return f"[已填写: {selector} = '{text[:50]}...']" + ('（已提交）' if submit else '')
    except ImportError:
        return '[错误：playwright 未安装]'
    except Exception as e:
        return f'[填写失败: {e}]'


def _do_get_text(selector: str, max_length: int) -> str:
    try:
        page = _get_page()
        if selector:
            text = page.inner_text(selector)
        else:
            text = page.inner_text('body')
        if len(text) > max_length:
            text = text[:max_length] + f'\n... [内容过长，已截断至 {max_length} 字符]'
        return text
    except ImportError:
        return '[错误：playwright 未安装]'
    except Exception as e:
        return f'[读取失败: {e}]'


def _do_navigate(url: str, wait_seconds: float) -> str:
    if not url.startswith(('http://', 'https://')):
        return '[错误：URL 必须以 http:// 或 https:// 开头]'
    try:
        page = _get_page()
        page.goto(url, wait_until='domcontentloaded')
        if wait_seconds > 0:
            page.wait_for_timeout(int(wait_seconds * 1000))
        info = _format_page_info(page)
        _write_audit('browser_navigate', url, f'[已导航] {info}')
        text = page.inner_text('body')[:500]
        return f'[已导航] {info}\n\n[页面内容预览]\n{text}'
    except ImportError:
        return '[错误：playwright 未安装]'
    except Exception as e:
        return f'[导航失败: {e}]'


def _write_audit(tool: str, target: str, result: str) -> None:
    import json

    record = {
        'timestamp': time.time(),
        'tool': tool,
        'target': target,
        'result_preview': result[:500],
    }
    try:
        audit_file = AUDIT_DIR / 'browser_audit.jsonl'
        with open(audit_file, 'a', encoding='utf-8') as f:
            f.write(json.dumps(record, ensure_ascii=False) + '\n')
    except Exception as e:
        logger.error(f'[Browser] audit write failed: {e}')
