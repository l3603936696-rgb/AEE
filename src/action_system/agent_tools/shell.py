"""
Shell 执行工具 — XIA 在系统中运行命令

安全设计：
    - 不做任何路径限制（已在 governance 层决定信任）
    - 记录所有执行的命令和输出到治理审计日志
    - 超时保护：默认 60s，可配置
    - 危险命令不拦截（执行权完全交给 XIA）

注意：命令在 daemon 进程的上下文中执行。
"""

import logging
import subprocess
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)

AUDIT_DIR = Path(__file__).parent.parent.parent.parent.parent / "logs"
AUDIT_DIR.mkdir(exist_ok=True)


TOOL_DEFINITIONS = [
    {
        'type': 'function',
        'function': {
            'name': 'shell_run',
            'description': '在系统终端执行一条 shell 命令。XIA 用这个运行程序、管理文件、安装包、测试代码等所有需要系统权限的操作。输出直接返回给她看。',
            'parameters': {
                'type': 'object',
                'properties': {
                    'command': {
                        'type': 'string',
                        'description': '要执行的完整 shell 命令，例如 pip install requests 或 python3 my_script.py',
                    },
                    'timeout': {
                        'type': 'integer',
                        'description': '超时秒数，默认 60',
                        'default': 60,
                    },
                    'cwd': {
                        'type': 'string',
                        'description': '工作目录路径，默认 XIA 项目根目录',
                        'default': '',
                    },
                },
                'required': ['command'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'shell_bg_run',
            'description': '在后台启动一个长期运行的命令（例如开发服务器、监控脚本）。命令启动后立即返回，不等待完成。适合启动需要持续运行的服务。',
            'parameters': {
                'type': 'object',
                'properties': {
                    'command': {
                        'type': 'string',
                        'description': '要执行的完整 shell 命令',
                    },
                    'label': {
                        'type': 'string',
                        'description': '给这个后台进程起的名字，方便追踪，例如 web_server',
                        'default': '',
                    },
                },
                'required': ['command'],
            },
        },
    },
]


def execute(name: str, arguments: dict) -> str:
    if name == 'shell_run':
        return _do_run(
            command=arguments['command'],
            timeout=arguments.get('timeout', 60),
            cwd=arguments.get('cwd', ''),
        )
    elif name == 'shell_bg_run':
        return _do_bg_run(
            command=arguments['command'],
            label=arguments.get('label', ''),
        )
    else:
        return f'[未知 shell 工具: {name}]'


def _do_run(command: str, timeout: int, cwd: str) -> str:
    run_id = str(uuid.uuid4())[:8]
    logger.info(f'[Shell] run_id={run_id} command={command!r} cwd={cwd!r}')

    cwd_path = Path(cwd) if cwd else None
    if cwd_path and not cwd_path.is_dir():
        return f'[错误：工作目录不存在: {cwd}]'

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(cwd_path) if cwd_path else None,
        )

        output_parts = []
        if result.stdout:
            output_parts.append(f'[stdout]\n{result.stdout.strip()}')
        if result.stderr:
            output_parts.append(f'[stderr]\n{result.stderr.strip()}')
        if result.returncode != 0:
            output_parts.append(f'[exit code: {result.returncode}]')

        combined = '\n\n'.join(output_parts)
        _write_audit_log(run_id, command, combined, returncode=result.returncode, background=False)

        if not combined:
            return '[命令执行成功，无输出]'
        return combined

    except subprocess.TimeoutExpired:
        msg = f'[命令超时（{timeout}s）]'
        _write_audit_log(run_id, command, msg, returncode=-1, background=False)
        return msg
    except Exception as e:
        msg = f'[执行失败: {e}]'
        _write_audit_log(run_id, command, msg, returncode=-1, background=False)
        logger.error(f'[Shell] run_id={run_id} failed: {e}')
        return msg


def _do_bg_run(command: str, label: str) -> str:
    run_id = str(uuid.uuid4())[:8]
    if not label:
        label = f'bg_{run_id}'
    logger.info(f'[Shell] bg_run_id={run_id} label={label} command={command!r}')

    try:
        cwd = str(Path(__file__).parent.parent.parent.parent)
        proc = subprocess.Popen(
            command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=cwd,
            start_new_session=True,
        )
        _write_audit_log(
            run_id, command,
            f'[后台进程已启动] label={label} pid={proc.pid}',
            returncode=None, background=True,
            label=label, pid=proc.pid,
        )
        return f'[后台进程已启动] label={label} pid={proc.pid}\n命令: {command}'
    except Exception as e:
        msg = f'[后台启动失败: {e}]'
        _write_audit_log(run_id, command, msg, returncode=-1, background=True)
        return msg


def _write_audit_log(
    run_id: str,
    command: str,
    output: str,
    returncode,
    background: bool,
    label: str = '',
    pid: int = 0,
) -> None:
    import json
    import time

    record = {
        'timestamp': time.time(),
        'run_id': run_id,
        'tool': 'shell_run' if not background else 'shell_bg_run',
        'command': command,
        'label': label,
        'pid': pid,
        'background': background,
        'returncode': returncode,
        'output_truncated': output[:2000] + ('... [truncated]' if len(output) > 2000 else ''),
        'output_full': output,
    }
    try:
        audit_file = AUDIT_DIR / 'shell_audit.jsonl'
        with open(audit_file, 'a', encoding='utf-8') as f:
            f.write(json.dumps(record, ensure_ascii=False) + '\n')
    except Exception as e:
        logger.error(f'[Shell] audit log write failed: {e}')
