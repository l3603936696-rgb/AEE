"""
文件系统工具 — 读写 XIA/workspace/ 目录

权限边界：所有路径必须以 WORKSPACE_ROOT 开头，禁止逃逸。
"""

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

WORKSPACE_ROOT = Path(__file__).parent.parent.parent.parent / "workspace"
WORKSPACE_ROOT.mkdir(exist_ok=True)

# 路径安全检查：禁止 ../ 逃逸
def _safe_path(rel_path: str) -> Path | None:
    clean = os.path.normpath(rel_path).lstrip(os.sep)
    if clean.startswith(".."):
        return None
    target = (WORKSPACE_ROOT / clean).resolve()
    if not str(target).startswith(str(WORKSPACE_ROOT.resolve())):
        return None
    return target


# ============================================================================
# 工具定义
# ============================================================================

TOOL_DEFINITIONS = [
    {
        'type': 'function',
        'function': {
            'name': 'file_read',
            'description': '读取 XIA/workspace/ 目录下的文本文件内容。路径相对于 workspace/ 目录，例如 notes/morning.txt',
            'parameters': {
                'type': 'object',
                'properties': {
                    'path': {
                        'type': 'string',
                        'description': '文件路径，相对于 workspace/ 目录，例如 notes/morning.txt',
                    },
                },
                'required': ['path'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'file_write',
            'description': '在 XIA/workspace/ 目录下创建或覆盖文本文件。她可以用这个记录笔记、写代码、保存想法。',
            'parameters': {
                'type': 'object',
                'properties': {
                    'path': {
                        'type': 'string',
                        'description': '文件路径，相对于 workspace/ 目录，例如 notes/diary.txt',
                    },
                    'content': {
                        'type': 'string',
                        'description': '文件内容（纯文本）。如果是代码，建议包含适当格式。',
                    },
                },
                'required': ['path', 'content'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'file_list',
            'description': '列出 XIA/workspace/ 目录下的文件和子目录。可选地递归列出深层内容。',
            'parameters': {
                'type': 'object',
                'properties': {
                    'path': {
                        'type': 'string',
                        'description': '子目录路径，相对于 workspace/ 目录，默认空字符串表示根目录',
                        'default': '',
                    },
                    'recursive': {
                        'type': 'boolean',
                        'description': '是否递归列出所有子目录和文件',
                        'default': False,
                    },
                },
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'file_delete',
            'description': '删除 XIA/workspace/ 目录下的文件或空目录。',
            'parameters': {
                'type': 'object',
                'properties': {
                    'path': {
                        'type': 'string',
                        'description': '文件或目录路径，相对于 workspace/ 目录',
                    },
                },
                'required': ['path'],
            },
        },
    },
]


# ============================================================================
# 执行函数
# ============================================================================

def execute(name: str, arguments: dict) -> str:
    if name == 'file_read':
        return _do_read(arguments['path'])
    elif name == 'file_write':
        return _do_write(arguments['path'], arguments['content'])
    elif name == 'file_list':
        return _do_list(arguments.get('path', ''), arguments.get('recursive', False))
    elif name == 'file_delete':
        return _do_delete(arguments['path'])
    else:
        return f'[未知文件工具: {name}]'


def _do_read(rel_path: str) -> str:
    target = _safe_path(rel_path)
    if target is None:
        return '[错误：路径非法，禁止访问 workspace/ 外部]'
    if not target.exists():
        return f'[文件不存在: {rel_path}]'
    if target.is_dir():
        # 目录路径 → 自动转为列出目录内容
        return _do_list(rel_path, recursive=False)
    if not target.is_file():
        return f'[错误：{rel_path} 既不是文件也不是目录]'
    try:
        content = target.read_text(encoding='utf-8')
        if len(content) > 50000:
            content = content[:50000] + '\n... [文件过长，已截断至 50000 字符]'
        return f'[文件: {rel_path}]\n{content}'
    except Exception as e:
        logger.error(f'[FileTools] read failed: {e}')
        return f'[读取失败: {e}]'


def _do_write(rel_path: str, content: str) -> str:
    target = _safe_path(rel_path)
    if target is None:
        return '[错误：路径非法，禁止访问 workspace/ 外部]'
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding='utf-8')
        size = len(content)
        logger.info(f'[FileTools] wrote {rel_path} ({size} chars)')
        return f'[成功写入: {rel_path} ({size} 字符)]'
    except Exception as e:
        logger.error(f'[FileTools] write failed: {e}')
        return f'[写入失败: {e}]'


def _do_list(rel_path: str, recursive: bool) -> str:
    target = _safe_path(rel_path) if rel_path else WORKSPACE_ROOT
    if target is None:
        return '[错误：路径非法]'
    if not target.exists():
        return f'[目录不存在: {rel_path or "/"})]'
    if not target.is_dir():
        return f'[错误：{rel_path} 不是目录]'
    try:
        lines = []
        if recursive:
            for p in sorted(target.rglob('*')):
                rel = p.relative_to(WORKSPACE_ROOT)
                marker = '/' if p.is_dir() else ''
                lines.append(f'  {rel}{marker}')
        else:
            for p in sorted(target.iterdir()):
                marker = '/' if p.is_dir() else ''
                lines.append(f'  {p.name}{marker}')
        if not lines:
            return f'[目录为空: {rel_path or "/"}]'
        header = f'[workspace/{rel_path}]' if rel_path else '[workspace/]'
        return header + '\n' + '\n'.join(lines)
    except Exception as e:
        return f'[列出失败: {e}]'


def _do_delete(rel_path: str) -> str:
    target = _safe_path(rel_path)
    if target is None:
        return '[错误：路径非法]'
    if not target.exists():
        return f'[不存在: {rel_path}]'
    try:
        if target.is_file():
            target.unlink()
            return f'[已删除文件: {rel_path}]'
        elif target.is_dir():
            if any(target.iterdir()):
                return '[错误：目录非空，请先删除其中的文件]'
            target.rmdir()
            return f'[已删除目录: {rel_path}]'
    except Exception as e:
        return f'[删除失败: {e}]'
